"""The seed run's concurrency and its Windows-facing parts: one synthesis
stream with the rest overlapped, two drainers never making a render twice,
clips cut and verified concurrently, the unknown-pronunciation guard, the
atomic local storage, progress arithmetic. Real DB, fake Kokoro / whisper /
storage (no GPU)."""

import asyncio
import threading
import time
import uuid
from pathlib import PureWindowsPath
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy import update
from sqlmodel import select

from app.core.config import settings
from app.core.database import async_session_factory
from app.models.audio_render import AudioRender, RenderKind, RenderStatus
from app.models.word_clip import ClipStatus, WordClip
from app.services import audio_pcm, tts, word_clips
from app.services import storage as storage_module
from app.services.infra_errors import InfrastructureError
from scripts import seed_tts
from tests.audio_helpers import (
    Created,
    FakeStorage,
    FakeSynth,
    add_clip,
    make_blob,
    sentence,
    tone,
    unique_word,
)


@pytest.fixture
async def created():
    made = Created()
    yield made
    await made.cleanup()


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "tts_retry_backoff_s", 0.0)
    monkeypatch.setattr(settings, "tts_infra_backoff_s", 0.0)


class SlowStorage(FakeStorage):
    """Every put takes ``delay`` seconds (a share across a LAN); records how
    many were in flight at once."""

    def __init__(self, delay: float = 0.15) -> None:
        super().__init__()
        self.delay, self.in_flight, self.max_in_flight = delay, 0, 0

    async def put(self, key: str, data: bytes, mime_type: str) -> None:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
            await super().put(key, data, mime_type)
        finally:
            self.in_flight -= 1


class ThreadWatchingSynth(FakeSynth):
    """Records the threads it ran on and whether two calls ever overlapped."""

    def __init__(self, fail_on: str | None = None) -> None:
        super().__init__(fail_on)
        self.threads: set[int] = set()
        self.active = self.max_active = 0
        self._guard = threading.Lock()

    def __call__(self, text: str, voice: str = "bf_emma") -> np.ndarray:
        with self._guard:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            self.threads.add(threading.get_ident())
            time.sleep(0.01)
            return super().__call__(text, voice)
        finally:
            with self._guard:
                self.active -= 1


async def _enqueue_words(created: Created, n: int) -> list[tts.RenderSpec]:
    specs = [tts.word_spec(unique_word(), None) for _ in range(n)]
    created.render_keys.extend(s.key for s in specs)
    await tts.enqueue(specs)
    return specs


async def _rows(keys: list[str]) -> list[AudioRender]:
    async with async_session_factory() as session:
        return list((await session.exec(select(AudioRender).where(AudioRender.key.in_(keys)))).all())


# --- the drain -------------------------------------------------------------------


async def test_storage_round_trips_overlap_but_synthesis_stays_on_one_thread(created: Created) -> None:
    specs = await _enqueue_words(created, 12)
    keys = [s.key for s in specs]
    storage, synth = SlowStorage(0.15), ThreadWatchingSynth()
    started = time.monotonic()
    done = await tts.drain(synth, keys=keys, storage=storage, concurrency=6)
    elapsed = time.monotonic() - started
    assert done == 12
    assert all(r.status == RenderStatus.READY for r in await _rows(keys))
    assert storage.max_in_flight >= 3  # the writes overlapped ...
    assert elapsed < 12 * 0.15 * 0.7  # ... so the run beat the serial 1.8 s
    assert synth.max_active == 1 and len(synth.threads) == 1  # ... one synthesis stream
    assert threading.get_ident() not in synth.threads  # off the event loop


async def test_concurrency_one_is_the_old_serial_drain(created: Created) -> None:
    specs = await _enqueue_words(created, 3)
    storage = SlowStorage(0.02)
    assert await tts.drain(FakeSynth(), keys=[s.key for s in specs], storage=storage) == 3
    assert storage.max_in_flight == 1


async def test_two_drainers_on_one_queue_never_make_a_render_twice(created: Created) -> None:
    specs = await _enqueue_words(created, 20)
    keys = [s.key for s in specs]
    first, second = FakeSynth(), FakeSynth()
    storage = SlowStorage(0.02)
    a, b = await asyncio.gather(
        tts.drain(first, keys=keys, storage=storage, concurrency=4),
        tts.drain(second, keys=keys, storage=storage, concurrency=4),
    )
    assert a + b == 20
    assert sorted(first.calls + second.calls) == sorted(s.input for s in specs)  # each exactly once
    assert first.calls and second.calls  # and both really worked
    assert all(r.status == RenderStatus.READY for r in await _rows(keys))


async def test_a_failure_is_recorded_on_its_own_row_and_the_rest_carry_on(created: Created) -> None:
    specs = await _enqueue_words(created, 6)
    bad = specs[2]
    keys = [s.key for s in specs]
    done = await tts.drain(FakeSynth(fail_on=bad.input), keys=keys, storage=FakeStorage(), concurrency=3)
    rows = {r.key: r for r in await _rows(keys)}
    assert rows[bad.key].status == RenderStatus.PENDING and rows[bad.key].attempts >= 1
    assert "synthesis failed" in rows[bad.key].error
    assert [r.status for k, r in rows.items() if k != bad.key] == [RenderStatus.READY] * 5
    assert done >= 6  # the failing row was retried (back-off is 0 here), the rest made once


async def test_limit_claims_no_more_than_asked(created: Created) -> None:
    specs = await _enqueue_words(created, 8)
    keys = [s.key for s in specs]
    assert await tts.drain(FakeSynth(), keys=keys, storage=FakeStorage(), limit=3, concurrency=5) == 3
    statuses = [r.status for r in await _rows(keys)]
    assert statuses.count(RenderStatus.READY) == 3 and statuses.count(RenderStatus.PENDING) == 5


async def test_cancelling_a_drain_gives_its_claimed_rows_back(created: Created) -> None:
    specs = await _enqueue_words(created, 6)
    keys = [s.key for s in specs]
    task = asyncio.create_task(tts.drain(FakeSynth(), keys=keys, storage=SlowStorage(5.0), concurrency=3))
    for _ in range(100):  # until some are claimed
        await asyncio.sleep(0.05)
        if any(r.status == RenderStatus.PROCESSING for r in await _rows(keys)):
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert all(r.status == RenderStatus.PENDING for r in await _rows(keys))


async def test_claim_renders_takes_a_batch_and_skips_what_is_claimed(created: Created) -> None:
    specs = await _enqueue_words(created, 5)
    keys = [s.key for s in specs]
    async with async_session_factory() as one, async_session_factory() as two:
        first = await tts.claim_renders(one, keys=keys, limit=3)
        second = await tts.claim_renders(two, keys=keys, limit=3)
    assert len(first) == 3 and len(second) == 2
    assert not {r.key for r in first} & {r.key for r in second}
    assert await tts.queue_depth([RenderKind.WORD]) >= 5


# --- the unknown-pronunciation guard ---------------------------------------------


def _tok(text: str, phonemes: str | None) -> SimpleNamespace:
    return SimpleNamespace(text=text, phonemes=phonemes)


def test_unknown_words_sees_empty_missing_and_marked_phonemes_but_not_punctuation() -> None:
    tokens = [
        _tok("hello", "həlˈO"), _tok(",", ","), _tok("zork", ""), _tok("blarg", None),
        _tok("half-zork", f"hˈæf{tts.UNKNOWN_MARK}"), _tok("...", None),
    ]
    assert tts.unknown_words(tokens) == ["zork", "blarg", "half-zork"]


class FakePipeline:
    def __init__(self, tokens: list, *, fallback: object | None = object(), voice_error: Exception | None = None):
        self._tokens = tokens
        self.g2p = SimpleNamespace(fallback=fallback, unk="")
        self.model = SimpleNamespace(device="cuda:0")
        self.voice_error = voice_error
        self.generated = 0

    def load_voice(self, voice: str):
        if self.voice_error is not None:
            raise self.voice_error

    def generate_from_tokens(self, tokens, voice, speed):
        self.generated += 1
        yield SimpleNamespace(audio=_Tensor(tone(300)))


class _Tensor:
    def __init__(self, array: np.ndarray) -> None:
        self._array = array

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self._array


def _synth_with(pipeline: FakePipeline) -> tts.KokoroSynth:
    pipeline.g2p = _CallableG2P(pipeline.g2p, pipeline._tokens)
    return tts.KokoroSynth(pipeline_factory=lambda lang, model: pipeline)


class _CallableG2P(SimpleNamespace):
    def __init__(self, base: SimpleNamespace, tokens: list) -> None:
        super().__init__(fallback=base.fallback, unk=base.unk)
        self._tokens = tokens

    def __call__(self, text: str):
        return "", self._tokens


def test_a_word_misaki_cannot_pronounce_fails_the_render_instead_of_a_silent_gap() -> None:
    pipeline = FakePipeline([_tok("the", "ðə"), _tok("zork", "")])
    synth = _synth_with(pipeline)
    with pytest.raises(tts.UnknownPronunciation, match="zork"):
        synth("the zork", "bf_emma")
    assert pipeline.generated == 0  # no GPU time spent on it


def test_the_reason_says_when_the_espeak_fallback_is_missing() -> None:
    synth = _synth_with(FakePipeline([_tok("zork", None)], fallback=None))
    with pytest.raises(tts.UnknownPronunciation, match="not available"):
        synth("zork", "af_heart")


def test_a_fully_pronounced_text_is_spoken() -> None:
    pipeline = FakePipeline([_tok("hello", "həlˈO")])
    audio = _synth_with(pipeline)("hello", "bf_emma")
    assert len(audio) > 0 and pipeline.generated == 1


def test_a_voice_file_that_will_not_load_is_the_machines_fault_not_the_words() -> None:
    synth = _synth_with(FakePipeline([_tok("hello", "həlˈO")], voice_error=OSError("no af_heart.pt")))
    with pytest.raises(InfrastructureError, match="af_heart"):
        synth("hello", "af_heart")


async def test_an_unknown_word_fails_its_row_with_the_reason_and_the_others_are_made(created: Created) -> None:
    good, bad = tts.word_spec(unique_word(), None), tts.word_spec("zork" + unique_word(), None)
    created.render_keys.extend([good.key, bad.key])
    await tts.enqueue([good, bad])

    class Picky(FakeSynth):
        def __call__(self, text: str, voice: str = "bf_emma") -> np.ndarray:
            if text.startswith("zork"):
                raise tts.UnknownPronunciation(f"no pronunciation for {text!r}")
            return super().__call__(text, voice)

    await tts.drain(Picky(), keys=[good.key, bad.key], storage=FakeStorage(), concurrency=2)
    rows = {r.key: r for r in await _rows([good.key, bad.key])}
    assert rows[good.key].status == RenderStatus.READY
    assert rows[bad.key].status != RenderStatus.READY and "no pronunciation" in rows[bad.key].error


# --- cutting and verifying concurrently ------------------------------------------


async def test_clips_are_cut_from_several_recordings_at_once(created: Created) -> None:
    source = np.concatenate([tone(1000, 300), tone(1000, 600), tone(1000, 900)])
    storage = FakeStorage()
    forms, blobs = [], []
    for _ in range(4):
        form = unique_word()
        blob = await make_blob(created, [sentence(["a", form, "c", "d"])], duration_ms=3000)
        storage.objects[blob.storage_key] = audio_pcm.encode_m4a(source)
        async with async_session_factory() as session:
            await word_clips.index_clips(session, blob_ids=[blob.id], forms=[form])
        forms.append(form)
        blobs.append(blob.id)

    active = peak = 0
    real_get = storage.get

    async def slow_get(key: str) -> bytes:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.1)
        active -= 1
        return await real_get(key)

    storage.get = slow_get  # type: ignore[method-assign]
    async with async_session_factory() as session:
        report = await word_clips.cut_clips(session, storage=storage, blob_ids=blobs, concurrency=4)
    assert (report.cut, report.failed, report.deferred) == (4, 0, 0)
    assert peak >= 2
    async with async_session_factory() as session:
        rows = (await session.exec(select(WordClip).where(WordClip.form.in_(forms)))).all()
    assert all(r.status == ClipStatus.CUT and r.storage_key in storage.objects for r in rows)


async def _cut_clip(created: Created, form: str, ms: int = 500) -> WordClip:
    blob = await make_blob(created, [sentence(["a", form, "c", "d"])])
    return await add_clip(blob, form, status=ClipStatus.CUT, start_ms=1000, end_ms=1000 + ms)


async def test_verify_overlaps_storage_reads_over_one_transcription_stream(created: Created) -> None:
    forms = [unique_word() for _ in range(6)]
    clips = [await _cut_clip(created, form) for form in forms]
    storage = FakeStorage()
    for clip in clips:
        storage.objects[clip.storage_key] = clip.storage_key.encode()
    active = peak = 0
    real_get = storage.get

    async def slow_get(key: str) -> bytes:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.1)
        active -= 1
        return await real_get(key)

    storage.get = slow_get  # type: ignore[method-assign]
    threads: set[int] = set()
    by_key = {c.storage_key: c.form for c in clips}
    running = peak_running = 0
    guard = threading.Lock()

    def transcribe(data: bytes) -> str:
        nonlocal running, peak_running
        with guard:
            running += 1
            peak_running = max(peak_running, running)
        threads.add(threading.get_ident())
        time.sleep(0.01)
        with guard:
            running -= 1
        return by_key[data.decode()]  # hears exactly the form

    report = word_clips.VerifyReport()
    async with async_session_factory() as session:
        await word_clips.verify_clips(
            session, transcribe, storage=storage, form_whitelist=forms, concurrency=6, report=report
        )
    assert (report.verified, report.rejected, report.forms_done, report.forms_total) == (6, 0, 6, 6)
    assert peak >= 3 and peak_running == 1 and len(threads) == 1
    async with async_session_factory() as session:
        rows = (await session.exec(select(WordClip).where(WordClip.form.in_(forms)))).all()
    assert all(r.status == ClipStatus.VERIFIED and r.verified_at for r in rows)


async def test_verify_does_not_overwrite_a_clip_somebody_else_already_resolved(created: Created) -> None:
    form = unique_word()
    clip = await _cut_clip(created, form)
    storage = FakeStorage()
    storage.objects[clip.storage_key] = b"x"

    def transcribe(data: bytes) -> str:
        return form

    async with async_session_factory() as session:
        await session.execute(update(WordClip).where(WordClip.id == clip.id).values(status=ClipStatus.REJECTED))
        await session.commit()
    async with async_session_factory() as session:
        report = await word_clips.verify_clips(session, transcribe, storage=storage, form_whitelist=[form])
    assert report.verified == 0  # it was no longer `cut`: nothing to do


async def test_verify_stops_loudly_when_nothing_can_be_transcribed(created: Created) -> None:
    forms = [unique_word() for _ in range(5)]
    for form in forms:
        clip = await _cut_clip(created, form)
    storage = FakeStorage()
    async with async_session_factory() as session:
        for clip in (await session.exec(select(WordClip).where(WordClip.form.in_(forms)))).all():
            storage.objects[clip.storage_key] = b"x"

    def broken(data: bytes) -> str:
        raise RuntimeError("Library cublas64_12.dll is not found")

    async with async_session_factory() as session:
        with pytest.raises(word_clips.VerifyAborted, match="cublas"):
            await word_clips.verify_clips(
                session, broken, storage=storage, form_whitelist=forms, max_consecutive_failures=3
            )
    async with async_session_factory() as session:
        rows = (await session.exec(select(WordClip).where(WordClip.form.in_(forms)))).all()
    assert all(r.status == ClipStatus.CUT for r in rows)  # nothing was marked


# --- check-files -----------------------------------------------------------------


async def test_check_files_lists_ready_rows_whose_file_is_missing(created: Created) -> None:
    specs = await _enqueue_words(created, 2)
    keys = [s.key for s in specs]
    storage = FakeStorage()
    await tts.drain(FakeSynth(), keys=keys, storage=storage)
    gone = next(iter(storage.objects))
    del storage.objects[gone]
    result = await seed_tts.check_files(storage, clips=False, renders=True)
    assert gone in [k for _i, k in result.missing_renders]


# --- storage ---------------------------------------------------------------------


async def test_local_put_is_atomic_and_leaves_no_temp_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    store = storage_module.LocalStorage()
    await store.put("tts/ab/cd.m4a", b"bytes", "audio/mp4")
    await store.put("tts/ab/cd.m4a", b"other", "audio/mp4")  # idempotent: first write stands
    assert await store.get("tts/ab/cd.m4a") == b"bytes"
    assert [p.name for p in (tmp_path / "tts" / "ab").iterdir()] == ["cd.m4a"]


async def test_a_media_root_that_is_not_there_is_retryable_not_a_missing_key(monkeypatch, tmp_path) -> None:
    from app.services.infra_errors import classify_error

    def refuse(*args, **kwargs):
        raise FileNotFoundError("[WinError 3] The system cannot find the path specified: 'Z:\\'")

    monkeypatch.setattr(settings, "media_root", str(tmp_path / "gone"))
    monkeypatch.setattr("pathlib.Path.mkdir", refuse)
    with pytest.raises(OSError) as raised:
        await storage_module.LocalStorage().put("tts/x.m4a", b"1", "audio/mp4")
    assert not isinstance(raised.value, FileNotFoundError)
    assert classify_error(raised.value) == "retryable"


def test_forward_slash_keys_join_correctly_under_a_windows_root() -> None:
    assert str(PureWindowsPath("D:\\voocab-media") / "tts/ab/cd.m4a") == "D:\\voocab-media\\tts\\ab\\cd.m4a"
    assert str(PureWindowsPath("Z:\\") / "clips/x.m4a") == "Z:\\clips\\x.m4a"


# --- progress and arguments --------------------------------------------------------


def test_throughput_is_a_windowed_rate_and_an_eta() -> None:
    now = [0.0]
    meter = seed_tts.Throughput(window_s=60, clock=lambda: now[0])
    assert meter.eta_s(100) is None  # nothing done yet: no promise
    now[0] = 10.0
    meter.record(50)
    assert meter.rate() == 5.0 and meter.eta_s(100) == 20.0
    now[0] = 200.0  # a long stall pushes the old samples out of the window
    meter.record(50)
    meter.record(50)
    assert meter.rate() == 0.0


def test_durations_are_short_and_readable() -> None:
    assert [seed_tts.format_duration(s) for s in (5, 75, 3725, None)] == ["5s", "1m15s", "1h02m", "?"]


def test_arguments_default_to_eight_in_flight_and_refuse_more_than_the_pool_holds() -> None:
    assert seed_tts._parse_args(["words"]).concurrency == 8
    assert seed_tts._parse_args(["clips"]).concurrency == 4
    with pytest.raises(SystemExit):
        seed_tts._parse_args(["words", "--concurrency", "40"])
    assert seed_tts._parse_args(["doctor"]).model == "large-v3"


def test_a_cuda_run_is_refused_without_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    fake = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False))
    monkeypatch.setitem(sys.modules, "torch", fake)
    with pytest.raises(SystemExit, match="--device cpu"):
        seed_tts.resolve_device(None)
    assert seed_tts.resolve_device("cpu") == "cpu"

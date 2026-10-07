"""The TTS layer (`app.services.tts`): keys, masked definitions spoken as
silence, item composition, and the render queue's claim / fail / retry path.
Kokoro is a fake; PyAV is real."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from sqlalchemy import update
from sqlmodel import select

from app.core.config import settings
from app.core.database import async_session_factory
from app.models.audio_render import AudioRender, RenderKind, RenderStatus
from app.services import audio_pcm, tts
from app.services.infra_errors import InfrastructureError
from app.worker import maintain_renders, render_once
from tests.audio_helpers import (
    Created,
    FakeStorage,
    FakeSynth,
    FlakyStorage,
    s3_error,
    tone,
    unique_word,
)

SR = audio_pcm.SAMPLE_RATE


@pytest.fixture
async def created():
    made = Created()
    yield made
    await made.cleanup()


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Most tests drive one render through several attempts back to back; the
    back-off has its own tests, which set it explicitly."""
    monkeypatch.setattr(settings, "tts_retry_backoff_s", 0.0)
    monkeypatch.setattr(settings, "tts_infra_backoff_s", 0.0)


def _longest_zero_run(samples: np.ndarray) -> int:
    best = run = 0
    for value in samples == 0:
        run = run + 1 if value else 0
        best = max(best, run)
    return best


# --- inputs and keys -------------------------------------------------------------


def test_the_key_is_the_hash_of_the_exact_input_voice_and_model() -> None:
    key = tts.render_key("word", "abandon")
    assert key == tts.render_key("word", "abandon")  # stable
    assert len(key) == 64
    assert key != tts.render_key("word", "abandons")
    assert key != tts.render_key("word", "abandon", voice="bf_isabella")
    assert key != tts.render_key("word", "abandon", model="other/model")
    assert key != tts.render_key("definition", "abandon")


def test_storage_keys_live_under_tts_and_renders() -> None:
    assert tts.storage_key_for("word", "ab" * 32) == f"tts/{'ab' * 32}.m4a"
    assert tts.storage_key_for("definition", "cd" * 32).startswith("tts/")
    assert tts.storage_key_for("item", "ef" * 32) == f"renders/{'ef' * 32}.m4a"


def test_a_heteronym_is_spoken_from_phonemes_and_anything_else_from_text() -> None:
    assert tts.word_input("abandon", None) == "abandon"
    assert tts.word_input("record", "ɹɪkˈɔːd") == "[record](/ɹɪkˈɔːd/)"
    # Two senses of one word are two renders; the same sense is one.
    a = tts.word_spec("record", "ɹˈɛkɔːd")
    b = tts.word_spec("record", "ɹɪkˈɔːd")
    assert a.key != b.key and a.key == tts.word_spec("record", "ɹˈɛkɔːd").key
    assert tts.word_spec("record", None).key != a.key


def test_the_definition_is_the_masked_text_recall_shows() -> None:
    spec = tts.definition_spec("to abandon something completely", "abandon")
    assert spec is not None and spec.input == "to _____ something completely"
    # A corrected definition is a new render, never an edit of the old one.
    corrected = tts.definition_spec("to give up something completely", "abandon")
    assert corrected is not None and corrected.key != spec.key
    assert tts.definition_spec("", "abandon") is None
    assert tts.definition_spec("_____", "abandon") is None  # nothing left to say


# --- masks become silence --------------------------------------------------------


def test_split_masked_turns_each_run_of_masks_into_one_silence() -> None:
    assert tts.split_masked("to _____ something") == ["to", None, "something"]
    assert tts.split_masked("_____ _____ _____ of a thing") == [None, "of a thing"]
    assert tts.split_masked("a thing that is _____") == ["a thing that is", None]
    assert tts.split_masked("no masks here") == ["no masks here"]
    assert tts.split_masked("one _____ and two _____ end") == ["one", None, "and two", None, "end"]
    assert tts.split_masked("_____,") == [None]  # a stray comma is not speech


def test_a_masked_definition_is_spoken_in_pieces_with_a_silence_at_each_mask() -> None:
    synth = FakeSynth()
    audio = tts.synthesise_definition(synth, "to _____ something completely")
    assert synth.calls == ["to", "something completely"]  # the mask itself is never spoken
    assert all("_" not in call for call in synth.calls)
    # The pause is real digital silence, as long as the mask pause.
    assert _longest_zero_run(audio) >= round(tts.MASK_PAUSE_MS * SR / 1000) - 2
    pieces = [tts.trim_edges(FakeSynth()(text)) for text in ("to", "something completely")]
    expected = sum(len(p) for p in pieces) + round(tts.MASK_PAUSE_MS * SR / 1000)
    assert abs(len(audio) - expected) <= 2


def test_trim_edges_leaves_a_short_lead_and_tail() -> None:
    raw = FakeSynth()("abc")  # 200 ms of silence either side of 100 ms of tone
    trimmed = tts.trim_edges(raw)
    assert len(raw) - len(trimmed) > 0.25 * SR
    assert audio_pcm.duration_ms(trimmed) < 100 + 2 * (tts._EDGE_KEEP_MS + 5)
    assert len(tts.trim_edges(np.zeros(1000, dtype=np.float32))) == 1000  # all silence: untouched


# --- composing an item -----------------------------------------------------------


def test_an_item_is_definition_pause_word_tail_and_records_where_the_word_starts() -> None:
    definition, word = tone(2000, amp=0.02), tone(600, freq=700, amp=0.4)
    samples, offset = tts.compose_item(definition, word)
    assert offset == 2000 + tts.ITEM_PAUSE_MS == 5000
    assert audio_pcm.duration_ms(samples) == 2000 + 3000 + 600 + 1500
    # The word begins exactly at the offset; before it, the pause is silence.
    start = round(offset * SR / 1000)
    assert float(np.max(np.abs(samples[start - 10 : start - 1]))) == 0.0
    assert float(np.max(np.abs(samples[start : start + 2000]))) > 0.05
    assert float(np.max(np.abs(samples[-SR:]))) == 0.0  # the 1.5 s tail
    # Levelled: a quiet definition and a loud word end up at one loudness.
    spoken_def = samples[: round(2000 * SR / 1000)]
    spoken_word = samples[start : start + round(600 * SR / 1000)]
    assert abs(audio_pcm.rms_dbfs(spoken_def) - audio_pcm.rms_dbfs(spoken_word)) < 0.5


def test_an_items_key_follows_its_parts() -> None:
    definition = tts.definition_spec("to abandon something", "abandon")
    word = tts.word_spec("abandon", None)
    assert definition is not None
    item = tts.item_spec(definition, word)
    assert item == tts.item_spec(definition, word)  # stable
    changed = tts.definition_spec("to give up something", "abandon")
    assert changed is not None
    assert tts.item_spec(changed, word).key != item.key
    with pytest.raises(ValueError):  # the word must be in the definition's voice
        tts.item_spec(definition, tts.word_spec("abandon", None, "american"))


# --- the queue -------------------------------------------------------------------


async def _row(key: str) -> AudioRender:
    async with async_session_factory() as session:
        return (await session.exec(select(AudioRender).where(AudioRender.key == key))).one()


async def _rows(key: str) -> list[AudioRender]:
    async with async_session_factory() as session:
        return list((await session.exec(select(AudioRender).where(AudioRender.key == key))).all())


async def test_enqueue_is_idempotent_and_leaves_existing_rows_alone(created: Created) -> None:
    spec = tts.word_spec(unique_word(), None)
    created.render_keys.append(spec.key)
    assert await tts.enqueue([spec]) == 1
    assert await tts.enqueue([spec, spec]) == 0
    async with async_session_factory() as session:
        await session.execute(
            update(AudioRender).where(AudioRender.key == spec.key).values(status="failed")
        )
        await session.commit()
    assert await tts.enqueue([spec]) == 0  # a failed render is not silently re-queued
    [row] = await _rows(spec.key)
    assert row.status == RenderStatus.FAILED and row.voice == tts.VOICE and row.model == tts.MODEL


async def test_claim_takes_words_before_definitions_before_items(created: Created) -> None:
    word = tts.word_spec(unique_word(), None)
    definition = tts.definition_spec(f"a {unique_word()} thing", "x")
    item = tts.item_spec(definition, word)
    keys = [item.key, definition.key, word.key]
    created.render_keys.extend(keys)
    await tts.enqueue([item, definition, word])  # inserted in the WRONG order
    claimed = []
    for _ in range(3):
        async with async_session_factory() as session:
            row = await tts.claim_render(session, keys=keys)
            assert row is not None and row.status == RenderStatus.PROCESSING
            claimed.append(row.kind)
    assert claimed == [RenderKind.WORD, RenderKind.DEFINITION, RenderKind.ITEM]
    async with async_session_factory() as session:
        assert await tts.claim_render(session, keys=keys) is None  # nothing pending left


async def test_two_workers_never_claim_the_same_render(created: Created) -> None:
    specs = [tts.word_spec(unique_word(), None) for _ in range(2)]
    created.render_keys.extend(s.key for s in specs)
    await tts.enqueue(specs)
    keys = [s.key for s in specs]
    async with async_session_factory() as first, async_session_factory() as second:
        a = await tts.claim_render(first, keys=keys)
        b = await tts.claim_render(second, keys=keys)
    assert a is not None and b is not None and a.id != b.id


async def test_recover_stale_puts_processing_rows_back(created: Created) -> None:
    spec = tts.word_spec(unique_word(), None)
    created.render_keys.append(spec.key)
    await tts.enqueue([spec])
    async with async_session_factory() as session:
        await tts.claim_render(session, keys=[spec.key])
        recovered = await tts.recover_stale_renders(session)
    assert recovered >= 1
    assert (await _row(spec.key)).status == RenderStatus.PENDING


async def _age(key: str, *, seconds: float, status: str | None = None) -> None:
    """Make a row look untouched for ``seconds``."""
    values: dict = {"updated_at": datetime.now(timezone.utc) - timedelta(seconds=seconds)}
    if status is not None:
        values["status"] = status
    async with async_session_factory() as session:
        await session.execute(update(AudioRender).where(AudioRender.key == key).values(**values))
        await session.commit()


async def test_recovery_by_age_takes_a_dead_workers_row_and_not_a_live_ones(
    created: Created,
) -> None:
    dead, live = tts.word_spec(unique_word(), None), tts.word_spec(unique_word(), None)
    created.render_keys.extend([dead.key, live.key])
    await tts.enqueue([dead, live])
    async with async_session_factory() as session:
        await tts.claim_render(session, keys=[dead.key])
        await tts.claim_render(session, keys=[live.key])  # claiming is the heartbeat
    await _age(dead.key, seconds=settings.tts_stale_after_s + 60)
    async with async_session_factory() as session:
        await tts.recover_stale_renders(session, older_than_s=settings.tts_stale_after_s)
    assert (await _row(dead.key)).status == RenderStatus.PENDING
    assert (await _row(live.key)).status == RenderStatus.PROCESSING  # another worker's


async def test_the_loops_housekeeping_recovers_a_stuck_row_and_never_raises(
    created: Created, monkeypatch: pytest.MonkeyPatch
) -> None:
    stuck = tts.word_spec(unique_word(), None)
    created.render_keys.append(stuck.key)
    await tts.enqueue([stuck])
    async with async_session_factory() as session:
        await tts.claim_render(session, keys=[stuck.key])
    await _age(stuck.key, seconds=settings.tts_stale_after_s + 60)
    await maintain_renders()
    assert (await _row(stuck.key)).status == RenderStatus.PENDING

    # A database that is down at startup must not escape into asyncio.gather.
    def broken():
        raise ConnectionError("db is not up yet")

    monkeypatch.setattr("app.worker.async_session_factory", broken)
    assert await maintain_renders() == (0, 0)


async def test_an_old_failed_render_is_requeued_a_recent_one_is_not(created: Created) -> None:
    old, recent = tts.word_spec(unique_word(), None), tts.word_spec(unique_word(), None)
    created.render_keys.extend([old.key, recent.key])
    await tts.enqueue([old, recent])
    await _age(old.key, seconds=7 * 3600, status=RenderStatus.FAILED)
    await _age(recent.key, seconds=60, status=RenderStatus.FAILED)
    async with async_session_factory() as session:
        await tts.requeue_failed_older_than(session, hours=settings.tts_failed_requeue_h)
    assert (await _row(old.key)).status == RenderStatus.PENDING
    assert (await _row(old.key)).attempts == 0
    assert (await _row(recent.key)).status == RenderStatus.FAILED


async def test_a_word_render_is_made_stored_and_marked_ready(created: Created) -> None:
    spec = tts.word_spec(unique_word(), None)
    created.render_keys.append(spec.key)
    await tts.enqueue([spec])
    storage, synth = FakeStorage(), FakeSynth()
    async with async_session_factory() as session:
        row = await tts.claim_render(session, keys=[spec.key])
        await tts.process_render(session, row, synth, storage)
    ready = await _row(spec.key)
    assert ready.status == RenderStatus.READY and ready.error is None
    assert ready.storage_key == f"tts/{spec.key}.m4a"
    assert synth.calls == [spec.input]
    audio = audio_pcm.decode(storage.objects[ready.storage_key])
    assert abs(audio_pcm.duration_ms(audio) - ready.duration_ms) < 60
    assert ready.word_offset_ms is None  # only items have one


async def test_a_failing_render_goes_back_to_pending_then_to_failed(created: Created) -> None:
    spec = tts.word_spec(unique_word(), None)
    created.render_keys.append(spec.key)
    await tts.enqueue([spec])
    storage, synth = FakeStorage(), FakeSynth(fail_on=spec.input)

    async def attempt() -> AudioRender:
        async with async_session_factory() as session:
            row = await tts.claim_render(session, keys=[spec.key])
            assert row is not None
            await tts.process_render(session, row, synth, storage, max_attempts=2)
        return await _row(spec.key)

    first = await attempt()
    assert (first.status, first.attempts) == (RenderStatus.PENDING, 1)
    assert "synthesis failed" in first.error
    second = await attempt()
    assert (second.status, second.attempts) == (RenderStatus.FAILED, 2)
    assert storage.objects == {}
    async with async_session_factory() as session:
        assert await tts.claim_render(session, keys=[spec.key]) is None  # failed is not claimable
        assert await tts.requeue_failed(session, kinds=[RenderKind.WORD]) >= 1
    assert (await _row(spec.key)).status == RenderStatus.PENDING
    assert (await _row(spec.key)).attempts == 0


async def _make(spec: tts.RenderSpec, synth, storage, *, max_attempts: int = 3) -> AudioRender:
    async with async_session_factory() as session:
        row = await tts.claim_render(session, keys=[spec.key])
        assert row is not None
        await tts.process_render(session, row, synth, storage, max_attempts=max_attempts)
    return await _row(spec.key)


async def test_a_failed_attempt_backs_off_before_it_can_be_claimed_again(
    created: Created, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "tts_retry_backoff_s", 60.0)
    spec = tts.word_spec(unique_word(), None)
    created.render_keys.append(spec.key)
    await tts.enqueue([spec])
    row = await _make(spec, FakeSynth(fail_on=spec.input), FakeStorage())
    assert (row.status, row.attempts) == (RenderStatus.PENDING, 1)
    assert row.next_attempt_at is not None
    wait = (row.next_attempt_at - datetime.now(timezone.utc)).total_seconds()
    assert 50 < wait <= 60
    async with async_session_factory() as session:
        assert await tts.claim_render(session, keys=[spec.key]) is None  # waiting it out
    async with async_session_factory() as session:
        await session.execute(
            update(AudioRender)
            .where(AudioRender.key == spec.key)
            .values(next_attempt_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        )
        await session.commit()
        assert await tts.claim_render(session, keys=[spec.key]) is not None  # due


async def test_a_systemic_failure_leaves_every_row_pending_with_a_back_off(
    created: Created, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Storage down: a pass over the whole queue, three times over, must not
    walk it to `failed` -- no attempt is spent, and no row is claimable until
    the back-off has passed."""
    monkeypatch.setattr(settings, "tts_infra_backoff_s", 120.0)
    specs = [tts.word_spec(unique_word(), None) for _ in range(4)]
    created.render_keys.extend(s.key for s in specs)
    await tts.enqueue(specs)
    storage = FlakyStorage()
    storage.put_error = s3_error("SlowDown")
    for spec in specs:
        row = await _make(spec, FakeSynth(), storage, max_attempts=1)  # one strike would fail it
        assert (row.status, row.attempts) == (RenderStatus.PENDING, 0)
        assert row.next_attempt_at is not None and "SlowDown" in row.error
    async with async_session_factory() as session:
        assert await tts.claim_render(session, keys=[s.key for s in specs]) is None
    # The outage ends and the back-off passes: they are made.
    storage.put_error = None
    async with async_session_factory() as session:
        await session.execute(
            update(AudioRender)
            .where(AudioRender.key.in_([s.key for s in specs]))
            .values(next_attempt_at=None)
        )
        await session.commit()
    for spec in specs:
        assert (await _make(spec, FakeSynth(), storage)).status == RenderStatus.READY


async def test_a_model_that_will_not_load_spends_no_attempts(created: Created) -> None:
    spec = tts.word_spec(unique_word(), None)
    created.render_keys.append(spec.key)
    await tts.enqueue([spec])

    def not_loaded(text: str, voice: str) -> np.ndarray:
        raise InfrastructureError("Kokoro failed to load: no weights")

    row = await _make(spec, not_loaded, FakeStorage(), max_attempts=1)
    assert (row.status, row.attempts) == (RenderStatus.PENDING, 0)


async def test_a_permanent_storage_error_still_counts_as_an_attempt(created: Created) -> None:
    spec = tts.word_spec(unique_word(), None)
    created.render_keys.append(spec.key)
    await tts.enqueue([spec])
    storage = FlakyStorage()
    storage.put_error = s3_error("AccessDenied")  # credentials wrong: retrying cannot help
    row = await _make(spec, FakeSynth(), storage, max_attempts=1)
    assert (row.status, row.attempts) == (RenderStatus.FAILED, 1)


async def test_overlapping_enqueues_in_different_orders_do_not_deadlock(
    created: Created,
) -> None:
    for _round in range(5):
        shared = [tts.word_spec(unique_word(), None) for _ in range(60)]
        only_a = [tts.word_spec(unique_word(), None) for _ in range(20)]
        only_b = [tts.word_spec(unique_word(), None) for _ in range(20)]
        created.render_keys.extend(s.key for s in shared + only_a + only_b)
        first = [*shared, *only_a]
        second = [*reversed(shared), *only_b]  # the same rows, the opposite order
        results = await asyncio.gather(tts.enqueue(first), tts.enqueue(second))
        assert sum(results) == len(shared) + len(only_a) + len(only_b)


async def test_enqueue_inserts_in_key_order(created: Created, monkeypatch: pytest.MonkeyPatch) -> None:
    specs = [tts.word_spec(unique_word(), None) for _ in range(10)]
    created.render_keys.extend(s.key for s in specs)
    seen: list[list[str]] = []
    real_values = tts.pg_insert

    def spy(table):
        stmt = real_values(table)
        original = stmt.values

        def values(rows):
            seen.append([r["key"] for r in rows])
            return original(rows)

        stmt.values = values  # type: ignore[method-assign]
        return stmt

    monkeypatch.setattr(tts, "pg_insert", spy)
    await tts.enqueue(list(reversed(specs)))
    assert seen == [sorted(s.key for s in specs)]


async def test_an_item_is_composed_from_parts_it_makes_itself(created: Created) -> None:
    lemma = unique_word()
    definition = tts.definition_spec(f"to {lemma} something completely", lemma)
    word = tts.word_spec(lemma, None)
    item = tts.item_spec(definition, word)
    created.render_keys.extend([definition.key, word.key, item.key])
    await tts.enqueue([item])  # ONLY the item: its parts have no rows yet
    storage, synth = FakeStorage(), FakeSynth()
    async with async_session_factory() as session:
        row = await tts.claim_render(session, keys=[item.key])
        await tts.process_render(session, row, synth, storage)
    ready = await _row(item.key)
    assert ready.status == RenderStatus.READY and ready.storage_key == f"renders/{item.key}.m4a"
    # The offset is the spoken definition plus the three-second pause.
    spoken_definition = tts.synthesise_definition(FakeSynth(), definition.input)
    assert ready.word_offset_ms == audio_pcm.duration_ms(spoken_definition) + tts.ITEM_PAUSE_MS
    word_ms = audio_pcm.duration_ms(tts.synthesise_word(FakeSynth(), lemma))
    assert abs(ready.duration_ms - (ready.word_offset_ms + word_ms + tts.ITEM_TAIL_MS)) <= 2
    # The parts it made are recorded as ready, so nothing makes them twice.
    assert (await _row(definition.key)).status == RenderStatus.READY
    assert (await _row(word.key)).status == RenderStatus.READY


async def test_the_worker_pass_reports_what_happened(created: Created) -> None:
    ok = tts.word_spec(unique_word(), None)
    bad_text = unique_word()
    bad = tts.word_spec(bad_text, None)
    created.render_keys.extend([ok.key, bad.key])
    await tts.enqueue([ok, bad])
    storage = FakeStorage()
    import app.services.tts as tts_module

    original = tts_module.get_storage
    tts_module.get_storage = lambda: storage
    try:
        synth = FakeSynth(fail_on=bad_text)
        assert await render_once(synth, keys=[ok.key]) == "ready"
        assert await render_once(synth, keys=[ok.key]) == "empty"
        assert await render_once(synth, keys=[bad.key]) == "retry"
        assert await render_once(synth, keys=[bad.key]) == "retry"
        assert await render_once(synth, keys=[bad.key]) == "failed"  # max_attempts = 3
    finally:
        tts_module.get_storage = original

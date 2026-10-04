"""Word clips (`app.services.word_clips`): which places in a transcript
become candidates, how they are padded, chosen, cut and verified."""

import uuid

import numpy as np
import pytest
from sqlalchemy import update
from sqlmodel import select

from app.core.database import async_session_factory
from app.models.audio_asset import AudioAsset
from app.models.material import Material
from app.models.word_clip import ClipStatus, WordClip
from app.services import audio_pcm, word_clips as wc
from tests.audio_helpers import (
    Created,
    FakeStorage,
    FlakyStorage,
    attach,
    make_blob,
    make_user,
    s3_error,
    sentence,
    tone,
    unique_word,
)

BLOB = uuid.uuid4()


def occurrences(tokens: list[str], forms: list[str], **kw) -> list[wc.Occurrence]:
    return wc.find_occurrences(
        BLOB, 0, sentence(tokens), wc.forms_index(forms), **kw
    )


# --- normalisation -------------------------------------------------------------


def test_normalise_word_lowercases_and_strips_punctuation_but_keeps_inner_marks() -> None:
    assert wc.normalise_word(" Hello, ") == "hello"
    assert wc.normalise_word("don’t") == "don't"  # curly apostrophe straightened
    assert wc.normalise_word("well-known.") == "well-known"
    assert wc.normalise_word("'quoted'") == "quoted"
    assert wc.normalise_word("U.S.") == "us"
    assert wc.normalise_word("—") is None
    assert wc.normalise_word("") is None


def test_normalise_form_joins_a_phrase_with_single_spaces() -> None:
    assert wc.normalise_form("Give  rise, to") == "give rise to"


def test_heard_contains_matches_consecutive_words_only() -> None:
    assert wc.heard_contains("hello", "Well, hello there.")
    assert wc.heard_contains("give rise to", "They give rise to doubt")
    assert not wc.heard_contains("give rise to", "give to rise")
    assert wc.heard_contains("e-mail", "my e mail")  # hyphen compares as a space
    assert not wc.heard_contains("play", "played")  # exact form, no stemming
    assert not wc.heard_contains("play", "")


# --- padding -------------------------------------------------------------------


def test_padding_is_150ms_a_side_and_clamped_to_the_recording() -> None:
    assert wc.padded_range(1000, 1400, 60_000) == (850, 1550)
    assert wc.padded_range(100, 400, 60_000) == (0, 550)  # not before zero
    assert wc.padded_range(59_900, 60_000, 60_000) == (59_750, 60_000)  # not past the end
    assert wc.padded_range(1000, 1400, None) == (850, 1550)  # duration unknown


# --- finding occurrences -------------------------------------------------------


def test_exact_form_only_inflections_are_not_clips() -> None:
    found = occurrences(["we", "play", "and", "played", "plays", "playing", "now"], ["play"])
    assert [(o.form, o.word_start_index) for o in found] == [("play", 1)]


def test_case_and_punctuation_do_not_matter() -> None:
    found = occurrences(["so", "Hello,", "there", "friend", "ok"], ["hello"])
    assert [o.word_start_index for o in found] == [1]


def test_a_phrase_is_a_consecutive_run() -> None:
    found = occurrences(["it", "will", "give", "rise", "to", "doubt", "ok"], ["give rise to"])
    assert [(o.form, o.word_start_index, o.word_end_index) for o in found] == [
        ("give rise to", 2, 4)
    ]
    assert occurrences(["a", "give", "and", "rise", "to", "b", "c"], ["give rise to"]) == []


def test_the_first_and_last_word_of_a_segment_are_skipped() -> None:
    tokens = ["alpha", "beta", "gamma", "delta"]
    assert occurrences(tokens, ["alpha"]) == []  # first
    assert occurrences(tokens, ["delta"]) == []  # last
    assert len(occurrences(tokens, ["beta"])) == 1
    # A phrase is skipped when its run touches either end.
    assert occurrences(tokens, ["alpha beta"]) == []
    assert occurrences(tokens, ["gamma delta"]) == []
    assert len(occurrences(tokens, ["beta gamma"])) == 1


def test_a_lone_punctuation_token_breaks_a_run() -> None:
    assert occurrences(["a", "give", "—", "rise", "to", "b"], ["give rise to"]) == []


def test_padded_timings_and_the_two_word_context() -> None:
    # Words 0..6, each 400 ms with 100 ms gaps, from 1000 ms.
    [found] = occurrences(["a", "b", "c", "target", "e", "f", "g"], ["target"], blob_duration_ms=60_000)
    assert (found.word_start_index, found.word_end_index) == (3, 3)
    # word 3 runs 2500..2900 -> padded 2350..3050
    assert (found.start_ms, found.end_ms) == (2350, 3050)
    # context: words 1..5 (two before, two after): 1500..3900 -> padded 1350..4050
    assert (found.context_start_index, found.context_end_index) == (1, 5)
    assert (found.context_start_ms, found.context_end_ms) == (1350, 4050)


def test_the_context_stops_at_the_segment_edge() -> None:
    [found] = occurrences(["a", "target", "c", "d"], ["target"])
    assert (found.context_start_index, found.context_end_index) == (0, 3)


def test_the_window_is_clamped_to_the_blob_duration() -> None:
    [found] = occurrences(["a", "target", "c", "d"], ["target"], blob_duration_ms=2000)
    assert found.end_ms <= 2000 and found.context_end_ms <= 2000


def test_implausible_timings_are_not_candidates() -> None:
    segment = [
        {"word": "a", "start_ms": 0, "end_ms": 100},
        {"word": "tiny", "start_ms": 100, "end_ms": 130},  # 30 ms: an artefact
        {"word": "long", "start_ms": 200, "end_ms": 4200},  # 4 s: swallowed a pause
        {"word": "ok", "start_ms": 4300, "end_ms": 4600},
        {"word": "z", "start_ms": 4700, "end_ms": 5000},
    ]
    found = wc.find_occurrences(BLOB, 0, segment, wc.forms_index(["tiny", "long", "ok"]))
    assert [o.form for o in found] == ["ok"]


def test_heteronyms_are_never_indexed() -> None:
    assert "record" not in wc.forms_index(["record", "table"])
    assert "table" in wc.forms_index(["record", "table"])


# --- choosing ------------------------------------------------------------------


def _occ(blob: uuid.UUID, index: int, ms: int) -> wc.Occurrence:
    return wc.Occurrence("w", blob, 0, index, index, 0, ms, 0, 0, 0, ms)


def test_at_most_three_distinct_recordings_first_then_longest() -> None:
    a, b, c, d = (uuid.UUID(int=i) for i in (1, 2, 3, 4))
    candidates = [
        _occ(a, 1, 900), _occ(a, 2, 800), _occ(a, 3, 700),  # one recording, long
        _occ(b, 1, 500), _occ(c, 1, 400), _occ(d, 1, 300),
    ]
    chosen = wc.choose_candidates(candidates)
    assert len(chosen) == 3
    assert {o.blob_id for o in chosen} == {a, b, c}  # distinct recordings, longest of each
    assert chosen[0].word_ms == 900


def test_one_recording_may_fill_the_slots_when_it_is_all_there_is() -> None:
    a = uuid.UUID(int=1)
    chosen = wc.choose_candidates([_occ(a, i, 100 + i) for i in range(5)])
    assert [o.word_ms for o in chosen] == [104, 103, 102]


def test_existing_rows_use_up_slots_and_are_not_offered_again() -> None:
    a, b = uuid.UUID(int=1), uuid.UUID(int=2)
    taken = _occ(a, 1, 900)
    chosen = wc.choose_candidates(
        [taken, _occ(a, 2, 800), _occ(b, 1, 100)],
        taken_places={taken.place}, taken_blobs={a}, slots=2,
    )
    assert taken not in chosen
    assert chosen[0].blob_id == b  # a recording not yet represented comes first


# --- the index, against the database -------------------------------------------


@pytest.fixture
async def created():
    made = Created()
    yield made
    await made.cleanup()


async def _clips(form: str) -> list[WordClip]:
    async with async_session_factory() as session:
        return list((await session.exec(select(WordClip).where(WordClip.form == form))).all())


async def test_index_writes_candidates_and_is_idempotent(created: Created) -> None:
    form = unique_word()
    blob = await make_blob(created, [sentence(["a", form, "c", "d"])])
    async with async_session_factory() as session:
        first = await wc.index_clips(session, blob_ids=[blob.id], forms=[form])
    assert first.inserted == 1
    async with async_session_factory() as session:
        again = await wc.index_clips(session, blob_ids=[blob.id], forms=[form])
    assert again.inserted == 0
    [clip] = await _clips(form)
    assert clip.status == ClipStatus.CANDIDATE and clip.storage_key is None
    assert (clip.word_start_index, clip.segment_order_index) == (1, 0)
    assert clip.blob_id == blob.id


async def test_an_overridden_segment_is_never_a_source(created: Created) -> None:
    form = unique_word()
    user = await make_user(created)
    blob = await make_blob(
        created, [sentence(["a", form, "c", "d"]), sentence(["a", form, "c", "d"])]
    )
    async with async_session_factory() as session:
        asset = AudioAsset(owner_id=user.id, blob_id=blob.id, transcript_overrides={"0": "fixed"})
        session.add(asset)
        await session.commit()
        created.asset_ids.append(asset.id)
        await wc.index_clips(session, blob_ids=[blob.id], forms=[form])
    [clip] = await _clips(form)
    assert clip.segment_order_index == 1  # segment 0 is corrected: its timings no longer fit


async def test_at_most_three_candidates_per_form_across_recordings(created: Created) -> None:
    form = unique_word()
    blobs = [await make_blob(created, [sentence(["a", form, "c", "d"], each_ms=300 + 50 * i)]) for i in range(5)]
    async with async_session_factory() as session:
        await wc.index_clips(session, blob_ids=[b.id for b in blobs], forms=[form])
    clips = await _clips(form)
    assert len(clips) == 3
    assert len({c.blob_id for c in clips}) == 3  # three different recordings
    # The three longest words won.
    longest = {b.id for b in blobs[2:]}
    assert {c.blob_id for c in clips} == longest
    # A later run adds nothing: the form is full.
    async with async_session_factory() as session:
        again = await wc.index_clips(session, blob_ids=[b.id for b in blobs], forms=[form])
    assert again.inserted == 0


async def test_only_a_blob_a_public_material_uses_is_a_source(created: Created) -> None:
    form = unique_word()
    tokens = ["a", form, "c", "d"]
    private = await make_blob(created, [sentence(tokens)], visibility="private")
    public = await make_blob(created, [sentence(tokens)], visibility="public")
    # Used by a private AND a public material: public wins, it is a source.
    both = await make_blob(created, [sentence(tokens)], visibility="private")
    await attach(created, both, "public")
    # An unattached upload: an ordinary user's asset, in no material at all.
    unattached = await make_blob(created, [sentence(tokens)], visibility=None)
    await attach(created, unattached, None)
    # Not even an asset.
    orphan = await make_blob(created, [sentence(tokens)], visibility=None)
    ids = [private.id, public.id, both.id, unattached.id, orphan.id]
    async with async_session_factory() as session:
        await wc.index_clips(session, blob_ids=ids, forms=[form])
        assert set(await wc.unindexed_blob_ids(session, set())) >= {public.id, both.id}
        listed = set(await wc.unindexed_blob_ids(session, set()))
    assert not listed & {private.id, unattached.id, orphan.id}
    assert {c.blob_id for c in await _clips(form)} == {public.id, both.id}


async def test_a_blob_that_is_not_ready_is_not_scanned(created: Created) -> None:
    form = unique_word()
    blob = await make_blob(created, [sentence(["a", form, "c", "d"])], status="pending")
    async with async_session_factory() as session:
        report = await wc.index_clips(session, blob_ids=[blob.id], forms=[form])
    assert report.blobs == 0 and await _clips(form) == []


# --- cutting -------------------------------------------------------------------


async def test_cut_stores_content_addressed_word_and_context_files(created: Created) -> None:
    form = unique_word()
    blob = await make_blob(created, [sentence(["a", form, "c", "d"])], duration_ms=3000)
    # A real recording behind the blob: a different pitch every second.
    source = np.concatenate([tone(1000, 300), tone(1000, 600), tone(1000, 900)])
    storage = FakeStorage()
    storage.objects[blob.storage_key] = audio_pcm.encode_m4a(source)
    async with async_session_factory() as session:
        await wc.index_clips(session, blob_ids=[blob.id], forms=[form])
        report = await wc.cut_clips(session, storage=storage, blob_ids=[blob.id])
    assert (report.cut, report.failed) == (1, 0)
    [clip] = await _clips(form)
    assert clip.status == ClipStatus.CUT and clip.cut_at is not None
    assert clip.storage_key.startswith("clips/") and clip.storage_key.endswith(".m4a")
    word = audio_pcm.decode_range(storage.objects[clip.storage_key])
    context = audio_pcm.decode_range(storage.objects[clip.context_storage_key])
    # Word: 1500..1900 padded 150 each way -> 700 ms; context: words 0..3, longer.
    assert abs(audio_pcm.duration_ms(word) - (clip.end_ms - clip.start_ms)) < 60
    assert audio_pcm.duration_ms(context) > audio_pcm.duration_ms(word)
    # Levelled, like every artefact the layer stores.
    assert abs(audio_pcm.rms_dbfs(word) - audio_pcm.TARGET_RMS_DBFS) < 1.0


async def test_a_clip_that_cannot_be_cut_fails_without_stopping_the_rest(created: Created) -> None:
    bad, good = unique_word(), unique_word()
    broken = await make_blob(created, [sentence(["a", bad, "c", "d"])])
    fine = await make_blob(created, [sentence(["a", good, "c", "d"])], duration_ms=3000)
    storage = FakeStorage()
    storage.objects[broken.storage_key] = b"not audio at all"
    storage.objects[fine.storage_key] = audio_pcm.encode_m4a(tone(3000))
    async with async_session_factory() as session:
        await wc.index_clips(session, blob_ids=[broken.id, fine.id], forms=[bad, good])
        report = await wc.cut_clips(session, storage=storage, blob_ids=[broken.id, fine.id])
    assert (report.cut, report.failed) == (1, 1)
    [failed] = await _clips(bad)
    assert failed.status == ClipStatus.FAILED and failed.error
    [cut] = await _clips(good)
    assert cut.status == ClipStatus.CUT


async def _real_blob(created: Created, form: str, storage: FakeStorage, **kw):
    blob = await make_blob(created, [sentence(["a", form, "c", "d"])], duration_ms=3000, **kw)
    storage.objects[blob.storage_key] = audio_pcm.encode_m4a(tone(3000))
    return blob


async def test_a_transient_storage_error_leaves_the_clip_for_the_next_pass(
    created: Created,
) -> None:
    form = unique_word()
    storage = FlakyStorage()
    blob = await _real_blob(created, form, storage)
    async with async_session_factory() as session:
        await wc.index_clips(session, blob_ids=[blob.id], forms=[form])

    # Fetching the recording fails for a throttling reason: nothing is `failed`.
    storage.get_error = s3_error("SlowDown")
    async with async_session_factory() as session:
        report = await wc.cut_clips(session, storage=storage, blob_ids=[blob.id])
    assert (report.cut, report.failed, report.deferred) == (0, 0, 1)
    [clip] = await _clips(form)
    assert clip.status == ClipStatus.CANDIDATE and "SlowDown" in clip.error

    # Writing the cut fails with a disk blip: still a candidate.
    storage.get_error, storage.put_error = None, OSError("disk blip")
    async with async_session_factory() as session:
        report = await wc.cut_clips(session, storage=storage, blob_ids=[blob.id])
    assert (report.cut, report.failed, report.deferred) == (0, 0, 1)
    assert (await _clips(form))[0].status == ClipStatus.CANDIDATE

    # The outage ends: the same row is cut.
    storage.put_error = None
    async with async_session_factory() as session:
        report = await wc.cut_clips(session, storage=storage, blob_ids=[blob.id])
    assert (report.cut, report.failed) == (1, 0)
    clip = (await _clips(form))[0]
    assert clip.status == ClipStatus.CUT and clip.error is None


async def test_a_permanent_storage_error_fails_the_clip(created: Created) -> None:
    for error in (s3_error("NoSuchKey"), FileNotFoundError("gone")):
        form = unique_word()
        storage = FlakyStorage()
        blob = await _real_blob(created, form, storage)
        storage.get_error = error
        async with async_session_factory() as session:
            await wc.index_clips(session, blob_ids=[blob.id], forms=[form])
            report = await wc.cut_clips(session, storage=storage, blob_ids=[blob.id])
        assert (report.failed, report.deferred) == (1, 0)
        assert (await _clips(form))[0].status == ClipStatus.FAILED


async def test_a_failed_clip_does_not_hold_a_slot_and_its_recording_is_not_reoffered(
    created: Created,
) -> None:
    form = unique_word()
    blobs = [
        await make_blob(created, [sentence(["a", form, "c", "d"], each_ms=300 + 50 * i)])
        for i in range(5)
    ]
    async with async_session_factory() as session:
        await wc.index_clips(session, blob_ids=[b.id for b in blobs], forms=[form])
    first = await _clips(form)
    assert len(first) == 3
    # Two of the three fail to cut.
    failed_blobs = {c.blob_id for c in first[:2]}
    async with async_session_factory() as session:
        await session.execute(
            update(WordClip)
            .where(WordClip.id.in_([c.id for c in first[:2]]))
            .values(status=ClipStatus.FAILED)
        )
        await session.commit()
        again = await wc.index_clips(session, blob_ids=[b.id for b in blobs], forms=[form])
    assert again.inserted == 2  # two replacements: the form is not stuck short
    rows = await _clips(form)
    live = [c for c in rows if c.status != ClipStatus.FAILED]
    assert len(live) == 3
    assert not {c.blob_id for c in live} & failed_blobs  # the broken recordings are not retried
    # ... and it converges: a third run adds nothing.
    async with async_session_factory() as session:
        assert (
            await wc.index_clips(session, blob_ids=[b.id for b in blobs], forms=[form])
        ).inserted == 0


async def test_a_clip_too_quiet_to_level_fails_with_a_reason(created: Created) -> None:
    form = unique_word()
    blob = await make_blob(created, [sentence(["a", form, "c", "d"])], duration_ms=3000)
    storage = FakeStorage()
    storage.objects[blob.storage_key] = audio_pcm.encode_m4a(tone(3000, amp=0.0005))  # -69 dBFS
    async with async_session_factory() as session:
        await wc.index_clips(session, blob_ids=[blob.id], forms=[form])
        report = await wc.cut_clips(session, storage=storage, blob_ids=[blob.id])
    assert (report.cut, report.failed) == (0, 1)
    [clip] = await _clips(form)
    assert clip.status == ClipStatus.FAILED and "too quiet" in clip.error
    assert not [k for k in storage.objects if k.startswith("clips/")]


# --- verifying -----------------------------------------------------------------


async def _cut_clip(created: Created, form: str, *, ms: int) -> WordClip:
    blob = await make_blob(created, [sentence(["a", form, "c", "d"], each_ms=ms)])
    async with async_session_factory() as session:
        await wc.index_clips(session, blob_ids=[blob.id], forms=[form])
        clip = (await session.exec(
            select(WordClip).where(WordClip.form == form, WordClip.blob_id == blob.id)
        )).one()
        clip.status, clip.storage_key = ClipStatus.CUT, f"clips/{uuid.uuid4().hex}.m4a"
        session.add(clip)
        await session.commit()
        await session.refresh(clip)
    return clip


async def test_verify_keeps_clips_where_the_word_is_heard_and_stops_at_the_first(
    created: Created,
) -> None:
    form = unique_word()
    heard_wrong = await _cut_clip(created, form, ms=500)  # longest: tried first
    heard_right = await _cut_clip(created, form, ms=450)
    spare = await _cut_clip(created, form, ms=300)
    storage = FakeStorage()
    for clip in (heard_wrong, heard_right, spare):
        storage.objects[clip.storage_key] = b"x"
    answers = {heard_wrong.storage_key: "something else", heard_right.storage_key: f"so {form}.", spare.storage_key: form}
    asked: list[str] = []

    def transcribe(data: bytes) -> str:  # keyed by call order via the storage lookup below
        asked.append("call")
        return answers[order.pop(0)]

    order = [heard_wrong.storage_key, heard_right.storage_key, spare.storage_key]
    async with async_session_factory() as session:
        report = await wc.verify_clips(session, transcribe, storage=storage, form_whitelist=[form])
    assert (report.verified, report.rejected) == (1, 1)
    assert len(asked) == 2  # the spare clip was never listened to
    states = {c.id: c for c in await _clips(form)}
    assert states[heard_wrong.id].status == ClipStatus.REJECTED
    assert states[heard_wrong.id].heard == "something else"
    assert states[heard_right.id].status == ClipStatus.VERIFIED
    assert states[heard_right.id].verified_at is not None
    assert states[spare.id].status == ClipStatus.CUT  # kept, unused


async def test_a_form_that_is_already_verified_is_skipped(created: Created) -> None:
    form = unique_word()
    done = await _cut_clip(created, form, ms=500)
    other = await _cut_clip(created, form, ms=300)
    async with async_session_factory() as session:
        await session.execute(
            update(WordClip).where(WordClip.id == done.id).values(status=ClipStatus.VERIFIED)
        )
        await session.commit()
    storage = FakeStorage()
    storage.objects[other.storage_key] = b"x"
    calls = []
    async with async_session_factory() as session:
        report = await wc.verify_clips(
            session, lambda data: calls.append(1) or form, storage=storage, form_whitelist=[form]
        )
    assert calls == [] and report.verified == 0

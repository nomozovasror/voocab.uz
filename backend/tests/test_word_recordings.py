"""Human word recordings (phase 2b): the learner's `word_voice` setting, which
recording a sense takes, the importer, and what `word_audio` serves.

The dictionary entries and the "recordings" here are INVENTED: entries with
made-up headwords and transcriptions, and audio that is a generated tone in a
tiny WAV file (the repository is public; nothing from the real source may be
in it). `record`, `live` and similar are real English words only because the
heteronym tables are keyed by real lemmas."""

import io
import wave
from pathlib import Path

import av
import numpy as np
import pytest
from sqlalchemy import event
from sqlmodel import select

from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.models.audio_render import AudioRender
from app.models.word_recording import WordRecording
from app.services import audio_pcm
from app.services import lexicon_cald as lc
from app.services import tts, word_audio
from app.services import word_recordings as wr
from tests.audio_helpers import Created, FakeStorage, make_lexeme, make_user, tone, unique_word
from tests.test_vocabulary_audio_practice import _client, created  # noqa: F401 - fixture


def write_wav(path: Path, *, rate: int = 16_000, ms: int = 400, amp: float = 0.05,
              lead_ms: int = 0, tail_ms: int = 0, freq: float = 300.0) -> None:
    """A mono 16-bit WAV: a tone with ``lead_ms``/``tail_ms`` of silence."""
    n = round(ms * rate / 1000)
    body = amp * np.sin(2 * np.pi * freq * np.arange(n) / rate)
    pcm = np.concatenate([np.zeros(round(lead_ms * rate / 1000)), body,
                          np.zeros(round(tail_ms * rate / 1000))])
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes((pcm * 32767).astype("<i2").tobytes())


def pron(uk: str | None, us: str | None) -> dict:
    out = {}
    if uk:
        out["uk"] = {"ipa": "x", "audio": f"media/audio/{uk}"}
    if us:
        out["us"] = {"ipa": "x", "audio": f"media/audio/{us}"}
    return out


def index_of(entries: dict) -> lc.CaldIndex:
    return lc.CaldIndex(lc.parse_entries(entries, {}))


def row(lemma: str, pos: str, cald_ref: str | None = None, sense_id=None) -> wr.SenseRow:
    import uuid

    return wr.SenseRow(sense_id or uuid.uuid4(), uuid.uuid4(), lemma, pos, cald_ref)


def picked(plan: wr.Plan, sense: wr.SenseRow, accent: str) -> str | None:
    pick = plan.picks.get((sense.id, accent))
    return pick.file_name if pick else None


# --- the setting ------------------------------------------------------------------


async def test_word_voice_defaults_to_recorded_round_trips_and_is_optional_on_put(
    created: Created,
) -> None:
    user = await make_user(created)
    cookies = {"access_token": create_access_token(str(user.id))}
    body = {"daily_minutes": 10, "direction": "passive", "exercise_types": None}
    async with _client() as client:
        got = (await client.get("/api/vocabulary/settings", cookies=cookies)).json()
        assert got["word_voice"] == "recorded"
        r = await client.put("/api/vocabulary/settings", cookies=cookies,
                             json={**body, "word_voice": "synthetic"})
        assert r.json()["word_voice"] == "synthetic"
        # Absent = unchanged, and another control does not flip it.
        r = await client.put("/api/vocabulary/settings", cookies=cookies,
                             json={**body, "accent": "american"})
        assert r.json()["word_voice"] == "synthetic" and r.json()["accent"] == "american"
        r = await client.put("/api/vocabulary/settings", cookies=cookies, json={"word_voice": "recorded"})
        assert r.json()["word_voice"] == "recorded" and r.json()["accent"] == "american"
        r = await client.put("/api/vocabulary/settings", cookies=cookies,
                             json={**body, "word_voice": "robot"})
        assert r.status_code == 422


# --- which recording a sense takes --------------------------------------------------


def test_a_heteronym_takes_the_recording_of_the_block_its_ref_points_into() -> None:
    index = index_of({"record": {"headword": "record", "blocks": [
        {"pos": "noun", "pron": pron("noun-uk.wav", "noun-us.wav"),
         "senses": [{"definition": "invented: a written account"}]},
        {"pos": "verb", "pron": pron("verb-uk.wav", "verb-us.wav"),
         "senses": [{"definition": "invented: to write down"}]},
    ]}})
    noun, verb = row("record", "n", "record#0#0"), row("record", "v", "record#1#0")
    plan = wr.plan(index, [noun, verb], {})
    assert picked(plan, noun, "british") == "noun-uk.wav"
    assert picked(plan, verb, "british") == "verb-uk.wav"
    assert picked(plan, noun, "american") == "noun-us.wav"
    assert picked(plan, verb, "american") == "verb-us.wav"
    assert {p.basis for p in plan.picks.values()} == {"ref"}


def test_a_heteronym_with_no_ref_is_synthetic_with_our_decided_phonemes() -> None:
    index = index_of({"record": {"headword": "record", "blocks": [
        {"pos": "noun", "pron": pron("noun-uk.wav", "noun-us.wav"),
         "senses": [{"definition": "invented: a written account"}]},
    ]}})
    sense = row("record", "n")  # the lexeme matched, but this sense was never mapped
    plan = wr.plan(index, [sense], {})
    assert not plan.picks
    assert plan.fallbacks[wr.HETERONYM] == {"british": 1, "american": 1}


def test_a_non_heteronym_with_no_ref_takes_the_first_block_of_its_pos_with_a_recording() -> None:
    index = index_of({"wugz": {"headword": "wugz", "blocks": [
        {"pos": "verb", "pron": pron("verb-uk.wav", "verb-us.wav"),
         "senses": [{"definition": "invented: to wugz"}]},
        {"pos": "noun", "guideword": "A", "pron": {},  # no recording on the first noun block
         "senses": [{"definition": "invented: a wugz"}]},
        {"pos": "noun", "guideword": "B", "pron": pron("noun-b-uk.wav", "noun-b-us.wav"),
         "senses": [{"definition": "invented: another wugz"}]},
        {"pos": "noun", "guideword": "C", "pron": pron("noun-c-uk.wav", "noun-c-us.wav"),
         "senses": [{"definition": "invented: a third wugz"}]},
    ]}})
    noun = row("wugz", "n")
    plan = wr.plan(index, [noun], {})
    # Never the verb's recording; the first NOUN block that has one.
    assert picked(plan, noun, "british") == "noun-b-uk.wav"
    assert picked(plan, noun, "american") == "noun-b-us.wav"
    assert plan.picks[(noun.id, "british")].basis == "pos"


def test_no_headword_means_synthetic_and_says_why() -> None:
    index = index_of({"wugz": {"headword": "wugz", "blocks": [
        {"pos": "noun", "pron": pron("a-uk.wav", "a-us.wav"),
         "senses": [{"definition": "invented: a wugz"}]}]}})
    absent, wrong_pos = row("zzabsent", "n"), row("wugz", "adj")
    plan = wr.plan(index, [absent, wrong_pos], {})
    assert not plan.picks
    assert plan.fallbacks["no-headword:none"]["british"] == 1
    assert plan.fallbacks["no-headword:headword-only"]["british"] == 1


def test_the_accent_chooses_the_file_and_a_missing_one_falls_back_for_that_accent_only() -> None:
    index = index_of({"wugz": {"headword": "wugz", "blocks": [
        {"pos": "noun", "pron": pron("only-uk.wav", None),
         "senses": [{"definition": "invented: a wugz"}]}]}})
    sense = row("wugz", "n", "wugz#0#0")
    plan = wr.plan(index, [sense], {})
    assert picked(plan, sense, "british") == "only-uk.wav"
    assert picked(plan, sense, "american") is None
    assert plan.fallbacks[wr.NO_ACCENT] == {"american": 1}


def test_a_ref_into_another_words_block_is_not_that_words_recording() -> None:
    # `wugzes` mapped to the page of `wugz`: the recording says "wugz".
    index = index_of({"wugz": {"headword": "wugz", "blocks": [
        {"pos": "noun", "forms": ["wugzes"], "pron": pron("w-uk.wav", "w-us.wav"),
         "senses": [{"definition": "invented: a wugz"}]}]}})
    plural = row("wugzes", "n", "wugz#0#0")
    plan = wr.plan(index, [plural], {})
    assert not plan.picks and plan.fallbacks[wr.OTHER_WORD]["british"] == 1


def test_a_spelling_variant_is_the_same_word() -> None:
    index = index_of({"colourz": {"headword": "colourz", "blocks": [
        {"pos": "noun", "pron": pron("c-uk.wav", "c-us.wav"),
         "senses": [{"definition": "invented: a hue"}]}]}})
    sense = row("colorz", "n", "colourz#0#0")
    assert picked(wr.plan(index, [sense], {}), sense, "american") == "c-us.wav"


def test_a_headword_listed_without_a_definition_still_has_its_recording() -> None:
    index = index_of({"wugz": {"headword": "wugz", "blocks": [
        {"pos": "noun", "pron": pron("w-uk.wav", "w-us.wav"),
         "senses": [{"definition": "invented: a wugz"}]},
        {"headword": "wugzness", "pos": "noun", "pron": pron("n-uk.wav", "n-us.wav"),
         "senses": [{"examples": ["Only an example."]}]},
    ]}})
    sense = row("wugzness", "n")
    plan = wr.plan(index, [sense], {})
    assert picked(plan, sense, "british") == "n-uk.wav"
    assert picked(plan, row("wugzness", "adv"), "british") is None  # not another part of speech


def test_a_pick_whose_file_is_not_there_falls_back(tmp_path: Path) -> None:
    index = index_of({"wugz": {"headword": "wugz", "blocks": [
        {"pos": "noun", "pron": pron("here-uk.wav", "gone-us.wav"),
         "senses": [{"definition": "invented: a wugz"}]}]}})
    write_wav(tmp_path / "media/audio/here-uk.wav")
    sense = row("wugz", "n", "wugz#0#0")
    plan = wr.plan(index, [sense], {}, source_dir=tmp_path)
    assert picked(plan, sense, "british") == "here-uk.wav"
    assert plan.fallbacks[wr.FILE_MISSING] == {"american": 1}


def test_a_row_already_holding_the_planned_file_is_not_done_again() -> None:
    index = index_of({"wugz": {"headword": "wugz", "blocks": [
        {"pos": "noun", "pron": pron("w-uk.wav", "w-us.wav"),
         "senses": [{"definition": "invented: a wugz"}]}]}})
    sense = row("wugz", "n", "wugz#0#0")
    plan = wr.plan(index, [sense], {(sense.id, "british"): "w-uk.wav", (sense.id, "american"): "old.wav"})
    assert plan.already == 1
    assert [rows[0][1] for rows in plan.todo.values()] == ["american"]  # the changed one is redone


# --- normalising a file -----------------------------------------------------------------


@pytest.mark.parametrize("rate", [16_000, 44_100])
def test_a_recording_becomes_24khz_mono_aac_trimmed_and_levelled(tmp_path: Path, rate: int) -> None:
    path = tmp_path / "w.wav"
    write_wav(path, rate=rate, ms=500, amp=0.02, lead_ms=700, tail_ms=700)
    result = wr.process_file(str(path))
    assert isinstance(result, wr.Normalised)
    assert result.data[4:8] == b"ftyp" and result.data.index(b"moov") < result.data.index(b"mdat")
    back = audio_pcm.decode(result.data)
    # The 1.9 s file keeps its 500 ms of sound and ~60 ms of edge either side.
    assert 560 <= result.duration_ms <= 700
    assert abs(audio_pcm.duration_ms(back) - result.duration_ms) < 60
    # ...and sits where a TTS render sits.
    assert abs(result.rms_out_dbfs - audio_pcm.TARGET_RMS_DBFS) < 1.0
    assert abs(audio_pcm.rms_dbfs(back) - audio_pcm.TARGET_RMS_DBFS) < 2.0
    with av.open(io.BytesIO(result.data)) as container:
        stream = container.streams.audio[0]
        assert stream.rate == audio_pcm.SAMPLE_RATE == 24_000 and stream.channels == 1


def test_a_corrupt_or_silent_file_is_a_result_not_a_crash(tmp_path: Path) -> None:
    (tmp_path / "bad.mp3").write_bytes(b"not audio at all")
    write_wav(tmp_path / "silent.wav", amp=0.0)
    for name in ("bad.mp3", "silent.wav", "missing.wav"):
        result = wr.process_file(str(tmp_path / name))
        assert isinstance(result, str) and result.startswith(wr.UNDECODABLE)


def test_a_recording_far_longer_than_a_word_is_refused(tmp_path: Path) -> None:
    write_wav(tmp_path / "long.wav", ms=wr.MAX_RECORDING_MS + 1500)
    result = wr.process_file(str(tmp_path / "long.wav"))
    assert isinstance(result, str) and "too long" in result


# --- the import ------------------------------------------------------------------------------


@pytest.fixture
def storage(monkeypatch) -> FakeStorage:
    fake = FakeStorage()
    monkeypatch.setattr(wr, "get_storage", lambda: fake)
    monkeypatch.setattr(word_audio, "get_storage", lambda: fake)
    return fake


async def _recordings(*sense_ids) -> list[WordRecording]:
    async with async_session_factory() as session:
        return list((await session.exec(
            select(WordRecording).where(WordRecording.lexeme_sense_id.in_(sense_ids))
            .order_by(WordRecording.accent))).all())


async def _import(index, senses, source: Path, *, workers: int = 1):
    async with async_session_factory() as session:
        existing = await wr.load_existing(await session.connection(), [s.id for s in senses])
    decided = wr.plan(index, senses, existing, source_dir=source)
    stats = await wr.run_import(async_session_factory, decided.todo, source,
                                stale=decided.stale, workers=workers)
    return decided, stats


async def test_the_import_stores_normalised_files_once_and_is_idempotent(
    created: Created, storage: FakeStorage, tmp_path: Path,
) -> None:
    lemma = unique_word()
    lexeme, first = await make_lexeme(created, lemma, pos="n")
    from app.models.lexicon import LexemeSense

    async with async_session_factory() as session:
        second = LexemeSense(lexeme_id=lexeme.id, sense_rank=2, definition_en="another thing",
                             meaning_uz="y")
        session.add(second)
        await session.commit()
        await session.refresh(second)
    entries = {lemma: {"headword": lemma, "blocks": [
        {"pos": "noun", "pron": pron("w-uk.wav", "w-us.wav"),
         "senses": [{"definition": "invented one"}, {"definition": "invented two"}]}]}}
    index = index_of(entries)
    write_wav(tmp_path / "media/audio/w-uk.wav", rate=16_000, lead_ms=300)
    write_wav(tmp_path / "media/audio/w-us.wav", rate=44_100, freq=500)
    senses = [
        wr.SenseRow(first.id, lexeme.id, lemma, "n", f"{lemma}#0#0"),
        wr.SenseRow(second.id, lexeme.id, lemma, "n", f"{lemma}#0#1"),
    ]
    decided, stats = await _import(index, senses, tmp_path, workers=2)  # through the process pool
    assert (stats.files, stats.rows, stats.failed) == (2, 4, {})
    rows = await _recordings(first.id, second.id)
    assert len(rows) == 4 and {r.basis for r in rows} == {"ref"}
    # Two senses on one block share one file per accent, under the `rec/` prefix.
    assert len({r.storage_key for r in rows}) == 2 and len(storage.objects) == 2
    assert all(key.startswith("rec/") and key.endswith(".m4a") for key in storage.objects)
    assert {r.source_file for r in rows} == {"w-uk.wav", "w-us.wav"}
    assert all(r.duration_ms > 0 for r in rows)
    stored = audio_pcm.decode(next(iter(storage.objects.values())))
    assert len(stored) > 0

    # Again: nothing to do, nothing duplicated, no new files.
    again, stats = await _import(index, senses, tmp_path)
    assert again.already == 4 and not again.todo and stats.rows == 0
    assert len(await _recordings(first.id, second.id)) == 4 and len(storage.objects) == 2

    # A changed ref replaces the row rather than adding one.
    write_wav(tmp_path / "media/audio/other-uk.wav", freq=700)
    index2 = index_of({lemma: {"headword": lemma, "blocks": [
        {"pos": "noun", "pron": pron("other-uk.wav", "w-us.wav"),
         "senses": [{"definition": "invented one"}, {"definition": "invented two"}]}]}})
    await _import(index2, senses, tmp_path)
    rows = await _recordings(first.id, second.id)
    assert len(rows) == 4
    assert {r.source_file for r in rows if r.accent == "british"} == {"other-uk.wav"}


async def test_a_file_that_cannot_be_read_is_reported_and_the_rest_still_imported(
    created: Created, storage: FakeStorage, tmp_path: Path,
) -> None:
    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma, pos="n")
    index = index_of({lemma: {"headword": lemma, "blocks": [
        {"pos": "noun", "pron": pron("bad-uk.mp3", "ok-us.wav"),
         "senses": [{"definition": "invented"}]}]}})
    (tmp_path / "media/audio").mkdir(parents=True)
    (tmp_path / "media/audio/bad-uk.mp3").write_bytes(b"garbage")
    write_wav(tmp_path / "media/audio/ok-us.wav")
    senses = [wr.SenseRow(sense.id, lexeme.id, lemma, "n", f"{lemma}#0#0")]
    _, stats = await _import(index, senses, tmp_path)
    assert list(stats.failed) == ["bad-uk.mp3"] and stats.rows == 1
    assert [r.accent for r in await _recordings(sense.id)] == ["american"]


async def test_restrict_limits_the_import_to_the_first_lexemes_with_work(created: Created) -> None:
    lemmas = [unique_word() for _ in range(3)]
    index = index_of({lemma: {"headword": lemma, "blocks": [
        {"pos": "noun", "pron": pron(f"{lemma}-uk.wav", f"{lemma}-us.wav"),
         "senses": [{"definition": "invented"}]}]} for lemma in lemmas})
    senses = [row(lemma, "n", f"{lemma}#0#0") for lemma in lemmas]
    cut = wr.restrict(wr.plan(index, senses, {}), senses, 2)
    assert sum(len(v) for v in cut.todo.values()) == 4  # 2 lexemes x 2 accents
    assert cut.covered("british") == 3  # the coverage figures stay the whole plan's


# --- what a learner hears ---------------------------------------------------------------------------


async def _add_recording(sense_id, accent: str, key: str) -> None:
    async with async_session_factory() as session:
        session.add(WordRecording(lexeme_sense_id=sense_id, accent=accent, storage_key=key,
                                  duration_ms=700, source_file="x.mp3", basis="ref"))
        await session.commit()


async def test_recorded_serves_the_recording_in_the_learners_accent_and_queues_nothing(
    created: Created,
) -> None:
    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma)
    await _add_recording(sense.id, "british", "rec/gb.m4a")
    await _add_recording(sense.id, "american", "rec/us.m4a")
    gb_key = tts.word_spec(lemma, None).key
    created.render_keys.append(gb_key)
    async with async_session_factory() as session:
        gb = await word_audio.word_audio(session, sense, lexeme)
        us = await word_audio.word_audio(session, sense, lexeme, accent="american")
        explicit = await word_audio.word_audio(session, sense, lexeme, word_voice="recorded")
    assert gb == explicit == word_audio.AudioOut(url="/media/rec/gb.m4a")
    assert us == word_audio.AudioOut(url="/media/rec/us.m4a")
    async with async_session_factory() as session:
        queued = (await session.exec(select(AudioRender).where(AudioRender.key == gb_key))).all()
    assert queued == []  # a word a person already said is not synthesised


async def test_synthetic_ignores_the_recording_and_takes_the_tts_path(created: Created) -> None:
    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma)
    await _add_recording(sense.id, "british", "rec/gb.m4a")
    spec = tts.word_spec(lemma, None)
    created.render_keys.append(spec.key)
    async with async_session_factory() as session:
        assert await word_audio.word_audio(session, sense, lexeme, word_voice="synthetic") is None
        rows = (await session.exec(select(AudioRender).where(AudioRender.key == spec.key))).all()
    assert len(rows) == 1 and rows[0].status == "pending"  # queued, exactly as before


async def test_no_recording_for_the_accent_falls_back_to_tts(created: Created) -> None:
    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma)
    await _add_recording(sense.id, "british", "rec/gb.m4a")  # no American one
    spec = tts.word_spec(lemma, None, "american")
    created.render_keys.append(spec.key)
    async with async_session_factory() as session:
        assert await word_audio.word_audio(session, sense, lexeme, accent="american") is None
        rows = (await session.exec(select(AudioRender).where(AudioRender.key == spec.key))).all()
    assert len(rows) == 1 and rows[0].voice == "af_heart"


async def test_the_default_voice_is_recorded() -> None:
    from app.services.accents import DEFAULT_WORD_VOICE

    assert DEFAULT_WORD_VOICE == "recorded"


async def test_a_list_is_resolved_without_a_query_per_word(created: Created) -> None:
    async def statements_for(count: int) -> int:
        senses = []
        for i in range(count):
            lexeme, sense = await make_lexeme(created, unique_word())
            created.render_keys.append(tts.word_spec(lexeme.lemma, None).key)
            if i % 2 == 0:
                await _add_recording(sense.id, "british", f"rec/{i}-{sense.id}.m4a")
            senses.append(sense)
        seen: list[str] = []
        engine = async_session_factory.kw["bind"].sync_engine

        def record(conn, cursor, statement, *rest) -> None:
            seen.append(statement)

        async with async_session_factory() as session:
            event.listen(engine, "before_cursor_execute", record)
            try:
                out = await word_audio.word_audio_many(session, senses)
            finally:
                event.remove(engine, "before_cursor_execute", record)
        assert sum(1 for v in out.values() if v is not None) == (count + 1) // 2
        return len([s for s in seen if "word_recordings" in s])

    # One recordings query however many words, and the TTS path's own count
    # does not grow with it either.
    assert await statements_for(2) == 1
    assert await statements_for(12) == 1


# --- the worker's hook ----------------------------------------------------------------------------------


async def test_the_hook_attaches_recordings_only_where_the_source_is_configured(
    created: Created, storage: FakeStorage, tmp_path: Path, monkeypatch, caplog,
) -> None:
    from app.core.config import settings

    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma, pos="n")
    async with async_session_factory() as session:
        sense_row = await session.get(type(sense), sense.id)
        sense_row.cald_ref = f"{lemma}#0#0"
        await session.commit()
    index = index_of({lemma: {"headword": lemma, "blocks": [
        {"pos": "noun", "pron": pron("h-uk.wav", "h-us.wav"),
         "senses": [{"definition": "invented"}]}]}})
    write_wav(tmp_path / "media/audio/h-uk.wav")
    write_wav(tmp_path / "media/audio/h-us.wav")

    monkeypatch.setattr(settings, "cald_source_dir", "")
    wr._said.clear()
    with caplog.at_level("INFO", logger="app.services.word_recordings"):
        assert not await wr.attach_for_lexemes(index, [lexeme.id])
        assert not await wr.attach_for_lexemes(index, [lexeme.id])
    assert sum("not configured" in r.getMessage() for r in caplog.records) == 1  # one line
    assert await _recordings(sense.id) == []

    monkeypatch.setattr(settings, "cald_source_dir", str(tmp_path))
    counts = await wr.attach_for_lexemes(index, [lexeme.id])
    assert counts["recordings"] == 2
    assert len(await _recordings(sense.id)) == 2
    assert not await wr.attach_for_lexemes(index, [lexeme.id])  # idempotent: nothing left to do


# --- review fixes --------------------------------------------------------------------------------------


def test_a_pos_pick_prefers_one_block_with_both_accents() -> None:
    index = index_of({"wugz": {"headword": "wugz", "blocks": [
        {"pos": "noun", "guideword": "A", "pron": pron("a-uk.wav", None),  # UK only
         "senses": [{"definition": "invented: a wugz"}]},
        {"pos": "noun", "guideword": "B", "pron": pron("b-uk.wav", "b-us.wav"),
         "senses": [{"definition": "invented: another wugz"}]},
    ]}})
    sense = row("wugz", "n")
    plan = wr.plan(index, [sense], {})
    assert picked(plan, sense, "british") == "b-uk.wav"  # not A's, though A comes first
    assert picked(plan, sense, "american") == "b-us.wav"


def test_a_heteronym_never_takes_the_entrys_recording_for_a_block_without_its_own() -> None:
    index = index_of({"record": {"headword": "record", "pron": pron("entry-uk.wav", "entry-us.wav"),
                                 "blocks": [
        {"pos": "noun", "pron": pron("noun-uk.wav", "noun-us.wav"),
         "senses": [{"definition": "invented: a written account"}]},
        {"pos": "verb",  # no pron of its own: the index gives it the entry's
         "senses": [{"definition": "invented: to write down"}]},
    ]}})
    noun, verb = row("record", "n", "record#0#0"), row("record", "v", "record#1#0")
    plan = wr.plan(index, [noun, verb], {})
    assert picked(plan, noun, "british") == "noun-uk.wav"
    assert picked(plan, verb, "british") is None and picked(plan, verb, "american") is None
    assert plan.fallbacks[wr.NO_ACCENT] == {"british": 1, "american": 1}


def test_the_entrys_recording_is_fine_for_a_word_that_is_not_a_heteronym() -> None:
    index = index_of({"wugz": {"headword": "wugz", "pron": pron("e-uk.wav", "e-us.wav"), "blocks": [
        {"pos": "noun", "senses": [{"definition": "invented: a wugz"}]}]}})
    sense = row("wugz", "n", "wugz#0#0")
    assert picked(wr.plan(index, [sense], {}), sense, "british") == "e-uk.wav"


def test_a_redirect_page_key_counts_only_when_it_is_a_variant_of_the_headword() -> None:
    index = index_of({
        # the search for `advisr` landed on a page showing `adviser`: a one-edit variant
        "advisr": {"headword": "advisr", "blocks": [
            {"headword": "adviser", "pos": "noun", "pron": pron("a-uk.wav", "a-us.wav"),
             "senses": [{"definition": "invented: someone who advises"}]}]},
        # the search for `zork` landed on `plimb`: another word
        "zork": {"headword": "zork", "blocks": [
            {"headword": "plimb", "pos": "noun", "pron": pron("p-uk.wav", "p-us.wav"),
             "senses": [{"definition": "invented: a thing"}]}]},
    })
    same, other = row("advisr", "n", "advisr#0#0"), row("zork", "n", "zork#0#0")
    plan = wr.plan(index, [same, other], {})
    assert picked(plan, same, "british") == "a-uk.wav"
    assert picked(plan, other, "british") is None
    assert plan.fallbacks[wr.OTHER_WORD]["british"] == 1
    assert wr.redirect_mismatches(index) == 1


def test_a_row_with_no_pick_any_more_is_stale_but_a_missing_source_file_is_not(tmp_path: Path) -> None:
    index = index_of({"wugz": {"headword": "wugz", "blocks": [
        {"pos": "noun", "pron": pron("here-uk.wav", "gone-us.wav"),
         "senses": [{"definition": "invented: a wugz"}]}]}})
    write_wav(tmp_path / "media/audio/here-uk.wav")
    kept, dropped, outside = row("wugz", "n", "wugz#0#0"), row("zzabsent", "n"), row("wugz", "n")
    existing = {
        (kept.id, "british"): "here-uk.wav",
        (kept.id, "american"): "gone-us.wav",   # the file is not in the source today: leave the row
        (dropped.id, "british"): "old.wav",     # the sense now has no headword: stale
    }
    plan = wr.plan(index, [kept, dropped], existing, source_dir=tmp_path)
    assert plan.stale == [(dropped.id, "british")]
    # A sense the plan did not cover is never touched.
    assert wr.plan(index, [outside], {(dropped.id, "british"): "old.wav"}).stale == []


async def test_the_import_deletes_stale_rows_and_never_the_files(
    created: Created, storage: FakeStorage, tmp_path: Path,
) -> None:
    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma, pos="n")
    entries = {lemma: {"headword": lemma, "blocks": [
        {"pos": "noun", "pron": pron("w-uk.wav", "w-us.wav"), "senses": [{"definition": "invented"}]}]}}
    write_wav(tmp_path / "media/audio/w-uk.wav")
    write_wav(tmp_path / "media/audio/w-us.wav", freq=600)
    senses = [wr.SenseRow(sense.id, lexeme.id, lemma, "n", f"{lemma}#0#0")]
    await _import(index_of(entries), senses, tmp_path)
    assert len(await _recordings(sense.id)) == 2 and len(storage.objects) == 2
    # The ref is cleared (what `restore` does) and the lemma is a heteronym now: no pick.
    senses = [wr.SenseRow(sense.id, lexeme.id, "record", "n", None)]
    index = index_of({"record": {"headword": "record", "blocks": [
        {"pos": "noun", "pron": pron("x-uk.wav", "x-us.wav"), "senses": [{"definition": "invented"}]}]}})
    decided, stats = await _import(index, senses, tmp_path)
    assert len(decided.stale) == 2 and stats.stale_removed == 2
    assert await _recordings(sense.id) == []
    assert len(storage.objects) == 2  # shared, content-addressed: never deleted


async def test_restore_drops_the_senses_recordings(created: Created) -> None:
    from datetime import datetime, timezone

    from app.models.lexicon import LexemeSense

    lexeme, sense = await make_lexeme(created, unique_word(), pos="n")
    async with async_session_factory() as session:
        row_ = await session.get(LexemeSense, sense.id)
        row_.definition_source, row_.cald_ref = "cald", "x#0#0"
        row_.definition_en_pre_cald, row_.cald_applied_at = "ours", datetime.now(timezone.utc)
        await session.commit()
    await _add_recording(sense.id, "british", "rec/a.m4a")
    async with async_session_factory() as session:
        counts, _ = await lc.restore_senses(session, [sense.id])
        await session.commit()
    assert counts["senses restored"] == 1
    assert await _recordings(sense.id) == []


async def test_check_files_removes_only_rows_whose_file_is_not_in_storage(
    created: Created, storage: FakeStorage,
) -> None:
    _, sense = await make_lexeme(created, unique_word())
    await _add_recording(sense.id, "british", "rec/present.m4a")
    await _add_recording(sense.id, "american", "rec/absent.m4a")
    storage.objects["rec/present.m4a"] = b"x"
    only = await wr.check_files(async_session_factory, delete=False)
    assert only["files_missing"] >= 1 and only["rows_removed"] == 0
    assert len(await _recordings(sense.id)) == 2
    done = await wr.check_files(async_session_factory, delete=True)
    assert done["rows_removed"] >= 1
    assert [r.accent for r in await _recordings(sense.id)] == ["british"]


async def test_a_broken_pool_ends_the_run_and_reports_the_rest_as_failed(
    created: Created, storage: FakeStorage, tmp_path: Path, monkeypatch,
) -> None:
    from concurrent.futures.process import BrokenProcessPool

    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma, pos="n")
    for name in ("a", "b", "c"):
        write_wav(tmp_path / f"media/audio/{name}.wav")
    calls: list[str] = []
    real = wr._process

    async def flaky(pool, gate, path):
        calls.append(path)
        if path.endswith("b.wav"):
            raise BrokenProcessPool("a worker died")
        return await real(pool, gate, path)

    monkeypatch.setattr(wr, "_process", flaky)
    todo = {f"media/audio/{n}.wav": [(sense.id, a, "ref")] for n, a in
            (("a", "british"), ("b", "american"), ("c", "british"))}
    # `c` shares the sense and accent with `a`: only the first window matters here.
    stats = await wr.run_import(async_session_factory, todo, tmp_path, window=1, workers=1)
    assert [p.rsplit("/", 1)[-1] for p in calls] == ["a.wav", "b.wav"]  # stopped: c never started
    assert stats.files == 1 and set(stats.failed) == {"b.wav", "c.wav"}


async def test_failed_words_skips_the_tts_word_key_of_a_word_that_has_audio(created: Created) -> None:
    from types import SimpleNamespace

    from sqlalchemy import update

    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma)
    spec = tts.word_spec(lemma, None)
    created.render_keys.append(spec.key)
    await tts.enqueue([spec])  # an old TTS render of this word that FAILED
    async with async_session_factory() as session:
        await session.execute(update(AudioRender).where(AudioRender.key == spec.key).values(status="failed"))
        await session.commit()
    created.render_keys.append(tts.definition_spec(sense.definition_en, lemma).key)
    word = SimpleNamespace(id=sense.id, lexeme_sense_id=sense.id)
    from app.services import on_the_go

    async with async_session_factory() as session:
        args = ([word], {sense.id: sense}, {lexeme.id: lexeme})
        assert await on_the_go._failed_words(session, *args) == {word.id}
        # Answered by a recording: its word part cannot have failed.
        assert await on_the_go._failed_words(session, *args, word_ready={sense.id}) == set()


async def test_the_sweep_picks_up_a_sense_the_hook_never_saw_and_then_goes_quiet(
    created: Created, storage: FakeStorage, tmp_path: Path, monkeypatch,
) -> None:
    from app.core.config import settings

    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma, pos="n")  # no cald_ref: the hook skipped it
    index = index_of({lemma: {"headword": lemma, "blocks": [
        {"pos": "noun", "pron": pron("s-uk.wav", "s-us.wav"), "senses": [{"definition": "invented"}]}]}})
    write_wav(tmp_path / "media/audio/s-uk.wav")
    write_wav(tmp_path / "media/audio/s-us.wav")
    loads: list[int] = []

    def fake_index(out_dir):
        loads.append(1)
        return index

    monkeypatch.setattr(lc, "worker_index", fake_index)
    monkeypatch.setattr(settings, "cald_recordings_workers", 1)
    wr.reset_sweep_state()

    monkeypatch.setattr(settings, "cald_source_dir", "")
    assert not await wr.sweep(tmp_path) and not loads  # no source: nothing, not even the index

    monkeypatch.setattr(settings, "cald_source_dir", str(tmp_path))  # configured LATER
    counts = await wr.sweep(tmp_path)
    assert counts["recordings"] >= 2 and len(await _recordings(sense.id)) == 2
    assert len(loads) == 1
    assert not await wr.sweep(tmp_path) and len(loads) == 1  # unchanged: the scan is skipped
    wr.reset_sweep_state()

"""The learner's accent (vocabulary stage 3, decisions 22-26): the setting, the
voice each accent is rendered in, and what it does -- and does not -- change."""

import json
import re
from pathlib import Path

from sqlmodel import select

from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.models.audio_render import AudioRender
from app.services import accents, practice as practice_service, tts, word_audio
from app.services import heteronym_decisions as hd
from app.services import pronunciation as pron
from scripts import decide_heteronyms
from tests.audio_helpers import (
    Created, FakeStorage, FakeSynth, add_clip, make_blob, make_lexeme, make_user,
    sentence, unique_word,
)
from tests.test_heteronyms import FakeGemini
from tests.test_vocabulary_audio_practice import (  # noqa: F401 - `created` is a fixture
    DEFINITION, _client, _word, created,
)


async def _rows(*keys: str) -> list[AudioRender]:
    async with async_session_factory() as session:
        return list((await session.exec(select(AudioRender).where(AudioRender.key.in_(keys)))).all())


# --- the setting -----------------------------------------------------------------


async def test_accent_defaults_to_british_round_trips_and_is_optional_on_put(created: Created) -> None:
    user = await make_user(created)
    cookies = {"access_token": create_access_token(str(user.id))}
    body = {"daily_minutes": 10, "direction": "passive", "exercise_types": None}
    async with _client() as client:
        assert (await client.get("/api/vocabulary/settings", cookies=cookies)).json()["accent"] == "british"
        r = await client.put("/api/vocabulary/settings", cookies=cookies, json={**body, "accent": "american"})
        assert r.json()["accent"] == "american"
        r = await client.put("/api/vocabulary/settings", cookies=cookies, json={**body, "daily_minutes": 15})
        assert r.json()["accent"] == "american"  # absent = unchanged
        assert (await client.get("/api/vocabulary/settings", cookies=cookies)).json()["accent"] == "american"
        r = await client.put("/api/vocabulary/settings", cookies=cookies, json={**body, "accent": "australian"})
        assert r.status_code == 422


# --- one table, distinct keys -----------------------------------------------------


def test_the_accent_table_is_the_one_source_of_voices() -> None:
    assert accents.ACCENTS["british"].voice == "bf_emma" and accents.ACCENTS["british"].lang_code == "b"
    assert accents.ACCENTS["american"].voice == "af_heart" and accents.ACCENTS["american"].lang_code == "a"
    assert accents.lang_code_for_voice("af_heart") == "a"


def test_every_kind_of_render_has_its_own_key_per_accent() -> None:
    gb_word, us_word = tts.word_spec("abandon", None), tts.word_spec("abandon", None, "american")
    assert gb_word == tts.word_spec("abandon", None, "british")  # British is the default
    assert gb_word.key != us_word.key and us_word.voice == "af_heart"
    gb_def = tts.definition_spec("to abandon something", "abandon")
    us_def = tts.definition_spec("to abandon something", "abandon", "american")
    assert gb_def.key != us_def.key and us_def.voice == "af_heart"
    gb_item = tts.item_spec(gb_def, word_spec_=gb_word, clip_storage_key=None)
    us_item = tts.item_spec(us_def, word_spec_=us_word, clip_storage_key=None)
    assert gb_item.key != us_item.key and us_item.voice == "af_heart"
    # a clip-worded item is still one per accent: its definition is the voice
    gb_clip = tts.item_spec(gb_def, word_spec_=None, clip_storage_key="clips/x.m4a")
    us_clip = tts.item_spec(us_def, word_spec_=None, clip_storage_key="clips/x.m4a")
    assert gb_clip.key != us_clip.key


async def test_the_worker_speaks_each_row_in_its_own_voice(created: Created) -> None:
    lemma = unique_word()
    definition = tts.definition_spec(f"to {lemma} something completely", lemma, "american")
    word = tts.word_spec(lemma, None, "american")
    item = tts.item_spec(definition, word_spec_=word, clip_storage_key=None)
    created.render_keys.extend([definition.key, word.key, item.key])
    await tts.enqueue([item])
    synth = FakeSynth()
    assert await tts.drain(synth, keys=[item.key], storage=FakeStorage()) == 1
    assert synth.voices and set(synth.voices) == {"af_heart"}  # parts made inline, same voice
    assert all(r.voice == "af_heart" for r in await _rows(definition.key, word.key, item.key))


# --- resolution ---------------------------------------------------------------------


async def test_a_plain_word_is_queued_in_the_learners_voice_only(created: Created) -> None:
    lemma = unique_word()
    _, sense = await make_lexeme(created, lemma)
    gb, us = tts.word_spec(lemma, None), tts.word_spec(lemma, None, "american")
    created.render_keys.extend([gb.key, us.key])
    async with async_session_factory() as session:
        assert await word_audio.word_audio(session, sense, accent="american") is None
    assert [r.key for r in await _rows(gb.key, us.key)] == [us.key]  # no British row


async def test_a_verified_clip_is_heard_by_both_accents_and_queues_nothing(created: Created) -> None:
    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma)
    blob = await make_blob(created, [sentence(["a", lemma, "c", "d"])])
    await add_clip(blob, lemma)
    keys = [tts.word_spec(lemma, None, a).key for a in accents.ACCENT_NAMES]
    created.render_keys.extend(keys)
    async with async_session_factory() as session:
        gb = await word_audio.word_audio(session, sense, lexeme)
        us = await word_audio.word_audio(session, sense, lexeme, accent="american")
    assert gb is not None and gb == us and gb.source == "clip"
    assert await _rows(*keys) == []


async def test_a_heteronym_uses_the_column_of_the_learners_accent(created: Created) -> None:
    lexeme, sense = await make_lexeme(
        created, "record", pos="v", pronunciation="ɹɪkˈɔːd", pronunciation_us="ɹəkˈɔɹd",
        definition="make a record of; set down in permanent form",
    )
    blob = await make_blob(created, [sentence(["a", "record", "c", "d"])])
    await add_clip(blob, "record")  # a heteronym is never a clip, in either accent
    gb = tts.word_spec("record", "ɹɪkˈɔːd")
    us = tts.word_spec("record", "ɹəkˈɔɹd", "american")
    created.render_keys.extend([gb.key, us.key])
    async with async_session_factory() as session:
        assert await word_audio.word_audio(session, sense, lexeme) is None
        assert await word_audio.word_audio(session, sense, lexeme, accent="american") is None
    rows = {r.key: r for r in await _rows(gb.key, us.key)}
    assert rows[gb.key].input == "[record](/ɹɪkˈɔːd/)" and rows[gb.key].voice == "bf_emma"
    assert rows[us.key].input == "[record](/ɹəkˈɔɹd/)" and rows[us.key].voice == "af_heart"


async def test_an_undecided_american_heteronym_falls_back_to_misakis_american_entry(
    created: Created,
) -> None:
    lexeme, sense = await make_lexeme(created, "record", pos="v", pronunciation="ɹɪkˈɔːd")
    expected = tts.word_spec("record", "ɹəkˈɔɹd", "american")  # misaki US VERB, not the GB column
    created.render_keys.append(expected.key)
    async with async_session_factory() as session:
        await word_audio.word_audio(session, sense, lexeme, accent="american")
    assert [r.input for r in await _rows(expected.key)] == ["[record](/ɹəkˈɔɹd/)"]


async def test_definitions_and_items_are_queued_in_the_learners_voice(created: Created) -> None:
    lemma = unique_word()
    _, sense = await make_lexeme(created, lemma, definition=f"to {lemma} something completely")
    gb_def = tts.definition_spec(sense.definition_en, lemma)
    us_def = tts.definition_spec(sense.definition_en, lemma, "american")
    created.render_keys.extend([gb_def.key, us_def.key])
    async with async_session_factory() as session:
        assert await word_audio.definition_audio_url(session, sense, accent="american") is None
    assert [r.key for r in await _rows(gb_def.key, us_def.key)] == [us_def.key]


# --- the callers use the learner's own setting ------------------------------------------


async def test_on_the_go_and_the_word_page_queue_only_the_learners_accent(created: Created) -> None:
    user = await make_user(created)
    word = await _word(created, user, level="recognise", due=False)
    cookies = {"access_token": create_access_token(str(user.id))}
    gb = tts.word_spec(word.lemma, None)
    us = tts.word_spec(word.lemma, None, "american")
    us_def = tts.definition_spec(DEFINITION, word.lemma, "american")
    us_item = tts.item_spec(us_def, word_spec_=us, clip_storage_key=None)
    gb_def = tts.definition_spec(DEFINITION, word.lemma)
    gb_item = tts.item_spec(gb_def, word_spec_=gb, clip_storage_key=None)
    created.render_keys.extend([gb.key, us.key, us_def.key, gb_def.key, us_item.key, gb_item.key])
    async with _client() as client:
        await client.put(
            "/api/vocabulary/settings", cookies=cookies,
            json={"daily_minutes": 10, "direction": "passive", "exercise_types": None, "accent": "american"},
        )
        assert (await client.get("/api/vocabulary/on-the-go", cookies=cookies)).status_code == 200
        assert (await client.get(f"/api/vocabulary/words/{word.id}", cookies=cookies)).status_code == 200
    assert {r.key for r in await _rows(gb.key, gb_def.key, gb_item.key)} == set()
    assert {r.key for r in await _rows(us.key, us_def.key, us_item.key)} == {us.key, us_def.key, us_item.key}


async def test_a_practice_session_asks_for_audio_in_the_learners_accent(created: Created) -> None:
    from tests.test_vocabulary_audio_practice import _session

    user = await make_user(created)
    word = await _word(created, user, level="listen")
    async with async_session_factory() as session:
        await practice_service.update_settings(
            session, user.id, daily_minutes=20, direction="passive", exercise_types=None,
            accent="american",
        )
    gb, us = tts.word_spec(word.lemma, None), tts.word_spec(word.lemma, None, "american")
    created.render_keys.extend([gb.key, us.key])
    await _session(user)
    assert [r.key for r in await _rows(gb.key, us.key)] == [us.key]


# --- the decisions, per accent --------------------------------------------------------------


async def test_decide_and_apply_are_per_accent(created: Created, tmp_path: Path) -> None:
    _, verb = await make_lexeme(created, "record", pos="v", definition="set down in permanent form")
    async with async_session_factory() as session:
        mine = [r for r in await hd.heteronym_senses(session, "american") if r.sense_id == verb.id]
    assert len(mine) == 1
    log = hd.DecisionLog(tmp_path / "us.jsonl")
    gemini = FakeGemini(lambda line: 2)  # 1 = DEFAULT, 2 = VERB
    report = await hd.decide(gemini, log, mine, accent="american")
    assert report.decided == 1
    assert "American" in gemini.prompts[0] and "/ɹˈɛkəɹd/" in gemini.prompts[0]
    assert log.get("record", "v", None, "set down in permanent form") == "ɹəkˈɔɹd"
    assert json.loads((tmp_path / "us.jsonl").read_text())["ipa"] == "ɹəkˈɔɹd"
    async with async_session_factory() as session:
        applied = await hd.apply(session, log, "american")
    assert applied.written == 1 and applied.stale == []
    async with async_session_factory() as session:
        stored = (await session.exec(select(type(verb)).where(type(verb).id == verb.id))).one()
    assert stored.pronunciation_us == "ɹəkˈɔɹd" and stored.pronunciation is None  # the other column is untouched
    # A British string is stale for the American accent: reported, not written.
    bad = hd.DecisionLog(None)
    bad.put("record", "v", None, "set down in permanent form", "ɹɪkˈɔːd", "test")
    async with async_session_factory() as session:
        stale = await hd.apply(session, bad, "american")
    assert stale.stale and stale.written == 0


def test_the_script_picks_the_accents_own_log_and_column() -> None:
    _, gb = decide_heteronyms.parse_args(["decide", "--confirm-db", "x"])
    _, us = decide_heteronyms.parse_args(["apply", "--confirm-db", "x", "--accent", "american"])
    assert gb.accent == "british" and gb.decisions.name == "heteronym_decisions.jsonl"
    assert us.accent == "american" and us.decisions.name == "heteronym_decisions_us.jsonl"
    assert re.fullmatch(r"heteronym_decisions_us\.jsonl", hd.LOG_PATHS["american"].name)

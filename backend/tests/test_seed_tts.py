"""scripts/seed_tts.py and the worker's audio steps -- real DB, fake Kokoro and
fake storage (no model, no GPU), like test_seed_audio.py."""

import logging

import pytest
from sqlalchemy import update
from sqlmodel import select

from app.core.database import async_session_factory
from app.models.audio_render import AudioRender, RenderStatus
from app.models.vocabulary import SavedWord
from app.services import lexicon_licences, tts
from app.worker import _render_loop
from scripts import seed_tts
from tests.audio_helpers import (
    Created,
    FakeStorage,
    FakeSynth,
    make_lexeme,
    make_user,
    unique_word,
)


@pytest.fixture
async def created():
    made = Created()
    yield made
    await made.cleanup()


async def _saved(created: Created, lexeme, sense) -> None:
    user = await make_user(created)
    async with async_session_factory() as session:
        session.add(SavedWord(user_id=user.id, lemma=lexeme.lemma, lexeme_sense_id=sense.id))
        await session.commit()


async def _row(key: str) -> AudioRender | None:
    async with async_session_factory() as session:
        return (await session.exec(select(AudioRender).where(AudioRender.key == key))).first()


async def test_saved_only_queues_just_the_words_somebody_saved(created: Created) -> None:
    kept, other = unique_word(), unique_word()
    kept_lexeme, kept_sense = await make_lexeme(created, kept)
    await make_lexeme(created, other)
    await _saved(created, kept_lexeme, kept_sense)
    keys = [tts.word_spec(w, None).key for w in (kept, other)]
    created.render_keys.extend(keys)
    async with async_session_factory() as session:
        await seed_tts.enqueue_words(session, saved_only=True, limit=None, accents_=["british"])
    assert await _row(keys[0]) is not None and await _row(keys[1]) is None


async def test_accent_both_queues_each_voice_and_one_accent_only_its_own(created: Created) -> None:
    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma, definition=f"to {lemma} something")
    await _saved(created, lexeme, sense)
    gb_word, us_word = tts.word_spec(lemma, None, "british"), tts.word_spec(lemma, None, "american")
    gb_def = tts.definition_spec(sense.definition_en, lemma, "british")
    us_def = tts.definition_spec(sense.definition_en, lemma, "american")
    keys = [gb_word.key, us_word.key, gb_def.key, us_def.key]
    assert len(set(keys)) == 4 and us_word.voice == "af_heart" and gb_word.voice == "bf_emma"
    created.render_keys.extend(keys)
    async with async_session_factory() as session:
        await seed_tts.enqueue_words(session, saved_only=True, limit=None, accents_=["american"])
        await seed_tts.enqueue_definitions(session, saved_only=True, limit=None, accents_=["american"])
    assert [bool(await _row(k)) for k in keys] == [False, True, False, True]
    both = seed_tts.selected_accents(seed_tts._parse_args(["words"]))
    assert both == ["british", "american"]  # the default is both
    assert seed_tts.selected_accents(seed_tts._parse_args(["words", "--accent", "american"])) == ["american"]
    async with async_session_factory() as session:
        await seed_tts.enqueue_words(session, saved_only=True, limit=None, accents_=both)
        await seed_tts.enqueue_definitions(session, saved_only=True, limit=None, accents_=both)
    assert all([bool(await _row(k)) for k in keys])
    # the row carries its own voice, and the drain speaks each in it
    synth = FakeSynth()
    await tts.drain(synth, keys=keys, storage=FakeStorage())
    assert sorted(set(synth.voices)) == ["af_heart", "bf_emma"]


async def test_heteronym_words_are_queued_with_their_pronunciation(created: Created) -> None:
    lexeme, sense = await make_lexeme(created, "record", pos="v", pronunciation="ɹɪkˈɔːd")
    await _saved(created, lexeme, sense)
    key = tts.word_spec("record", "ɹɪkˈɔːd").key
    created.render_keys.append(key)
    async with async_session_factory() as session:
        await seed_tts.enqueue_words(session, saved_only=True, limit=None, accents_=["british"])
    row = await _row(key)
    assert row is not None and row.input == "[record](/ɹɪkˈɔːd/)"


async def test_the_seed_drains_the_queue_in_process_and_writes_the_workers_rows(
    created: Created,
) -> None:
    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma, definition=f"to {lemma} something completely")
    await _saved(created, lexeme, sense)
    word = tts.word_spec(lemma, None)
    definition = tts.definition_spec(sense.definition_en, lemma)
    created.render_keys.extend([word.key, definition.key])
    storage, synth = FakeStorage(), FakeSynth()
    async with async_session_factory() as session:
        await seed_tts.enqueue_words(session, saved_only=True, limit=None, accents_=["british"])
        await seed_tts.enqueue_definitions(session, saved_only=True, limit=None, accents_=["british"])
    done = await tts.drain(synth, keys=[word.key, definition.key], storage=storage)
    assert done == 2
    for spec in (word, definition):
        row = await _row(spec.key)
        assert row.status == RenderStatus.READY
        assert row.storage_key == f"tts/{spec.key}.m4a"  # the key the worker would write
        assert row.storage_key in storage.objects
    # Run again: nothing new to make.
    async with async_session_factory() as session:
        await seed_tts.enqueue_words(session, saved_only=True, limit=None, accents_=["british"])
    assert await tts.drain(synth, keys=[word.key, definition.key], storage=storage) == 0


# --- the worker's audio steps ----------------------------------------------------


async def test_the_render_loop_says_once_that_it_is_off_without_kokoro(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(tts, "kokoro_available", lambda: False)
    with caplog.at_level(logging.INFO, logger="app.worker"):
        await _render_loop()  # returns at once: nothing to run
    messages = [r.getMessage() for r in caplog.records if r.name == "app.worker"]
    assert messages == ["text to speech disabled (kokoro is not installed in this image)"]


# --- licences --------------------------------------------------------------------


async def test_the_licences_page_credits_kokoro_and_misaki_once_audio_exists(
    created: Created,
) -> None:
    spec = tts.word_spec(unique_word(), None)
    created.render_keys.append(spec.key)
    await tts.enqueue([spec])
    async with async_session_factory() as session:
        await session.execute(
            update(AudioRender).where(AudioRender.key == spec.key).values(status="ready")
        )
        await session.commit()
        rows = {r["key"]: r for r in await lexicon_licences.sources(session)}
    for key in ("kokoro", "misaki"):
        assert rows[key]["licence_name"] == "Apache-2.0"
        assert rows[key]["authors"] == "hexgrad" and rows[key]["count"] >= 1
        assert rows[key]["source_url"].startswith("https://")

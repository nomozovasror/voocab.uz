"""scripts/seed_tts.py and the worker's audio steps -- real DB, fake Kokoro and
fake storage (no model, no GPU), like test_seed_audio.py."""

import logging

import pytest
from sqlalchemy import update
from sqlmodel import select

from app.core.database import async_session_factory
from app.models.audio_render import AudioRender, RenderStatus
from app.models.vocabulary import SavedWord
from app.services import lexicon_licences, tts, word_clips
from app.worker import _render_loop, clips_once
from scripts import seed_tts
from tests.audio_helpers import (
    Created,
    FakeStorage,
    FakeSynth,
    add_clip,
    make_blob,
    make_lexeme,
    make_user,
    sentence,
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
        await seed_tts.enqueue_words(session, saved_only=True, limit=None, include_clipped=False)
    assert await _row(keys[0]) is not None and await _row(keys[1]) is None


async def test_a_word_with_a_verified_clip_gets_no_tts_unless_asked(created: Created) -> None:
    clipped, bare = unique_word(), unique_word()
    for lemma in (clipped, bare):
        lexeme, sense = await make_lexeme(created, lemma)
        await _saved(created, lexeme, sense)
    blob = await make_blob(created, [sentence(["a", clipped, "c", "d"])])
    await add_clip(blob, clipped)
    keys = {w: tts.word_spec(w, None).key for w in (clipped, bare)}
    created.render_keys.extend(keys.values())
    async with async_session_factory() as session:
        await seed_tts.enqueue_words(session, saved_only=True, limit=None, include_clipped=False)
    assert await _row(keys[clipped]) is None and await _row(keys[bare]) is not None
    async with async_session_factory() as session:
        await seed_tts.enqueue_words(session, saved_only=True, limit=None, include_clipped=True)
    assert await _row(keys[clipped]) is not None  # --all


async def test_heteronym_words_are_queued_with_their_pronunciation(created: Created) -> None:
    lexeme, sense = await make_lexeme(created, "record", pos="v", pronunciation="ɹɪkˈɔːd")
    await _saved(created, lexeme, sense)
    key = tts.word_spec("record", "ɹɪkˈɔːd").key
    created.render_keys.append(key)
    async with async_session_factory() as session:
        await seed_tts.enqueue_words(session, saved_only=True, limit=None, include_clipped=False)
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
        await seed_tts.enqueue_words(session, saved_only=True, limit=None, include_clipped=False)
        await seed_tts.enqueue_definitions(session, saved_only=True, limit=None)
    done = await tts.drain(synth, keys=[word.key, definition.key], storage=storage)
    assert done == 2
    for spec in (word, definition):
        row = await _row(spec.key)
        assert row.status == RenderStatus.READY
        assert row.storage_key == f"tts/{spec.key}.m4a"  # the key the worker would write
        assert row.storage_key in storage.objects
    # Run again: nothing new to make.
    async with async_session_factory() as session:
        await seed_tts.enqueue_words(session, saved_only=True, limit=None, include_clipped=False)
    assert await tts.drain(synth, keys=[word.key, definition.key], storage=storage) == 0


async def test_items_for_words_in_rotation_are_queued_with_their_parts(created: Created) -> None:
    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma, definition=f"to {lemma} something")
    await _saved(created, lexeme, sense)
    definition = tts.definition_spec(sense.definition_en, lemma)
    word = tts.word_spec(lemma, None)
    item = tts.item_spec(definition, word_spec_=word, clip_storage_key=None)
    created.render_keys.extend([definition.key, word.key, item.key])
    async with async_session_factory() as session:
        await seed_tts.enqueue_items(session, limit=1)  # newest first: the one just saved
    assert all([await _row(k) for k in (definition.key, word.key, item.key)])
    storage = FakeStorage()
    assert await tts.drain(FakeSynth(), keys=[definition.key, word.key, item.key], storage=storage) == 3
    ready = await _row(item.key)
    assert ready.status == RenderStatus.READY and ready.word_offset_ms > tts.ITEM_PAUSE_MS


# --- the worker's audio steps ----------------------------------------------------


async def test_the_render_loop_says_once_that_it_is_off_without_kokoro(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(tts, "kokoro_available", lambda: False)
    with caplog.at_level(logging.INFO, logger="app.worker"):
        await _render_loop()  # returns at once: nothing to run
    messages = [r.getMessage() for r in caplog.records if r.name == "app.worker"]
    assert messages == ["text to speech disabled (kokoro is not installed in this image)"]


async def test_the_clip_step_primes_only_recordings_it_has_not_seen(created: Created) -> None:
    blob = await make_blob(created, [sentence(["a", unique_word(), "c", "d"])])
    async with async_session_factory() as session:
        assert blob.id in await word_clips.unindexed_blob_ids(session, set())
        assert blob.id not in await word_clips.unindexed_blob_ids(session, {blob.id})


async def test_the_clip_step_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*args, **kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr(word_clips, "unindexed_blob_ids", boom)
    assert await clips_once() == (0, 0)


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

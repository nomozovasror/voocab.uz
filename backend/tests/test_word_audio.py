"""What a learner hears for a word (`app.services.word_audio`): the TTS
render, heteronym phonemes, enqueueing, and the On the go item list."""


import pytest
from sqlalchemy import delete, update
from sqlmodel import select

from app.core.database import async_session_factory
from app.models.audio_render import AudioRender, RenderStatus
from app.models.lexicon import LexemeSense
from app.models.user import User
from app.models.vocabulary import SavedWord, VocabularySettings
from app.models.word_audio_log import OnTheGoExposure, SpeakMiss
from app.services import on_the_go, practice, pronunciation, tts, word_audio
from tests.audio_helpers import (
    Created,
    make_lexeme,
    make_user,
    unique_word,
)


@pytest.fixture
async def created():
    made = Created()
    yield made
    async with async_session_factory() as session:
        if made.user_ids:
            await session.execute(
                delete(VocabularySettings).where(VocabularySettings.user_id.in_(made.user_ids))
            )
            await session.commit()
    await made.cleanup()


async def _render_rows(*keys: str) -> list[AudioRender]:
    async with async_session_factory() as session:
        return list((await session.exec(select(AudioRender).where(AudioRender.key.in_(keys)))).all())


async def _mark_ready(spec: tts.RenderSpec, *, duration_ms: int = 700) -> None:
    async with async_session_factory() as session:
        await tts.enqueue([spec])
        await session.execute(
            update(AudioRender)
            .where(AudioRender.key == spec.key)
            .values(
                status=RenderStatus.READY,
                storage_key=tts.storage_key_for(spec.kind, spec.key),
                duration_ms=duration_ms,
            )
        )
        await session.commit()


# --- a plain word ---------------------------------------------------------------


async def test_a_word_with_nothing_ready_is_queued_and_answers_none(created: Created) -> None:
    lemma = unique_word()
    _, sense = await make_lexeme(created, lemma)
    spec = tts.word_spec(lemma, None)
    created.render_keys.append(spec.key)
    async with async_session_factory() as session:
        assert await word_audio.word_audio(session, sense) is None
    [row] = await _render_rows(spec.key)
    assert row.status == RenderStatus.PENDING and row.kind == "word" and row.input == lemma


async def test_asking_again_does_not_queue_a_second_render(created: Created) -> None:
    lemma = unique_word()
    _, sense = await make_lexeme(created, lemma)
    spec = tts.word_spec(lemma, None)
    created.render_keys.append(spec.key)
    for _ in range(3):
        async with async_session_factory() as session:
            assert await word_audio.word_audio(session, sense) is None
    assert len(await _render_rows(spec.key)) == 1


async def test_a_ready_render_is_served_as_tts(created: Created) -> None:
    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma)
    spec = tts.word_spec(lemma, None)
    created.render_keys.append(spec.key)
    await _mark_ready(spec)
    async with async_session_factory() as session:
        audio = await word_audio.word_audio(session, sense, lexeme)
    assert audio == word_audio.AudioOut(url=f"/media/tts/{spec.key}.m4a")


async def test_a_failed_render_is_not_ready_and_not_requeued_by_a_page_view(created: Created) -> None:
    lemma = unique_word()
    _, sense = await make_lexeme(created, lemma)
    spec = tts.word_spec(lemma, None)
    created.render_keys.append(spec.key)
    await tts.enqueue([spec])
    async with async_session_factory() as session:
        await session.execute(
            update(AudioRender).where(AudioRender.key == spec.key).values(status="failed")
        )
        await session.commit()
        assert await word_audio.word_audio(session, sense) is None
    [row] = await _render_rows(spec.key)
    assert row.status == RenderStatus.FAILED


async def test_works_from_a_sense_alone_no_saved_word_needed(created: Created) -> None:
    # A word-list entry nobody has saved is a LexemeSense and nothing more.
    lemma = unique_word()
    _, sense = await make_lexeme(created, lemma)
    spec = tts.word_spec(lemma, None)
    created.render_keys.append(spec.key)
    await _mark_ready(spec)
    async with async_session_factory() as session:
        fresh = await session.get(LexemeSense, sense.id)
        audio = await word_audio.word_audio(session, fresh)  # lexeme loaded for us
    assert audio is not None and audio.url.endswith(f"{spec.key}.m4a")


# --- heteronyms -----------------------------------------------------------------


async def test_a_heteronym_is_always_tts_with_the_senses_own_pronunciation(created: Created) -> None:
    # `record` the verb: the sense's own phonemes, not the bare word.
    lexeme, sense = await make_lexeme(
        created, "record", pos="v", pronunciation="ɹɪkˈɔːd",
        definition="make a record of; set down in permanent form",
    )
    spec = tts.word_spec("record", "ɹɪkˈɔːd")
    created.render_keys.append(spec.key)
    async with async_session_factory() as session:
        assert await word_audio.word_audio(session, sense, lexeme) is None  # queued
    [row] = await _render_rows(spec.key)
    assert row.input == "[record](/ɹɪkˈɔːd/)"
    await _mark_ready(spec)
    async with async_session_factory() as session:
        audio = await word_audio.word_audio(session, sense, lexeme)
    assert audio is not None and audio.url == f"/media/tts/{spec.key}.m4a"


async def test_two_senses_of_a_heteronym_get_two_different_renders(created: Created) -> None:
    noun, noun_sense = await make_lexeme(created, "record", pos="n", pronunciation="ɹˈɛkɔːd")
    verb, verb_sense = await make_lexeme(created, "record", pos="v", pronunciation="ɹɪkˈɔːd")
    keys = [tts.word_spec("record", "ɹˈɛkɔːd").key, tts.word_spec("record", "ɹɪkˈɔːd").key]
    created.render_keys.extend(keys)
    async with async_session_factory() as session:
        result = await word_audio.word_audio_many(session, [noun_sense, verb_sense])
    assert result == {noun_sense.id: None, verb_sense.id: None}
    assert len(await _render_rows(*keys)) == 2


async def test_a_heteronym_sense_with_no_decision_uses_misakis_entry_for_its_pos(
    created: Created,
) -> None:
    # No `pronunciation` stored: the voice still gets phonemes, misaki's own.
    lexeme, sense = await make_lexeme(created, "record", pos="v")
    expected = tts.word_spec("record", pronunciation.fallback_pronunciation("record", "v"))
    created.render_keys.append(expected.key)
    async with async_session_factory() as session:
        await word_audio.word_audio(session, sense, lexeme)
    [row] = await _render_rows(expected.key)
    assert row.input == "[record](/ɹɪkˈɔːd/)"  # the VERB entry, not DEFAULT


# --- many at once ---------------------------------------------------------------


async def test_the_batch_variant_answers_every_sense_in_one_go(created: Created) -> None:
    a, b, c = unique_word(), unique_word(), unique_word()
    senses = [(await make_lexeme(created, lemma))[1] for lemma in (a, b, c)]
    ready = tts.word_spec(a, None)
    created.render_keys.extend(tts.word_spec(x, None).key for x in (a, b, c))
    await _mark_ready(ready)
    async with async_session_factory() as session:
        result = await word_audio.word_audio_many(session, senses)
    assert result[senses[0].id].url == f"/media/tts/{ready.key}.m4a"
    assert result[senses[1].id] is None and result[senses[2].id] is None  # queued
    assert len(await _render_rows(tts.word_spec(b, None).key, tts.word_spec(c, None).key)) == 2


# --- definitions ----------------------------------------------------------------


async def test_the_spoken_definition_is_masked_queued_and_then_served(created: Created) -> None:
    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma, definition=f"to {lemma} something completely")
    spec = tts.definition_spec(sense.definition_en, lemma)
    created.render_keys.append(spec.key)
    async with async_session_factory() as session:
        assert await word_audio.definition_audio_url(session, sense, lexeme) is None
    [row] = await _render_rows(spec.key)
    assert row.kind == "definition" and row.input == "to _____ something completely"
    await _mark_ready(spec)
    async with async_session_factory() as session:
        assert await word_audio.definition_audio_url(session, sense, lexeme) == f"/media/tts/{spec.key}.m4a"


async def test_a_sense_with_no_definition_has_no_definition_audio(created: Created) -> None:
    lexeme, sense = await make_lexeme(created, unique_word(), definition="")
    async with async_session_factory() as session:
        assert await word_audio.definition_audio_url(session, sense, lexeme) is None


# --- On the go ------------------------------------------------------------------


async def _saved_word(created: Created, lexeme, sense) -> SavedWord:
    user = await make_user(created)
    async with async_session_factory() as session:
        word = SavedWord(user_id=user.id, lemma=lexeme.lemma, lexeme_sense_id=sense.id)
        session.add(word)
        await session.commit()
        await session.refresh(word)
    return word


async def test_an_item_is_listed_only_when_both_parts_are_ready(created: Created) -> None:
    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma, definition=f"to {lemma} something completely")
    saved = await _saved_word(created, lexeme, sense)
    definition = tts.definition_spec(sense.definition_en, lemma)
    word = tts.word_spec(lemma, None)
    created.render_keys.extend([definition.key, word.key])

    async def listed() -> tuple[list[on_the_go.Item], int]:
        async with async_session_factory() as session:
            return await on_the_go.item_list(session, await session.get(User, saved.user_id))

    assert await listed() == ([], 1)  # both parts queued by the request
    rows = {r.kind: r for r in await _render_rows(definition.key, word.key)}
    assert set(rows) == {"definition", "word"}  # no composed item any more
    assert all(r.status == RenderStatus.PENDING for r in rows.values())
    await _mark_ready(word)
    assert await listed() == ([], 1)  # half a pair is still being prepared
    await _mark_ready(definition)
    items, preparing = await listed()
    assert preparing == 0 and len(items) == 1
    assert items[0].word.id == saved.id
    assert items[0].word_url == f"/media/tts/{word.key}.m4a"
    assert items[0].definition_masked_url == f"/media/tts/{definition.key}.m4a"
    # The plain definition is the other render: queued by the same request, and
    # not ready, so it rides as None and does not hold the item back.
    assert items[0].definition_full_url is None
    full = tts.definition_spec(sense.definition_en, lemma, masked=False)
    created.render_keys.append(full.key)
    assert full.key != definition.key
    assert (await _render_rows(full.key))[0].status == RenderStatus.PENDING


async def _set_order(user_id, order: str) -> None:
    async with async_session_factory() as session:
        await practice.update_settings(session, user_id, on_the_go_order=order)


async def test_word_first_lists_an_item_only_with_the_plain_definition_ready(
    created: Created,
) -> None:
    """Masking hides the answer when the definition is heard BEFORE the word; in
    "word first" the word has been said, so the item needs the plain render --
    the masked one is not enough, and the other way round."""
    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma, definition=f"to {lemma} something completely")
    saved = await _saved_word(created, lexeme, sense)
    masked = tts.definition_spec(sense.definition_en, lemma)
    full = tts.definition_spec(sense.definition_en, lemma, masked=False)
    word = tts.word_spec(lemma, None)
    created.render_keys.extend([masked.key, full.key, word.key])
    assert masked.key != full.key and full.input == f"to {lemma} something completely"
    await _set_order(saved.user_id, "word_first")

    async def listed() -> tuple[list[on_the_go.Item], int]:
        async with async_session_factory() as session:
            return await on_the_go.item_list(session, await session.get(User, saved.user_id))

    await listed()  # queues everything
    await _mark_ready(word)
    await _mark_ready(masked)
    assert await listed() == ([], 1)  # the masked render does not serve "word first"
    await _mark_ready(full)
    items, preparing = await listed()
    assert preparing == 0 and len(items) == 1
    # Both are on the item, so the client can change the order from the next one.
    assert items[0].definition_full_url == f"/media/tts/{full.key}.m4a"
    assert items[0].definition_masked_url == f"/media/tts/{masked.key}.m4a"

    # Back to "meaning first": the masked render alone is enough, the plain one
    # being absent changes nothing about the listing.
    await _set_order(saved.user_id, "meaning_first")
    async with async_session_factory() as session:
        await session.execute(update(AudioRender).where(AudioRender.key == full.key).values(
            status=RenderStatus.PENDING, storage_key=None))
        await session.commit()
    items, preparing = await listed()
    assert preparing == 0 and len(items) == 1
    assert items[0].definition_masked_url is not None and items[0].definition_full_url is None


async def test_a_failed_plain_definition_does_not_hide_a_meaning_first_item(
    created: Created,
) -> None:
    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma, definition=f"to {lemma} something completely")
    saved = await _saved_word(created, lexeme, sense)
    masked = tts.definition_spec(sense.definition_en, lemma)
    full = tts.definition_spec(sense.definition_en, lemma, masked=False)
    word = tts.word_spec(lemma, None)
    created.render_keys.extend([masked.key, full.key, word.key])
    await _mark_ready(word)
    await _mark_ready(full)
    async with async_session_factory() as session:
        await tts.enqueue([masked])
        await session.execute(update(AudioRender).where(AudioRender.key == full.key).values(
            status=RenderStatus.FAILED))
        await session.commit()
    # meaning_first needs the masked one: pending, so preparing -- a failed plain
    # render is nobody's part of this item.
    async with async_session_factory() as session:
        _, preparing = await on_the_go.item_list(session, await session.get(User, saved.user_id))
    assert preparing == 1
    # word_first needs the plain one, and it has failed: in neither number.
    await _set_order(saved.user_id, "word_first")
    async with async_session_factory() as session:
        items, preparing = await on_the_go.item_list(session, await session.get(User, saved.user_id))
    assert (items, preparing) == ([], 0)


async def test_the_plain_definition_is_the_masked_render_when_nothing_was_masked(
    created: Created,
) -> None:
    lemma = unique_word()
    lexeme, sense = await make_lexeme(
        created, lemma, definition="a thing that people do on every single ordinary day"
    )
    saved = await _saved_word(created, lexeme, sense)
    masked = tts.definition_spec(sense.definition_en, lemma)
    full = tts.definition_spec(sense.definition_en, lemma, masked=False)
    word = tts.word_spec(lemma, None)
    assert masked.key == full.key  # one render, made once
    created.render_keys.extend([masked.key, word.key])
    await _mark_ready(word)
    await _mark_ready(masked)
    for order in ("meaning_first", "word_first"):
        await _set_order(saved.user_id, order)
        async with async_session_factory() as session:
            items, preparing = await on_the_go.item_list(session, await session.get(User, saved.user_id))
        assert preparing == 0 and len(items) == 1
        assert items[0].definition_masked_url == items[0].definition_full_url


async def test_a_changed_definition_is_a_new_definition_render(created: Created) -> None:
    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma, definition=f"to {lemma} something")
    saved = await _saved_word(created, lexeme, sense)
    old = tts.definition_spec(sense.definition_en, lemma)
    word = tts.word_spec(lemma, None)
    await _mark_ready(old)
    await _mark_ready(word)
    new_text = f"to give up {lemma} entirely"
    new = tts.definition_spec(new_text, lemma)
    created.render_keys.extend([old.key, word.key, new.key])

    async def listed() -> tuple[list[on_the_go.Item], int]:
        async with async_session_factory() as session:
            return await on_the_go.item_list(session, await session.get(User, saved.user_id))

    assert len((await listed())[0]) == 1
    async with async_session_factory() as session:
        await session.execute(
            update(LexemeSense).where(LexemeSense.id == sense.id).values(definition_en=new_text)
        )
        await session.commit()
    assert await listed() == ([], 1)  # a new key, queued; the old file is not referenced
    assert new.key != old.key and await _render_rows(new.key)


async def test_forgetting_a_word_keeps_its_exposure_and_speak_miss_history(
    created: Created,
) -> None:
    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma)
    word = await _saved_word(created, lexeme, sense)
    async with async_session_factory() as session:
        session.add(OnTheGoExposure(user_id=word.user_id, saved_word_id=word.id, lemma=lemma))
        session.add(SpeakMiss(user_id=word.user_id, saved_word_id=word.id, lemma=lemma, attempt=2))
        # A writer that has not heard of `lemma` still works: it defaults to "".
        session.add(OnTheGoExposure(user_id=word.user_id, saved_word_id=word.id))
        await session.commit()
        await session.delete(await session.get(SavedWord, word.id))
        await session.commit()
    async with async_session_factory() as session:
        exposures = (
            await session.exec(select(OnTheGoExposure).where(OnTheGoExposure.user_id == word.user_id))
        ).all()
        misses = (
            await session.exec(select(SpeakMiss).where(SpeakMiss.user_id == word.user_id))
        ).all()
    assert len(exposures) == 2 and all(e.saved_word_id is None for e in exposures)
    assert sorted(e.lemma for e in exposures) == ["", lemma]
    assert len(misses) == 1 and misses[0].saved_word_id is None and misses[0].lemma == lemma

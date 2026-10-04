"""What a learner hears for a word (`app.services.word_audio`): the
resolution order, heteronym routing, enqueueing, and the On the go item."""


import pytest
from sqlalchemy import update
from sqlmodel import select

from app.core.database import async_session_factory
from app.models.audio_asset import AudioAsset
from app.models.audio_render import AudioRender, RenderStatus
from app.models.lexicon import LexemeSense
from app.models.material import Material
from app.models.vocabulary import SavedWord
from app.models.word_audio_log import OnTheGoExposure, SpeakMiss
from app.services import pronunciation, tts, word_audio
from tests.audio_helpers import (
    Created,
    add_clip,
    attach,
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


async def _render_rows(*keys: str) -> list[AudioRender]:
    async with async_session_factory() as session:
        return list((await session.exec(select(AudioRender).where(AudioRender.key.in_(keys)))).all())


async def _mark_ready(spec: tts.RenderSpec, *, duration_ms: int = 700, offset: int | None = None) -> None:
    async with async_session_factory() as session:
        await tts.enqueue([spec])
        await session.execute(
            update(AudioRender)
            .where(AudioRender.key == spec.key)
            .values(
                status=RenderStatus.READY,
                storage_key=tts.storage_key_for(spec.kind, spec.key),
                duration_ms=duration_ms,
                word_offset_ms=offset,
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
    assert audio == word_audio.AudioOut(
        url=f"/media/tts/{spec.key}.m4a", context_url=None, source="tts"
    )


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
    assert audio is not None and audio.source == "tts"


# --- clips ----------------------------------------------------------------------


async def test_a_verified_clip_beats_tts_and_carries_its_context(created: Created) -> None:
    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma)
    blob = await make_blob(created, [sentence(["a", lemma, "c", "d"])])
    clip = await add_clip(blob, lemma)
    tts_spec = tts.word_spec(lemma, None)
    created.render_keys.append(tts_spec.key)
    async with async_session_factory() as session:
        audio = await word_audio.word_audio(session, sense, lexeme)
    assert audio == word_audio.AudioOut(
        url=f"/media/{clip.storage_key}",
        context_url=f"/media/{clip.context_storage_key}",
        source="clip",
    )
    # A word a clip serves never has TTS queued for it.
    assert await _render_rows(tts_spec.key) == []
    # ... and a ready TTS render does not outrank the clip either.
    await _mark_ready(tts_spec)
    async with async_session_factory() as session:
        assert (await word_audio.word_audio(session, sense, lexeme)).source == "clip"


async def test_only_verified_clips_are_ever_served(created: Created) -> None:
    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma)
    blob = await make_blob(created, [sentence(["a", lemma, "c", "d"])])
    for status in ("candidate", "cut", "rejected", "failed"):
        await add_clip(blob, lemma, status=status)
    spec = tts.word_spec(lemma, None)
    created.render_keys.append(spec.key)
    async with async_session_factory() as session:
        assert await word_audio.word_audio(session, sense, lexeme) is None
    assert len(await _render_rows(spec.key)) == 1  # fell through to TTS, queued


async def _source_of(session, sense, lexeme) -> str | None:
    audio = await word_audio.word_audio(session, sense, lexeme)
    return None if audio is None else audio.source


async def test_a_clip_stops_being_served_when_its_material_goes_private(
    created: Created,
) -> None:
    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma)
    blob = await make_blob(created, [sentence(["a", lemma, "c", "d"])])
    await add_clip(blob, lemma)
    spec = tts.word_spec(lemma, None)
    created.render_keys.append(spec.key)
    async with async_session_factory() as session:
        assert await _source_of(session, sense, lexeme) == "clip"

    # The author withdraws the material AFTER the clip was verified.
    async with async_session_factory() as session:
        await session.execute(
            update(Material)
            .where(Material.id.in_(created.material_ids))
            .values(visibility="private")
        )
        await session.commit()
    async with async_session_factory() as session:
        assert await _source_of(session, sense, lexeme) is None  # TTS, queued
    assert len(await _render_rows(spec.key)) == 1

    # Published again: the clip is back (nothing was deleted).
    async with async_session_factory() as session:
        await session.execute(
            update(Material)
            .where(Material.id.in_(created.material_ids))
            .values(visibility="public")
        )
        await session.commit()
    async with async_session_factory() as session:
        assert await _source_of(session, sense, lexeme) == "clip"


async def test_a_verified_clip_on_a_recording_no_public_material_uses_is_not_served(
    created: Created,
) -> None:
    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma)
    unattached = await make_blob(created, [sentence(["a", lemma, "c", "d"])], visibility=None)
    await attach(created, unattached, None)  # an ordinary user's private upload
    await add_clip(unattached, lemma)
    spec = tts.word_spec(lemma, None)
    created.render_keys.append(spec.key)
    async with async_session_factory() as session:
        assert await _source_of(session, sense, lexeme) is None


async def test_a_clip_stops_being_served_when_its_segment_is_corrected_later(
    created: Created,
) -> None:
    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma)
    blob = await make_blob(created, [sentence(["a", lemma, "c", "d"])])
    await add_clip(blob, lemma)  # on segment 0
    spec = tts.word_spec(lemma, None)
    created.render_keys.append(spec.key)
    async with async_session_factory() as session:
        assert await _source_of(session, sense, lexeme) == "clip"
        asset = (
            await session.exec(select(AudioAsset).where(AudioAsset.id.in_(created.asset_ids)))
        ).one()
        # A correction to ANOTHER segment leaves the clip alone ...
        asset.transcript_overrides = {"7": "unrelated"}
        session.add(asset)
        await session.commit()
    async with async_session_factory() as session:
        assert await _source_of(session, sense, lexeme) == "clip"
        asset = (
            await session.exec(select(AudioAsset).where(AudioAsset.id.in_(created.asset_ids)))
        ).one()
        # ... a correction to ITS segment, by any asset over the recording, takes it out.
        asset.transcript_overrides = {"0": "corrected text"}
        session.add(asset)
        await session.commit()
    async with async_session_factory() as session:
        assert await _source_of(session, sense, lexeme) is None


async def test_the_learners_own_materials_come_first_then_the_longest_word(created: Created) -> None:
    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma)
    user = await make_user(created)
    other = await make_blob(created, [sentence(["a", lemma, "c", "d"])])
    mine = await make_blob(created, [sentence(["a", lemma, "c", "d"])])
    longer_elsewhere = await add_clip(other, lemma, start_ms=1000, end_ms=2000)
    own = await add_clip(mine, lemma, start_ms=1000, end_ms=1400)
    async with async_session_factory() as session:
        asset = AudioAsset(owner_id=user.id, blob_id=mine.id)
        session.add(asset)
        await session.flush()
        material = Material(author_id=user.id, type="listening", title="mine", audio_asset_id=asset.id)
        session.add(material)
        await session.commit()
        created.asset_ids.append(asset.id)
        created.material_ids.append(material.id)
        preferred = await word_audio.word_audio(
            session, sense, lexeme, prefer_material_ids=[material.id]
        )
        default = await word_audio.word_audio(session, sense, lexeme)
    assert preferred is not None and preferred.url == f"/media/{own.storage_key}"
    assert default is not None and default.url == f"/media/{longer_elsewhere.storage_key}"


# --- heteronyms -----------------------------------------------------------------


async def test_a_heteronym_is_always_tts_with_the_senses_own_pronunciation(created: Created) -> None:
    # `record` the verb, with a VERIFIED clip of "record" in the library: the
    # clip must be ignored (the transcript has no part of speech).
    lexeme, sense = await make_lexeme(
        created, "record", pos="v", pronunciation="ɹɪkˈɔːd",
        definition="make a record of; set down in permanent form",
    )
    blob = await make_blob(created, [sentence(["a", "record", "c", "d"])])
    await add_clip(blob, "record")
    spec = tts.word_spec("record", "ɹɪkˈɔːd")
    created.render_keys.append(spec.key)
    async with async_session_factory() as session:
        assert await word_audio.word_audio(session, sense, lexeme) is None  # queued, not the clip
    [row] = await _render_rows(spec.key)
    assert row.input == "[record](/ɹɪkˈɔːd/)"
    await _mark_ready(spec)
    async with async_session_factory() as session:
        audio = await word_audio.word_audio(session, sense, lexeme)
    assert audio is not None and audio.source == "tts" and audio.context_url is None


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
    blob = await make_blob(created, [sentence(["x", b, "y", "z"])])
    clip = await add_clip(blob, b)
    async with async_session_factory() as session:
        result = await word_audio.word_audio_many(session, senses)
    assert result[senses[0].id].source == "tts"
    assert result[senses[1].id].url == f"/media/{clip.storage_key}"
    assert result[senses[2].id] is None  # queued
    assert len(await _render_rows(tts.word_spec(c, None).key)) == 1


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


async def test_an_item_queues_its_parts_first_and_is_served_once_ready(created: Created) -> None:
    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma, definition=f"to {lemma} something completely")
    saved = await _saved_word(created, lexeme, sense)
    definition = tts.definition_spec(sense.definition_en, lemma)
    word = tts.word_spec(lemma, None)
    item = tts.item_spec(definition, word_spec_=word, clip_storage_key=None)
    created.render_keys.extend([definition.key, word.key, item.key])
    async with async_session_factory() as session:
        assert await word_audio.item_render(session, saved) is None
    rows = {r.kind: r for r in await _render_rows(definition.key, word.key, item.key)}
    assert set(rows) == {"definition", "word", "item"}
    assert all(r.status == RenderStatus.PENDING for r in rows.values())
    await _mark_ready(item, duration_ms=9000, offset=4200)
    async with async_session_factory() as session:
        result = await word_audio.item_render(session, saved)
    assert result == (f"/media/renders/{item.key}.m4a", 9000, 4200)
    assert (result.url, result.duration_ms, result.word_offset_ms) == tuple(result)


async def test_an_item_with_a_verified_clip_is_built_from_the_clip(created: Created) -> None:
    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma, definition=f"to {lemma} something completely")
    saved = await _saved_word(created, lexeme, sense)
    blob = await make_blob(created, [sentence(["a", lemma, "c", "d"])])
    clip = await add_clip(blob, lemma)
    definition = tts.definition_spec(sense.definition_en, lemma)
    item = tts.item_spec(definition, word_spec_=None, clip_storage_key=clip.storage_key)
    created.render_keys.extend([definition.key, item.key, tts.word_spec(lemma, None).key])
    async with async_session_factory() as session:
        assert await word_audio.item_render(session, saved) is None
    rows = {r.kind for r in await _render_rows(definition.key, item.key, tts.word_spec(lemma, None).key)}
    assert rows == {"definition", "item"}  # no word TTS: the clip is the word


async def test_a_changed_definition_is_a_new_item(created: Created) -> None:
    lemma = unique_word()
    lexeme, sense = await make_lexeme(created, lemma, definition=f"to {lemma} something")
    saved = await _saved_word(created, lexeme, sense)
    old = tts.item_spec(
        tts.definition_spec(sense.definition_en, lemma),
        word_spec_=tts.word_spec(lemma, None), clip_storage_key=None,
    )
    await _mark_ready(old, duration_ms=8000, offset=4000)
    created.render_keys.extend(
        [old.key, tts.word_spec(lemma, None).key, tts.definition_spec(sense.definition_en, lemma).key]
    )
    async with async_session_factory() as session:
        assert (await word_audio.item_render(session, saved)).duration_ms == 8000
        await session.execute(
            update(LexemeSense)
            .where(LexemeSense.id == sense.id)
            .values(definition_en=f"to give up {lemma} entirely")
        )
        await session.commit()
        assert await word_audio.item_render(session, saved) is None  # new key, queued
    new = tts.item_spec(
        tts.definition_spec(f"to give up {lemma} entirely", lemma),
        word_spec_=tts.word_spec(lemma, None), clip_storage_key=None,
    )
    created.render_keys.extend([new.key, tts.definition_spec(f"to give up {lemma} entirely", lemma).key])
    assert new.key != old.key and await _render_rows(new.key)


async def test_the_batch_item_variant_covers_every_saved_word_without_one_query_each(
    created: Created,
) -> None:
    saved: list[SavedWord] = []
    for _ in range(3):
        lemma = unique_word()
        lexeme, sense = await make_lexeme(created, lemma, definition=f"to {lemma} something")
        saved.append(await _saved_word(created, lexeme, sense))
        definition = tts.definition_spec(sense.definition_en, lemma)
        created.render_keys.extend(
            [definition.key, tts.word_spec(lemma, None).key,
             tts.item_spec(definition, word_spec_=tts.word_spec(lemma, None), clip_storage_key=None).key]
        )
    async with async_session_factory() as session:
        result = await word_audio.item_renders(session, saved)
    assert set(result) == {w.id for w in saved} and all(v is None for v in result.values())


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

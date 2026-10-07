"""On the go: the words in rotation as audio to listen to, and the log of
having heard them (vocabulary stage 3, decisions 11-14).

Nothing here is practice, and nothing here is composed: an item is two files
(the word, the masked definition) that the CLIENT plays in the learner's order
with the learner's pause, so what is stored for it is only those two renders
(2026-10-07, superseding decision 13). The list is **independent of the daily queue** -- it
is simply the learner's words in rotation, newest first, so what they saved
this morning is what they hear on the walk home -- and playing it writes only
``on_the_go_exposures``, never a card: hearing a word is not recalling it, and
a review row for it would raise a card's stability with no evidence, so the
schedule would start to lie (decision 14).

"In rotation" is the module's own notion, not a second one: ``learning`` and
``review`` words (:data:`app.services.practice.EXCLUDED_STATUSES` keeps
``known``, ``suspended`` and ``leech`` out of every queue) that are not a
proper noun or a function word (:func:`app.services.practice
._practisable_clause`). A word nobody has practised yet is ``learning`` and is
in -- a word is worth hearing before it is worth being asked.
"""

import uuid
from typing import NamedTuple

from sqlmodel import select

from app.core.database import AsyncSession
from app.models.audio_render import AudioRender, RenderStatus
from app.models.lexicon import Lexeme, LexemeSense
from app.models.user import User
from app.models.vocabulary import SavedWord
from app.models.word_audio_log import OnTheGoExposure
from app.services import practice, tts, word_audio
from app.services.accents import DEFAULT_ACCENT, Accent


async def in_rotation(session: AsyncSession, user_id: uuid.UUID) -> list[SavedWord]:
    """The learner's words in rotation, newest first (``created_at`` desc, the
    id breaking a tie so the order is stable between two requests)."""
    await practice._reap_suspensions(session, user_id)
    rows = await session.exec(
        select(SavedWord)
        .where(
            SavedWord.user_id == user_id,
            practice._practisable_clause(),
            SavedWord.status.not_in(practice.EXCLUDED_STATUSES),
        )
        .order_by(SavedWord.created_at.desc(), SavedWord.id.desc())
    )
    return list(rows.all())


class Item(NamedTuple):
    """One word in the On the go list: the word's own audio and its sense's
    masked definition, as two files the client plays in the learner's order."""

    word: SavedWord
    word_url: str
    definition_url: str


async def item_list(session: AsyncSession, user: User) -> tuple[list[Item], int]:
    """``(ready items in order, how many are still being prepared)``.

    An item is listed only when BOTH its audios are ready -- half of a pair is
    no use in a pocket, and the client cannot know which half it may skip.
    Anything else that is still being made counts towards ``preparing``; the
    two ``*_many`` calls have already queued it. A word with a ``failed`` part
    is in neither number (:func:`_failed_words`). All words go through ONE call
    per part: the queries are per table, not per word.

    A word whose sense has nothing speakable as a definition can never have an
    item (``tts.definition_spec`` is ``None``), so it is left out of both
    numbers instead of being "preparing" for ever.

    The audios are the very ones the rest of the app plays -- the word in the
    learner's accent (what the reveal plays) and the masked definition -- so a
    word heard here is made once, however often it is asked for.
    """
    words = await in_rotation(session, user.id)
    # The learner's own accent and word voice, read once: every definition is
    # in the accent's Kokoro voice, and every word is that accent's recording
    # (or, under `synthetic` / with none, its Kokoro voice).
    learner = await practice.get_settings(session, user.id)
    accent = learner.accent
    senses = {
        sense.id: sense
        for sense in (
            await session.exec(
                select(LexemeSense).where(
                    LexemeSense.id.in_({w.lexeme_sense_id for w in words})
                )
            )
        ).all()
    } if words else {}
    lexemes = {
        lexeme.id: lexeme
        for lexeme in (
            await session.exec(
                select(Lexeme).where(
                    Lexeme.id.in_({s.lexeme_id for s in senses.values()})
                )
            )
        ).all()
    } if senses else {}
    playable = [
        word
        for word in words
        if word.lexeme_sense_id in senses
        and senses[word.lexeme_sense_id].lexeme_id in lexemes
        and tts.definition_spec(
            senses[word.lexeme_sense_id].definition_en,
            lexemes[senses[word.lexeme_sense_id].lexeme_id].lemma,
            accent,
        )
        is not None
    ]
    wanted = [senses[word.lexeme_sense_id] for word in playable]
    word_urls = await word_audio.word_audio_many(
        session, wanted, lexemes=lexemes, accent=accent,
        word_voice=learner.word_voice,  # type: ignore[arg-type]
    )
    definition_urls = await word_audio.definition_audio_urls(
        session, wanted, lexemes=lexemes, accent=accent
    )
    ready: list[Item] = []
    waiting: list[SavedWord] = []
    for word in playable:
        audio = word_urls.get(word.lexeme_sense_id)
        definition_url = definition_urls.get(word.lexeme_sense_id)
        if audio is not None and definition_url is not None:
            ready.append(Item(word, audio.url, definition_url))
        else:
            waiting.append(word)
    failed = await _failed_words(session, waiting, senses, lexemes, accent=accent)
    return ready, len(waiting) - len(failed)


async def _failed_words(
    session: AsyncSession,
    words: list[SavedWord],
    senses: dict[uuid.UUID, LexemeSense],
    lexemes: dict[uuid.UUID, Lexeme],
    *,
    accent: Accent = DEFAULT_ACCENT,
) -> set[uuid.UUID]:
    """The words with a ``failed`` render among the two parts of their item
    (definition, word). Such a word is not "being prepared": a failed render
    waits for an operator's requeue (or the age-based one), and counting it in
    ``preparing`` would keep the client's "preparing N" up for ever. A word
    whose parts are merely ``pending``/``processing`` is not in the set.

    The keys are re-derived with the same public helpers
    :func:`app.services.word_audio.word_audio_many` uses, so they are the same
    keys; only unready words are looked at."""
    if not words:
        return set()
    keys_of: dict[uuid.UUID, list[str]] = {}
    for word in words:
        sense = senses[word.lexeme_sense_id]
        lexeme = lexemes[sense.lexeme_id]
        definition = tts.definition_spec(sense.definition_en, lexeme.lemma, accent)
        if definition is None:
            continue
        keys_of[word.id] = [
            definition.key, word_audio.tts_word_spec(sense, lexeme, accent).key
        ]
    all_keys = {key for keys in keys_of.values() for key in keys}
    if not all_keys:
        return set()
    failed_keys = set(
        (
            await session.exec(
                select(AudioRender.key).where(
                    AudioRender.key.in_(all_keys),
                    AudioRender.status == RenderStatus.FAILED,
                )
            )
        ).all()
    )
    return {
        word_id for word_id, keys in keys_of.items() if failed_keys.intersection(keys)
    }


async def record_exposure(
    session: AsyncSession, user: User, word_id: uuid.UUID
) -> bool:
    """One ``on_the_go_exposures`` row: the WORD part of this learner's item
    played. ``False`` for a word that is not theirs (the API's 404, the same
    shape as every by-id word route). Touches no card, no review log, no
    counter on the word."""
    word = await session.get(SavedWord, word_id)
    if word is None or word.user_id != user.id:
        return False
    # `lemma` is copied so the row still says which word it was after the word
    # is forgotten (`saved_word_id` goes null), as `vocabulary_review_logs` does.
    session.add(
        OnTheGoExposure(user_id=user.id, saved_word_id=word.id, lemma=word.lemma)
    )
    await session.commit()
    return True

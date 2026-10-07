"""On the go: the words in rotation as files to listen to, and the log of
having heard them (vocabulary stage 3, decisions 11-14).

Nothing here is practice. The list is **independent of the daily queue** -- it
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


async def item_list(
    session: AsyncSession, user: User
) -> tuple[list[tuple[SavedWord, word_audio.ItemAudio]], int]:
    """``(ready items in order, how many are still being prepared)``.

    Only items whose render is READY are listed -- a half-made file is no use
    in a pocket -- and everything else that is still being made counts towards
    ``preparing``;
    :func:`app.services.word_audio.item_renders` has already queued it. A word
    whose render has ``failed`` is in neither number (:func:`_failed_words`).
    All words go through ONE ``item_renders`` call: its queries are per table, not
    per word.

    A word whose sense has nothing speakable as a definition can never have an
    item (``tts.definition_spec`` is ``None``), so it is left out of both
    numbers instead of being "preparing" for ever.
    """
    words = await in_rotation(session, user.id)
    # The learner's own accent, read once: every word's definition and (TTS)
    # word is in that voice.
    accent = (await practice.get_settings(session, user.id)).accent
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
    playable = [
        word
        for word in words
        if word.lexeme_sense_id in senses
        and tts.definition_spec(
            senses[word.lexeme_sense_id].definition_en, word.lemma, accent
        )
        is not None
    ]
    renders = await word_audio.item_renders(session, playable, accent=accent)
    ready = [(word, renders[word.id]) for word in playable if renders.get(word.id)]
    waiting = [word for word in playable if not renders.get(word.id)]
    failed = await _failed_words(session, waiting, senses, accent=accent)
    return ready, len(waiting) - len(failed)


async def _failed_words(
    session: AsyncSession,
    words: list[SavedWord],
    senses: dict[uuid.UUID, LexemeSense],
    *,
    accent: Accent = DEFAULT_ACCENT,
) -> set[uuid.UUID]:
    """The words whose item, or one of the parts it is made of (definition,
    word), has a ``failed`` render. Such a word is not "being prepared": a
    failed render waits for an operator's requeue (or the age-based one), and
    counting it in ``preparing`` would keep the client's "preparing N" up for
    ever. A word whose parts are merely ``pending``/``processing`` -- or not
    enqueued yet -- is not in the set.

    The keys are re-derived with the same public helpers
    :func:`app.services.word_audio.item_renders` uses, so they are the same
    keys; only unready words are looked at."""
    if not words:
        return set()
    wanted = [senses[word.lexeme_sense_id] for word in words]
    lexemes = {
        lexeme.id: lexeme
        for lexeme in (
            await session.exec(
                select(Lexeme).where(Lexeme.id.in_({s.lexeme_id for s in wanted}))
            )
        ).all()
    }
    keys_of: dict[uuid.UUID, list[str]] = {}
    for word in words:
        sense = senses[word.lexeme_sense_id]
        lexeme = lexemes.get(sense.lexeme_id)
        if lexeme is None:
            continue
        definition = tts.definition_spec(sense.definition_en, lexeme.lemma, accent)
        if definition is None:
            continue
        word_spec = word_audio.tts_word_spec(sense, lexeme, accent)
        keys_of[word.id] = [
            definition.key, word_spec.key, tts.item_spec(definition, word_spec).key
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

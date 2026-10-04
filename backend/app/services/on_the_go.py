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
from app.models.lexicon import LexemeSense
from app.models.user import User
from app.models.vocabulary import SavedWord
from app.models.word_audio_log import OnTheGoExposure
from app.services import practice, tts, word_audio


def _lemma_of(word: SavedWord) -> dict[str, str]:
    """The word's lemma, copied onto the log row once the model has the
    column (the audio-layer fix adds it so the row outlives a forgotten word,
    as ``vocabulary_review_logs`` does). Until then, nothing."""
    return {"lemma": word.lemma} if "lemma" in OnTheGoExposure.model_fields else {}


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
    in a pocket -- and everything else counts towards ``preparing``;
    :func:`app.services.word_audio.item_renders` has already queued it. All
    words go through ONE ``item_renders`` call: its queries are per table, not
    per word.

    A word whose sense has nothing speakable as a definition can never have an
    item (``tts.definition_spec`` is ``None``), so it is left out of both
    numbers instead of being "preparing" for ever.
    """
    words = await in_rotation(session, user.id)
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
        and tts.definition_spec(senses[word.lexeme_sense_id].definition_en, word.lemma)
        is not None
    ]
    renders = await word_audio.item_renders(
        session, playable,
        prefer_material_ids=await practice.learner_material_ids(session, user.id),
    )
    ready = [(word, renders[word.id]) for word in playable if renders.get(word.id)]
    return ready, len(playable) - len(ready)


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
    session.add(OnTheGoExposure(user_id=user.id, saved_word_id=word.id, **_lemma_of(word)))
    await session.commit()
    return True

"""Looking a word up, reading a passage's vocabulary, and keeping one.

Addressed by material id rather than by skill, and so mounted on its own
rather than through ``paper_router``. The reasoning is the one already
written into ``app/api/papers.py``: a client holding an id should not have to
know which router minted it. Only reading passages carry vocabulary today,
and the day a listening transcript is extracted the same way, none of this
changes.

## Three lookups, and where that rule lives

The budget is enforced in the browser (``features/reading/lookups.ts``). It
is a rule whose purpose is to make somebody CHOOSE -- a reader with three
left spends them on the words the questions turn on -- and a rule like that
works by being visible, not by being unforgeable. There is also nothing to
forge against: no attempt row exists while a paper is open, and the words
spent are reported by the same client at submit.

What IS enforced here is the thing that would make the browser's rule a
formality. :func:`material_vocabulary` hands out the whole list, and it is
refused to anybody who has not submitted the paper. One word at a time while
the clock is running; eighty-six of them on the review page, which is what
the list is for.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import CurrentUser
from app.api.materials import _load_owned_or_public
from app.core.database import AsyncSession, get_session
from app.models.material import Material
from app.models.vocabulary import MaterialVocabulary
from app.schemas.vocabulary import (
    LookupIn,
    LookupOut,
    SavedContextOut,
    SavedWordOut,
    SavedWordsOut,
    SaveWordsIn,
    VocabularyEntryOut,
    VocabularyListOut,
)
from app.services import materials as materials_service
from app.services import vocabulary as vocabulary_service

router = APIRouter(prefix="/api", tags=["vocabulary"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _entry(
    entry: MaterialVocabulary, material: Material, *, saved: bool = False
) -> VocabularyEntryOut:
    return VocabularyEntryOut(
        id=entry.id,
        lemma=entry.lemma,
        surface=entry.surface,
        pos=entry.pos,
        meaning_en=entry.meaning_en,
        meaning_uz=entry.meaning_uz,
        example=entry.example,
        cefr_level=entry.cefr_level,
        is_phrase=entry.is_phrase,
        paragraph_index=entry.paragraph_index,
        offset_start=entry.offset_start,
        offset_end=entry.offset_end,
        stale=vocabulary_service.stale(material, entry),
        saved=saved,
    )


@router.post("/materials/{material_id}/lookups", response_model=LookupOut)
async def look_up_word(
    material_id: uuid.UUID,
    data: LookupIn,
    user: CurrentUser,
    session: SessionDep,
) -> LookupOut:
    """One word, in this passage's sense.

    One word per request, and that shape is the point: it is what the take
    screen is allowed to ask for while the paper is open. An empty answer is
    ordinary rather than an error -- a name, a number, or a word nothing can
    gloss -- and the panel says so.
    """
    material = await _load_owned_or_public(session, material_id, user.id)
    found = await vocabulary_service.look_up(
        session,
        material,
        word=data.word,
        paragraph_index=data.paragraph_index,
        offset=data.offset,
    )
    return LookupOut(
        word=_entry(found["word"], material) if found["word"] else None,
        phrase=_entry(found["phrase"], material) if found["phrase"] else None,
    )


@router.get(
    "/materials/{material_id}/vocabulary", response_model=VocabularyListOut
)
async def material_vocabulary(
    material_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> VocabularyListOut:
    """Everything worth learning in one material.

    403 for a caller who has not submitted the paper, and the message says
    why rather than pretending the material does not exist: they can see it,
    they are simply not finished with it. The whole list mid-paper is a
    dictionary, which is the thing this feature exists not to be.
    """
    material = await _load_owned_or_public(session, material_id, user.id)
    if not await vocabulary_service.may_see_all(session, material, user.id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "The vocabulary of a passage opens when you have finished it.",
        )
    entries = await vocabulary_service.entries(session, material_id)
    saved = await vocabulary_service.saved_lemmas(
        session, user.id, [entry.lemma for entry in entries]
    )
    levels = {level: 0 for level in vocabulary_service.LEVELS}
    for entry in entries:
        if entry.cefr_level in levels:
            levels[entry.cefr_level] += 1
    return VocabularyListOut(
        material_id=material_id,
        total=len(entries),
        levels=levels,
        entries=[
            _entry(entry, material, saved=entry.lemma in saved)
            for entry in entries
        ],
    )


@router.post(
    "/vocabulary/words",
    response_model=SavedWordsOut,
    status_code=status.HTTP_201_CREATED,
)
async def save_words(
    data: SaveWordsIn, user: CurrentUser, session: SessionDep
) -> SavedWordsOut:
    """Put words on the learner's list, with the sense they had here.

    Takes a list because the review offers "save all" and "save the ones I
    looked up" beside the per-row button. Three endpoints for one verb is
    three places for the rules to drift, and the rules -- one word however
    many passages, one context per passage -- are the interesting part.
    """
    await _load_owned_or_public(session, data.material_id, user.id)
    await vocabulary_service.save(
        session,
        user_id=user.id,
        material_id=data.material_id,
        lemmas=data.lemmas,
    )
    return await _saved(session, user.id)


@router.get("/vocabulary/words", response_model=SavedWordsOut)
async def list_saved_words(
    user: CurrentUser, session: SessionDep
) -> SavedWordsOut:
    return await _saved(session, user.id)


@router.delete(
    "/vocabulary/words/{lemma}", status_code=status.HTTP_204_NO_CONTENT
)
async def forget_word(
    lemma: str, user: CurrentUser, session: SessionDep
) -> None:
    if not await vocabulary_service.forget(session, user.id, lemma):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not on your list")


async def _saved(session: AsyncSession, user_id: uuid.UUID) -> SavedWordsOut:
    """The learner's list, with the title of every passage a word came from.

    The titles are fetched in one query over the materials the contexts name,
    rather than by a relationship per row: a hundred saved words across forty
    passages is one lookup here and a hundred and one without it.
    """
    rows = await vocabulary_service.saved_list(session, user_id)
    wanted = {
        context.material_id for _, contexts in rows for context in contexts
    }
    titles = await materials_service.titles_for(session, list(wanted))
    return SavedWordsOut(
        total=len(rows),
        words=[
            SavedWordOut(
                lemma=word.lemma,
                created_at=word.created_at,
                contexts=[
                    SavedContextOut(
                        material_id=context.material_id,
                        material_title=titles.get(context.material_id, ""),
                        surface=context.surface,
                        pos=context.pos,
                        meaning_en=context.meaning_en,
                        meaning_uz=context.meaning_uz,
                        example=context.example,
                        cefr_level=context.cefr_level,
                        is_phrase=context.is_phrase,
                        created_at=context.created_at,
                    )
                    for context in contexts
                ],
            )
            for word, contexts in rows
        ],
    )

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

## And no budget at all after the paper is over

The review page lets a reader tap ANY word in the passage, unrationed. That
is not a relaxation of the rule -- it is the rule finishing. Three lookups
exist to protect an exam habit: a candidate who can look anything up is
reading with a dictionary, which is not the skill being scored. Once the
paper is submitted there is no habit left to protect and what remains is
studying, where rationing a learner's own curiosity teaches nothing.

The endpoint does not have to know any of that, and deliberately does not
enforce it either way. ``LookupIn.context`` is written down rather than
checked.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.deps import CurrentUser
from app.api.materials import _load_owned_or_public
from app.core.database import AsyncSession, get_session
from app.models.lexicon import LexemeSense
from app.models.material import Material
from app.models.vocabulary import MaterialVocabulary
from app.schemas.vocabulary import (
    KnownCheckIn,
    LookupIn,
    LookupOut,
    PracticeAnswerIn,
    PracticeAnswerOut,
    PracticeItemOut,
    PracticeSessionIn,
    PracticeSessionOut,
    PracticeSummaryOut,
    SavedContextOut,
    SavedWordDetailOut,
    SavedWordOut,
    SavedWordsOut,
    SaveWordsIn,
    TranslationReportIn,
    TranslationReportOut,
    VocabularyEntryOut,
    VocabularyListOut,
    VocabularySettingsIn,
    VocabularySettingsOut,
    WordBulkActionIn,
    WordBulkActionOut,
    WordHistoryEntryOut,
    WordLeechChoiceIn,
)
from app.services import lexicon as lexicon_service
from app.services import materials as materials_service
from app.services import practice as practice_service
from app.services import vocabulary as vocabulary_service

router = APIRouter(prefix="/api", tags=["vocabulary"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

#: ``TranslationReportIn.where`` is the wire's own name for
#: ``TranslationReport.source`` -- see that schema's docstring for why
#: "practice" maps onto the stored ``practice_reveal`` rather than the
#: column gaining a third value.
_REPORT_SOURCE = {"word_page": "word_page", "practice": "practice_reveal"}


def _entry(
    entry: MaterialVocabulary,
    material: Material,
    *,
    sense: LexemeSense | None = None,
    saved: bool = False,
    saved_word_id: uuid.UUID | None = None,
    other_sense_saved: bool = False,
) -> VocabularyEntryOut:
    # A row written since P3 no longer carries its own usual-meaning copy
    # (`app.services.lexicon.link_row`) -- filled here from the row's own
    # sense where empty, so the review page and the popover keep showing a
    # usual meaning without the frontend reader changing at all.
    meaning_core_en = entry.meaning_core_en
    meaning_core_uz = entry.meaning_core_uz
    if not meaning_core_en and sense is not None:
        meaning_core_en = sense.definition_en
        meaning_core_uz = sense.meaning_uz
    return VocabularyEntryOut(
        id=entry.id,
        lexeme_id=entry.lexeme_id,
        sense_id=entry.sense_id,
        lemma=entry.lemma,
        surface=entry.surface,
        pos=entry.pos,
        meaning_core_en=meaning_core_en,
        meaning_core_uz=meaning_core_uz,
        meaning_en=entry.meaning_en,
        meaning_uz=entry.meaning_uz,
        sense_differs=entry.sense_differs,
        example=entry.example,
        cefr_level=entry.cefr_level,
        is_phrase=entry.is_phrase,
        part_id=entry.part_id,
        paragraph_index=entry.paragraph_index,
        offset_start=entry.offset_start,
        offset_end=entry.offset_end,
        also_at=entry.also_at,
        stale=vocabulary_service.stale(material, entry),
        saved=saved,
        saved_word_id=saved_word_id,
        other_sense_saved=other_sense_saved,
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

    The same endpoint serves the REVIEW page, where any word in the passage
    can be tapped and nothing is rationed. Nothing had to be opened for that
    and nothing had to be guarded: the budget was never enforced here (see
    the module docstring), and the one rule this file does enforce -- the
    whole list is refused until the paper is submitted -- is about the whole
    list. A reader on the review page has submitted by definition.

    ``data.context`` is therefore not a permission. It is what the event is
    logged under, and what a newly generated entry is filed as.
    """
    material = await _load_owned_or_public(session, material_id, user.id)
    found = await vocabulary_service.look_up(
        session,
        material,
        user_id=user.id,
        word=data.word,
        paragraph_index=data.paragraph_index,
        offset=data.offset,
        context=data.context,
    )
    # Whether it is already on their list, which the card's button is. It
    # used to be left at its default of false, so a reader who saved a word,
    # closed the card and opened it again was offered Save a second time --
    # the page having forgotten what they had just done. One query over at
    # most two entries, keyed by SENSE now (P4): `bank` the river and `bank`
    # the financial institution answer "saved" separately.
    answers = [entry for entry in found.values() if entry is not None]
    saved_state = await vocabulary_service.saved_state_for(session, user.id, answers)
    senses = await vocabulary_service.usual_meanings_for(session, answers)

    def _answer(entry: MaterialVocabulary | None) -> VocabularyEntryOut | None:
        if entry is None:
            return None
        state = saved_state.get(
            entry.id, {"saved": False, "saved_word_id": None, "other_sense_saved": False}
        )
        return _entry(
            entry, material,
            sense=senses.get(entry.sense_id) if entry.sense_id else None,
            saved=state["saved"],
            saved_word_id=state["saved_word_id"],
            other_sense_saved=state["other_sense_saved"],
        )

    return LookupOut(word=_answer(found["word"]), phrase=_answer(found["phrase"]))


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
    saved_state = await vocabulary_service.saved_state_for(session, user.id, entries)
    senses = await vocabulary_service.usual_meanings_for(session, entries)
    levels = {level: 0 for level in vocabulary_service.LEVELS}
    for entry in entries:
        if entry.cefr_level in levels:
            levels[entry.cefr_level] += 1
    return VocabularyListOut(
        material_id=material_id,
        total=len(entries),
        levels=levels,
        # Counted over `sense_differs` rather than `unusual`, so the figure
        # in the header is the one the toggle beneath it filters by. The
        # narrower column still exists and still feeds the arithmetic that
        # compares passages; what a reader is offered is every word whose
        # sense here is not the one they know, common or not.
        unusual=sum(1 for entry in entries if entry.sense_differs),
        entries=[
            _entry(
                entry, material,
                sense=senses.get(entry.sense_id) if entry.sense_id else None,
                **saved_state.get(
                    entry.id,
                    {"saved": False, "saved_word_id": None, "other_sense_saved": False},
                ),
            )
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
    "/vocabulary/words/{word_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def forget_word(
    word_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> None:
    """By id (P4) -- a lemma is no longer unique to one saved word, so the
    lemma-path route this used to be is gone."""
    if not await vocabulary_service.forget(session, user.id, word_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not on your list")


@router.post(
    "/vocabulary/words/{word_id}/browsed", status_code=status.HTTP_204_NO_CONTENT
)
async def mark_word_browsed(
    word_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> None:
    """Browse (§C) showed this card. Writes ``browsed_at`` and NOTHING
    else -- no review log, no FSRS card, no due change, not counted in
    daily minutes (see `app.services.vocabulary.mark_browsed`). Owner-only,
    404 for a word id that is not this learner's, the same shape as every
    other by-id word route.
    """
    if not await vocabulary_service.mark_browsed(session, user.id, word_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not on your list")


@router.get("/vocabulary/words/{word_id}", response_model=SavedWordDetailOut)
async def get_saved_word(
    word_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> SavedWordDetailOut:
    """The word page: the word, every context, and its review history.

    By id (P4): two rows may share a lemma now (`bank` finance, `bank`
    river), so a lemma can no longer name one on its own. 404 for an id that
    is not this learner's -- including one that belongs to somebody else --
    rather than distinguishing "never saved" from "somebody else's word",
    which would tell a caller something about another learner's list.
    """
    # The lazy half of "set aside for 30 days" -- resolved here too, not
    # only at the top of a practice queue, so a word whose 30 days passed
    # while nobody built a session does not show as still set aside on the
    # one screen that would otherwise print a stale status.
    await practice_service._reap_suspensions(session, user.id)
    found = await vocabulary_service.saved_word_with_history(
        session, user.id, word_id
    )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not on your list")
    word, contexts, history = found
    titles = await materials_service.titles_for(
        session, [context.material_id for context in contexts]
    )
    settings = await practice_service.get_settings(session, user.id)
    lapse_counts = (
        await practice_service.lapse_counts_for(session, [word.id])
    ).get(word.id, {"passive": 0, "active": 0})
    sense = await session.get(LexemeSense, word.lexeme_sense_id)
    return SavedWordDetailOut(
        word=_saved_word_out(
            word, contexts, titles, direction=settings.direction,
            lapse_counts=lapse_counts, sense=sense,
        ),
        history=[
            WordHistoryEntryOut(
                reviewed_at=log.reviewed_at,
                direction=log.direction,
                exercise_type=log.exercise_type,
                rating=log.rating,
                given=log.given,
                elapsed_ms=log.elapsed_ms,
            )
            for log in history
        ],
    )


@router.post("/vocabulary/words/bulk", response_model=WordBulkActionOut)
async def bulk_word_action(
    data: WordBulkActionIn, user: CurrentUser, session: SessionDep
) -> WordBulkActionOut:
    changed = await vocabulary_service.bulk_action(
        session, user_id=user.id, word_ids=data.word_ids, action=data.action
    )
    return WordBulkActionOut(changed=changed)


@router.post(
    "/vocabulary/translation-reports",
    response_model=TranslationReportOut,
    status_code=status.HTTP_201_CREATED,
)
async def report_translation(
    data: TranslationReportIn,
    user: CurrentUser,
    session: SessionDep,
    response: Response,
) -> TranslationReportOut:
    """"This translation is wrong" -- the word page, or right after a
    practice reveal (`data.where`). One open report per ``(user, sense)``:
    a repeat is a no-op that answers 200 with the report already open,
    rather than a second row -- set here rather than left at this route's
    201 default, since FastAPI has already committed to the decorator's
    status code by the time a handler runs.
    """
    if await session.get(LexemeSense, data.sense_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sense not found")
    report, created = await lexicon_service.report_translation(
        session,
        user_id=user.id,
        sense_id=data.sense_id,
        source=_REPORT_SOURCE[data.where],
        note=(data.note or "").strip(),
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return TranslationReportOut(
        id=report.id, sense_id=report.lexeme_sense_id, status=report.status,
    )


@router.post("/vocabulary/words/{word_id}/leech", response_model=SavedWordOut)
async def leech_choice(
    word_id: uuid.UUID, data: WordLeechChoiceIn, user: CurrentUser, session: SessionDep
) -> SavedWordOut:
    await practice_service._reap_suspensions(session, user.id)
    word = await practice_service.resolve_leech(
        session, user, word_id=word_id, choice=data.choice
    )
    if word is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not on your list")
    contexts = (await vocabulary_service.saved_list_for(session, [word.id])).get(
        word.id, []
    )
    titles = await materials_service.titles_for(
        session, [context.material_id for context in contexts]
    )
    settings = await practice_service.get_settings(session, user.id)
    lapse_counts = (
        await practice_service.lapse_counts_for(session, [word.id])
    ).get(word.id, {"passive": 0, "active": 0})
    sense = await session.get(LexemeSense, word.lexeme_sense_id)
    return _saved_word_out(
        word, contexts, titles, direction=settings.direction,
        lapse_counts=lapse_counts, sense=sense,
    )


def _saved_word_out(
    word, contexts, titles: dict, *, direction: str,
    lapse_counts: dict | None = None,
    sense: LexemeSense | None = None,
) -> SavedWordOut:
    """One saved word, in the extended shape stage 2 shows on the words list
    and the word page -- see :class:`SavedWordOut`'s own docstring for why
    everything past ``contexts`` is additive.

    ``direction`` is the learner's CURRENT settings value, not anything
    stored on the word -- ``active_paused`` is true exactly when an active
    card exists and that setting is ``passive``, per
    ``practice._gather_candidates``'s pause rule.

    ``lapse_counts`` is this one word's ``{"passive": n, "active": n}`` from
    ``practice.lapse_counts_for`` -- computed by the caller, once, over
    every word a listing needs rather than per row here, so a hundred saved
    words cost one extra query and not a hundred and one.

    ``sense`` is the word's own ``LexemeSense`` (P4), also batched by the
    caller -- its ``definition_en``/``meaning_uz``/``cefr`` are what the
    word's usual meaning/CEFR are read LIVE from, never the dead
    ``SavedWord.meaning_core_*`` columns. Absent only for a row the P4
    migration could not resolve at all (should not happen; every saved word
    has a `lexeme_sense_id`), in which case the word's own dead copy is the
    last thing left to show rather than an empty line.
    """
    lapse_counts = lapse_counts or {"passive": 0, "active": 0}
    newest_cefr = contexts[-1].cefr_level if contexts else ""
    definition_en = sense.definition_en if sense is not None else word.meaning_core_en
    meaning_uz = sense.meaning_uz if sense is not None else word.meaning_core_uz
    sense_cefr = (sense.cefr or "") if sense is not None else ""
    return SavedWordOut(
        id=word.id,
        lexeme_id=sense.lexeme_id if sense is not None else None,
        sense_id=word.lexeme_sense_id,
        lemma=word.lemma,
        created_at=word.created_at,
        contexts=[
            SavedContextOut(
                material_id=context.material_id,
                material_title=titles.get(context.material_id, ""),
                surface=context.surface,
                pos=context.pos,
                meaning_core_en=context.meaning_core_en,
                meaning_core_uz=context.meaning_core_uz,
                meaning_en=context.meaning_en,
                meaning_uz=context.meaning_uz,
                sense_differs=context.sense_differs,
                example=context.example,
                cefr_level=context.cefr_level,
                is_phrase=context.is_phrase,
                created_at=context.created_at,
            )
            for context in contexts
        ],
        status=word.status,
        pos=word.pos,
        # DEAD stored copy replaced by the sense's own live values (P4) --
        # same field names, so a caller that has not moved onto
        # `definition_en`/`meaning_uz` yet keeps seeing the right thing.
        meaning_core_en=definition_en,
        meaning_core_uz=meaning_uz,
        definition_en=definition_en,
        meaning_uz=meaning_uz,
        sense_cefr=sense_cefr,
        cefr_level=newest_cefr,
        passive_level=word.passive_level,
        active_level=word.active_level,
        passive_due=word.passive_due,
        active_due=word.active_due,
        passive_stability=word.passive_stability,
        active_stability=word.active_stability,
        lapses=word.lapses,
        passive_lapses=lapse_counts["passive"],
        active_lapses=lapse_counts["active"],
        reps=word.reps,
        suspended_until=word.suspended_until,
        active_paused=word.active_state is not None and direction == "passive",
        browsed_at=word.browsed_at,
    )


async def _saved(session: AsyncSession, user_id: uuid.UUID) -> SavedWordsOut:
    """The learner's list, with the title of every passage a word came from.

    The titles are fetched in one query over the materials the contexts name,
    rather than by a relationship per row: a hundred saved words across forty
    passages is one lookup here and a hundred and one without it.
    """
    # See `get_saved_word`'s own comment -- the same lazy 30-day return,
    # so the list a learner scans is never the one screen still showing a
    # word as set aside after its time is up.
    await practice_service._reap_suspensions(session, user_id)
    rows = await vocabulary_service.saved_list(session, user_id)
    wanted = {
        context.material_id for _, contexts in rows for context in contexts
    }
    titles = await materials_service.titles_for(session, list(wanted))
    settings = await practice_service.get_settings(session, user_id)
    lapse_counts = await practice_service.lapse_counts_for(
        session, [word.id for word, _ in rows]
    )
    senses = await vocabulary_service.senses_by_id(
        session, {word.lexeme_sense_id for word, _ in rows}
    )
    return SavedWordsOut(
        total=len(rows),
        words=[
            _saved_word_out(
                word, contexts, titles, direction=settings.direction,
                lapse_counts=lapse_counts.get(word.id),
                sense=senses.get(word.lexeme_sense_id),
            )
            for word, contexts in rows
        ],
    )


# --- Practice ----------------------------------------------------------------
#
# Everything below reads and writes through `app.services.practice`, the one
# module that touches `fsrs`. This file stays about HTTP -- turning a query
# param into a timezone, a missing word into a 404 -- and never computes a
# rating or a due date itself.


@router.get("/vocabulary/practice/summary", response_model=PracticeSummaryOut)
async def practice_summary(
    user: CurrentUser,
    session: SessionDep,
    tz: str | None = Query(
        default=None,
        description="IANA timezone naming the learner's day; falls back to "
        "Asia/Tashkent.",
    ),
    mode: str = Query(default="auto"),
) -> PracticeSummaryOut:
    return PracticeSummaryOut(
        **await practice_service.summary(session, user, tz=tz, mode=mode)
    )


@router.post("/vocabulary/practice/session", response_model=PracticeSessionOut)
async def practice_session(
    data: PracticeSessionIn,
    user: CurrentUser,
    session: SessionDep,
    tz: str | None = Query(default=None),
) -> PracticeSessionOut:
    """Build today's queue now, over the same plan `practice_summary`
    promised. Building it here rather than the client assembling it from
    the summary's counts keeps the context-rotation and gap-building logic
    -- both stateful across a learner's whole history -- on the one side
    that can see that history.
    """
    items = await practice_service.build_session(
        session, user, tz=tz, material_id=data.material_id, mode=data.mode
    )
    return PracticeSessionOut(items=[PracticeItemOut(**item) for item in items])


@router.post(
    "/vocabulary/practice/known-check", response_model=PracticeItemOut
)
async def practice_known_check(
    data: KnownCheckIn, user: CurrentUser, session: SessionDep
) -> PracticeItemOut:
    """"I know this": one recall attempt, offered only on a brand-new
    word's first appearance -- see ``app.services.practice
    .build_known_check_item``. The client posts the single answer that
    follows to ``/practice/answers`` with ``claim_known: true``.
    """
    item = await practice_service.build_known_check_item(session, user, data.word_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not on your list")
    return PracticeItemOut(**item)


@router.post("/vocabulary/practice/answers", response_model=PracticeAnswerOut)
async def practice_answer(
    data: PracticeAnswerIn, user: CurrentUser, session: SessionDep
) -> PracticeAnswerOut:
    result = await practice_service.record_answer(
        session,
        user,
        word_id=data.word_id,
        context_id=data.context_id,
        direction=data.direction,
        exercise_type=data.exercise_type,
        planned_exercise=data.planned_exercise,
        given=data.given,
        elapsed_ms=data.elapsed_ms,
        claim_known=data.claim_known,
        requeued=data.requeued,
    )
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not on your list")
    return PracticeAnswerOut(**result)


@router.get("/vocabulary/settings", response_model=VocabularySettingsOut)
async def get_vocabulary_settings(
    user: CurrentUser, session: SessionDep
) -> VocabularySettingsOut:
    settings = await practice_service.get_settings(session, user.id)
    return VocabularySettingsOut(
        daily_minutes=settings.daily_minutes,
        direction=settings.direction,
        exercise_types=settings.exercise_types,
        pronunciation=settings.pronunciation,
        active_in_progress=await practice_service.active_in_progress_count(
            session, user.id
        ),
    )


@router.put("/vocabulary/settings", response_model=VocabularySettingsOut)
async def put_vocabulary_settings(
    data: VocabularySettingsIn, user: CurrentUser, session: SessionDep
) -> VocabularySettingsOut:
    settings = await practice_service.update_settings(
        session,
        user.id,
        daily_minutes=data.daily_minutes,
        direction=data.direction,
        exercise_types=data.exercise_types,
    )
    return VocabularySettingsOut(
        daily_minutes=settings.daily_minutes,
        direction=settings.direction,
        exercise_types=settings.exercise_types,
        pronunciation=settings.pronunciation,
        active_in_progress=await practice_service.active_in_progress_count(
            session, user.id
        ),
    )

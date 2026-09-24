"""Scheduling a saved word: FSRS, the gap exercise, and the daily budget.

The only module in this codebase that imports ``fsrs``. Everything the rest
of the app needs from a card -- its state, when it's next due, whether an
answer was good enough -- comes through the functions here, so the library
can be swapped or re-parametrised (see :class:`app.models.vocabulary
.VocabularyReviewLog`, kept from the first answer for exactly that reason)
without a second module having learnt its shapes.

## The rating is computed, never asked

Anki asks the learner to grade themselves "easy / good / hard" after every
card, which is the one part of Anki this module refuses to copy. A learner
mid-sentence has no real basis for that judgement, and self-graded ease is
famously unreliable -- flattering on an easy day, harsh on a tired one, and
never comparable between two people. What IS reliable is the pairing of
*which exercise* and *how the answer went*: recognising a translation and
correctly TYPING the word from a bare definition are different strengths of
evidence for the same card, however right the answer was. :data:`RATING_TABLE`
is that pairing, spelled out for all four exercises stage 1 will ever need
even though only ``recall`` is wired up yet -- so the day ``produce`` or
``listen`` is built, the rating logic needs no rethinking, only a caller.

## No interval halving on a wrong answer

The plan is explicit about this because it is the everyday mistake: a wrong
answer feels like it should shrink the interval, and FSRS already does the
right, non-obvious thing on its own -- ``Rating.Again`` drops the card's
*stability* (see ``fsrs.Scheduler._next_forget_stability``) and raises its
*difficulty*, which is what actually slows the card down long-term. A second
halving on top, bolted on here, would be double-counting a penalty the
library already applies and would hide struggling words behind an interval
that looks deceptively short-but-fine. The only thing stage 1 adds on top of
the library's own judgement is the 10-minute relearning step, which is the
library's own feature (``relearning_steps``) and not a bypass of it.

## Card <-> columns, one direction at a time

``saved_words`` holds two independent ``fsrs.Card``s (``passive_*``,
``active_*``) because recognising a word and producing it are different
skills a learner can have one of without the other. ``_load_card``/
``_store_card`` are the only translation between the six stored columns and
an actual ``fsrs.Card``, and the one subtlety worth stating twice: a null
``{direction}_state`` means "never practised" and is NOT the same as
``fsrs.State.Learning`` -- a fresh ``fsrs.Card()`` starts Learning the instant
it exists, but a saved word nobody has drilled has no stability or
difficulty for that state to mean anything about. ``_load_card`` builds a
throwaway fresh card for that case rather than ever writing state 1 to a row
nobody has reviewed.
"""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import fsrs
from sqlalchemy import exists, func
from sqlmodel import select

from app.core.database import AsyncSession
from app.models.user import User
from app.models.vocabulary import (
    SavedWord,
    SavedWordContext,
    VocabularyReviewLog,
    VocabularySettings,
)
from app.services import materials as materials_service
from app.services import mistakes
from app.services.answers import normalize_answer

#: The scheduler every card in the platform is read and written through.
#: One instance, module-level, because its parameters ARE the schedule: two
#: callers using two ``Scheduler``s with different settings would silently
#: disagree about when the same card is due. Exactly the plan's numbers --
#: a single 10-minute step both ways (FSRS's own docs warn against long
#: learning steps), default retention, fuzzing on so two cards due the same
#: day don't all land on the same day forever.
SCHEDULER = fsrs.Scheduler(
    desired_retention=0.9,
    learning_steps=(timedelta(minutes=10),),
    relearning_steps=(timedelta(minutes=10),),
    enable_fuzzing=True,
)

Direction = Literal["passive", "active"]
ExerciseType = Literal["recognise", "recall", "produce", "listen"]
Verdict = Literal["correct", "close", "wrong"]

#: Rating from exercise + verdict -- see the module docstring. ``close`` on
#: ``recognise`` has no cell of its own in the brief's table (multiple
#: choice has no spelling to be close about) and falls back to the same
#: place ``wrong`` does, which is why the two columns are identical here.
RATING_TABLE: dict[ExerciseType, dict[Verdict, fsrs.Rating]] = {
    "recognise": {
        "correct": fsrs.Rating.Good,
        "close": fsrs.Rating.Again,
        "wrong": fsrs.Rating.Again,
    },
    "recall": {
        "correct": fsrs.Rating.Good,
        "close": fsrs.Rating.Hard,
        "wrong": fsrs.Rating.Again,
    },
    "produce": {
        "correct": fsrs.Rating.Easy,
        "close": fsrs.Rating.Good,
        "wrong": fsrs.Rating.Again,
    },
    "listen": {
        "correct": fsrs.Rating.Good,
        "close": fsrs.Rating.Hard,
        "wrong": fsrs.Rating.Again,
    },
}

#: Excluded from every queue -- a suspended word was set aside on purpose, a
#: leech is set aside until stage 2 gives the learner a choice about it, and
#: a known word has nothing left to schedule. Not excluded from the totals
#: below, which count all three; the totals are a report and the queue is a
#: plan, and the same word answers both questions differently.
EXCLUDED_STATUSES: frozenset[str] = frozenset({"known", "suspended", "leech"})

#: A passive card this stable has been remembered for three weeks running,
#: which is the plan's own line for "no longer worth calling `learning`" on
#: the home progress bar. Not an FSRS constant -- FSRS has no notion of
#: "mastered" at all, only ever-lengthening intervals -- so this is a
#: product decision, kept as one named number rather than buried in the
#: totals query.
MASTERED_STABILITY_DAYS = 21.0

DEFAULT_DAILY_MINUTES = 10
DEFAULT_AVG_SECONDS = 12.0
MIN_AVG_SECONDS = 4.0
MAX_AVG_SECONDS = 60.0
AVG_SECONDS_SAMPLE = 200
MIN_LOGS_FOR_AVERAGE = 20
#: A new word is likely answered twice before it settles (once badly, once
#: better) -- see the plan -- so it is costed at twice one review's time
#: rather than measured on its own, which nothing has data for on day one.
NEW_WORD_COST_FACTOR = 2

FALLBACK_TZ = "Asia/Tashkent"


# --- FSRS <-> columns --------------------------------------------------------


def _load_card(word: SavedWord, direction: Direction) -> fsrs.Card:
    """The direction's card, or a fresh one if it has never been practised.

    ``card_id`` is set to a constant rather than left to generate one,
    because ``fsrs.Card.__init__`` mints one from the clock and then SLEEPS
    a millisecond to avoid a collision with the next card it builds -- a
    cost worth paying when the id is kept, and dead weight here, where
    nothing downstream ever reads it.
    """
    state = getattr(word, f"{direction}_state")
    if state is None:
        return fsrs.Card()
    return fsrs.Card(
        card_id=0,
        state=fsrs.State(state),
        step=getattr(word, f"{direction}_step"),
        stability=getattr(word, f"{direction}_stability"),
        difficulty=getattr(word, f"{direction}_difficulty"),
        due=getattr(word, f"{direction}_due"),
        last_review=getattr(word, f"{direction}_last_review"),
    )


def _store_card(word: SavedWord, direction: Direction, card: fsrs.Card) -> None:
    """Write a reviewed card back onto its six columns. Does not flush or
    commit -- the caller is mid-transaction, also writing the review log and
    the word's ``status``/``lapses``/``reps`` in the same unit of work."""
    setattr(word, f"{direction}_state", int(card.state))
    setattr(word, f"{direction}_step", card.step)
    setattr(word, f"{direction}_stability", card.stability)
    setattr(word, f"{direction}_difficulty", card.difficulty)
    setattr(word, f"{direction}_due", card.due)
    setattr(word, f"{direction}_last_review", card.last_review)


def _status_for(state: fsrs.State) -> str:
    """``learning`` while the card is Learning or Relearning, ``review``
    once it reaches Review. Never returns ``known``/``suspended``/``leech``
    -- those are set (or not) by something other than an FSRS transition,
    and stage 1 sets none of them."""
    return "review" if state == fsrs.State.Review else "learning"


# --- Verdict and rating -------------------------------------------------------


def verdict_for(given: str, answer: str) -> Verdict:
    """What kind of answer this was, reusing the reading review's own
    classifier rather than a second opinion about spelling.

    ``normalize_answer`` (trim, collapse whitespace, lowercase -- §3.5, the
    same rule grading uses) decides CORRECT. Everything else goes to
    :func:`app.services.mistakes.classify`, which already knows the
    difference between a slipped letter and a different word; only
    ``spelling`` and ``plural`` count as ``close`` here -- a wrong answer
    that happens to be the right LENGTH is still wrong, and an empty one
    (``missed`` from the classifier) is wrong too, per the brief.
    """
    normalised_given = normalize_answer(given or "")
    normalised_answer = normalize_answer(answer or "")
    if normalised_given and normalised_given == normalised_answer:
        return "correct"
    kind = mistakes.classify(given or "", [answer], None)
    if kind in ("spelling", "plural"):
        return "close"
    return "wrong"


def rating_for(exercise_type: ExerciseType, verdict: Verdict) -> fsrs.Rating:
    """The one function every exercise's grading runs through -- see
    :data:`RATING_TABLE` and the module docstring for why this is computed
    rather than self-reported."""
    return RATING_TABLE[exercise_type][verdict]


# --- The gap (recall) ---------------------------------------------------------


@dataclass(frozen=True)
class Gap:
    """What a recall prompt shows, and the answer it is graded against.

    ``answer`` never reaches the client before the answer is submitted --
    see the API layer, which builds :class:`PracticeItemOut` from this same
    dataclass but leaves the field off. It is recomputed, not stored,
    when the learner's answer comes back in: ``resolve_gap`` is a pure
    function of the word and the context, so asking it twice for the same
    pair gives the same gap, and nothing about a session needs to be kept
    on the server between the two requests.
    """

    before: str
    after: str
    cue: str
    kind: Literal["sentence", "definition"]
    definition: str | None
    answer: str


#: A word (or phrase, which may contain internal spaces) as a whole token:
#: not preceded or followed by a word character. Anchored this way rather
#: than with ``\b`` on both sides so a multi-word surface like `give rise
#: to` still refuses to match inside a longer word at either end, which
#: plain ``\b...\b`` would already do -- named here because the search runs
#: twice (surface, then lemma) and both have to agree on what "whole word"
#: means.
def _find_surface(text: str, surface: str) -> tuple[int, int] | None:
    if not text or not surface:
        return None
    pattern = re.compile(
        r"(?<!\w)" + re.escape(surface) + r"(?!\w)", re.IGNORECASE | re.UNICODE
    )
    match = pattern.search(text)
    return (match.start(), match.end()) if match else None


def resolve_gap(word: SavedWord, context: SavedWordContext | None) -> Gap:
    """The recall prompt for one word, in one context.

    Tries the context's own sentence first, searching for its ``surface``
    -- the INFLECTED form actually stored ("Undertaken", not "undertake"),
    which is what makes the gap read naturally rather than leaving a
    dictionary form sitting oddly in a real sentence. Falls back to the
    lemma inside the same sentence for a context saved before ``surface``
    was reliably filled.

    Falls all the way back to a bare definition -- no sentence, no context
    at all, or a surface that genuinely is not IN the sentence text
    (edited since, or copied wrong) -- using the word's own usual meaning
    first and the context's contextual one only if that is empty, per the
    brief. The answer there is the lemma, because there is no sentence
    for any other form of the word to have stood in.

    The cue is always just the answer's first character: the reveal after
    submitting is where the meanings do the teaching, not the cue.
    """
    if context is not None and context.example:
        match = _find_surface(context.example, context.surface or word.lemma)
        if match is None and context.surface and context.surface != word.lemma:
            match = _find_surface(context.example, word.lemma)
        if match is not None:
            start, end = match
            answer = context.example[start:end]
            return Gap(
                before=context.example[:start],
                after=context.example[end:],
                cue=answer[:1],
                kind="sentence",
                definition=None,
                answer=answer,
            )

    definition = word.meaning_core_en or (context.meaning_en if context else "") or ""
    return Gap(
        before="",
        after="",
        cue=word.lemma[:1],
        kind="definition",
        definition=definition or None,
        answer=word.lemma,
    )


# --- Context rotation ---------------------------------------------------------


#: A context that has never been reviewed sorts as though it were used at
#: the start of time -- the "never used" case and the "everything is tied,
#: pick the newest" case documented on :func:`_pick_context` are the same
#: code path for exactly this reason.
_NEVER_USED = datetime.min.replace(tzinfo=timezone.utc)


def _pick_context(
    contexts: list[SavedWordContext],
    last_used: dict[uuid.UUID, datetime],
) -> SavedWordContext | None:
    """Which of a word's contexts to practise next.

    The least recently used wins, ties broken by the newest context -- which
    also IS "the newest context the first time", since a word with no review
    history yet has every context tied at "never used". One rule, not two.

    ``last_used`` is passed in rather than queried here so a whole session's
    worth of words can share a single GROUP BY instead of one per word.
    """
    if not contexts:
        return None
    if len(contexts) == 1:
        return contexts[0]

    def rank(context: SavedWordContext) -> tuple[datetime, float]:
        used_at = last_used.get(context.id, _NEVER_USED)
        return (used_at, -context.created_at.timestamp())

    return min(contexts, key=rank)


async def _last_used_map(
    session: AsyncSession, context_ids: list[uuid.UUID]
) -> dict[uuid.UUID, datetime]:
    if not context_ids:
        return {}
    rows = await session.exec(
        select(
            VocabularyReviewLog.context_id, func.max(VocabularyReviewLog.reviewed_at)
        )
        .where(VocabularyReviewLog.context_id.in_(context_ids))
        .group_by(VocabularyReviewLog.context_id)
    )
    return dict(rows.all())


async def _contexts_by_word(
    session: AsyncSession, word_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[SavedWordContext]]:
    if not word_ids:
        return {}
    rows = await session.exec(
        select(SavedWordContext)
        .where(SavedWordContext.saved_word_id.in_(word_ids))
        .order_by(SavedWordContext.created_at)
    )
    by_word: dict[uuid.UUID, list[SavedWordContext]] = {}
    for context in rows.all():
        by_word.setdefault(context.saved_word_id, []).append(context)
    return by_word


# --- Queues: due, new, and the material filter --------------------------------


def _has_material_clause(material_id: uuid.UUID):
    """An EXISTS rather than a JOIN, so a word met in three materials is one
    row in the queue and not three."""
    return exists(
        select(SavedWordContext.id).where(
            SavedWordContext.saved_word_id == SavedWord.id,
            SavedWordContext.material_id == material_id,
        )
    )


async def _due_words(
    session: AsyncSession, user_id: uuid.UUID, *, material_id: uuid.UUID | None = None
) -> list[SavedWord]:
    """Every practised, unexcluded passive card due now, most overdue
    first -- "most overdue" being the smallest ``due``, not the largest gap,
    which is the same thing but cheaper to sort by."""
    query = select(SavedWord).where(
        SavedWord.user_id == user_id,
        SavedWord.status.not_in(EXCLUDED_STATUSES),
        SavedWord.passive_state.is_not(None),
        SavedWord.passive_due <= datetime.now(timezone.utc),
    )
    if material_id is not None:
        query = query.where(_has_material_clause(material_id))
    rows = await session.exec(query.order_by(SavedWord.passive_due))
    return list(rows.all())


async def _new_words(
    session: AsyncSession, user_id: uuid.UUID, *, material_id: uuid.UUID | None = None
) -> list[SavedWord]:
    """Every never-practised, unexcluded word, oldest save first -- a plain
    FIFO, so a word does not wait behind one saved a minute later than it."""
    query = select(SavedWord).where(
        SavedWord.user_id == user_id,
        SavedWord.status.not_in(EXCLUDED_STATUSES),
        SavedWord.passive_state.is_(None),
    )
    if material_id is not None:
        query = query.where(_has_material_clause(material_id))
    rows = await session.exec(query.order_by(SavedWord.created_at))
    return list(rows.all())


async def _next_due_at(session: AsyncSession, user_id: uuid.UUID) -> datetime | None:
    row = await session.exec(
        select(func.min(SavedWord.passive_due)).where(
            SavedWord.user_id == user_id,
            SavedWord.status.not_in(EXCLUDED_STATUSES),
            SavedWord.passive_state.is_not(None),
        )
    )
    return row.one()


# --- The daily time budget ----------------------------------------------------


def _day_window(tz_name: str | None) -> tuple[datetime, datetime]:
    """Today's [start, end) in UTC, as midnight-to-midnight in the caller's
    own clock. The boundary is a fact about the LEARNER's day, not the
    server's, so it is computed in their timezone and converted -- a
    learner in Tashkent whose day starts at 00:00 local should not see
    "today" reset at a UTC midnight that falls in their afternoon.
    """
    try:
        tz = ZoneInfo(tz_name) if tz_name else ZoneInfo(FALLBACK_TZ)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo(FALLBACK_TZ)
    local_now = datetime.now(tz)
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_start.astimezone(timezone.utc), (
        local_start + timedelta(days=1)
    ).astimezone(timezone.utc)


async def _avg_seconds(session: AsyncSession, user_id: uuid.UUID) -> float:
    """The median answer time of this learner's last 200 logs, clamped to
    [4s, 60s] so one lightning-fast or one abandoned-mid-thought answer
    cannot swing the whole day's plan. Median rather than mean for the same
    reason: a handful of very slow answers (a phone call mid-session) should
    not inflate every estimate after them.

    Below 20 logs there is nothing to measure yet, so a flat default stands
    in -- an average from four answers is a guess dressed as data.
    """
    rows = await session.exec(
        select(VocabularyReviewLog.elapsed_ms)
        .where(VocabularyReviewLog.user_id == user_id)
        .order_by(VocabularyReviewLog.reviewed_at.desc())
        .limit(AVG_SECONDS_SAMPLE)
    )
    values = sorted(rows.all())
    if len(values) < MIN_LOGS_FOR_AVERAGE:
        return DEFAULT_AVG_SECONDS
    mid = len(values) // 2
    median_ms = (
        values[mid]
        if len(values) % 2
        else (values[mid - 1] + values[mid]) / 2
    )
    return min(max(median_ms / 1000, MIN_AVG_SECONDS), MAX_AVG_SECONDS)


async def _seconds_spent_today(
    session: AsyncSession, user_id: uuid.UUID, window: tuple[datetime, datetime]
) -> float:
    start, end = window
    row = await session.exec(
        select(func.coalesce(func.sum(VocabularyReviewLog.elapsed_ms), 0)).where(
            VocabularyReviewLog.user_id == user_id,
            VocabularyReviewLog.reviewed_at >= start,
            VocabularyReviewLog.reviewed_at < end,
        )
    )
    return row.one() / 1000


def _plan_counts(
    budget_seconds: float, avg_seconds: float, due_count: int, new_count: int
) -> tuple[int, int]:
    """Reviews first, capped by the budget; whatever budget is left over
    buys new words at :data:`NEW_WORD_COST_FACTOR`× a review's cost each,
    because a new word is normally answered twice before the session ends
    (once cold, once having just seen the answer). This is the entire
    reason new-word intake shrinks automatically as reviews pile up --
    the Anki failure mode the brief names by name -- with no cap ever
    chosen by the learner.
    """
    if avg_seconds <= 0:
        return 0, 0
    review_count = min(due_count, math.floor(budget_seconds / avg_seconds))
    remaining = budget_seconds - review_count * avg_seconds
    new_word_cost = NEW_WORD_COST_FACTOR * avg_seconds
    new_count_planned = min(new_count, math.floor(remaining / new_word_cost))
    return review_count, new_count_planned


async def _totals(session: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    """Total / learning / mastered for the home progress bar.

    Loaded as two plain columns for every saved word rather than counted in
    three separate queries, because the three buckets are not independent
    conditions to run past the database separately -- they are a PARTITION
    of the same rows, and the one case that needs care (a ``suspended`` word
    that also happens to be stable enough to count as ``mastered``) is
    easiest to get right by looking at both columns together in Python. A
    learner's saved words are at most a few thousand rows; this is the same
    trade ``collections.py`` makes for a course's progress.
    """
    rows = await session.exec(
        select(SavedWord.status, SavedWord.passive_stability).where(
            SavedWord.user_id == user_id
        )
    )
    total = mastered = suspended = 0
    for status, stability in rows.all():
        total += 1
        if status == "known" or (
            stability is not None and stability >= MASTERED_STABILITY_DAYS
        ):
            mastered += 1
        elif status == "suspended":
            suspended += 1
    return {
        "total": total,
        "learning": total - mastered - suspended,
        "mastered": mastered,
    }


# --- Settings ------------------------------------------------------------------


async def get_settings(session: AsyncSession, user_id: uuid.UUID) -> VocabularySettings:
    """This learner's preferences, or the defaults -- unsaved -- if they have
    never touched the settings screen. Returning a transient row rather than
    writing one on every read means opening the home page for the first time
    never has a side effect."""
    row = await session.get(VocabularySettings, user_id)
    return row if row is not None else VocabularySettings(user_id=user_id)


async def set_daily_minutes(
    session: AsyncSession, user_id: uuid.UUID, daily_minutes: int
) -> VocabularySettings:
    """Stage 1's one writable preference. An upsert rather than requiring a
    row to already exist, because the first time anyone changes this IS the
    first settings row they will ever have."""
    row = await session.get(VocabularySettings, user_id)
    if row is None:
        row = VocabularySettings(user_id=user_id, daily_minutes=daily_minutes)
    else:
        row.daily_minutes = daily_minutes
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


# --- Summary and session -------------------------------------------------------


async def summary(
    session: AsyncSession, user: User, *, tz: str | None
) -> dict:
    """Everything the home screen needs in one call: what's due, what today
    will look like if the learner starts a session, and the two progress
    numbers. See :func:`build_session` for the same plan actually realised
    as a queue of items -- the two are computed the same way on purpose, so
    the number promised here is the number the session delivers.
    """
    settings = await get_settings(session, user.id)
    avg = await _avg_seconds(session, user.id)
    window = _day_window(tz)
    spent = await _seconds_spent_today(session, user.id, window)
    budget = max(0.0, settings.daily_minutes * 60 - spent)

    due_words = await _due_words(session, user.id)
    new_words = await _new_words(session, user.id)
    planned_reviews, planned_new = _plan_counts(
        budget, avg, len(due_words), len(new_words)
    )

    return {
        "due_now": len(due_words),
        "new_available": len(new_words),
        "planned_reviews": planned_reviews,
        "planned_new": planned_new,
        "daily_minutes": settings.daily_minutes,
        "seconds_spent_today": spent,
        "avg_seconds": avg,
        "next_due_at": await _next_due_at(session, user.id),
        "totals": await _totals(session, user.id),
    }


def _item_dict(
    word: SavedWord, context: SavedWordContext | None, *, is_new: bool
) -> dict:
    gap = resolve_gap(word, context)
    return {
        "word_id": word.id,
        "context_id": context.id if context else None,
        "lemma": word.lemma,
        "pos": word.pos or (context.pos if context else ""),
        "cefr_level": context.cefr_level if context else "",
        "is_new": is_new,
        "direction": "passive",
        "exercise_type": "recall",
        "prompt": {
            "before": gap.before,
            "after": gap.after,
            "cue": gap.cue,
            "kind": gap.kind,
            "definition": gap.definition,
        },
    }


async def build_session(
    session: AsyncSession,
    user: User,
    *,
    tz: str | None,
    material_id: uuid.UUID | None = None,
) -> list[dict]:
    """The queue for one sitting, planned right now -- see
    :func:`_plan_counts`. Stage 1 issues only ``passive``/``recall``, so
    every item is built the same way; a later exercise type is a second
    branch here, not a rewrite of the planning above it.

    Whichever context each item uses is decided ONCE per word, up front,
    over a single query shared by the whole queue (:func:`_last_used_map`)
    rather than one lookup per word -- a session is at most a few dozen
    items, and this is the difference between one round trip and a few
    dozen.
    """
    settings = await get_settings(session, user.id)
    avg = await _avg_seconds(session, user.id)
    window = _day_window(tz)
    spent = await _seconds_spent_today(session, user.id, window)
    budget = max(0.0, settings.daily_minutes * 60 - spent)

    due_words = await _due_words(session, user.id, material_id=material_id)
    new_words = await _new_words(session, user.id, material_id=material_id)
    review_count, new_count = _plan_counts(
        budget, avg, len(due_words), len(new_words)
    )

    queue: list[tuple[SavedWord, bool]] = [
        (word, False) for word in due_words[:review_count]
    ] + [(word, True) for word in new_words[:new_count]]
    if not queue:
        return []

    word_ids = [word.id for word, _ in queue]
    contexts_by_word = await _contexts_by_word(session, word_ids)
    all_context_ids = [
        context.id
        for contexts in contexts_by_word.values()
        for context in contexts
    ]
    last_used = await _last_used_map(session, all_context_ids)

    items = []
    for word, is_new in queue:
        context = _pick_context(contexts_by_word.get(word.id, []), last_used)
        items.append(_item_dict(word, context, is_new=is_new))
    return items


# --- Recording an answer --------------------------------------------------------


async def record_answer(
    session: AsyncSession,
    user: User,
    *,
    word_id: uuid.UUID,
    context_id: uuid.UUID | None,
    direction: Direction,
    exercise_type: ExerciseType,
    given: str,
    elapsed_ms: int,
) -> dict | None:
    """Grade one answer, advance its card, and log it. Returns ``None`` for
    a word that is not this learner's -- the API turns that into a 404 --
    and otherwise the shape :class:`PracticeAnswerOut` sends back.

    The context named in the request is trusted only as far as it actually
    belongs to this word; a mismatched or unknown id is treated as no
    context at all (the fallback-definition gap) rather than an error,
    because the one thing that must never happen is a learner's answer
    failing to record over a client-side bookkeeping slip.
    """
    word = await session.get(SavedWord, word_id)
    if word is None or word.user_id != user.id:
        return None

    context: SavedWordContext | None = None
    if context_id is not None:
        candidate = await session.get(SavedWordContext, context_id)
        if candidate is not None and candidate.saved_word_id == word.id:
            context = candidate

    gap = resolve_gap(word, context)
    verdict = verdict_for(given, gap.answer)
    rating = rating_for(exercise_type, verdict)

    now = datetime.now(timezone.utc)
    card = _load_card(word, direction)
    # The schedule this answer is judged against -- null for a card that has
    # never been reviewed, since there is no prior due date to have been
    # early or late against. Read BEFORE `review_card` mutates a copy.
    was_review = card.state == fsrs.State.Review
    scheduled_at = card.due if card.last_review is not None else None

    updated, _library_log = SCHEDULER.review_card(
        card, rating, review_datetime=now, review_duration=elapsed_ms
    )
    _store_card(word, direction, updated)

    # A lapse is specifically a REVIEW-state card answered Again -- a card
    # still in Learning failing a step is normal progress, not a lapse.
    if was_review and rating == fsrs.Rating.Again:
        word.lapses += 1
    word.reps += 1
    word.status = _status_for(updated.state)
    session.add(word)

    session.add(
        VocabularyReviewLog(
            user_id=user.id,
            saved_word_id=word.id,
            lemma=word.lemma,
            context_id=context.id if context else None,
            direction=direction,
            exercise_type=exercise_type,
            rating=int(rating),
            given=(given or "")[:200],
            elapsed_ms=elapsed_ms,
            scheduled_at=scheduled_at,
            reviewed_at=now,
            state=int(updated.state),
            stability=updated.stability,
            difficulty=updated.difficulty,
        )
    )
    await session.commit()

    material_id = context.material_id if context else None
    material_title = ""
    if material_id is not None:
        titles = await materials_service.titles_for(session, [material_id])
        material_title = titles.get(material_id, "")

    return {
        "verdict": verdict,
        "rating": int(rating),
        "answer": gap.answer,
        "returns_this_session": rating == fsrs.Rating.Again,
        "next_due_at": updated.due,
        "word": {
            "lemma": word.lemma,
            "pos": word.pos or (context.pos if context else ""),
            "cefr_level": context.cefr_level if context else "",
            "meaning_core_en": word.meaning_core_en
            or (context.meaning_core_en if context else ""),
            "meaning_core_uz": word.meaning_core_uz
            or (context.meaning_core_uz if context else ""),
            "meaning_en": context.meaning_en if context else "",
            "meaning_uz": context.meaning_uz if context else "",
            "sense_differs": context.sense_differs if context else False,
            "material_id": material_id,
            "material_title": material_title,
        },
    }

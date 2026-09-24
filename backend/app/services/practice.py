"""Scheduling a saved word: FSRS, the ladder, leech, and the daily budget.

The only module in this codebase that imports ``fsrs``. Everything the rest
of the app needs from a card -- its state, when it's next due, whether an
answer was good enough -- comes through the functions here, so the library
can be swapped or re-parametrised (see :class:`app.models.vocabulary
.VocabularyReviewLog`, kept from the first answer for exactly that reason)
without a second module having learnt its shapes.

``app.services.distractors`` sits beside this module rather than inside it:
building a recognise item's four options is a pure candidate-and-filter
pipeline over ``material_vocabulary`` that touches no FSRS card at all, and
keeping it apart means the pipeline the plan expects to be RE-TUNED (the
similarity guard's threshold) lives in a file with no scheduling logic in it
to accidentally also change.

## The rating is computed, never asked

Anki asks the learner to grade themselves "easy / good / hard" after every
card, which is the one part of Anki this module refuses to copy. A learner
mid-sentence has no real basis for that judgement, and self-graded ease is
famously unreliable -- flattering on an easy day, harsh on a tired one, and
never comparable between two people. What IS reliable is the pairing of
*which exercise* and *how the answer went*: recognising a translation and
correctly TYPING the word from a bare definition are different strengths of
evidence for the same card, however right the answer was. :data:`RATING_TABLE`
is that pairing, spelled out for all four exercises.

## No interval halving on a wrong answer

The plan is explicit about this because it is the everyday mistake: a wrong
answer feels like it should shrink the interval, and FSRS already does the
right, non-obvious thing on its own -- ``Rating.Again`` drops the card's
*stability* and raises its *difficulty*, which is what actually slows the
card down long-term. The ladder (below) is a second, DELIBERATELY separate
thing: promotion and demotion move a word between TASKS (``recognise`` /
``recall`` / ``produce``), never touch a schedule, and FSRS keeps scoring
this card exactly as it would with no ladder at all.

## The ladder is a stored level, not a derived one

``SavedWord.passive_level``/``active_level`` say which task is currently
served for each direction. Promotion needs 2 consecutive corrects at the
floor (``recognise``) -- or 1, if the word has ever been at the top rung
before (a re-promotion after a demotion, which shouldn't cost what the FIRST
promotion cost) -- and demotion is a single Again at the top rung. Both are
read from ``vocabulary_review_logs.planned_exercise`` (see that column's own
docstring), never recomputed from FSRS state, because the ladder's question
-- "which task was this encounter AT" -- and FSRS's question -- "how well
was it remembered" -- are independent facts about the same answer.

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

import logging
import math
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import fsrs
from fastapi import HTTPException, status
from sqlalchemy import exists, func
from sqlmodel import select

from app.core.database import AsyncSession
from app.models.user import User
from app.models.vocabulary import (
    ACTIVE_LEVELS,
    PASSIVE_LEVELS,
    SavedWord,
    SavedWordContext,
    VocabularyReviewLog,
    VocabularySettings,
)
from app.services import distractors
from app.services import materials as materials_service
from app.services import mistakes
from app.services.answers import normalize_answer

logger = logging.getLogger("app.services.practice")

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
#: leech is set aside until the learner makes one of the three choices, and
#: a known word has nothing left to schedule. Not excluded from the totals
#: below, which count all three; the totals are a report and the queue is a
#: plan, and the same word answers both questions differently.
EXCLUDED_STATUSES: frozenset[str] = frozenset({"known", "suspended", "leech"})

#: A passive card this stable has been remembered for three weeks running,
#: which is the plan's own line for "no longer worth calling `learning`" on
#: the home progress bar -- AND, in stage 2, the line for "stable enough to
#: start the active card too" (see :data:`ACTIVE_UNLOCK_STABILITY_DAYS`,
#: which is the same number for a different reason kept as its own name).
MASTERED_STABILITY_DAYS = 21.0
#: A learner can produce a word from nothing only once they can recognise it
#: without hesitation -- a passive card stable for three weeks is the plan's
#: own bar for that. Named separately from ``MASTERED_STABILITY_DAYS``
#: despite sharing its value today: one is "no longer `learning`" (a display
#: bucket) and the other is "safe to start a second skill on" (an unlock
#: gate), and a future change to either must not silently move the other.
ACTIVE_UNLOCK_STABILITY_DAYS = 21.0

#: How many consecutive correct answers at the ladder's floor
#: (``recognise``) are needed to promote -- unless the word has been at the
#: top rung before, which needs only 1 (see :func:`_apply_ladder`).
PROMOTE_STREAK = 2

#: The ONE exercise a fallback may substitute for the ladder's own planned
#: level -- see :func:`record_answer`'s server-side authority check.
#: ``recognise`` is the only level a fallback ever leaves (a fallback is
#: always a step FORWARD, never sideways or back -- see
#: ``app.services.distractors``), so this is the whole table: no entry for
#: ``recall``/``produce`` means no fallback is ever accepted there, and an
#: ``exercise_type`` claiming one is rejected outright.
FALLBACK_EXERCISE: dict[Direction, str] = {"passive": "recall", "active": "produce"}

#: Leech: either this many lapses since the last reset...
LEECH_LAPSE_THRESHOLD = 6
#: ...or this many within this many days, also since the last reset. Two
#: separate thresholds because a word wrong six times over a year and a
#: word wrong four times in a fortnight are different problems -- the
#: second is the one actually costing a learner their week, and the first
#: would miss it for months.
LEECH_RECENT_LAPSE_THRESHOLD = 4
LEECH_RECENT_WINDOW_DAYS = 14
#: How long "set aside" lasts. A learner who chooses it is saying "not now",
#: not "never" -- resolved lazily wherever a queue is built
#: (:func:`_reap_suspensions`), never by a worker.
SUSPEND_DAYS = 30

DEFAULT_DAILY_MINUTES = 10
DEFAULT_AVG_SECONDS = 12.0
MIN_AVG_SECONDS = 4.0
MAX_AVG_SECONDS = 60.0
AVG_SECONDS_SAMPLE = 200
MIN_LOGS_FOR_AVERAGE = 20
#: A new word is likely answered twice before it settles (once badly, once
#: better) -- see the plan -- so it is costed at twice one review's time
#: rather than measured on its own, which nothing has data for on day one.
#: A newly unlocked ACTIVE card is costed the same way, for the same reason.
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
    -- those are set by something other than an FSRS transition."""
    return "review" if state == fsrs.State.Review else "learning"


def recompute_status(word: SavedWord) -> str:
    """The status a word should carry when nothing else is claiming it --
    ``known``, ``suspended`` and ``leech`` are all deliberate overrides, and
    this is what a word falls back to once one of those is lifted (a bulk
    ``restore``, or a leech choice other than "set aside"). Read off
    whichever direction's card has actually been reviewed; the passive card
    always has been, for any word this function is ever asked about, so the
    active branch only matters for a word whose active card started and
    whose passive one somehow never did.
    """
    state = word.passive_state if word.passive_state is not None else word.active_state
    if state is None:
        return "learning"
    return _status_for(fsrs.State(state))


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


_VERDICT_RANK: dict[Verdict, int] = {"correct": 0, "close": 1, "wrong": 2}


def _kindest(verdicts: list[Verdict]) -> Verdict:
    """The best of several verdicts for the same answer against several
    accepted forms -- see :func:`_accepted_produce_forms`. An answer one
    edit from one accepted spelling and unrecognisable against another is
    a spelling slip, because the learner was plainly reaching for the
    first; the same rule :func:`app.services.mistakes.classify` already
    applies across accepted ANSWERS, used here across accepted FORMS of one
    word."""
    return min(verdicts, key=lambda v: _VERDICT_RANK[v])


def _was_correct(exercise_type: ExerciseType, rating: fsrs.Rating) -> bool:
    """Whether an already-graded answer counts as CORRECT for the ladder's
    promotion rule -- derived from the stored rating rather than a second
    stored verdict, because :data:`RATING_TABLE` already makes "correct"
    the unique rating each exercise reserves for it: ``Easy`` for
    ``produce`` (``close`` there is ``Good``), ``Good`` for everything else
    (``close`` there is ``Hard`` or, on ``recognise``, ``Again``)."""
    if exercise_type == "produce":
        return rating == fsrs.Rating.Easy
    return rating == fsrs.Rating.Good


# --- The gap (recall) ---------------------------------------------------------


@dataclass(frozen=True)
class Gap:
    """What a recall prompt shows, and the answer it is graded against.

    ``answer`` never reaches the client before the answer is submitted --
    see the API layer, which builds :class:`PracticeItemOut` from this same
    dataclass but leaves the field off. It is recomputed, not stored,
    when the learner's answer comes back in: ``resolve_gap`` is a pure
    function of the word and the chosen context, so it is called once to
    build the prompt (dropping the ``answer`` field) and again, identically,
    when the submitted answer comes back -- no session state is kept
    between the two requests.
    """

    before: str
    after: str
    cue: str
    kind: Literal["sentence", "definition"]
    definition: str | None
    answer: str


@dataclass(frozen=True)
class Mark:
    """What a recognise prompt shows: the word marked in its sentence,
    UNBLANKED -- the learner is choosing its meaning, not typing it back,
    so there is nothing to hide about which letters it is."""

    before: str
    target: str
    after: str


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
    at all, or a surface that genuinely is not IN the sentence text -- using
    the word's own usual meaning first and the context's contextual one
    only if that is empty, per the brief. The answer there is the lemma.

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


def resolve_mark(word: SavedWord, context: SavedWordContext | None) -> Mark:
    """The recognise prompt's sentence, with the word marked rather than
    blanked. Same search as :func:`resolve_gap` (surface, then lemma, in
    the same sentence) -- the two are the same rule wearing two hats,
    kept apart because a gap's "answer" and a mark's "target" are different
    facts even when the coordinates that find them are identical.
    """
    if context is not None and context.example:
        match = _find_surface(context.example, context.surface or word.lemma)
        if match is None and context.surface and context.surface != word.lemma:
            match = _find_surface(context.example, word.lemma)
        if match is not None:
            start, end = match
            return Mark(
                before=context.example[:start],
                target=context.example[start:end],
                after=context.example[end:],
            )
    return Mark(before="", target=word.lemma, after="")


def _passive_definition(word: SavedWord, context: SavedWordContext | None) -> str:
    """The ENGLISH definition a passive `recognise` right answer shows, and
    the text the similarity guard compares every candidate against, for
    both directions -- see ``app.services.distractors``."""
    return word.meaning_core_en or (context.meaning_en if context else "") or ""


def _active_meaning_uz(word: SavedWord, context: SavedWordContext | None) -> str:
    """The Uzbek meaning an active item shows -- the prompt itself, for
    `recognise` and `produce` alike."""
    return word.meaning_core_uz or (context.meaning_uz if context else "") or ""


def _recognise_right_text(
    word: SavedWord, context: SavedWordContext | None, direction: Direction
) -> str:
    """The text the CORRECT option shows: a definition for passive, the
    lemma itself for active -- see ``app.services.distractors.build``'s
    ``option_field``."""
    if direction == "active":
        return word.lemma
    return _passive_definition(word, context)


def grade_choice(given: str, word_id: uuid.UUID, right_text: str) -> Verdict:
    """A recognise answer, graded by recomputing the right option's opaque
    id and comparing -- see ``distractors.option_id``. Nothing about which
    four options were shown is stored anywhere; the four are rebuilt only
    when the prompt is, and grading needs none of that, only the ONE text
    that was correct.
    """
    correct_id = distractors.option_id(word_id, right_text)
    return "correct" if given == correct_id else "wrong"


async def _accepted_produce_forms(
    session: AsyncSession, word: SavedWord
) -> list[str]:
    """Every spelling a `produce` answer is accepted against: the lemma,
    and every context's surface -- "the boy WENT" should not be marked
    wrong for typing `went` because the dictionary form is `go`. The
    kindest verdict across all of them wins (see :func:`_kindest`)."""
    rows = await session.exec(
        select(SavedWordContext.surface).where(
            SavedWordContext.saved_word_id == word.id
        )
    )
    return [word.lemma] + [surface for surface in rows.all() if surface]


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


# --- The ladder ----------------------------------------------------------------


def _current_level(word: SavedWord, direction: Direction) -> str:
    """The task a direction is currently AT. ``passive_level`` is never
    null; ``active_level`` is null until the active card's first real
    answer (see :func:`record_answer`), and "not started yet" reads as the
    ladder's own floor for any caller building a fresh item."""
    if direction == "passive":
        return word.passive_level
    return word.active_level or "recognise"


async def _promotion_streak(
    session: AsyncSession, word_id: uuid.UUID, direction: Direction, level: str
) -> int:
    """How many of the most recent answers AT ``level`` (by
    ``planned_exercise``, not ``exercise_type`` -- a fallback answered
    harder still counts) were correct, most recent first, stopping at the
    first one that wasn't or that was asked at a different level. That stop
    condition is also the whole of "a wrong answer at recognise just resets
    the streak": the wrong answer becomes the newest row, and the very next
    read of this function stops on it immediately.
    """
    rows = await session.exec(
        select(
            VocabularyReviewLog.exercise_type,
            VocabularyReviewLog.rating,
            VocabularyReviewLog.planned_exercise,
        )
        .where(
            VocabularyReviewLog.saved_word_id == word_id,
            VocabularyReviewLog.direction == direction,
        )
        .order_by(VocabularyReviewLog.reviewed_at.desc())
        .limit(50)
    )
    streak = 0
    for exercise_type, rating, planned in rows.all():
        if planned != level:
            break
        if not _was_correct(exercise_type, fsrs.Rating(rating)):
            break
        streak += 1
    return streak


async def _has_reached_level(
    session: AsyncSession, word_id: uuid.UUID, direction: Direction, level: str
) -> bool:
    """Whether this word has EVER been asked at ``level`` before -- the
    ladder's re-promotion exception: a word demoted from the top rung goes
    back up after 1 correct, not :data:`PROMOTE_STREAK`, because it has
    already proven it once."""
    row = await session.exec(
        select(VocabularyReviewLog.id)
        .where(
            VocabularyReviewLog.saved_word_id == word_id,
            VocabularyReviewLog.direction == direction,
            VocabularyReviewLog.planned_exercise == level,
        )
        .limit(1)
    )
    return row.first() is not None


async def _apply_ladder(
    session: AsyncSession,
    word: SavedWord,
    direction: Direction,
    planned_exercise: str,
    exercise_type: ExerciseType,
    rating: fsrs.Rating,
) -> None:
    """Move a word one rung, if this answer earned it -- see the module
    docstring. Reads ``planned_exercise`` (what the ladder asked for this
    encounter), never ``exercise_type`` alone, so a fallback answered
    correctly at a HARDER exercise than the ladder currently asks for still
    counts as evidence for promotion, and a fallback answered wrong still
    counts as a miss at the floor rather than nothing at all.

    Demotion and promotion are mutually exclusive branches on purpose: the
    floor (``recognise``) can only be promoted FROM, the top rung
    (``recall``/``produce``) can only be demoted FROM, and there is no third
    rung either direction could be asked at.
    """
    low, high = PASSIVE_LEVELS if direction == "passive" else ACTIVE_LEVELS
    if planned_exercise == low:
        if not _was_correct(exercise_type, rating):
            return
        streak = await _promotion_streak(session, word.id, direction, low) + 1
        ever_reached_higher = await _has_reached_level(
            session, word.id, direction, high
        )
        threshold = 1 if ever_reached_higher else PROMOTE_STREAK
        if streak >= threshold:
            setattr(word, f"{direction}_level", high)
    elif planned_exercise == high:
        # Hard (spelling/plural, `close`) does NOT demote -- only an actual
        # Again does, which is exactly the rating a `wrong` verdict produces
        # at the top rung of either ladder (see RATING_TABLE: recall's
        # `close` is Hard, produce's is Good, neither is Again).
        if rating == fsrs.Rating.Again:
            setattr(word, f"{direction}_level", low)


# --- Leech -----------------------------------------------------------------


async def _lapses_since_reset(
    session: AsyncSession, word: SavedWord, direction: Direction
) -> list[datetime]:
    """Every genuine lapse (a REVIEW-state card answered Again) for this
    word's ``direction``, since ``leech_reset_at`` -- or ever, if it has
    never reset.

    Whether a row is a lapse is not stored on the row itself (see
    ``VocabularyReviewLog`` -- it keeps the POST-answer state). It is
    reconstructed instead from the state chain: a card's state entering
    answer N is exactly the state answer N-1 left it in, so walking the log
    in order and remembering the previous row's ``state`` recovers the same
    fact ``record_answer`` had live when it happened, with no extra column.
    """
    rows = await session.exec(
        select(
            VocabularyReviewLog.reviewed_at,
            VocabularyReviewLog.rating,
            VocabularyReviewLog.state,
        )
        .where(
            VocabularyReviewLog.saved_word_id == word.id,
            VocabularyReviewLog.direction == direction,
        )
        .order_by(VocabularyReviewLog.reviewed_at)
    )
    lapses: list[datetime] = []
    previous_state: int | None = None
    for reviewed_at, rating, state in rows.all():
        if previous_state == int(fsrs.State.Review) and rating == int(
            fsrs.Rating.Again
        ):
            if word.leech_reset_at is None or reviewed_at > word.leech_reset_at:
                lapses.append(reviewed_at)
        previous_state = state
    return lapses


def _is_leech(lapse_times: list[datetime], now: datetime) -> bool:
    """Either threshold trips it -- see the two constants' own docstrings
    for why they are separate numbers rather than one."""
    if len(lapse_times) >= LEECH_LAPSE_THRESHOLD:
        return True
    window_start = now - timedelta(days=LEECH_RECENT_WINDOW_DAYS)
    recent = sum(1 for t in lapse_times if t >= window_start)
    return recent >= LEECH_RECENT_LAPSE_THRESHOLD


async def resolve_leech(
    session: AsyncSession,
    user: User,
    *,
    lemma: str,
    choice: Literal["set_aside", "see_context", "keep"],
) -> SavedWord | None:
    """One of the three choices the brief gives a leech word. "Set aside"
    is the only one that actually leaves the word out of rotation; "see it
    where you met it" and "keep practising" are the SAME mutation --
    status recomputed, lapse count reset -- because the difference between
    them is only which screen the learner asked from, not anything the
    server needs to remember.
    """
    rows = await session.exec(
        select(SavedWord).where(SavedWord.user_id == user.id, SavedWord.lemma == lemma)
    )
    word = rows.first()
    if word is None:
        return None
    now = datetime.now(timezone.utc)
    if choice == "set_aside":
        word.status = "suspended"
        word.suspended_until = now + timedelta(days=SUSPEND_DAYS)
    else:
        word.status = recompute_status(word)
        word.suspended_until = None
        word.leech_reset_at = now
    session.add(word)
    await session.commit()
    await session.refresh(word)
    return word


async def _reap_suspensions(session: AsyncSession, user_id: uuid.UUID) -> None:
    """The lazy half of "set aside for 30 days": resolved here, at the top
    of every queue-building call, rather than by a worker sweeping for
    expired ones. A learner who never opens the app while a word is
    suspended costs nothing extra; one who does gets a queue that is
    already correct.
    """
    now = datetime.now(timezone.utc)
    rows = await session.exec(
        select(SavedWord).where(
            SavedWord.user_id == user_id,
            SavedWord.status == "suspended",
            SavedWord.suspended_until.is_not(None),
            SavedWord.suspended_until <= now,
        )
    )
    words = list(rows.all())
    if not words:
        return
    for word in words:
        word.status = recompute_status(word)
        word.suspended_until = None
        word.leech_reset_at = now
        session.add(word)
    await session.commit()


# --- Queues: due, new, active unlock, and the material filter ----------------


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


async def _active_due_words(
    session: AsyncSession, user_id: uuid.UUID, *, material_id: uuid.UUID | None = None
) -> list[SavedWord]:
    """The active card's own due queue.

    Unconditional in ITSELF -- ``direction`` is not read here, the same
    separation every other query in this section keeps: this is the plain
    fact "which active cards are due", and the caller (:func:`_gather_
    candidates`) decides whether the setting means that fact should be
    acted on right now. See that function's own docstring for the pause
    rule this enables."""
    query = select(SavedWord).where(
        SavedWord.user_id == user_id,
        SavedWord.status.not_in(EXCLUDED_STATUSES),
        SavedWord.active_state.is_not(None),
        SavedWord.active_due <= datetime.now(timezone.utc),
    )
    if material_id is not None:
        query = query.where(_has_material_clause(material_id))
    rows = await session.exec(query.order_by(SavedWord.active_due))
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


async def _active_unlock_candidates(
    session: AsyncSession, user_id: uuid.UUID, *, material_id: uuid.UUID | None = None
) -> list[SavedWord]:
    """Words whose active card has not started but is ELIGIBLE to: passive
    stability past :data:`ACTIVE_UNLOCK_STABILITY_DAYS`. Gated by
    ``direction == "both"`` in the caller, not here, so this query stays
    the plain fact "which words qualify" and the setting stays a filter
    over it, the same separation ``_gather_candidates`` keeps everywhere
    else."""
    query = select(SavedWord).where(
        SavedWord.user_id == user_id,
        SavedWord.status.not_in(EXCLUDED_STATUSES),
        SavedWord.active_state.is_(None),
        SavedWord.passive_stability.is_not(None),
        SavedWord.passive_stability >= ACTIVE_UNLOCK_STABILITY_DAYS,
    )
    if material_id is not None:
        query = query.where(_has_material_clause(material_id))
    rows = await session.exec(query.order_by(SavedWord.created_at))
    return list(rows.all())


async def _next_due_at(
    session: AsyncSession, user_id: uuid.UUID, *, active_enabled: bool
) -> datetime | None:
    """The nearest due time across BOTH directions -- a learner who has
    finished today's session wants to know when anything next needs them,
    not only when their passive cards do. ``active_enabled`` is
    ``settings.direction == "both"``; while it is false every active card is
    paused (see :func:`_gather_candidates`) and has no bearing on "when does
    this learner need to come back"."""
    passive_row = await session.exec(
        select(func.min(SavedWord.passive_due)).where(
            SavedWord.user_id == user_id,
            SavedWord.status.not_in(EXCLUDED_STATUSES),
            SavedWord.passive_state.is_not(None),
        )
    )
    candidates = [passive_row.one()]
    if active_enabled:
        active_row = await session.exec(
            select(func.min(SavedWord.active_due)).where(
                SavedWord.user_id == user_id,
                SavedWord.status.not_in(EXCLUDED_STATUSES),
                SavedWord.active_state.is_not(None),
            )
        )
        candidates.append(active_row.one())
    candidates = [d for d in candidates if d is not None]
    return min(candidates) if candidates else None


async def active_in_progress_count(session: AsyncSession, user_id: uuid.UUID) -> int:
    """How many of this learner's active cards have actually started
    (``active_state`` not null) and are not already retired (``known`` or
    ``suspended``) -- the settings screen's own line, shown beside the
    direction toggle: "N words are being practised actively -- they'll
    pause, not reset." Read regardless of the CURRENT ``direction`` value,
    because it answers the same question -- what is at stake in flipping the
    toggle -- whether it is about to turn active practice off or on.

    A ``leech`` word still counts: its active card really is running (see
    :func:`_gather_candidates`'s pause rule), it is merely excluded from
    queues until the learner resolves it, which is a different fact from
    "retired"."""
    row = await session.exec(
        select(func.count()).where(
            SavedWord.user_id == user_id,
            SavedWord.active_state.is_not(None),
            SavedWord.status.not_in(("known", "suspended")),
        )
    )
    return row.one()


# --- Mode, and gathering one session's candidates ----------------------------


def _effective_mode(mode: str, settings: VocabularySettings) -> str:
    """``auto`` unless the caller forced something, or the learner's own
    default narrows it for them: a settings screen with exactly ONE
    exercise type ticked is exactly as forceful as typing that mode by
    hand, and the brief's "bugun faqat yozish" is meant to work either way.
    """
    if mode and mode != "auto":
        return mode
    if settings.exercise_types and len(settings.exercise_types) == 1:
        return settings.exercise_types[0]
    return "auto"


@dataclass
class _Candidate:
    """One word, claimed for one direction, for one session -- the shape
    :func:`_gather_candidates` de-duplicates over so no word is ever queued
    twice (see the brief's "a word never appears twice in one session")."""

    word: SavedWord
    direction: Direction
    is_new: bool
    due_at: datetime | None
    level: str


_FAR_FUTURE = datetime.max.replace(tzinfo=timezone.utc)


async def _gather_candidates(
    session: AsyncSession,
    user: User,
    settings: VocabularySettings,
    *,
    mode: str,
    material_id: uuid.UUID | None,
) -> tuple[list[_Candidate], list[_Candidate]]:
    """Everything :func:`summary` and :func:`build_session` need, computed
    identically for both so the number one promises is the number the
    other delivers.

    Returns ``(due, new)``, each already de-duplicated by word (the more
    overdue direction wins a tie) and filtered to ``mode``. Order inside
    ``due`` is most-overdue-first; order inside ``new`` is active unlocks
    before brand-new words, each FIFO by save time -- the brief's own
    ordering for "reviews, then new active cards, then new words".

    ``active_enabled`` (``direction == "both"``) gates BOTH active queries,
    not only the unlock one. Turning the toggle off PAUSES every active
    card, already-running ones included: none of them enter ``due`` or
    ``new``, so none of them can be answered this session, but nothing
    about the card itself -- its FSRS state, its stored ``active_level`` --
    is touched, and nothing resets. Turning the toggle back to ``both``
    resumes exactly where each card was, because pausing never wrote
    anything to resume FROM. This is the one place that decision is made;
    :func:`_active_due_words` and :func:`_active_unlock_candidates`
    themselves stay unconditional so they answer the same question
    (:func:`active_in_progress_count` reads the same fact for the settings
    screen's own count) regardless of who is asking or why.
    """
    effective_mode = _effective_mode(mode, settings)
    active_enabled = settings.direction == "both"

    passive_due = await _due_words(session, user.id, material_id=material_id)
    active_due = (
        await _active_due_words(session, user.id, material_id=material_id)
        if active_enabled
        else []
    )
    passive_new = await _new_words(session, user.id, material_id=material_id)
    active_new = (
        await _active_unlock_candidates(session, user.id, material_id=material_id)
        if active_enabled
        else []
    )

    due_by_word: dict[uuid.UUID, _Candidate] = {}
    for word in passive_due:
        due_by_word[word.id] = _Candidate(
            word=word, direction="passive", is_new=False,
            due_at=word.passive_due, level=word.passive_level,
        )
    for word in active_due:
        candidate = _Candidate(
            word=word, direction="active", is_new=False,
            due_at=word.active_due, level=_current_level(word, "active"),
        )
        existing = due_by_word.get(word.id)
        if existing is None or (candidate.due_at or _FAR_FUTURE) < (
            existing.due_at or _FAR_FUTURE
        ):
            due_by_word[word.id] = candidate

    used_ids = set(due_by_word)
    new_candidates: list[_Candidate] = []
    for word in active_new:
        if word.id in used_ids:
            continue
        used_ids.add(word.id)
        new_candidates.append(
            _Candidate(
                word=word, direction="active", is_new=True, due_at=None,
                level="recognise",
            )
        )
    for word in passive_new:
        if word.id in used_ids:
            continue
        used_ids.add(word.id)
        new_candidates.append(
            _Candidate(
                word=word, direction="passive", is_new=True, due_at=None,
                level="recognise",
            )
        )

    def _matches_mode(candidate: _Candidate) -> bool:
        return effective_mode == "auto" or candidate.level == effective_mode

    due_list = sorted(
        (c for c in due_by_word.values() if _matches_mode(c)),
        key=lambda c: c.due_at or _FAR_FUTURE,
    )
    new_list = [c for c in new_candidates if _matches_mode(c)]
    return due_list, new_list


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
    buys new items (brand-new words AND newly unlocked active cards alike)
    at :data:`NEW_WORD_COST_FACTOR`x a review's cost each, because either
    is normally answered twice before the session ends (once cold, once
    having just seen the answer). This is the entire reason new-word intake
    shrinks automatically as reviews pile up -- the Anki failure mode the
    brief names by name -- with no cap ever chosen by the learner.
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
    easiest to get right by looking at both columns together in Python.
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


async def _set_aside_count(session: AsyncSession, user_id: uuid.UUID) -> int:
    """How many words are currently set aside -- the home screen's "N words
    set aside" line, so a 30-day return is never a silent surprise."""
    row = await session.exec(
        select(func.count()).where(
            SavedWord.user_id == user_id, SavedWord.status == "suspended"
        )
    )
    return row.one()


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
    """Stage 1's one writable preference, kept as its own function because
    existing callers (and tests) ask for exactly this and nothing else."""
    row = await session.get(VocabularySettings, user_id)
    if row is None:
        row = VocabularySettings(user_id=user_id, daily_minutes=daily_minutes)
    else:
        row.daily_minutes = daily_minutes
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def update_settings(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    daily_minutes: int,
    direction: Literal["passive", "both"],
    exercise_types: list[str] | None,
) -> VocabularySettings:
    """Stage 2's settings screen, all three fields at once -- a PUT rather
    than three separate setters, because the screen shows them together and
    saves them together."""
    row = await session.get(VocabularySettings, user_id)
    if row is None:
        row = VocabularySettings(user_id=user_id)
    row.daily_minutes = daily_minutes
    row.direction = direction
    row.exercise_types = exercise_types
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


# --- Building one item ---------------------------------------------------------


def _base_item(
    word: SavedWord,
    context: SavedWordContext | None,
    *,
    direction: Direction,
    exercise_type: ExerciseType,
    planned_exercise: str,
    is_new: bool,
) -> dict:
    return {
        "word_id": word.id,
        "context_id": context.id if context else None,
        "lemma": word.lemma,
        "pos": word.pos or (context.pos if context else ""),
        "cefr_level": context.cefr_level if context else "",
        "is_new": is_new,
        "direction": direction,
        "exercise_type": exercise_type,
        "planned_exercise": planned_exercise,
    }


def _recall_item(
    word: SavedWord,
    context: SavedWordContext | None,
    *,
    direction: Direction,
    planned_exercise: str,
    is_new: bool,
) -> dict:
    gap = resolve_gap(word, context)
    item = _base_item(
        word, context, direction=direction, exercise_type="recall",
        planned_exercise=planned_exercise, is_new=is_new,
    )
    item["prompt"] = {
        "kind": gap.kind,
        "before": gap.before,
        "after": gap.after,
        "cue": gap.cue,
        "definition": gap.definition,
    }
    return item


def _produce_item(
    word: SavedWord,
    context: SavedWordContext | None,
    *,
    is_new: bool,
    planned_exercise: str,
) -> dict:
    item = _base_item(
        word, context, direction="active", exercise_type="produce",
        planned_exercise=planned_exercise, is_new=is_new,
    )
    item["prompt"] = {
        "kind": "produce",
        "meaning_uz": _active_meaning_uz(word, context),
        "pos": item["pos"],
        "cue": word.lemma[:1],
    }
    return item


def _choice_item(
    word: SavedWord,
    context: SavedWordContext | None,
    *,
    direction: Direction,
    is_new: bool,
    options: list[distractors.Option],
    shown_meaning_uz: str | None,
) -> dict:
    item = _base_item(
        word, context, direction=direction, exercise_type="recognise",
        planned_exercise="recognise", is_new=is_new,
    )
    # Passive marks the sentence; active shows only the Uzbek meaning (per
    # the brief) and has no sentence to mark.
    mark = resolve_mark(word, context) if direction == "passive" else None
    item["prompt"] = {
        "kind": "choice",
        "before": mark.before if mark else "",
        "target": mark.target if mark else "",
        "after": mark.after if mark else "",
        "shown_meaning_uz": shown_meaning_uz,
        "options": [{"id": option.id, "text": option.text} for option in options],
    }
    return item


def _rng_seed(word_id: uuid.UUID, context: SavedWordContext | None) -> int:
    """Deterministic per (word, context) so the same item, rebuilt, shuffles
    its options the same way -- ``uuid.UUID.__hash__``/``.int`` are not
    salted the way ``str``'s is, so this is stable across requests without
    needing to store anything."""
    return (word_id.int ^ (context.id.int if context else 0)) & 0xFFFFFFFF


async def _build_item(
    session: AsyncSession,
    word: SavedWord,
    direction: Direction,
    level: str,
    context: SavedWordContext | None,
    *,
    is_new: bool,
    source_material_ids: frozenset[uuid.UUID],
    family_keys: frozenset[str],
) -> dict:
    """One queued (word, direction) -> one item, dispatching on the
    ladder's current level. ``recall``/``produce`` are direct; ``recognise``
    tries the distractor pipeline first and falls back one step FORWARD
    (never sideways to a worse prompt) when it comes back empty -- see the
    module docstring and ``app.services.distractors``.
    """
    if direction == "passive" and level == "recall":
        return _recall_item(
            word, context, direction="passive", planned_exercise="recall",
            is_new=is_new,
        )
    if direction == "active" and level == "produce":
        return _produce_item(word, context, is_new=is_new, planned_exercise="produce")

    # `recognise`, either direction.
    right_text = _recognise_right_text(word, context, direction)
    definition = _passive_definition(word, context)
    built = await distractors.build(
        session,
        word_id=word.id,
        right_text=right_text,
        right_definition=definition,
        pos=word.pos or (context.pos if context else ""),
        cefr_level=context.cefr_level if context else "",
        source_material_ids=source_material_ids,
        family_keys=family_keys,
        exclude_lemma=word.lemma,
        option_field="lemma" if direction == "active" else "definition",
        rng_seed=_rng_seed(word.id, context),
    )
    if built.options is None:
        logger.info(
            "vocabulary distractor fallback",
            extra={
                "lemma": word.lemma,
                "direction": direction,
                "reason": built.fallback_reason,
            },
        )
        if direction == "passive":
            return _recall_item(
                word, context, direction="passive", planned_exercise="recognise",
                is_new=is_new,
            )
        return _produce_item(
            word, context, is_new=is_new, planned_exercise="recognise"
        )

    shown_meaning_uz = (
        _active_meaning_uz(word, context) if direction == "active" else None
    )
    return _choice_item(
        word, context, direction=direction, is_new=is_new, options=built.options,
        shown_meaning_uz=shown_meaning_uz,
    )


# --- Summary and session -------------------------------------------------------


async def summary(session: AsyncSession, user: User, *, tz: str | None, mode: str = "auto") -> dict:
    """Everything the home screen needs in one call: what's due, what today
    will look like if the learner starts a session, and the two progress
    numbers. See :func:`build_session` for the same plan actually realised
    as a queue of items -- the two share :func:`_gather_candidates` so the
    number promised here is the number the session delivers.
    """
    await _reap_suspensions(session, user.id)
    settings = await get_settings(session, user.id)
    avg = await _avg_seconds(session, user.id)
    window = _day_window(tz)
    spent = await _seconds_spent_today(session, user.id, window)
    budget = max(0.0, settings.daily_minutes * 60 - spent)

    due_list, new_list = await _gather_candidates(
        session, user, settings, mode=mode, material_id=None
    )
    planned_reviews, planned_new = _plan_counts(
        budget, avg, len(due_list), len(new_list)
    )

    return {
        "due_now": len(due_list),
        "new_available": len(new_list),
        "planned_reviews": planned_reviews,
        "planned_new": planned_new,
        "daily_minutes": settings.daily_minutes,
        "seconds_spent_today": spent,
        "avg_seconds": avg,
        "next_due_at": await _next_due_at(
            session, user.id, active_enabled=settings.direction == "both"
        ),
        "totals": await _totals(session, user.id),
        "set_aside": await _set_aside_count(session, user.id),
    }


async def build_session(
    session: AsyncSession,
    user: User,
    *,
    tz: str | None,
    material_id: uuid.UUID | None = None,
    mode: str = "auto",
) -> list[dict]:
    """The queue for one sitting, planned right now -- see
    :func:`_plan_counts`.

    Whichever context each item uses is decided ONCE per word, up front,
    over a single query shared by the whole queue (:func:`_last_used_map`)
    rather than one lookup per word -- a session is at most a few dozen
    items, and this is the difference between one round trip and a few
    dozen. The learner's ``learning``-status family keys (for the
    distractor pipeline's step 4) are the same story: computed once, shared
    by every recognise item this queue builds.
    """
    await _reap_suspensions(session, user.id)
    settings = await get_settings(session, user.id)
    avg = await _avg_seconds(session, user.id)
    window = _day_window(tz)
    spent = await _seconds_spent_today(session, user.id, window)
    budget = max(0.0, settings.daily_minutes * 60 - spent)

    due_list, new_list = await _gather_candidates(
        session, user, settings, mode=mode, material_id=material_id
    )
    review_count, new_count = _plan_counts(
        budget, avg, len(due_list), len(new_list)
    )

    queue = due_list[:review_count] + new_list[:new_count]
    if not queue:
        return []

    word_ids = [candidate.word.id for candidate in queue]
    contexts_by_word = await _contexts_by_word(session, word_ids)
    all_context_ids = [
        context.id
        for contexts in contexts_by_word.values()
        for context in contexts
    ]
    last_used = await _last_used_map(session, all_context_ids)
    family_keys = await distractors.learning_family_keys(session, user.id)

    items = []
    for candidate in queue:
        contexts = contexts_by_word.get(candidate.word.id, [])
        context = _pick_context(contexts, last_used)
        source_material_ids = frozenset(context.material_id for context in contexts)
        item = await _build_item(
            session, candidate.word, candidate.direction, candidate.level, context,
            is_new=candidate.is_new, source_material_ids=source_material_ids,
            family_keys=family_keys,
        )
        items.append(item)
    return items


async def build_known_check_item(
    session: AsyncSession, user: User, word_id: uuid.UUID
) -> dict | None:
    """The one-attempt recall prompt behind "I know this" -- always
    `recall`, never the ladder's own current level, because this is a
    bypass of the ladder and not a step on it (see the brief: offered only
    on a word's first appearance, before the ladder has asked anything).
    """
    word = await session.get(SavedWord, word_id)
    if word is None or word.user_id != user.id:
        return None
    contexts_by_word = await _contexts_by_word(session, [word.id])
    contexts = contexts_by_word.get(word.id, [])
    last_used = await _last_used_map(session, [context.id for context in contexts])
    context = _pick_context(contexts, last_used)
    return _recall_item(
        word, context, direction="passive", planned_exercise="recall", is_new=True
    )


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
    planned_exercise: str | None = None,
    claim_known: bool = False,
) -> dict | None:
    """Grade one answer, advance its card, move the ladder, and log it.
    Returns ``None`` for a word that is not this learner's -- the API turns
    that into a 404 -- and otherwise the shape :class:`PracticeAnswerOut`
    sends back.

    ``planned_exercise`` is accepted on the wire (:class:`PracticeAnswerIn`
    echoes whatever the item carried) but its VALUE is never read here --
    see below. The server is the only party that gets to say what the
    ladder asked for; a client that could name its own ``planned_exercise``
    could plant a fabricated ``vocabulary_review_logs`` row claiming a word
    "has already reached" its top rung (:func:`_has_reached_level`), buying
    every later real promotion the cheap 1-correct re-promotion price
    instead of :data:`PROMOTE_STREAK` -- a forged log a re-fit of FSRS
    could not tell from a real one. So it is recomputed from the word's own
    stored level for this ``direction`` (:func:`_current_level`) every time,
    and ``exercise_type`` is checked against THAT, not trusted either:
    the only exercise a caller may serve is the level itself, or -- when the
    level is the ladder's floor (``recognise``) -- the one harder exercise a
    distractor-pipeline fallback is allowed to substitute
    (:data:`FALLBACK_EXERCISE`). Anything else is a 422: a client asking for
    ``produce`` on a word still at passive ``recognise``, say, is not a
    fallback the pipeline would ever choose and not a level the ladder ever
    served.

    ``direction="active"`` is refused unless the active card has already
    started (:func:`_current_level` returning something is not enough on its
    own -- see ``active_level``'s own null-means-not-started rule) or the
    unlock gate is met right now: ``direction`` setting ``both`` AND passive
    stability past :data:`ACTIVE_UNLOCK_STABILITY_DAYS`. Otherwise a client
    could start producing a word it was never granted, which is exactly the
    skill the gate exists to withhold until recognising it is effortless.

    ``claim_known`` is refused unless the word's passive card has NEVER been
    practised (``passive_state is None``) -- "I know this" is a bypass
    offered on a brand-new word's first appearance and nothing else (see the
    brief), so a claim against a word already in rotation is rejected
    outright rather than silently marking it known on a technicality.

    The context named in the request is trusted only as far as it actually
    belongs to this word; a mismatched or unknown id is treated as no
    context at all, because the one thing that must never happen is a
    learner's answer failing to record over a client-side bookkeeping slip.
    """
    word = await session.get(SavedWord, word_id)
    if word is None or word.user_id != user.id:
        return None

    context: SavedWordContext | None = None
    if context_id is not None:
        candidate = await session.get(SavedWordContext, context_id)
        if candidate is not None and candidate.saved_word_id == word.id:
            context = candidate

    if claim_known:
        # The known-check bypass is new-word-only -- a passive card that has
        # ever been practised is already in rotation, and removing it is a
        # deliberate act on the words list, never an in-session reflex.
        if word.passive_state is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "claim_known is only valid on a word that has never been "
                "practised",
            )
        if direction != "passive" or exercise_type != "recall":
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "claim_known's one follow-up is always a passive recall "
                "answer",
            )
        planned_exercise = "recall"
    else:
        if direction == "active":
            already_started = (
                word.active_level is not None or word.active_state is not None
            )
            if not already_started:
                settings = await get_settings(session, user.id)
                unlocked = (
                    settings.direction == "both"
                    and word.passive_stability is not None
                    and word.passive_stability >= ACTIVE_UNLOCK_STABILITY_DAYS
                )
                if not unlocked:
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_ENTITY,
                        "active practice is not unlocked for this word",
                    )

        planned_exercise = _current_level(word, direction)
        fallback = FALLBACK_EXERCISE.get(direction) if planned_exercise == "recognise" else None
        if exercise_type != planned_exercise and exercise_type != fallback:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "exercise_type does not match the ladder's planned level "
                "for this word",
            )

    if exercise_type == "recognise":
        right_text = _recognise_right_text(word, context, direction)
        verdict = grade_choice(given, word.id, right_text)
        answer_text = right_text
    elif exercise_type == "produce":
        forms = await _accepted_produce_forms(session, word)
        verdict = _kindest([verdict_for(given, form) for form in forms])
        answer_text = word.lemma
    else:  # "recall" -- including every fallback that lands here
        gap = resolve_gap(word, context)
        verdict = verdict_for(given, gap.answer)
        answer_text = gap.answer

    # "I know this": correct is rated Easy and the word is `known` outright
    # -- a stronger signal than an ordinary correct recall answer, and one
    # the learner asked for by pressing the button, not one the scheduler
    # inferred. Anything else grades exactly as an ordinary recall answer
    # and the word stays in rotation, per the brief.
    became_known = claim_known and verdict == "correct"
    rating = fsrs.Rating.Easy if became_known else rating_for(exercise_type, verdict)

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
    is_lapse = was_review and rating == fsrs.Rating.Again
    if is_lapse:
        word.lapses += 1
    word.reps += 1
    word.status = "known" if became_known else _status_for(updated.state)

    # The active card's very first real answer is what starts its ladder --
    # not the moment it was queued as a new item, which never touched the
    # database. See `SavedWord.active_level`'s own docstring.
    if direction == "active" and word.active_level is None:
        word.active_level = "recognise"
    await _apply_ladder(session, word, direction, planned_exercise, exercise_type, rating)

    session.add(word)
    session.add(
        VocabularyReviewLog(
            user_id=user.id,
            saved_word_id=word.id,
            lemma=word.lemma,
            context_id=context.id if context else None,
            direction=direction,
            exercise_type=exercise_type,
            planned_exercise=planned_exercise,
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

    # Checked only on a genuine new lapse -- anything else cannot possibly
    # have pushed the count over either threshold, and a leech word is
    # never re-flagged (it is excluded from every queue the moment it
    # becomes one, so it cannot lapse again before the learner resolves it).
    became_leech = False
    if is_lapse and word.status != "known":
        lapses = await _lapses_since_reset(session, word, direction)
        if _is_leech(lapses, now):
            word.status = "leech"
            session.add(word)
            await session.commit()
            became_leech = True

    material_id = context.material_id if context else None
    material_title = ""
    if material_id is not None:
        titles = await materials_service.titles_for(session, [material_id])
        material_title = titles.get(material_id, "")

    return {
        "verdict": verdict,
        "rating": int(rating),
        "answer": answer_text,
        "returns_this_session": rating == fsrs.Rating.Again,
        "next_due_at": updated.due,
        "known": became_known,
        "became_leech": became_leech,
        "status": word.status,
        "level": getattr(word, f"{direction}_level") or "recognise",
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

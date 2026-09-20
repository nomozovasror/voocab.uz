"""How hard a material is — worked out from what people got wrong, not
declared by whoever wrote it.

An author is the worst judge of their own paper's difficulty: they know where
the answers are. So difficulty here is a *measurement* over
:class:`QuestionAttempt` — the share of answers that came back correct — and
the band an author's material carries is whatever that measurement says today.

**Nothing in here is stored on the material.** That is the point, and it is
what makes the next stage cheap. Today's answer is a classic proportion
correct (stage 1); the one after it is a Rasch/1PL estimate (stage 2), which
exists because a proportion is biased by *who sat the paper*: a hard material
that only strong candidates attempt comes back looking easy. Rasch separates
item difficulty from candidate ability and undoes that. When that day comes,
only the body of :func:`_band` and the query feeding it change — no column, no
migration, no UI.

**When it is computed.** :func:`recompute` on the worker's timer, plus one
targeted refresh at the moment a material first crosses :data:`MIN_ANSWERS`
(:func:`refresh_if_unrated`) — see there for why that one transition is worth
not waiting for and the rest are not.

**How it is served.** The measurement is expensive in exactly the way that
does not scale: it is an aggregate over every answer on the platform, and at
a thousand materials computing it per request means scanning the whole of
``question_attempts`` to draw a four-letter chip. So the material-level tally
lives in a projection table (:class:`app.models.material_difficulty.MaterialDifficulty`)
that :func:`recompute` refills on a schedule, and :func:`material_difficulty`
reads it back by primary key.

That is a cache, not a column. Nothing authored ever reaches it, it is a pure
function of the attempts, and dropping it costs one recompute — which is the
line CLAUDE.md's rule is drawing. The price is honest and worth naming: a
band can be up to one refresh interval out of date. Difficulty is an average
over hundreds of answers, so it does not meaningfully move in fifteen
minutes; what does happen is that a material crossing :data:`MIN_ANSWERS` for
the first time keeps saying ``New`` until the next pass, and that is the
right trade against a page that takes seconds to load.

:func:`question_difficulty` is deliberately NOT projected: it is scoped to
one material, so it is bounded by that material's own answers however big the
library gets.
"""

import uuid
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import case, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select

from app.core.database import AsyncSession
from app.models.attempt import Attempt, AttemptStatus
from app.models.material import PAPER_TYPES, Material
from app.models.material_difficulty import MaterialDifficulty
from app.models.part import Part
from app.models.question import Question
from app.models.question_attempt import QuestionAttempt
from app.models.question_group import QuestionGroup

#: Difficulty bands, in the order a learner reads them as "getting harder".
#: ``new`` is not a fourth level of hard — it is the absence of a level.
Band = Literal["new", "easy", "medium", "hard"]

#: How many answers a material needs before its band means anything.
#:
#: A percentage over three answers is noise wearing a number's clothes: one
#: candidate having a bad morning would move a material two bands. Below this
#: the honest answer is that we do not know yet, and the honest label for that
#: is ``New`` — never a fabricated "50%".
MIN_ANSWERS = 20

#: Proportion correct at or above which a material is ``easy``; below
#: :data:`MEDIUM_AT` it is ``hard``, and between them ``medium``. Read as
#: "three quarters of people get these right" and "fewer than half do".
EASY_AT = 0.75
MEDIUM_AT = 0.45

#: Where a passage's VOCABULARY puts it, for the materials nobody has
#: answered enough of yet.
#:
#: The figure is the share of a passage's running words that neither the NGSL
#: nor the NAWL knows -- ``profile()["off_list_share"]`` in `seed/vocabulary.py`
#: -- and these two numbers are the tertiles of it measured over 86 glossed
#: Cambridge passages: p33 = 0.095, p67 = 0.127, over a range of 0.049 to
#: 0.196.
#:
#: Tertiles rather than round numbers, because the scale is comparative and
#: has no absolute meaning. "12% of this passage is off-list" is not a fact a
#: learner can place; "harder than two thirds of the reading papers here" is.
#: Splitting the corpus in three is the only calibration that makes the three
#: words mean what they say.
#:
#: Note which measure this is and which it is not. ``frequency_band`` is
#: deterministic and identical across the whole catalogue, which is what
#: makes two passages comparable. ``cefr_level`` is the model's, sees the
#: context, and is the better figure for ONE word -- and drifts from material
#: to material, so an average of it cannot be compared with another average
#: of it. The learner sees CEFR; the arithmetic uses frequency.
VOCAB_EASY_UNDER = 0.095
VOCAB_HARD_OVER = 0.127


def _estimate(load: float | None) -> Band:
    """The band a passage's vocabulary alone suggests.

    A guess, and it says so wherever it is shown. What it is guessing from is
    real though: how often a reader is stopped by a word neither frequency
    list knows. It cannot see the questions, and a passage of plain words can
    carry a brutal set of TRUE/FALSE/NOT GIVEN — which is exactly why the
    measured band replaces this the moment there are enough answers to have
    one.
    """
    if load is None:
        return "new"
    if load < VOCAB_EASY_UNDER:
        return "easy"
    if load <= VOCAB_HARD_OVER:
        return "medium"
    return "hard"


def _band(
    correct: int, answered: int, load: float | None = None
) -> tuple[Band, int | None]:
    """The band for one tally, plus the percentage it came from.

    The percentage is returned alongside rather than recomputed by callers,
    so the band and the number that justifies it can never disagree — and it
    is ``None`` below the threshold, because a band that came from the
    vocabulary has no proportion-correct to show.

    Below :data:`MIN_ANSWERS` the vocabulary answers if it can. That is the
    cold-start fix: a material nobody has sat is not a material nobody can
    judge, because its TEXT is right there and measurable. What the
    measurement cannot do is outlive the real thing — twenty answers and the
    estimate is gone, replaced by what actually happened to people.
    """
    if answered < MIN_ANSWERS:
        return _estimate(load), None
    rate = correct / answered
    if rate >= EASY_AT:
        return "easy", round(rate * 100)
    if rate >= MEDIUM_AT:
        return "medium", round(rate * 100)
    return "hard", round(rate * 100)


def unknown() -> dict:
    """What a material with no answers against it looks like. One definition,
    so the "never attempted" row and the "attempted twice" row are the same
    shape and the caller never has to check which it got."""
    return {"band": "new", "correct_pct": None, "answered": 0, "estimated": False}


async def _tally(
    session: AsyncSession, material_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int]]:
    """``(correct, answered)`` per material, over everybody's answers.

    Everybody's, deliberately: this is a property of the paper, not of the
    person reading the list. A learner's own history sits in their own column
    of the catalogue row, and mixing the two would mean a material got easier
    because you personally happened to do well on it.

    One grouped aggregate for every material at once rather than a query per
    row. Materials with nothing against them are simply absent from the
    result — the callers fill that in, each in the way that suits them.

    **Drills are excluded**, and this is the one aggregate that has to say so
    out loud. Everywhere else a drill is invisible for free, because every
    other reader compares ``status == SUBMITTED`` and a drill is ``DRILLED``.
    This one never joins :class:`Attempt` at all — it counts answer rows —
    so without the join below it would sweep in answers from people who never
    sat the paper. A map drill answers six of Part 2's ten questions and
    skips the four multiple-choice ones entirely; folding that into "how hard
    is this material" would rate the paper on a sample chosen by which task
    people happened to be practising.

    The QUESTION-level aggregate below (:func:`question_difficulty`)
    deliberately does the opposite and keeps no such filter: a drill answer is
    a genuine answer to that question, and that is where the evidence belongs.
    """
    if not material_ids:
        return {}
    return {
        material_id: (int(correct or 0), int(answered or 0))
        for material_id, answered, correct in (
            await session.exec(
                select(
                    Part.material_id,
                    func.count(QuestionAttempt.id),
                    func.count(QuestionAttempt.id).filter(QuestionAttempt.is_correct),
                )
                .select_from(QuestionAttempt)
                .join(Attempt, Attempt.id == QuestionAttempt.attempt_id)  # type: ignore[arg-type]
                .join(Question, Question.id == QuestionAttempt.question_id)  # type: ignore[arg-type]
                .join(QuestionGroup, QuestionGroup.id == Question.group_id)  # type: ignore[arg-type]
                .join(Part, Part.id == QuestionGroup.part_id)  # type: ignore[arg-type]
                .where(
                    Part.material_id.in_(material_ids),  # type: ignore[attr-defined]
                    Attempt.status == AttemptStatus.SUBMITTED,
                )
                .group_by(Part.material_id)  # type: ignore[arg-type]
            )
        ).all()
    }


async def recompute(
    session: AsyncSession, material_ids: list[uuid.UUID] | None = None
) -> int:
    """Refill the projection. Returns how many materials were written.

    ``material_ids`` narrows it to those; the default is every listening
    material there is, which is what the periodic refresher runs. The
    narrowed form is here because it is the seam for the other cadence — a
    submit-time refresh of the one material just answered — without anything
    else moving. That is deliberately not wired up: it would put a write on
    the submit path to keep a number fresher than it needs to be.

    Materials with no answers at all are written too, as a ``new`` row with a
    zero tally, rather than left out. A missing row and a row saying nobody
    has answered are the same fact, and having only one of them exist means
    the read path never has to guess which it is looking at.

    One statement for the write. A thousand upserts in a loop is a thousand
    round trips, and this runs against the whole library.
    """
    if material_ids is None:
        material_ids = list(
            (
                await session.exec(
                    select(Material.id).where(
                        Material.type.in_(PAPER_TYPES)  # type: ignore[attr-defined]
                    )
                )
            ).all()
        )
    if not material_ids:
        return 0

    tallies = await _tally(session, material_ids)
    # The one column here that is not a function of the attempts. Read back
    # rather than recomputed, because computing it means tokenising every
    # passage against the frequency lists — which happens once, in the seed
    # pipeline, and must not happen again every fifteen minutes.
    loads = await _loads(session, material_ids)
    now = datetime.now(timezone.utc)
    rows = []
    for material_id in material_ids:
        correct, answered = tallies.get(material_id, (0, 0))
        band, _pct = _band(correct, answered, loads.get(material_id))
        rows.append(
            {
                "material_id": material_id,
                "answered": answered,
                "correct": correct,
                "band": band,
                "computed_at": now,
            }
        )

    statement = pg_insert(MaterialDifficulty).values(rows)
    await session.exec(  # type: ignore[call-overload]
        statement.on_conflict_do_update(
            index_elements=[MaterialDifficulty.material_id],
            # `vocabulary_load` is deliberately absent. It is written by the
            # importer, measured from the text, and a refresh of the
            # attempt tally has nothing to say about it — listing it here
            # would blank it on the next pass of the worker.
            set_={
                "answered": statement.excluded.answered,
                "correct": statement.excluded.correct,
                "band": statement.excluded.band,
                "computed_at": statement.excluded.computed_at,
            },
        )
    )
    await session.commit()
    return len(rows)


async def _loads(
    session: AsyncSession, material_ids: list[uuid.UUID]
) -> dict[uuid.UUID, float]:
    """The vocabulary load of each of these, where one has been measured."""
    return {
        material_id: float(load)
        for material_id, load in (
            await session.exec(
                select(
                    MaterialDifficulty.material_id,
                    MaterialDifficulty.vocabulary_load,
                ).where(
                    MaterialDifficulty.material_id.in_(material_ids),  # type: ignore[attr-defined]
                    MaterialDifficulty.vocabulary_load.is_not(None),  # type: ignore[attr-defined]
                )
            )
        ).all()
    }


async def set_vocabulary_load(
    session: AsyncSession, material_id: uuid.UUID, load: float
) -> None:
    """Record how much of this material's text is off the frequency lists.

    Called by the passage importer, which is the only thing that has the
    figure: it is produced by `seed/vocabulary.py` while the passage is being
    read and cannot be recovered from the database, because the frequency
    lists do not live on this side of the fence.

    The measurement is ALWAYS recorded; the band it implies is written only
    while nothing better exists. Those are two different things, and guarding
    them with one condition got it wrong: a material twenty people had
    already sat kept its measured band, correctly, and silently failed to
    record the input behind the estimate it no longer needed. The fact about
    the text is true whatever anybody scored.

    Setting the band here as well as the load, rather than leaving it to the
    next :func:`recompute`, is what makes the catalogue's own filter right
    immediately: that column is what SQL sorts and filters by, and an
    estimate a learner cannot find the material by only decorates a row.
    """
    statement = pg_insert(MaterialDifficulty).values(
        material_id=material_id,
        vocabulary_load=load,
        band=_estimate(load),
        computed_at=datetime.now(timezone.utc),
    )
    await session.exec(  # type: ignore[call-overload]
        statement.on_conflict_do_update(
            index_elements=[MaterialDifficulty.material_id],
            set_={
                "vocabulary_load": statement.excluded.vocabulary_load,
                # Past the threshold the stored band is a measurement of what
                # happened to people, and an import must not talk over it.
                "band": case(
                    (
                        MaterialDifficulty.answered < MIN_ANSWERS,
                        statement.excluded.band,
                    ),
                    else_=MaterialDifficulty.band,
                ),
            },
        )
    )


async def refresh_if_unrated(
    session: AsyncSession, material_id: uuid.UUID
) -> bool:
    """Recompute one material, but only while it has no band worth waiting
    for. Returns whether it did.

    The timer is the right cadence for a measurement averaged over hundreds
    of answers: a rated material's band does not move in fifteen minutes, and
    refreshing it on every submit would be a write on the path a learner is
    waiting on to keep a number fresher than anybody can perceive.

    The exception is the first crossing of :data:`MIN_ANSWERS`. Until then the
    material reads ``New`` — "nobody has answered enough of this yet" — and a
    material that a class of twenty has just worked through, still advertising
    that nobody has been near it, is the catalogue contradicting itself in
    front of the people who proved it wrong. So that one transition happens
    immediately and everything after it waits for the worker.

    What it costs in the common case is a primary-key lookup: a material past
    the threshold is answered here and goes no further. In the uncommon case
    it is the tally for one material, bounded by that material's own answers
    however big the library grows.
    """
    row = await session.get(MaterialDifficulty, material_id)
    if row is not None and row.answered >= MIN_ANSWERS:
        return False
    await recompute(session, [material_id])
    return True


async def material_difficulty(
    session: AsyncSession, material_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict]:
    """Difficulty per material, read back from the projection.

    A primary-key lookup over the ids on the page, and that is the whole
    point of the table: what this used to do — aggregate every answer on the
    platform — is now :func:`recompute`'s job and runs on a schedule.

    The band is derived here from the stored tally rather than read out of
    the stored ``band`` column, and the difference matters exactly once: the
    day :data:`EASY_AT` or :data:`MIN_ANSWERS` moves. What the API says is
    then correct immediately, while the column — which exists so SQL can
    filter and sort by it — catches up on the next refresh. The alternative
    is an API that disagrees with its own thresholds until a job runs.

    A material with no row yet (created since the last refresh, or a database
    where the refresher has never run) comes back as :func:`unknown`. Every
    id asked about comes back, so the caller never has to check.
    """
    if not material_ids:
        return {}

    stored = {
        material_id: (int(correct or 0), int(answered or 0), load)
        for material_id, answered, correct, load in (
            await session.exec(
                select(
                    MaterialDifficulty.material_id,
                    MaterialDifficulty.answered,
                    MaterialDifficulty.correct,
                    MaterialDifficulty.vocabulary_load,
                ).where(
                    MaterialDifficulty.material_id.in_(material_ids)  # type: ignore[attr-defined]
                )
            )
        ).all()
    }

    out: dict[uuid.UUID, dict] = {}
    for material_id in material_ids:
        if material_id not in stored:
            out[material_id] = unknown()
            continue
        correct, answered, load = stored[material_id]
        band, pct = _band(correct, answered, load)
        out[material_id] = {
            "band": band,
            "correct_pct": pct,
            "answered": answered,
            # Said out loud, because the two bands are not the same claim.
            # One is what happened to people who sat this; the other is a
            # guess from the words in it, and a page that printed them
            # identically would be passing off a guess as a measurement.
            "estimated": band != "new" and pct is None,
        }
    return out


async def question_difficulty(
    session: AsyncSession, material_id: uuid.UUID
) -> dict[uuid.UUID, dict]:
    """The same measurement, one row per question of one material.

    The catalogue shows the material's band; this is the level underneath it,
    and it is what stage 2 will actually estimate — Rasch fits *items*, and a
    material's difficulty is a summary of its items'. Built now so the shape
    exists before the model that fills it does; a review screen that wants to
    say "everyone misses number 7" reads it too.
    """
    tallies = {
        question_id: (int(correct or 0), int(answered or 0))
        for question_id, answered, correct in (
            await session.exec(
                select(
                    QuestionAttempt.question_id,
                    func.count(QuestionAttempt.id),
                    func.count(QuestionAttempt.id).filter(QuestionAttempt.is_correct),
                )
                .select_from(QuestionAttempt)
                .join(Question, Question.id == QuestionAttempt.question_id)  # type: ignore[arg-type]
                .join(QuestionGroup, QuestionGroup.id == Question.group_id)  # type: ignore[arg-type]
                .join(Part, Part.id == QuestionGroup.part_id)  # type: ignore[arg-type]
                .where(Part.material_id == material_id)
                .group_by(QuestionAttempt.question_id)  # type: ignore[arg-type]
            )
        ).all()
    }
    out: dict[uuid.UUID, dict] = {}
    for question_id, (correct, answered) in tallies.items():
        band, pct = _band(correct, answered)
        out[question_id] = {
            "band": band,
            "correct_pct": pct,
            "answered": answered,
        }
    return out

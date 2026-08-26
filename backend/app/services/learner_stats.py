"""What a learner is good and bad at, from their own answers.

The catalogue tells someone what there is to sit; this tells them what to do
next. Three rules run through all of it, and all three are about not lying:

* **First attempts are the measurement.** Somebody who sits a material three
  times and finishes on 95% has not learned to listen — they have learned that
  paper. Every figure here that describes ability (the average, the mistake
  breakdown, the trend, the part split) counts each material's FIRST submitted
  attempt and nothing else. The best-of average is reported beside it, clearly
  labelled, because progress is worth seeing too; it is never the headline.
* **A pattern needs enough of a sample.** The mistake breakdown is withheld
  until there are enough answers and enough mistakes to mean something
  (:data:`MIN_ANSWERS`, :data:`MIN_MISTAKES`), and the trend until there are
  ten attempts to draw. Below those, the page says so in words.
* **Nothing is fabricated to fill a shape.** A learner with no history gets
  nulls and empty lists, not zeroes; the page turns that into "start with Part
  1" rather than "0%".
"""

import math
import uuid
from collections import Counter
from datetime import datetime

from sqlalchemy import Float, Integer, cast, func
from sqlmodel import select

from app.core.database import AsyncSession
from app.models.attempt import Attempt, AttemptStatus
from app.models.material import Material
from app.models.part import Part
from app.models.question import Question
from app.models.question_attempt import QuestionAttempt
from app.models.question_group import QuestionGroup
from app.services import mistakes as mistakes_service
from app.services.listening import answers_are_letters

#: How many answers a distribution row needs before its percentage is worth
#: drawing. A percentage over three answers is noise wearing a number's
#: clothes.
MIN_ANSWERS = 20

#: And how many mistakes the breakdown needs before the biggest slice means
#: anything. Twelve of twenty-eight is a pattern; three of five is a morning.
MIN_MISTAKES = 10

#: How many attempts the trend needs. Fewer than this and a line chart is
#: joining up noise.
TREND_WINDOW = 10

#: The four parts of a listening paper, always reported, in order.
PARTS = (1, 2, 3, 4)


def _pct(value: float) -> int:
    """A percentage, rounded the way a person rounds.

    Not ``round()``: Python rounds halves to even, so 72.5 comes out 72 and
    73.5 comes out 74. Nobody reading a score expects that, and two figures
    on the same panel disagreeing by one because of it is the kind of bug
    that never gets reported and never stops being noticed.
    """
    return math.floor(value + 0.5)


def _score_pct(attempt: Attempt) -> int | None:
    """One attempt as a percentage, or nothing where it can't be one."""
    if not attempt.total_questions:
        return None
    return _pct((attempt.score or 0) / attempt.total_questions * 100)


def _mean(values: list[int]) -> int | None:
    return _pct(sum(values) / len(values)) if values else None


async def _submitted(session: AsyncSession, user_id: uuid.UUID) -> list[Attempt]:
    """Every attempt this learner has finished, oldest first.

    Read whole rather than aggregated in SQL, and deliberately: almost every
    figure below needs to know which attempt at a material came FIRST, which
    is an ordering question, and answering it five times in five queries would
    be five chances for the five answers to disagree. A learner's finished
    attempts number in the tens.
    """
    return list(
        (
            await session.exec(
                select(Attempt)
                .where(
                    Attempt.user_id == user_id,
                    Attempt.status == AttemptStatus.SUBMITTED,
                    Attempt.submitted_at.is_not(None),  # type: ignore[attr-defined]
                )
                .order_by(Attempt.submitted_at)  # type: ignore[arg-type]
            )
        ).all()
    )


def _first_and_best(
    attempts: list[Attempt],
) -> tuple[dict[uuid.UUID, Attempt], dict[uuid.UUID, int], bool]:
    """Each material's first attempt, its best percentage, and whether anyone
    ever sat anything twice."""
    first: dict[uuid.UUID, Attempt] = {}
    best: dict[uuid.UUID, int] = {}
    repeated = False
    for attempt in attempts:
        if attempt.material_id in first:
            repeated = True
        else:
            first[attempt.material_id] = attempt
        pct = _score_pct(attempt)
        if pct is not None:
            best[attempt.material_id] = max(
                best.get(attempt.material_id, pct), pct
            )
    return first, best, repeated


async def _resume(
    session: AsyncSession, attempts: list[Attempt]
) -> dict | None:
    """The last thing they sat, and which try it was.

    The ordinal matters: "83% on your 2nd try" and "83% on your 1st try" are
    different facts about the same number, and the panel is about being honest
    on exactly that point.
    """
    if not attempts:
        return None
    last = attempts[-1]
    material = await session.get(Material, last.material_id)
    if material is None:
        return None
    return {
        "material_id": material.id,
        "title": material.title,
        "attempt_id": last.id,
        "submitted_at": last.submitted_at,
        "score_pct": _score_pct(last),
        "attempt_number": sum(
            1 for a in attempts if a.material_id == last.material_id
        ),
    }


def _trend(first_attempts: list[Attempt]) -> dict | None:
    """The last ten first attempts, and whether they are going up.

    The comparison is between the two halves of that window rather than
    against everything before it: a window that carries its own baseline says
    something the moment it is full, and a learner who has sat exactly ten
    materials should not be told to come back later for the delta.
    """
    scored = [
        (a.submitted_at, pct)
        for a in first_attempts
        if (pct := _score_pct(a)) is not None
    ]
    if len(scored) < TREND_WINDOW:
        return None

    window = scored[-TREND_WINDOW:]
    points = [pct for _, pct in window]
    half = len(points) // 2
    earlier = _mean(points[:half]) or 0
    later = _mean(points[half:]) or 0

    return {
        "average_pct": _mean(points) or 0,
        "delta_pct": later - earlier,
        "from_pct": earlier,
        "to_pct": later,
        "points": points,
        "since": window[0][0],
    }


async def _by_part(
    session: AsyncSession, first_attempt_ids: list[uuid.UUID]
) -> list[dict]:
    """Accuracy by part, over first attempts only.

    Not shown in the sidebar any more — the difference between 62% and 66% was
    being dressed up as "your weakest area" when it is statistical noise. It
    stays on the API because the catalogue's material preview uses it to say
    what a row is worth to this reader, and because the full statistics page
    will want it.
    """
    tally: dict[int, list[int]] = {n: [0, 0] for n in PARTS}
    if not first_attempt_ids:
        return [
            {"part": n, "answered": 0, "accuracy_pct": None} for n in PARTS
        ]

    rows = (
        await session.exec(
            select(
                Part.order_index,
                func.count(QuestionAttempt.id),
                func.count(QuestionAttempt.id).filter(QuestionAttempt.is_correct),
            )
            .select_from(QuestionAttempt)
            .join(Question, Question.id == QuestionAttempt.question_id)  # type: ignore[arg-type]
            .join(QuestionGroup, QuestionGroup.id == Question.group_id)  # type: ignore[arg-type]
            .join(Part, Part.id == QuestionGroup.part_id)  # type: ignore[arg-type]
            .where(QuestionAttempt.attempt_id.in_(first_attempt_ids))  # type: ignore[attr-defined]
            .group_by(Part.order_index)  # type: ignore[arg-type]
        )
    ).all()

    for order_index, answered, correct in rows:
        part = int(order_index) + 1
        if part in tally:
            tally[part][0] += int(answered or 0)
            tally[part][1] += int(correct or 0)

    return [
        {
            "part": n,
            "answered": tally[n][0],
            "accuracy_pct": (
                _pct(tally[n][1] / tally[n][0] * 100)
                if tally[n][0] >= MIN_ANSWERS
                else None
            ),
        }
        for n in PARTS
    ]


async def _mistakes(
    session: AsyncSession, first_attempt_ids: list[uuid.UUID]
) -> dict | None:
    """What the wrong answers were wrong ABOUT.

    Over first attempts only, and over typed answers only — a letter has no
    spelling, and which distractor pulls a candidate is a different question
    for a page with room for it (see app/services/mistakes.py).

    Returns ``None`` rather than a thin breakdown when there is not enough to
    see a pattern in: the sidebar says so in a sentence, which is more use
    than a chart of four bars of one.
    """
    if not first_attempt_ids:
        return None

    rows = (
        await session.exec(
            select(QuestionAttempt, Question, QuestionGroup)
            .join(Question, Question.id == QuestionAttempt.question_id)  # type: ignore[arg-type]
            .join(QuestionGroup, QuestionGroup.id == Question.group_id)  # type: ignore[arg-type]
            .where(QuestionAttempt.attempt_id.in_(first_attempt_ids))  # type: ignore[attr-defined]
        )
    ).all()

    answered = 0
    counts: Counter[str] = Counter()
    for question_attempt, question, group in rows:
        if answers_are_letters(group):
            continue
        answered += 1
        if question_attempt.is_correct:
            continue
        counts[
            mistakes_service.classify(
                question_attempt.given_answer,
                question.correct_answers,
                group.word_limit,
            )
        ] += 1

    total = sum(counts.values())
    if answered < MIN_ANSWERS or total < MIN_MISTAKES:
        return None

    return {
        "total": total,
        "answered": answered,
        "groups": [
            {"kind": kind, "count": count}
            # Biggest first, and ties broken by the kind's own order so the
            # list doesn't reshuffle itself between two equal counts.
            for kind, count in sorted(
                counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ],
    }


async def _time_spent(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Every finished attempt, retries included — time spent is time spent.

    From ``time_spent_ms`` where the client reported it and from the gap
    between starting and submitting where it didn't; the second is always true
    and the first is more honest about pauses, so the reported number wins.
    """
    elapsed_ms = cast(
        func.extract("epoch", Attempt.submitted_at - Attempt.started_at) * 1000,
        Integer,
    )
    total = (
        await session.exec(
            select(
                func.coalesce(
                    func.sum(
                        func.greatest(
                            func.coalesce(Attempt.time_spent_ms, elapsed_ms), 0
                        )
                    ),
                    0,
                )
            )
            # Listening only. ``attempts`` is general across material types —
            # a dictation attempt scores an accuracy percentage into the same
            # column — and a listening panel that summed both would report a
            # number that is about neither.
            .join(Material, Material.id == Attempt.material_id)  # type: ignore[arg-type]
            .where(
                Attempt.user_id == user_id,
                Attempt.status == AttemptStatus.SUBMITTED,
                Attempt.submitted_at.is_not(None),  # type: ignore[attr-defined]
                Material.type == "listening",
            )
        )
    ).one()
    return int(total or 0)


async def listening_stats(session: AsyncSession, user_id: uuid.UUID) -> dict:
    """The practice page's right-hand column, whole.

    ``materials_done == 0`` is the signal the page reads to drop every card
    and put guidance in their place.
    """
    attempts = await _submitted(session, user_id)
    first_by_material, best_by_material, repeated = _first_and_best(attempts)
    first_attempts = sorted(
        first_by_material.values(),
        key=lambda a: a.submitted_at or datetime.min,
    )
    first_ids = [a.id for a in first_attempts]

    first_scores = [
        pct for a in first_attempts if (pct := _score_pct(a)) is not None
    ]

    return {
        "materials_done": len(first_by_material),
        "first_try_avg_pct": _mean(first_scores),
        # Absent until somebody has actually sat something twice: with no
        # retries it is the first-try average again under a second name, and
        # two identical numbers labelled differently is a panel inviting you
        # to work out what it means.
        "best_avg_pct": (
            _mean(list(best_by_material.values())) if repeated else None
        ),
        "time_spent_ms": await _time_spent(session, user_id),
        "resume": await _resume(session, attempts),
        "mistakes": await _mistakes(session, first_ids),
        "trend": _trend(first_attempts),
        "by_part": await _by_part(session, first_ids),
    }

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

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select

from app.core.database import AsyncSession
from app.models.material import Material
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


def _band(correct: int, answered: int) -> tuple[Band, int | None]:
    """The band for one tally, plus the percentage it came from.

    The percentage is returned alongside rather than recomputed by callers,
    so the band and the number that justifies it can never disagree — and it
    is ``None`` below the threshold, because a band of ``new`` has no
    percentage to show.
    """
    if answered < MIN_ANSWERS:
        return "new", None
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
    return {"band": "new", "correct_pct": None, "answered": 0}


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
                .join(Question, Question.id == QuestionAttempt.question_id)  # type: ignore[arg-type]
                .join(QuestionGroup, QuestionGroup.id == Question.group_id)  # type: ignore[arg-type]
                .join(Part, Part.id == QuestionGroup.part_id)  # type: ignore[arg-type]
                .where(Part.material_id.in_(material_ids))  # type: ignore[attr-defined]
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
                    select(Material.id).where(Material.type == "listening")
                )
            ).all()
        )
    if not material_ids:
        return 0

    tallies = await _tally(session, material_ids)
    now = datetime.now(timezone.utc)
    rows = []
    for material_id in material_ids:
        correct, answered = tallies.get(material_id, (0, 0))
        band, _pct = _band(correct, answered)
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
        material_id: (int(correct or 0), int(answered or 0))
        for material_id, answered, correct in (
            await session.exec(
                select(
                    MaterialDifficulty.material_id,
                    MaterialDifficulty.answered,
                    MaterialDifficulty.correct,
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
        correct, answered = stored[material_id]
        band, pct = _band(correct, answered)
        out[material_id] = {
            "band": band,
            "correct_pct": pct,
            "answered": answered,
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

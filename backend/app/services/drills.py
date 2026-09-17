"""Drills: one question group, practised on its own.

A learner who wants to get better at map labelling has 23 maps in the library
and no way to reach them. Filtering the catalogue to ``map_labelling`` finds
the 23 MATERIALS that contain one, but sitting one means sitting the whole of
Part 2 — and a map group is never alone: all 23 in the corpus sit beside a
multiple-choice, matching, note- or table-completion group. So "practise only
maps" cannot be answered by choosing better materials. It has to cut a group
out of one, which is what a drill is.

Its own module rather than more of ``listening.py``'s 1600 lines, on the same
reasoning that gave collections one: a second learner-facing list, with its
own question to answer, is its own thing. What stays in ``listening.py`` is
everything about the GROUP itself — ``group_clip``, ``get_drill_tree``,
``get_group_questions`` — beside the trees and helpers they belong with.

The counting rules here are the catalogue's, deliberately and to the letter
(see ``app/services/CLAUDE.md``): facets are counted over the whole library
and never over the page, ``done`` defaults to hidden and the endpoint says how
many that hid, and a filter exists in two places or not at all.
"""

import uuid

from sqlalchemy import Integer, case, func
from sqlalchemy import true as sa_true
from sqlmodel import select

from app.core.database import AsyncSession
from app.models.attempt import Attempt, AttemptStatus
from app.models.material import Material
from app.models.part import Part
from app.models.question import Question
from app.models.question_group import QuestionGroup
from app.services import listening as listening_service

DRILL_PAGE = 30


def _public() -> list:
    """The library a learner may drill: the same two predicates the catalogue
    opens with (``_catalogue_where``), so a drill can never reach a material
    the catalogue would not list."""
    return [Material.type == "listening", Material.visibility == "public"]


def _in_part(part_number: int | None):
    """Only drills cut from one of the paper's four parts.

    Matched on ``first_number``, never on ``parts.order_index``. The importer
    writes one part per material at index 0 whatever part it really is, so
    every seeded material looks like Part 1 by its index — ten numbers per
    part is what actually says which one it is (11 is Part 2, 31 is Part 4).
    An author-written part, which has no ``first_number``, falls back to the
    index, where the editor's ``Part {order_index + 1}`` titling does make the
    index carry the number.
    """
    if part_number is None:
        return sa_true()
    lo = (part_number - 1) * 10 + 1
    return case(
        (Part.first_number.is_not(None), Part.first_number),  # type: ignore[attr-defined]
        else_=Part.order_index * 10 + 1,
    ) == lo


def _drillable():
    """Whether a group can be drilled at all, as one SQL expression.

    A group is drillable when it has questions and every one of them carries a
    replay mark — because the clip is derived from those marks, and a group
    missing one cannot be given a clip that contains all its answers.
    ``group_clip`` returns ``None`` for exactly this case; this is the same
    judgement in SQL, so the count, the list and the take guard cannot come to
    disagree about what there is to drill. One expression, four callers: "add
    a filter in two places or not at all".

    A mark counts if it is in the columns OR in ``config["option_replay"]`` —
    a multiple-choice question keeps its per-option spans in the JSON, and
    reading only the columns would call a whole type undrillable.
    """
    has_questions = (
        select(Question.id).where(Question.group_id == QuestionGroup.id).exists()
    )
    unmarked = (
        select(Question.id)
        .where(
            Question.group_id == QuestionGroup.id,
            Question.replay_start_ms.is_(None),  # type: ignore[attr-defined]
            func.coalesce(
                func.jsonb_typeof(Question.config["option_replay"]), "null"
            )
            != "object",
        )
        .exists()
    )
    return has_questions & ~unmarked


async def type_summary(
    session: AsyncSession, user_id: uuid.UUID, *, part: int | None = None
) -> list[dict]:
    """One row per question type: how many drills there are, how many numbers
    they cover, and how many the caller has already done.

    Counted over the WHOLE public library, never over a page and never over
    what another filter left — an option that appears and vanishes as you
    filter is one nobody can aim at. Eleven rows, so it is not paged.
    """
    counts = (
        await session.exec(
            select(
                QuestionGroup.type,
                func.count(func.distinct(QuestionGroup.id)),
                func.coalesce(func.sum(_group_marks()), 0),
            )
            .select_from(QuestionGroup)
            .join(Part, Part.id == QuestionGroup.part_id)  # type: ignore[arg-type]
            .join(Material, Material.id == Part.material_id)  # type: ignore[arg-type]
            .where(*_public(), _drillable(), _in_part(part))
            .group_by(QuestionGroup.type)  # type: ignore[arg-type]
        )
    ).all()

    done = dict(
        (
            await session.exec(
                select(QuestionGroup.type, func.count(func.distinct(QuestionGroup.id)))
                .select_from(Attempt)
                .join(QuestionGroup, QuestionGroup.id == Attempt.group_id)  # type: ignore[arg-type]
                .join(Part, Part.id == QuestionGroup.part_id)  # type: ignore[arg-type]
                .where(
                    Attempt.user_id == user_id,
                    Attempt.status == AttemptStatus.DRILLED,
                    # Narrowed the same way as the total above, or a card
                    # could read "3 done" over "2 drills".
                    _in_part(part),
                )
                .group_by(QuestionGroup.type)  # type: ignore[arg-type]
            )
        ).all()
    )

    return [
        {
            "value": group_type,
            "exercises": int(exercises),
            "questions": int(questions or 0),
            "done": int(done.get(group_type, 0)),
        }
        for group_type, exercises, questions in counts
    ]


def _group_marks():
    """How many NUMBERS one group covers on the paper, as a scalar subquery.

    Not its row count. A "Choose TWO letters" question is one row and two of
    the numbers printed down the side of the paper, so a card advertising
    "124 questions" over a set marked out of 138 tells the same lie the test
    header used to tell about a 40-mark paper. ``answers_per_question`` lives
    in the group's config and is what :func:`listening.question_marks` reads;
    this is that rule in SQL.

    Correlated rather than joined, because the caller is grouped by type and a
    join to ``questions`` would multiply the group count by the question
    count.
    """
    rows = (
        select(func.count(Question.id))
        .where(Question.group_id == QuestionGroup.id)
        .scalar_subquery()
    )
    per_question = func.greatest(
        func.coalesce(
            QuestionGroup.config["answers_per_question"].astext.cast(Integer), 1
        ),
        1,
    )
    return rows * per_question


async def list_drills(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    group_type: str,
    query: str | None = None,
    part: int | None = None,
    done: bool = False,
    limit: int = DRILL_PAGE,
    offset: int = 0,
) -> dict:
    """One page of drills of a given type, with the total and what was hidden.

    ``done`` defaults to False and hides drills the caller has already
    submitted, reporting how many that hid — the catalogue's rule, for the
    catalogue's reason: a list answering "what shall I practise next" that
    leads with work already finished has stopped answering it, and a filter
    that hides things silently is one that makes the list look broken.
    """
    base = (
        select(QuestionGroup, Material, Part)
        .join(Part, Part.id == QuestionGroup.part_id)  # type: ignore[arg-type]
        .join(Material, Material.id == Part.material_id)  # type: ignore[arg-type]
    )
    where = [
        *_public(),
        _drillable(),
        QuestionGroup.type == group_type,
        _in_part(part),
    ]

    if query:
        # The same term-by-term AND the catalogue searches by, over the one
        # title a drill has: its material's.
        for term in query.split():
            where.append(Material.title.ilike(f"%{term}%"))  # type: ignore[attr-defined]

    drilled = (
        select(Attempt.id)
        .where(
            Attempt.group_id == QuestionGroup.id,
            Attempt.user_id == user_id,
            Attempt.status == AttemptStatus.DRILLED,
        )
        .exists()
    )

    total = int(
        (
            await session.exec(
                select(func.count())
                .select_from(QuestionGroup)
                .join(Part, Part.id == QuestionGroup.part_id)  # type: ignore[arg-type]
                .join(Material, Material.id == Part.material_id)  # type: ignore[arg-type]
                .where(*where, *([] if done else [~drilled]))
            )
        ).one()
    )

    done_hidden = 0
    if not done:
        done_hidden = int(
            (
                await session.exec(
                    select(func.count())
                    .select_from(QuestionGroup)
                    .join(Part, Part.id == QuestionGroup.part_id)  # type: ignore[arg-type]
                    .join(Material, Material.id == Part.material_id)  # type: ignore[arg-type]
                    .where(*where, drilled)
                )
            ).one()
        )

    rows = (
        await session.exec(
            base.where(*where, *([] if done else [~drilled]))
            # A total order, for the reason the catalogue's own order has one:
            # without the tail, row 30 of page 1 can also be row 1 of page 2.
            .order_by(
                Material.created_at.desc(),  # type: ignore[attr-defined]
                Material.id,  # type: ignore[arg-type]
                QuestionGroup.order_index,  # type: ignore[arg-type]
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()

    return {
        "items": [
            await drill_row(session, user_id, group, material, part)
            for group, material, part in rows
        ],
        "total": total,
        "done_hidden": done_hidden,
    }


async def drill_row(
    session: AsyncSession,
    user_id: uuid.UUID,
    group: QuestionGroup,
    material: Material,
    part: Part,
) -> dict:
    """Everything one drill card prints.

    ``clip_ms`` is the promise the card makes — "6 questions, 2:14" — so it is
    the clip's own length and not the recording's. It costs one
    :func:`listening.group_clip` per row, which is thirty small computations
    over questions the page is loading anyway.
    """
    questions = await listening_service.get_questions(session, group.id)
    marks = listening_service.question_marks(group)
    first_number = await listening_service.group_first_number(session, group)
    clip = await listening_service.group_clip(session, group)
    last = (
        await session.exec(
            select(Attempt)
            .where(
                Attempt.group_id == group.id,
                Attempt.user_id == user_id,
                Attempt.status == AttemptStatus.DRILLED,
            )
            .order_by(Attempt.submitted_at.desc())  # type: ignore[attr-defined]
        )
    ).first()
    return {
        "group_id": group.id,
        "type": group.type,
        "material_id": material.id,
        "material_title": material.title,
        "part_number": listening_service.part_number(part),
        "first_number": first_number,
        "last_number": first_number + len(questions) * marks - 1,
        "question_count": len(questions) * marks,
        "clip_ms": (clip["end_ms"] - clip["start_ms"]) if clip else None,
        "attempts": 0 if last is None else 1,
        "last_attempt_id": last.id if last else None,
        "last_attempt_at": last.submitted_at if last else None,
        "best_score": int(last.score or 0) if last else None,
    }


async def next_after(
    session: AsyncSession, user_id: uuid.UUID, group: QuestionGroup
) -> uuid.UUID | None:
    """The next drill of the same type the caller has not done — what the
    review's "Next map" points at.

    From a DIFFERENT material, because the drill just finished and the one
    beside it in the same Part 2 are the same recording: offering it as the
    next map would be offering the same two minutes again. Newest-first, like
    the list, so the button and the list agree about what comes next.
    """
    drilled = (
        select(Attempt.id)
        .where(
            Attempt.group_id == QuestionGroup.id,
            Attempt.user_id == user_id,
            Attempt.status == AttemptStatus.DRILLED,
        )
        .exists()
    )
    part = await session.get(Part, group.part_id)
    return (
        await session.exec(
            select(QuestionGroup.id)
            .join(Part, Part.id == QuestionGroup.part_id)  # type: ignore[arg-type]
            .join(Material, Material.id == Part.material_id)  # type: ignore[arg-type]
            .where(
                *_public(),
                _drillable(),
                QuestionGroup.type == group.type,
                Part.material_id != (part.material_id if part else None),
                ~drilled,
            )
            .order_by(
                Material.created_at.desc(),  # type: ignore[attr-defined]
                Material.id,  # type: ignore[arg-type]
            )
        )
    ).first()

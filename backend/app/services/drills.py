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
from datetime import datetime, timedelta, timezone

from sqlalchemy import Integer, case, func
from sqlalchemy import true as sa_true
from sqlmodel import select

from app.core.database import AsyncSession
from app.models.attempt import Attempt, AttemptStatus
from app.models.material import Material
from app.models.part import Part
from app.models.question import Question
from app.models.question_group import (
    LABELLING_TYPES,
    MATCHING_TYPES,
    QuestionGroup,
)
from app.services import listening as listening_service

DRILL_PAGE = 30


def _public(skill: str) -> list:
    """The library a learner may drill: the same two predicates the catalogue
    opens with (``_catalogue_where``), so a drill can never reach a material
    the catalogue would not list."""
    return [Material.type == skill, Material.visibility == "public"]


def family_of(group_type: str) -> list[str]:
    """The types a card covers, given one of them.

    Two families are more than themselves. Map and diagram labelling are the
    same task on two kinds of picture, the library holds twenty-three maps
    and two diagrams, and the tab draws them as one card. And matching is one
    task under five names — headings, information, features, sentence endings
    and listening's own — where what differs is the instruction line and how
    the box is lettered, which is exactly what a drill is practice AT.

    One definition, because two readers ask the question and they must agree —
    what "the next one of the same kind" means (:func:`next_after`) and what
    somebody is part-way through (:func:`in_progress_for`). The client has the
    same table; this is the half of it the server needs, and it is derived
    from the same ``LABELLING_TYPES`` and ``MATCHING_TYPES`` the models
    already declare.
    """
    for family in (LABELLING_TYPES, MATCHING_TYPES):
        if group_type in family:
            return sorted(family)
    return [group_type]


#: The number each part's first question carries, by paper. A listening
#: paper is ten to a part; a reading paper is roughly thirteen to a passage
#: and the boundaries are fixed by the exam rather than by the book. Both are
#: the same table the importers write ``first_number`` from.
FIRST_NUMBER = {
    "listening": (1, 11, 21, 31),
    "reading": (1, 14, 27),
}


def _in_part(part_number: int | None, skill: str = "listening"):
    """Only drills cut from one named part of the paper.

    Matched on ``first_number``, never on ``parts.order_index``. The importer
    writes one part per material at index 0 whatever part it really is, so
    every seeded material looks like Part 1 by its index — the number its
    first question carries is what actually says which one it is (11 is
    listening Part 2, 27 is Reading Passage 3). An author-written part, which
    has no ``first_number``, falls back to the index, where the editor's
    ``Part {order_index + 1}`` titling does make the index carry the number.

    The arithmetic is per paper. Ten a part is listening's; applied to
    reading it asks for a Passage 2 starting at question 11, which no reading
    material has, so every reading part filter came back empty.
    """
    numbers = FIRST_NUMBER.get(skill, FIRST_NUMBER["listening"])
    if part_number is None or not 1 <= part_number <= len(numbers):
        return sa_true()
    lo = numbers[part_number - 1]
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
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    skill: str,
    part: int | None = None,
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
            .where(*_public(skill), _drillable(), _in_part(part, skill))
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
                    _in_part(part, skill),
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
    skill: str,
    group_types: list[str],
    query: str | None = None,
    part: int | None = None,
    done: bool = False,
    limit: int = DRILL_PAGE,
    offset: int = 0,
) -> dict:
    """One page of drills, with the total and what was hidden.

    Several types rather than one, because a card on the tab can cover more
    than a single kind: map and diagram labelling are the same task on two
    kinds of picture, and there are two diagrams in the whole library. A card
    per type would be a card nobody clicks beside one that answers the same
    question.

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
        *_public(skill),
        _drillable(),
        QuestionGroup.type.in_(group_types),  # type: ignore[attr-defined]
        _in_part(part, skill),
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
    run = list(
        (
            await session.exec(
                select(Attempt)
                .where(
                    Attempt.group_id == group.id,
                    Attempt.user_id == user_id,
                    Attempt.status == AttemptStatus.DRILLED,
                )
                .order_by(Attempt.submitted_at)  # type: ignore[arg-type]
            )
        ).all()
    )
    last = run[-1] if run else None
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
        "attempts": len(run),
        "last_attempt_id": last.id if last else None,
        "last_attempt_at": last.submitted_at if last else None,
        "best_score": max((int(a.score or 0) for a in run), default=None),
        # The FIRST try, which is what anything measuring the learner reads —
        # the same split the catalogue row makes. The grid colours by this
        # one: drawn from best-of it would go green as somebody re-sat things
        # and stop showing where the trouble was.
        "first_score": int(run[0].score or 0) if run else None,
    }


async def next_after(
    session: AsyncSession, user_id: uuid.UUID, group: QuestionGroup, *, skill: str
) -> uuid.UUID | None:
    """The next drill of the same type the caller has not done — what the
    review's "Next map" points at.

    From a DIFFERENT material, because the drill just finished and the one
    beside it in the same Part 2 are the same recording: offering it as the
    next map would be offering the same two minutes again. Newest-first, like
    the list, so the button and the list agree about what comes next.

    "The same kind" means the same FAMILY, not the same type — the two
    labelling types are one card on the tab, and somebody who has worked
    every map should be offered the diagrams rather than told they are done.
    Anything else is its own family of one.
    """
    kin = family_of(group.type)
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
                *_public(skill),
                _drillable(),
                QuestionGroup.type.in_(kin),  # type: ignore[attr-defined]
                Part.material_id != (part.material_id if part else None),
                ~drilled,
            )
            .order_by(
                Material.created_at.desc(),  # type: ignore[attr-defined]
                Material.id,  # type: ignore[arg-type]
            )
        )
    ).first()


#: How many of a kind must be done before "carry on" is a fair thing to say.
#:
#: Two, and the reason is the same one the whole recommender rests on: one is
#: not a habit. Somebody who tried a single map found out what a map is; two
#: in the same kind is a person working through them, which is the only thing
#: worth interrupting the page to point at.
CARRY_ON_FROM = 2

#: And how recently the last one has to have been. A course carry-on has no
#: window, because a course is a thing somebody committed to and its order is
#: still waiting for them. A kind of question is not a commitment — nobody
#: enrolled — so "carry on with maps" a month after the last one is the page
#: inventing a plan the learner never made. A week is the unit study is
#: planned in; past it, the honest thing to carry on with is whatever they did
#: most recently instead.
CARRY_ON_WITHIN = timedelta(days=7)


async def in_progress_for(
    session: AsyncSession, user_id: uuid.UUID, *, skill: str
) -> dict | None:
    """The kind of exercise this learner was last working through, or None.

    "Last working on" and not "furthest through", exactly as the collections
    answer it: the question a page asks when somebody comes back is where they
    left off, and the most recent attempt is the only honest answer. Furthest
    through would keep pointing at the maps they abandoned in March because
    they happened to get most of the way through them first.

    Two conditions, and both are about not inventing a plan the learner never
    made — see :data:`CARRY_ON_FROM` and :data:`CARRY_ON_WITHIN`.

    Returns the family, how much of it is done, and the next one not done.
    ``None`` when there is nothing to carry on with, including when they have
    finished every exercise of the kind: "carry on" with nothing left is a
    button onto an empty page.
    """
    last = (
        await session.exec(
            select(Attempt)
            .where(
                Attempt.user_id == user_id,
                Attempt.status == AttemptStatus.DRILLED,
                Attempt.submitted_at.is_not(None),  # type: ignore[attr-defined]
            )
            .order_by(Attempt.submitted_at.desc())  # type: ignore[attr-defined]
        )
    ).first()
    if last is None or last.submitted_at is None:
        return None
    if datetime.now(timezone.utc) - last.submitted_at > CARRY_ON_WITHIN:
        return None

    group = await session.get(QuestionGroup, last.group_id)
    if group is None:
        return None
    kin = family_of(group.type)

    drilled = (
        select(Attempt.id)
        .where(
            Attempt.group_id == QuestionGroup.id,
            Attempt.user_id == user_id,
            Attempt.status == AttemptStatus.DRILLED,
        )
        .exists()
    )
    in_family = [*_public(skill), _drillable(), QuestionGroup.type.in_(kin)]  # type: ignore[attr-defined]

    def count(*extra):
        return (
            select(func.count())
            .select_from(QuestionGroup)
            .join(Part, Part.id == QuestionGroup.part_id)  # type: ignore[arg-type]
            .join(Material, Material.id == Part.material_id)  # type: ignore[arg-type]
            .where(*in_family, *extra)
        )

    total = int((await session.exec(count())).one())
    done = int((await session.exec(count(drilled))).one())
    if done < CARRY_ON_FROM or done >= total:
        return None

    # The next one not done, in the order the list shows them, so the button
    # and the list agree about what comes next.
    next_id = (
        await session.exec(
            select(QuestionGroup.id)
            .join(Part, Part.id == QuestionGroup.part_id)  # type: ignore[arg-type]
            .join(Material, Material.id == Part.material_id)  # type: ignore[arg-type]
            .where(*in_family, ~drilled)
            .order_by(
                Material.created_at.desc(),  # type: ignore[attr-defined]
                Material.id,  # type: ignore[arg-type]
                QuestionGroup.order_index,  # type: ignore[arg-type]
            )
        )
    ).first()
    if next_id is None:
        return None

    return {
        # The type the card is keyed by. The client turns it into the family's
        # name, because what we call a kind of question is not the server's
        # business — the same split the catalogue's facets already make.
        "type": group.type,
        #: When they last did one, so the caller can weigh this against a
        #: course they were also part-way through.
        "last_at": last.submitted_at,
        "done": done,
        "total": total,
        "next_group_id": next_id,
    }

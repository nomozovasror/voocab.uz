"""Listening Part-1 form-completion authoring: create/read/update/delete
Parts, QuestionGroups and their Questions.

Pure data layer — no HTTP. The router (``app/api/listening.py``) handles
authorization (owner-only) and translates absence into 404/403, plus the
one-time-use 409 for a duplicate Part ``order_index``.

``QuestionGroup`` + its ``Question`` rows are always written/replaced as one
atomic unit (§3.6/§5): the questions are never embedded in the group's JSON
``config`` — they stay normalized rows so each answer is individually
gradeable and event-sourceable via ``QuestionAttempt`` (Faza 3).
"""

import uuid

from fastapi import HTTPException, status
from sqlmodel import select

from app.core.database import AsyncSession
from app.models.part import Part
from app.models.question import Question
from app.models.question_attempt import QuestionAttempt
from app.models.question_group import QuestionGroup
from app.schemas.listening import PartCreate, PartUpdate, QuestionGroupIn


# --- Part ---------------------------------------------------------------


async def get_parts(session: AsyncSession, material_id: uuid.UUID) -> list[Part]:
    return list(
        (
            await session.exec(
                select(Part)
                .where(Part.material_id == material_id)
                .order_by(Part.order_index)
            )
        ).all()
    )


async def get_part(session: AsyncSession, part_id: uuid.UUID) -> Part | None:
    return await session.get(Part, part_id)


async def create_part(
    session: AsyncSession, material_id: uuid.UUID, data: PartCreate
) -> Part:
    part = Part(
        material_id=material_id,
        order_index=data.order_index,
        title=data.title,
        audio_start_ms=data.audio_start_ms,
        audio_end_ms=data.audio_end_ms,
    )
    session.add(part)
    await session.commit()
    await session.refresh(part)
    return part


async def update_part(session: AsyncSession, part: Part, data: PartUpdate) -> Part:
    """Partial update (title / audio range).

    A field is touched only when the key is actually present in the request
    body -- "absent" and "sent as null" are different requests, and telling
    them apart is what lets a range be cleared. Treating null as absent (the
    obvious reading of ``if data.audio_start_ms is not None``) meant a part
    trimmed to a range could never be widened back to the whole recording:
    the editor sent nulls, the server ignored them, and the old range came
    back on the next reload with no error anywhere.

    The title is the exception: it is not nullable on the row, so a null
    there is nothing to apply rather than a request to clear it.

    The end>start check runs against the MERGED result (existing DB value for
    whichever bound wasn't sent), so e.g. sending only a new ``audio_end_ms``
    still gets validated against the part's current ``audio_start_ms``."""
    sent = data.model_fields_set
    if data.title is not None:
        part.title = data.title
    if "audio_start_ms" in sent:
        part.audio_start_ms = data.audio_start_ms
    if "audio_end_ms" in sent:
        part.audio_end_ms = data.audio_end_ms

    if (
        part.audio_start_ms is not None
        and part.audio_end_ms is not None
        and part.audio_end_ms <= part.audio_start_ms
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "The part's end must come after its start",
        )

    session.add(part)
    await session.commit()
    await session.refresh(part)
    return part


async def _remove_questions(
    session: AsyncSession, questions: list[Question]
) -> None:
    """Delete questions along with the per-question attempt rows pointing at
    them.

    ``question_attempts.question_id`` is a plain FK with no ON DELETE, so a
    question anyone has ever answered cannot simply be dropped — the delete
    raises a ForeignKeyViolation and the whole request 500s. That is not a
    theoretical case: the editor autosaves the whole group, so a single test
    attempt used to make every subsequent save fail.

    Losing a gap costs its per-question detail, but not the attempt itself:
    ``attempts`` carries its own ``score``/``total_questions``, so the record
    that someone sat this material — and how they did — survives. Callers
    reach here only for questions that are genuinely going away; a question
    that merely changed is updated in place (see ``replace_question_group``)
    and keeps everything.
    """
    if not questions:
        return
    ids = [question.id for question in questions]
    attempts = (
        await session.exec(
            select(QuestionAttempt).where(QuestionAttempt.question_id.in_(ids))  # type: ignore[attr-defined]
        )
    ).all()
    # Loaded and deleted one by one rather than in a bulk DELETE: these rows
    # may already be in the session's identity map, and a bulk statement
    # leaves those copies behind as live objects pointing at rows that are
    # gone.
    for attempt in attempts:
        await session.delete(attempt)
    await session.flush()
    for question in questions:
        await session.delete(question)


async def delete_part(session: AsyncSession, part: Part) -> None:
    groups = await get_question_groups(session, part.id)
    for group in groups:
        await _remove_questions(session, await get_questions(session, group.id))
    # Flush the question deletes before the groups, and the groups before the
    # part: there's no ORM relationship to teach the unit-of-work the FK
    # order, so without this a parent delete can be issued first and trip the
    # FK constraint (same pattern as the audio/dictation delete paths).
    await session.flush()
    for group in groups:
        await session.delete(group)
    await session.flush()
    await session.delete(part)
    await session.commit()


# --- QuestionGroup + Question ---------------------------------------------


async def get_question_groups(
    session: AsyncSession, part_id: uuid.UUID
) -> list[QuestionGroup]:
    return list(
        (
            await session.exec(
                select(QuestionGroup)
                .where(QuestionGroup.part_id == part_id)
                .order_by(QuestionGroup.order_index)
            )
        ).all()
    )


async def get_question_group(
    session: AsyncSession, group_id: uuid.UUID
) -> QuestionGroup | None:
    return await session.get(QuestionGroup, group_id)


async def get_questions(
    session: AsyncSession, group_id: uuid.UUID
) -> list[Question]:
    return list(
        (
            await session.exec(
                select(Question)
                .where(Question.group_id == group_id)
                .order_by(Question.number)
            )
        ).all()
    )


async def create_question_group(
    session: AsyncSession, part_id: uuid.UUID, data: QuestionGroupIn
) -> QuestionGroup:
    """Create a group and its questions atomically. ``order_index`` is
    server-derived (append), mirroring how dictation segment order_index is
    derived from array position rather than trusted from the client."""
    existing = await get_question_groups(session, part_id)
    group = QuestionGroup(
        part_id=part_id,
        order_index=len(existing),
        type=data.type,
        instructions=data.instructions,
        word_limit=data.word_limit,
        config=data.config.model_dump(),
    )
    session.add(group)
    await session.flush()  # assign group.id
    for q in data.questions:
        session.add(
            Question(
                group_id=group.id,
                number=q.number,
                correct_answers=q.correct_answers,
                replay_start_ms=q.replay_start_ms,
                replay_end_ms=q.replay_end_ms,
            )
        )
    await session.commit()
    await session.refresh(group)
    return group


async def replace_question_group(
    session: AsyncSession, group: QuestionGroup, data: QuestionGroupIn
) -> QuestionGroup:
    """Full atomic replace of the template + question set (PATCH).

    The question set is reconciled BY NUMBER rather than wiped and recreated:
    number 3 that survives the edit stays the same row, with the same id.
    Recreating it looked equivalent — the tree that comes back is identical —
    but a ``Question`` is referenced by ``QuestionAttempt``, so dropping it
    both broke the FK (the editor autosaves, so one attempt was enough to
    make every later save 500) and, had it been allowed to cascade, would
    have thrown away the record of what learners answered every time the
    author touched a comma.

    Only numbers that disappear from the payload are removed, and that path
    goes through ``_remove_questions`` for the attempts they leave behind."""
    group.type = data.type
    group.instructions = data.instructions
    group.word_limit = data.word_limit
    group.config = data.config.model_dump()
    session.add(group)

    existing = {q.number: q for q in await get_questions(session, group.id)}
    incoming = {q.number for q in data.questions}

    # Removals first, and flushed: a question's attempt rows have to go
    # before the question, and the question before the group's new rows are
    # written, or the unit of work is free to order those statements the
    # other way round and trip the FK it was ordered around.
    await _remove_questions(
        session, [q for number, q in existing.items() if number not in incoming]
    )
    await session.flush()

    for q in data.questions:
        question = existing.get(q.number)
        if question is None:
            question = Question(group_id=group.id, number=q.number, correct_answers=[])
        question.correct_answers = q.correct_answers
        question.replay_start_ms = q.replay_start_ms
        question.replay_end_ms = q.replay_end_ms
        session.add(question)
    await session.commit()
    await session.refresh(group)
    return group


async def delete_question_group(session: AsyncSession, group: QuestionGroup) -> None:
    await _remove_questions(session, await get_questions(session, group.id))
    await session.flush()
    await session.delete(group)
    await session.commit()


async def get_material_questions(
    session: AsyncSession, material_id: uuid.UUID
) -> list[Question]:
    """Every ``Question`` belonging to a material, in the material's display
    order (part ``order_index`` -> group ``order_index`` -> question
    ``number``). ``Question.number`` is only unique within its group, not
    globally, so this traversal order — not a bare ORDER BY number — is what
    grading (Faza 3) uses to order per-question results and to build the
    question_id -> correct_answers map."""
    questions: list[Question] = []
    for part in await get_parts(session, material_id):
        for group in await get_question_groups(session, part.id):
            questions.extend(await get_questions(session, group.id))
    return questions


# --- Consumption read tree (§7, §3.4) ---------------------------------------


async def get_take_tree(session: AsyncSession, material_id: uuid.UUID) -> list[dict]:
    """The student-facing render tree (parts -> question_groups ->
    questions). Deliberately a SEPARATE function from ``get_author_tree``:
    this one never reads ``Question.correct_answers`` at all, so there is no
    code path here — no flag, no branch — that could leak it. Each question
    dict carries only ``id``/``number``."""
    tree: list[dict] = []
    for part in await get_parts(session, material_id):
        groups: list[dict] = []
        for group in await get_question_groups(session, part.id):
            questions = [
                {"id": question.id, "number": question.number}
                for question in await get_questions(session, group.id)
            ]
            groups.append(
                {
                    "id": group.id,
                    "order_index": group.order_index,
                    "type": group.type,
                    "instructions": group.instructions,
                    "word_limit": group.word_limit,
                    "config": group.config,
                    "questions": questions,
                }
            )
        tree.append(
            {
                "id": part.id,
                "order_index": part.order_index,
                "title": part.title,
                "audio_start_ms": part.audio_start_ms,
                "audio_end_ms": part.audio_end_ms,
                "question_groups": groups,
            }
        )
    return tree


# --- Author read tree ------------------------------------------------------


async def get_author_tree(
    session: AsyncSession, material_id: uuid.UUID, *, include_answers: bool
) -> list[dict]:
    """The full authoring tree (parts -> question_groups -> questions) for a
    material, ordered by ``order_index``/``number``. ``correct_answers`` is
    included in each question dict ONLY when ``include_answers`` is true —
    callers (the API layer) must gate this on ``material.author_id ==
    caller.id`` so a non-owner viewing a public material never sees answers
    (§3.4 applies to every read path, not just /take)."""
    tree: list[dict] = []
    for part in await get_parts(session, material_id):
        groups: list[dict] = []
        for group in await get_question_groups(session, part.id):
            questions: list[dict] = []
            for question in await get_questions(session, group.id):
                q: dict = {
                    "id": question.id,
                    "number": question.number,
                    # Where the answer is said. Author-facing only — this tree
                    # is gated on ownership by the caller, and the take tree
                    # (get_take_tree) is a separate function that never sees
                    # these. Left out here, reopening a material lost every
                    # mark, and the next autosave wrote the loss back.
                    "replay_start_ms": question.replay_start_ms,
                    "replay_end_ms": question.replay_end_ms,
                }
                if include_answers:
                    q["correct_answers"] = question.correct_answers
                questions.append(q)
            groups.append(
                {
                    "id": group.id,
                    "order_index": group.order_index,
                    "type": group.type,
                    "instructions": group.instructions,
                    "word_limit": group.word_limit,
                    "config": group.config,
                    "questions": questions,
                }
            )
        tree.append(
            {
                "id": part.id,
                "order_index": part.order_index,
                "title": part.title,
                "audio_start_ms": part.audio_start_ms,
                "audio_end_ms": part.audio_end_ms,
                "question_groups": groups,
            }
        )
    return tree

"""Listening authoring API (brief §5).

Authorization mirrors ``app/api/materials.py``: mutations are owner-only —
foreign material/part/group -> 403, missing -> 404. Group create/replace
persist the group and its questions atomically (validation happens in
``app/schemas/listening.py`` and raises 422 before any DB write).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser
from app.api.materials import (
    _load_owned,
    _load_owned_or_public,
    _resolve_audio,
    claim_material_version,
    settle_visibility,
)
from app.core.database import AsyncSession, get_session
from app.models.material import Material
from app.models.part import Part
from app.models.question_group import QuestionGroup
from app.schemas.listening import (
    AttemptResultOut,
    AttemptSubmit,
    MaterialTakeOut,
    PartCreate,
    PartOut,
    PartUpdate,
    QuestionGroupIn,
    QuestionGroupOrderIn,
    QuestionGroupOut,
    QuestionOut,
    QuestionResultOut,
)
from app.services import grading as grading_service
from app.services import listening as listening_service

router = APIRouter(prefix="/api", tags=["listening"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _part_out(part: Part) -> PartOut:
    return PartOut(
        id=part.id,
        material_id=part.material_id,
        order_index=part.order_index,
        title=part.title,
        audio_start_ms=part.audio_start_ms,
        audio_end_ms=part.audio_end_ms,
        created_at=part.created_at,
    )


async def _group_out(session: AsyncSession, group: QuestionGroup) -> QuestionGroupOut:
    questions = await listening_service.get_questions(session, group.id)
    return QuestionGroupOut(
        id=group.id,
        part_id=group.part_id,
        order_index=group.order_index,
        type=group.type,
        instructions=group.instructions,
        word_limit=group.word_limit,
        config=group.config,
        questions=[
            QuestionOut(
                id=q.id,
                number=q.number,
                correct_answers=q.correct_answers,
                replay_start_ms=q.replay_start_ms,
                replay_end_ms=q.replay_end_ms,
                prompt=None if q.config is None else q.config.get("prompt", ""),
                options=q.options,
                mode=None if q.config is None else q.config.get("mode", "one"),
            )
            for q in questions
        ],
    )


async def _load_owned_part(
    session: AsyncSession, part_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[Part, Material]:
    part = await listening_service.get_part(session, part_id)
    if part is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Part not found")
    material = await _load_owned(session, part.material_id, user_id)
    return part, material


async def _load_owned_group(
    session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[QuestionGroup, Part, Material]:
    group = await listening_service.get_question_group(session, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question group not found")
    part, material = await _load_owned_part(session, group.part_id, user_id)
    return group, part, material


@router.post(
    "/materials/{material_id}/parts",
    response_model=PartOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_part(
    material_id: uuid.UUID,
    data: PartCreate,
    user: CurrentUser,
    session: SessionDep,
    request: Request,
    response: Response,
) -> PartOut:
    material = await _load_owned(session, material_id, user.id)
    claim_material_version(request, response, session, material)
    # Fast-path pre-check: cheap, and covers the common (non-racing) case
    # with a clean error before touching the DB constraint at all.
    existing = await listening_service.get_parts(session, material_id)
    if any(p.order_index == data.order_index for p in existing):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Part order_index {data.order_index} already used for this material",
        )
    try:
        part = await listening_service.create_part(session, material_id, data)
    except IntegrityError:
        # Two concurrent POSTs can both pass the pre-check above and then
        # race on the DB's UniqueConstraint(material_id, order_index) — the
        # loser must surface as a clean 409, not an unhandled 500.
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Part order_index {data.order_index} already used for this material",
        )
    await settle_visibility(response, session, material)
    return _part_out(part)


@router.patch("/parts/{part_id}", response_model=PartOut)
async def update_part(
    part_id: uuid.UUID,
    data: PartUpdate,
    user: CurrentUser,
    session: SessionDep,
    request: Request,
    response: Response,
) -> PartOut:
    part, material = await _load_owned_part(session, part_id, user.id)
    claim_material_version(request, response, session, material)
    part = await listening_service.update_part(session, part, data)
    await settle_visibility(response, session, material)
    return _part_out(part)


@router.delete("/parts/{part_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_part(
    part_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    request: Request,
    response: Response,
) -> None:
    part, material = await _load_owned_part(session, part_id, user.id)
    claim_material_version(request, response, session, material)
    await listening_service.delete_part(session, part)
    await settle_visibility(response, session, material)


@router.post(
    "/parts/{part_id}/question-groups",
    response_model=QuestionGroupOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_question_group(
    part_id: uuid.UUID,
    data: QuestionGroupIn,
    user: CurrentUser,
    session: SessionDep,
    request: Request,
    response: Response,
) -> QuestionGroupOut:
    _part, material = await _load_owned_part(session, part_id, user.id)
    claim_material_version(request, response, session, material)
    try:
        group = await listening_service.create_question_group(session, part_id, data)
    except IntegrityError:
        # Same race as create_part: two concurrent creates can compute the
        # same server-derived order_index and lose to
        # UniqueConstraint(part_id, order_index) at commit time.
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Question group order_index conflict for this part — retry",
        )
    await settle_visibility(response, session, material)
    return await _group_out(session, group)


@router.patch("/question-groups/{group_id}", response_model=QuestionGroupOut)
async def update_question_group(
    group_id: uuid.UUID,
    data: QuestionGroupIn,
    user: CurrentUser,
    session: SessionDep,
    request: Request,
    response: Response,
) -> QuestionGroupOut:
    group, _part, material = await _load_owned_group(session, group_id, user.id)
    claim_material_version(request, response, session, material)
    group = await listening_service.replace_question_group(session, group, data)
    await settle_visibility(response, session, material)
    return await _group_out(session, group)


@router.put(
    "/parts/{part_id}/question-groups/order",
    response_model=list[QuestionGroupOut],
)
async def reorder_question_groups(
    part_id: uuid.UUID,
    data: QuestionGroupOrderIn,
    user: CurrentUser,
    session: SessionDep,
    request: Request,
    response: Response,
) -> list[QuestionGroupOut]:
    """Reorder a part's question groups. PUT rather than PATCH: the body is
    the whole order, not a change to it."""
    _part, material = await _load_owned_part(session, part_id, user.id)
    claim_material_version(request, response, session, material)
    groups = await listening_service.reorder_question_groups(
        session, part_id, data.group_ids
    )
    await settle_visibility(response, session, material)
    return [await _group_out(session, group) for group in groups]


@router.delete("/question-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_question_group(
    group_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    request: Request,
    response: Response,
) -> None:
    group, _part, material = await _load_owned_group(session, group_id, user.id)
    claim_material_version(request, response, session, material)
    await listening_service.delete_question_group(session, group)
    await settle_visibility(response, session, material)


# --- Consumption (§7) -------------------------------------------------------


@router.get("/materials/{material_id}/take", response_model=MaterialTakeOut)
async def take_material(
    material_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> MaterialTakeOut:
    """The student's render payload. §3.4: ``correct_answers`` MUST NEVER
    appear here. Built from ``get_take_tree`` (which never reads
    ``Question.correct_answers``) and validated against ``MaterialTakeOut``
    (whose nested question schema has no such field at all) — two
    independent guarantees against a leak, not one."""
    material = await _load_owned_or_public(session, material_id, user.id)
    parts = await listening_service.get_take_tree(session, material.id)
    audio = await _resolve_audio(session, material)
    return MaterialTakeOut(
        id=material.id,
        title=material.title,
        audio_url=audio["audio_url"],
        duration_ms=audio["duration_ms"],
        parts=parts,
    )


@router.post("/materials/{material_id}/attempts", response_model=AttemptResultOut)
async def submit_attempt(
    material_id: uuid.UUID,
    data: AttemptSubmit,
    user: CurrentUser,
    session: SessionDep,
) -> AttemptResultOut:
    """Submit + grade (§7). Visibility check matches ``/take`` — anyone who
    can take the material can submit an attempt. Grading + persistence is
    entirely server-side (app/services/grading.py); the response's
    ``correct_answers`` here is intentional post-submit feedback, not a
    leak."""
    await _load_owned_or_public(session, material_id, user.id)
    attempt, results = await grading_service.submit_attempt(
        session,
        user_id=user.id,
        material_id=material_id,
        answers=data.answers,
    )
    return AttemptResultOut(
        score=int(attempt.score or 0),
        total_questions=attempt.total_questions or 0,
        results=[QuestionResultOut(**r) for r in results],
    )

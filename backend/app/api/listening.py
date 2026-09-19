"""Paper authoring API, and the endpoints addressed by a material id.

Authorization mirrors ``app/api/materials.py``: mutations are owner-only —
foreign material/part/group -> 403, missing -> 404. Group create/replace
persist the group and its questions atomically (validation happens in
``app/schemas/listening.py`` and raises 422 before any DB write).

Named for listening because listening is what it was written for, and shared
with reading because a part, a question group and an attempt are the same
objects in both. What is addressed by SKILL rather than by id — the
catalogue, the recommendation, the statistics, the drills — lives in
``app/api/papers.py``, which builds one router and mounts it per skill.

The three endpoints here that a learner reaches (``/materials/{id}/take``,
``/materials/{id}/attempts``, ``/attempts/{id}``) stay unprefixed on purpose:
a client holding a material id does not know which paper it is, and asking it
to know would be asking it to keep two clients.
"""

import logging
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
from app.models.attempt import Attempt
from app.models.material import Material
from app.models.part import Part
from app.models.question_group import QuestionGroup
from app.schemas.listening import (
    AttemptResultOut,
    LastAttemptOut,
    AttemptSubmit,
    MaterialTakeOut,
    PartCreate,
    PartOut,
    PartUpdate,
    QuestionGroupIn,
    QuestionGroupOrderIn,
    QuestionGroupOut,
    QuestionOut,
)
from app.services import difficulty as difficulty_service
from app.services import grading as grading_service
from app.services import listening as listening_service

router = APIRouter(prefix="/api", tags=["listening"])

logger = logging.getLogger("app.api.listening")

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _part_out(part: Part) -> PartOut:
    return PartOut(
        id=part.id,
        material_id=part.material_id,
        order_index=part.order_index,
        title=part.title,
        audio_start_ms=part.audio_start_ms,
        audio_end_ms=part.audio_end_ms,
        # Both built by name, like every other field here — and both were
        # missing, so a part came back from its own create saying it had
        # neither. `first_number` nobody noticed because only the importer
        # writes it; the passage is the whole of a reading part.
        first_number=part.first_number,
        passage=part.passage,
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
        # Resolved rather than raw, so the response to the save that attached a
        # picture already carries a URL to draw it from — the editor shouldn't
        # have to reload the material to see what it just uploaded.
        config=await listening_service.group_config_out(session, group),
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
    # What the caller already did with this paper, so the page can offer the
    # review instead of making them sit it a second time to reach one.
    done = await grading_service.last_submitted_attempt(
        session, user.id, material.id
    )
    return MaterialTakeOut(
        id=material.id,
        title=material.title,
        reference=material.reference,
        audio_url=audio["audio_url"],
        duration_ms=audio["duration_ms"],
        parts=parts,
        last_attempt=(
            LastAttemptOut(
                attempt_id=done.id,
                score=int(done.score or 0),
                total_questions=done.total_questions or 0,
                submitted_at=done.submitted_at,
            )
            if done is not None and done.submitted_at is not None
            else None
        ),
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
    attempt = await grading_service.submit_attempt(
        session,
        user_id=user.id,
        material_id=material_id,
        data=data,
    )
    # The one moment a difficulty band is worth not waiting for the worker on:
    # a material that has just been answered enough times to be rated at all.
    # Everything after that first crossing waits for the timer — see
    # difficulty.refresh_if_unrated.
    #
    # Guarded, and the order matters: the attempt is committed by now, so a
    # failure here must cost a stale band and never the learner's answers. The
    # next scheduled refresh puts it right regardless.
    try:
        await difficulty_service.refresh_if_unrated(session, material_id)
    except Exception:  # noqa: BLE001 - a band is not worth an attempt
        logger.exception(
            "difficulty refresh after attempt on %s failed", material_id
        )
    return AttemptResultOut.model_validate(
        await grading_service.attempt_result(session, attempt)
    )


@router.get("/attempts/{attempt_id}", response_model=AttemptResultOut)
async def get_attempt(
    attempt_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> AttemptResultOut:
    """One of the caller's own attempts, in full.

    What makes this endpoint necessary is the refresh key: the result of a
    submit lives in the response to that submit, and a review screen that only
    ever exists in a variable is a review screen that a reload throws away.

    Someone else's attempt is a 404 rather than a 403 — this is a different
    person's answers and mistakes, and confirming which ids exist would leak
    the shape of their practice. There is no author exception: owning the
    material does not make a learner's attempt yours to read."""
    attempt = await session.get(Attempt, attempt_id)
    if attempt is None or attempt.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attempt not found")
    return AttemptResultOut.model_validate(
        await grading_service.attempt_result(session, attempt)
    )

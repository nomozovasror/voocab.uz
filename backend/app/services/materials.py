"""Material authoring: create/read/update/delete materials and their segments.

Pure data layer — no HTTP. The router handles authorization (owner vs public)
and translates absence into 404/403. The one exception is
``_check_owned_audio_asset``: it raises 422 directly (rather than returning a
sentinel the router re-raises) so create/update can call it inline and stay
atomic with the rest of validation — matching how pydantic validators in
app/schemas/ already raise before any DB write.
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlmodel import select

from app.core.database import AsyncSession
from app.models.material import Material
from app.models.segment import Segment
from app.models.segment_attempt import SegmentAttempt
from app.schemas.material import MaterialCreate, MaterialUpdate, SegmentIn
from app.services import audio as audio_service


async def _check_owned_audio_asset(
    session: AsyncSession, audio_asset_id: uuid.UUID, author_id: uuid.UUID
) -> None:
    """A material may only attach an ``AudioAsset`` the caller themselves
    own (uploaded via POST /api/uploads/audio). 422, not 403: this is
    request-payload validation (an invalid/foreign asset id in the body),
    the same status the rest of material authoring uses for bad input —
    403 stays reserved for "you don't own the resource you're mutating"."""
    asset = await audio_service.get_asset(session, audio_asset_id)
    if asset is None or asset.owner_id != author_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "audio_asset_id does not exist or is not owned by you",
        )


async def _remove_segments(session: AsyncSession, segments: list[Segment]) -> None:
    """Delete segments along with the per-segment attempt rows pointing at
    them.

    ``segment_attempts.segment_id`` is a plain FK with no ON DELETE, so a
    segment anyone has ever practised cannot simply be dropped — the delete
    raises a ForeignKeyViolation and the whole request 500s. What is lost is
    the word-level detail of a segment that no longer exists; the attempt
    itself keeps its own ``score``, so the record that someone worked through
    this material survives. (Same reasoning, and the same shape, as
    ``listening._remove_questions``.)
    """
    if not segments:
        return
    ids = [segment.id for segment in segments]
    attempts = (
        await session.exec(
            select(SegmentAttempt).where(SegmentAttempt.segment_id.in_(ids))  # type: ignore[attr-defined]
        )
    ).all()
    for attempt in attempts:
        await session.delete(attempt)
    await session.flush()
    for segment in segments:
        await session.delete(segment)


async def _replace_segments(
    session: AsyncSession, material_id: uuid.UUID, segments: list[SegmentIn]
) -> None:
    """Reconcile the segment set BY POSITION rather than wiping and
    recreating it. Segment 3 that survives an edit stays the same row, with
    the same id: it is what ``SegmentAttempt`` points at, so recreating it
    both broke the FK — an edit to a material anyone had practised failed
    outright — and would have thrown away what learners typed every time the
    author fixed a comma. Only positions that fall off the end are removed,
    and those go through ``_remove_segments`` for the attempts they leave
    behind."""
    existing = {
        segment.order_index: segment
        for segment in (
            await session.exec(
                select(Segment).where(Segment.material_id == material_id)
            )
        ).all()
    }

    # Removals first, and flushed: an attempt row has to go before its
    # segment, or the unit of work is free to order the statements the other
    # way round and trip the FK this is ordered around.
    await _remove_segments(
        session,
        [
            segment
            for order_index, segment in existing.items()
            if order_index >= len(segments)
        ],
    )
    await session.flush()

    for i, seg in enumerate(segments):
        segment = existing.get(i)
        if segment is None:
            segment = Segment(
                material_id=material_id,
                order_index=i,
                start_ms=seg.start_ms,
                end_ms=seg.end_ms,
                reference_text=seg.reference_text,
            )
        else:
            segment.start_ms = seg.start_ms
            segment.end_ms = seg.end_ms
            segment.reference_text = seg.reference_text
        session.add(segment)


async def create_material(
    session: AsyncSession, author_id: uuid.UUID, data: MaterialCreate
) -> Material:
    if data.audio_asset_id is not None:
        await _check_owned_audio_asset(session, data.audio_asset_id, author_id)
    material = Material(
        author_id=author_id,
        type=data.type,
        title=data.title,
        audio_asset_id=data.audio_asset_id,
        case_sensitive=data.case_sensitive,
        punctuation_sensitive=data.punctuation_sensitive,
        visibility=data.visibility,
    )
    session.add(material)
    await session.flush()  # assign material.id
    await _replace_segments(session, material.id, data.segments)
    await session.commit()
    await session.refresh(material)
    return material


async def get_material(
    session: AsyncSession, material_id: uuid.UUID
) -> Material | None:
    return await session.get(Material, material_id)


async def get_segments(
    session: AsyncSession, material_id: uuid.UUID
) -> list[Segment]:
    return list(
        (
            await session.exec(
                select(Segment)
                .where(Segment.material_id == material_id)
                .order_by(Segment.order_index)
            )
        ).all()
    )


async def list_materials(
    session: AsyncSession,
    *,
    author_id: uuid.UUID | None = None,
    visibility: str | None = None,
) -> list[tuple[Material, int]]:
    """Materials plus their segment counts, newest first."""
    stmt = (
        select(Material, func.count(Segment.id))
        .outerjoin(Segment, Segment.material_id == Material.id)  # type: ignore[arg-type]
        .group_by(Material.id)
        .order_by(Material.created_at.desc())  # type: ignore[attr-defined]
    )
    if author_id is not None:
        stmt = stmt.where(Material.author_id == author_id)
    if visibility is not None:
        stmt = stmt.where(Material.visibility == visibility)
    rows = (await session.exec(stmt)).all()
    return [(material, count) for material, count in rows]


async def update_material(
    session: AsyncSession, material: Material, data: MaterialUpdate
) -> Material:
    if data.title is not None:
        material.title = data.title
    if data.audio_asset_id is not None:
        await _check_owned_audio_asset(
            session, data.audio_asset_id, material.author_id
        )
        material.audio_asset_id = data.audio_asset_id
    if data.case_sensitive is not None:
        material.case_sensitive = data.case_sensitive
    if data.punctuation_sensitive is not None:
        material.punctuation_sensitive = data.punctuation_sensitive
    if data.visibility is not None:
        material.visibility = data.visibility
    if data.segments is not None:
        await _replace_segments(session, material.id, data.segments)
    session.add(material)
    await session.commit()
    await session.refresh(material)
    return material


async def delete_material(session: AsyncSession, material: Material) -> None:
    await _remove_segments(session, await get_segments(session, material.id))
    # Flush the segment deletes before removing the parent: there's no ORM
    # relationship to teach the unit-of-work the FK order, so without this the
    # material delete can be issued first and trip the FK constraint.
    await session.flush()
    await session.delete(material)
    await session.commit()

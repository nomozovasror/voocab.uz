"""Material authoring: create/read/update/delete materials and their segments.

Pure data layer — no HTTP. The router handles authorization (owner vs public)
and translates absence into 404/403.
"""

import uuid

from sqlalchemy import func
from sqlmodel import select

from app.core.database import AsyncSession
from app.models.material import Material
from app.models.segment import Segment
from app.schemas.material import MaterialCreate, MaterialUpdate, SegmentIn


async def _replace_segments(
    session: AsyncSession, material_id: uuid.UUID, segments: list[SegmentIn]
) -> None:
    existing = (
        await session.exec(
            select(Segment).where(Segment.material_id == material_id)
        )
    ).all()
    for seg in existing:
        await session.delete(seg)
    for i, seg in enumerate(segments):
        session.add(
            Segment(
                material_id=material_id,
                order_index=i,
                start_ms=seg.start_ms,
                end_ms=seg.end_ms,
                reference_text=seg.reference_text,
            )
        )


async def create_material(
    session: AsyncSession, author_id: uuid.UUID, data: MaterialCreate
) -> Material:
    material = Material(
        author_id=author_id,
        type=data.type,
        title=data.title,
        audio_url=data.audio_url,
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
    if data.audio_url is not None:
        material.audio_url = data.audio_url
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
    for seg in await get_segments(session, material.id):
        await session.delete(seg)
    # Flush the segment deletes before removing the parent: there's no ORM
    # relationship to teach the unit-of-work the FK order, so without this the
    # material delete can be issued first and trip the FK constraint.
    await session.flush()
    await session.delete(material)
    await session.commit()

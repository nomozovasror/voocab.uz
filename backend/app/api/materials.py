"""Material authoring API: audio upload + material/segment CRUD.

Authorization model (content is user-generated):
* anyone signed in can create and manage **their own** materials,
* reads are allowed for the owner, or for anyone if the material is ``public``,
* mutations require ownership.
"""

import uuid
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.api.deps import CurrentUser
from app.core.database import AsyncSession, get_session
from app.models.material import Material
from app.schemas.material import (
    AudioUploadRead,
    MaterialCreate,
    MaterialDetail,
    MaterialRead,
    MaterialUpdate,
    SegmentRead,
)
from app.services import materials as materials_service
from app.services import storage

router = APIRouter(prefix="/api", tags=["materials"])

MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MB

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _base(material: Material) -> dict:
    return {
        "id": material.id,
        "author_id": material.author_id,
        "type": material.type,
        "title": material.title,
        "audio_url": material.audio_url,
        "case_sensitive": material.case_sensitive,
        "punctuation_sensitive": material.punctuation_sensitive,
        "visibility": material.visibility,
        "created_at": material.created_at,
    }


@router.post("/uploads/audio", response_model=AudioUploadRead)
async def upload_audio(
    user: CurrentUser,
    file: UploadFile = File(...),
) -> AudioUploadRead:
    """Store an audio clip and return a URL to reference from a material."""
    ext = Path(file.filename or "").suffix.lower()
    content_type = storage.AUDIO_CONTENT_TYPES.get(ext)
    if content_type is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unsupported audio type. Allowed: {', '.join(storage.AUDIO_CONTENT_TYPES)}",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "Audio exceeds 25 MB",
        )
    url = await storage.save(storage.audio_key(ext), data, content_type)
    return AudioUploadRead(audio_url=url)


@router.post(
    "/materials", response_model=MaterialDetail, status_code=status.HTTP_201_CREATED
)
async def create_material(
    data: MaterialCreate, user: CurrentUser, session: SessionDep
) -> MaterialDetail:
    material = await materials_service.create_material(session, user.id, data)
    segments = await materials_service.get_segments(session, material.id)
    return MaterialDetail(
        **_base(material),
        segment_count=len(segments),
        segments=[SegmentRead.model_validate(s, from_attributes=True) for s in segments],
    )


@router.get("/materials", response_model=list[MaterialRead])
async def list_materials(
    user: CurrentUser,
    session: SessionDep,
    scope: Literal["mine", "public"] = "mine",
) -> list[MaterialRead]:
    """``scope=mine`` (default) lists the caller's materials; ``scope=public``
    lists everyone's public materials (for browsing)."""
    if scope == "public":
        rows = await materials_service.list_materials(session, visibility="public")
    else:
        rows = await materials_service.list_materials(session, author_id=user.id)
    return [MaterialRead(**_base(m), segment_count=count) for m, count in rows]


async def _load_owned_or_public(
    session: AsyncSession, material_id: uuid.UUID, user_id: uuid.UUID
) -> Material:
    material = await materials_service.get_material(session, material_id)
    if material is None or (
        material.author_id != user_id and material.visibility != "public"
    ):
        # Hide existence of private materials the caller can't see.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Material not found")
    return material


async def _load_owned(
    session: AsyncSession, material_id: uuid.UUID, user_id: uuid.UUID
) -> Material:
    material = await materials_service.get_material(session, material_id)
    if material is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Material not found")
    if material.author_id != user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your material")
    return material


@router.get("/materials/{material_id}", response_model=MaterialDetail)
async def get_material(
    material_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> MaterialDetail:
    material = await _load_owned_or_public(session, material_id, user.id)
    segments = await materials_service.get_segments(session, material.id)
    return MaterialDetail(
        **_base(material),
        segment_count=len(segments),
        segments=[SegmentRead.model_validate(s, from_attributes=True) for s in segments],
    )


@router.patch("/materials/{material_id}", response_model=MaterialDetail)
async def update_material(
    material_id: uuid.UUID,
    data: MaterialUpdate,
    user: CurrentUser,
    session: SessionDep,
) -> MaterialDetail:
    material = await _load_owned(session, material_id, user.id)
    material = await materials_service.update_material(session, material, data)
    segments = await materials_service.get_segments(session, material.id)
    return MaterialDetail(
        **_base(material),
        segment_count=len(segments),
        segments=[SegmentRead.model_validate(s, from_attributes=True) for s in segments],
    )


@router.delete("/materials/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_material(
    material_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> None:
    material = await _load_owned(session, material_id, user.id)
    await materials_service.delete_material(session, material)

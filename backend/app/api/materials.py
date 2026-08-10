"""Material authoring API: audio upload + material/segment CRUD.

Authorization model (content is user-generated):
* anyone signed in can create and manage **their own** materials,
* reads are allowed for the owner, or for anyone if the material is ``public``,
* mutations require ownership.
"""

import uuid
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status

from app.api.deps import CurrentUser
from app.core.database import AsyncSession, get_session
from app.models.audio_blob import AudioBlob
from app.models.material import Material
from app.schemas.material import (
    AudioUploadRead,
    MaterialCreate,
    MaterialDetail,
    MaterialRead,
    MaterialUpdate,
    SegmentRead,
)
from app.services import audio as audio_service
from app.services import listening as listening_service
from app.services import materials as materials_service
from app.services import storage

router = APIRouter(prefix="/api", tags=["materials"])

MAX_AUDIO_BYTES = 60 * 1024 * 1024  # 60 MB

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def _resolve_audio(session: AsyncSession, material: Material) -> dict:
    """Resolve ``material.audio_asset_id`` (if set) into a playable URL plus
    the transcript state, for the author view. The consumption ``/take``
    endpoint (a later phase) will resolve audio the same way."""
    if material.audio_asset_id is None:
        return {"audio_url": None, "transcript_status": None, "duration_ms": None}
    asset = await audio_service.get_asset(session, material.audio_asset_id)
    if asset is None:
        # FK-consistent in practice, but degrade gracefully rather than 500.
        return {"audio_url": None, "transcript_status": None, "duration_ms": None}
    blob = await session.get(AudioBlob, asset.blob_id)
    assert blob is not None  # FK-enforced: every asset has a blob
    return {
        "audio_url": await storage.get_storage().url(blob.storage_key),
        "transcript_status": blob.transcript_status,
        "duration_ms": blob.duration_ms,
    }


def _base(material: Material) -> dict:
    return {
        "id": material.id,
        "author_id": material.author_id,
        "type": material.type,
        "title": material.title,
        "audio_asset_id": material.audio_asset_id,
        "case_sensitive": material.case_sensitive,
        "punctuation_sensitive": material.punctuation_sensitive,
        "visibility": material.visibility,
        "created_at": material.created_at,
    }


@router.post("/uploads/audio", response_model=AudioUploadRead)
async def upload_audio(
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    file: UploadFile = File(...),
) -> AudioUploadRead:
    """Ingest an audio clip: hash it, dedup against existing blobs, and claim
    an owner asset. New bytes land in storage and a fresh ``AudioBlob`` is
    left ``pending`` for the (Faza 4) transcription worker to pick up — the
    blob row itself is the queue, there's no separate enqueue step here.
    """
    ext = Path(file.filename or "").suffix.lower()
    content_type = storage.AUDIO_CONTENT_TYPES.get(ext)
    if content_type is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unsupported audio type. Allowed: {', '.join(storage.AUDIO_CONTENT_TYPES)}",
        )

    # Cheap DoS reduction: reject up front from a declared Content-Length
    # before buffering the body into memory. Not authoritative -- a client
    # can omit or lie about Content-Length -- so the post-read len(data)
    # check below remains the real guard.
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_AUDIO_BYTES:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "Audio exceeds 60 MB",
                )
        except ValueError:
            pass  # malformed header; fall through to the authoritative check

    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Empty file")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Audio exceeds 60 MB",
        )

    sha256 = audio_service.sha256_hex(data)
    key = storage.audio_storage_key(sha256, content_type)

    blob, created = await audio_service.get_or_create_blob(
        session,
        sha256=sha256,
        storage_key=key,
        size_bytes=len(data),
        mime_type=content_type,
    )
    if created:
        # Only write bytes when we actually created the blob row — a dedup
        # hit must never rewrite storage (put() is idempotent anyway, but
        # skipping it entirely avoids the wasted read/hash/upload).
        await storage.get_storage().put(key, data, content_type)

    asset = await audio_service.get_or_create_asset(session, user.id, blob.id)
    await session.commit()
    await session.refresh(blob)
    await session.refresh(asset)

    return AudioUploadRead(
        asset_id=asset.id,
        blob_id=blob.id,
        sha256=blob.sha256,
        transcript_status=blob.transcript_status,
    )


@router.post(
    "/materials", response_model=MaterialDetail, status_code=status.HTTP_201_CREATED
)
async def create_material(
    data: MaterialCreate, user: CurrentUser, session: SessionDep
) -> MaterialDetail:
    material = await materials_service.create_material(session, user.id, data)
    segments = await materials_service.get_segments(session, material.id)
    # Caller is always the owner here (just created the material), so the
    # (empty, at this point) listening tree may safely include answers.
    parts = await listening_service.get_author_tree(
        session, material.id, include_answers=True
    )
    audio = await _resolve_audio(session, material)
    return MaterialDetail(
        **_base(material),
        segment_count=len(segments),
        segments=[SegmentRead.model_validate(s, from_attributes=True) for s in segments],
        parts=parts,
        **audio,
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
    # §3.4 applies here too: a non-owner viewing a public listening material
    # must never see correct_answers, even though the take/take-answer flow
    # itself is out of scope for this phase.
    parts = await listening_service.get_author_tree(
        session, material.id, include_answers=material.author_id == user.id
    )
    audio = await _resolve_audio(session, material)
    return MaterialDetail(
        **_base(material),
        segment_count=len(segments),
        segments=[SegmentRead.model_validate(s, from_attributes=True) for s in segments],
        parts=parts,
        **audio,
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
    parts = await listening_service.get_author_tree(
        session, material.id, include_answers=True
    )
    audio = await _resolve_audio(session, material)
    return MaterialDetail(
        **_base(material),
        segment_count=len(segments),
        segments=[SegmentRead.model_validate(s, from_attributes=True) for s in segments],
        parts=parts,
        **audio,
    )


@router.delete("/materials/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_material(
    material_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> None:
    material = await _load_owned(session, material_id, user.id)
    await materials_service.delete_material(session, material)

"""Material authoring API: audio upload + material/segment CRUD.

Authorization model (content is user-generated):
* anyone signed in can create and manage **their own** materials,
* reads are allowed for the owner, or for anyone if the material is ``public``,
* mutations require ownership.
"""

import uuid
from pathlib import Path
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)

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
from app.services import audio_codec
from app.services import listening as listening_service
from app.services import materials as materials_service
from app.services import publishing as publishing_service
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
        "version": material.version,
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

    # The extension named a container; this asks what is inside it. Refused
    # here rather than discovered in the editor: the file transcribes either
    # way, so a material built on one browsers can't decode looks finished
    # right up until someone presses play (services/audio_codec.py).
    unplayable = audio_codec.unplayable_reason(ext, data)
    if unplayable is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, unplayable)

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
    # A brand-new material has no audio and no questions, so it could never
    # meet the requirements — but the field was there to be set, and saying
    # so plainly beats creating something public and demoting it a moment
    # later.
    if data.visibility == "public":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Create the material first, then publish it once it's ready.",
        )
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


MATERIAL_VERSION_HEADER = "X-Material-Version"


def claim_material_version(
    request: Request,
    response: Response,
    session: AsyncSession,
    material: Material,
) -> None:
    """Optimistic concurrency for one authoring write.

    Editors autosave, so two windows open on the same material used to
    overwrite each other with no sign either way: whoever typed last won, and
    the other author's work was simply gone the next time they reloaded.

    A caller that sends ``X-Material-Version`` with the version it loaded is
    told (409) when the material has moved on since, instead of writing over
    whatever moved it. Sending the header is optional — omit it and the old
    last-write-wins behaviour is unchanged, which is what keeps every other
    client and the whole existing test suite working.

    The bump rides along in the caller's transaction rather than committing
    on its own: the service function called next is what commits, so the
    version and the change it stands for land together or not at all. The new
    value goes back in the same header so the client can carry on without a
    re-read.
    """
    sent = request.headers.get(MATERIAL_VERSION_HEADER)
    if sent is not None and sent.strip() != str(material.version):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This material was changed somewhere else — reload to get the "
            "latest version before editing further.",
        )

    material.version += 1
    session.add(material)
    response.headers[MATERIAL_VERSION_HEADER] = str(material.version)


MATERIAL_VISIBILITY_HEADER = "X-Material-Visibility"


async def settle_visibility(
    response: Response, session: AsyncSession, material: Material
) -> None:
    """Run after an authoring write: a public material that no longer meets
    the publishing requirements goes back to draft.

    Authors edit published work, and an edit can genuinely break it — empty
    the form, drop the audio mark off an answer. Refusing the edit would be
    the wrong trade (it is their material, and half-finished is a normal
    state to pass through); leaving it public would put something unusable in
    front of learners. So the edit stands and the material stops being
    public.

    The outcome rides back in a header for the editor to react to — the same
    trick as the version, and for the same reason: not every authoring
    response is shaped to carry it in the body.
    """
    if await publishing_service.demote_if_unpublishable(session, material):
        response.headers[MATERIAL_VISIBILITY_HEADER] = material.visibility


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
    request: Request,
    response: Response,
) -> MaterialDetail:
    material = await _load_owned(session, material_id, user.id)
    claim_material_version(request, response, session, material)
    # Checked before the write, against the material as it stands: going
    # public is the one change to refuse rather than accept and undo, since
    # the whole point is that nobody else sees it until it holds up.
    if data.visibility == "public" and material.visibility != "public":
        blockers = await publishing_service.publish_blockers(session, material)
        if blockers:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "This material isn't ready to be public — " + " ".join(blockers),
            )
    material = await materials_service.update_material(session, material, data)
    await settle_visibility(response, session, material)
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

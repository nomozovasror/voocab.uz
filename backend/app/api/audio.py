"""Audio asset read API (§10 of the audio-ingestion brief).

Authorization model: ``AudioAsset`` is a per-owner claim with no public/shared
concept yet (that's a later feature), so a caller who isn't the owner gets the
same 404 as a nonexistent asset — matching the "hide existence of private
content" pattern already used for materials in app/api/materials.py. Once
shared/public access exists, a non-owner-but-permitted case would be 403
instead of the blanket 404 used here.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import CurrentUser
from app.core.database import AsyncSession, get_session
from app.models.audio_blob import AudioBlob, TranscriptStatus
from app.schemas.audio import AudioAssetRead, AudioSegmentRead
from app.services import audio as audio_service

router = APIRouter(prefix="/api", tags=["audio"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/audio-assets/{asset_id}", response_model=AudioAssetRead)
async def get_audio_asset(
    asset_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> AudioAssetRead:
    asset = await audio_service.get_asset(session, asset_id)
    if asset is None or asset.owner_id != user.id:
        # Hide existence of assets the caller doesn't own (no sharing yet).
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Audio asset not found")

    blob = await session.get(AudioBlob, asset.blob_id)
    assert blob is not None  # FK-enforced: every asset has a blob

    segments: list[AudioSegmentRead] = []
    if blob.transcript_status == TranscriptStatus.READY:
        rows = await audio_service.get_asset_segments(session, blob.id)
        segments = [
            AudioSegmentRead.model_validate(row, from_attributes=True) for row in rows
        ]

    return AudioAssetRead(
        asset_id=asset.id,
        blob_id=blob.id,
        title=asset.title,
        sha256=blob.sha256,
        transcript_status=blob.transcript_status,
        duration_ms=blob.duration_ms,
        created_at=asset.created_at,
        transcript_error=blob.transcript_error,
        segments=segments,
    )

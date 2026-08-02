"""Integration tests for scripts/seed_audio.py (§11) — real DB, a FAKE
transcriber (no faster-whisper, no GPU needed). Drives ingest_file() exactly
the way the real script would, just with transcribe= swapped out.

Storage: uses the real (local, in this sandbox) AudioStorage backend so the
dedup path is exercised end-to-end; the written file is removed afterward.
"""

import uuid
from pathlib import Path

import pytest
from sqlmodel import select

from app.core.database import async_session_factory
from app.core.config import settings
from app.models.audio_asset import AudioAsset
from app.models.audio_blob import AudioBlob, TranscriptStatus
from app.models.audio_segment import AudioSegment
from app.models.user import User
from app.services.asr import TranscriptResult, TranscriptSegment, WordTiming
from app.services.audio import sha256_hex
from scripts.seed_audio import ingest_file

FIXTURE_RESULT = TranscriptResult(
    duration_ms=2000,
    segments=[
        TranscriptSegment(
            order_index=0,
            start_ms=0,
            end_ms=1000,
            text="Seeded segment one.",
            words=[WordTiming(word="Seeded", start_ms=0, end_ms=400)],
        ),
        TranscriptSegment(
            order_index=1,
            start_ms=1000,
            end_ms=2000,
            text="Seeded segment two.",
            words=[WordTiming(word="two", start_ms=1500, end_ms=1800)],
        ),
    ],
)


async def _fake_transcribe(path: Path) -> TranscriptResult:
    return FIXTURE_RESULT


async def _make_user(email: str) -> User:
    async with async_session_factory() as session:
        user = (await session.exec(select(User).where(User.email == email))).first()
        if user is not None:
            return user
        user = User(email=email, display_name=f"Seed test {email}")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _cleanup(sha256: str, owner_id: uuid.UUID) -> None:
    async with async_session_factory() as session:
        blob = (
            await session.exec(select(AudioBlob).where(AudioBlob.sha256 == sha256))
        ).first()
        if blob is not None:
            segments = (
                await session.exec(
                    select(AudioSegment).where(AudioSegment.blob_id == blob.id)
                )
            ).all()
            for seg in segments:
                await session.delete(seg)
            await session.flush()
            assets = (
                await session.exec(
                    select(AudioAsset).where(AudioAsset.blob_id == blob.id)
                )
            ).all()
            for asset in assets:
                await session.delete(asset)
            await session.flush()
            await session.delete(blob)
            await session.commit()

            import os

            disk_path = os.path.join(settings.media_root, blob.storage_key)
            if os.path.exists(disk_path):
                os.remove(disk_path)


async def _cleanup_user(email: str) -> None:
    async with async_session_factory() as session:
        user = (await session.exec(select(User).where(User.email == email))).first()
        if user is not None:
            await session.delete(user)
            await session.commit()


@pytest.mark.asyncio
async def test_ingest_new_file_creates_blob_segments_asset(tmp_path: Path) -> None:
    owner = await _make_user("faza6-seed-owner@example.com")
    audio_path = tmp_path / "clip.mp3"
    payload = f"seed-audio fixture bytes {uuid.uuid4()}".encode()
    audio_path.write_bytes(payload)
    sha256 = sha256_hex(payload)

    try:
        await ingest_file(
            audio_path, owner.id, transcribe=_fake_transcribe, title="My Seeded Clip"
        )

        async with async_session_factory() as session:
            blob = (
                await session.exec(select(AudioBlob).where(AudioBlob.sha256 == sha256))
            ).first()
            assert blob is not None
            assert blob.transcript_status == TranscriptStatus.READY
            assert blob.duration_ms == 2000

            segments = (
                await session.exec(
                    select(AudioSegment)
                    .where(AudioSegment.blob_id == blob.id)
                    .order_by(AudioSegment.order_index)
                )
            ).all()
            assert len(segments) == 2
            assert segments[0].text == "Seeded segment one."
            assert segments[0].words == [{"word": "Seeded", "start_ms": 0, "end_ms": 400}]
            assert segments[1].order_index == 1

            assets = (
                await session.exec(
                    select(AudioAsset).where(
                        AudioAsset.owner_id == owner.id, AudioAsset.blob_id == blob.id
                    )
                )
            ).all()
            assert len(assets) == 1
            assert assets[0].title == "My Seeded Clip"

        # storage actually has the bytes
        disk_path = Path(settings.media_root) / blob.storage_key
        assert disk_path.exists()
    finally:
        await _cleanup(sha256, owner.id)
        await _cleanup_user("faza6-seed-owner@example.com")


@pytest.mark.asyncio
async def test_ingest_same_bytes_twice_dedups_no_new_blob_or_segments(
    tmp_path: Path,
) -> None:
    owner = await _make_user("faza6-seed-owner-dedup@example.com")
    audio_path = tmp_path / "clip.mp3"
    payload = f"seed-audio dedup fixture {uuid.uuid4()}".encode()
    audio_path.write_bytes(payload)
    sha256 = sha256_hex(payload)

    call_count = {"n": 0}

    async def _counting_fake_transcribe(path: Path) -> TranscriptResult:
        call_count["n"] += 1
        return FIXTURE_RESULT

    try:
        await ingest_file(audio_path, owner.id, transcribe=_counting_fake_transcribe)
        await ingest_file(audio_path, owner.id, transcribe=_counting_fake_transcribe)

        assert call_count["n"] == 1, "transcriber must NOT run again on a dedup hit"

        async with async_session_factory() as session:
            blobs = (
                await session.exec(select(AudioBlob).where(AudioBlob.sha256 == sha256))
            ).all()
            assert len(blobs) == 1, "dedup must not create a second blob"
            blob_id = blobs[0].id

            segments = (
                await session.exec(
                    select(AudioSegment).where(AudioSegment.blob_id == blob_id)
                )
            ).all()
            assert len(segments) == 2, "dedup must not duplicate segments"

            assets = (
                await session.exec(
                    select(AudioAsset).where(
                        AudioAsset.owner_id == owner.id, AudioAsset.blob_id == blob_id
                    )
                )
            ).all()
            assert len(assets) == 1, "same owner re-ingesting must not duplicate the asset"
    finally:
        await _cleanup(sha256, owner.id)
        await _cleanup_user("faza6-seed-owner-dedup@example.com")

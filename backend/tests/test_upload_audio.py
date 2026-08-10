"""Integration tests for POST /api/uploads/audio (§7 / §12 "upload+dedup") —
real DB, ASGI-transport + minted-cookie approach (same pattern used
elsewhere). Every test seeds its own throwaway user(s) and cleans up its own
rows/files afterward with targeted deletes.
"""

import os
import uuid

import httpx
import pytest
from sqlmodel import select

from app.core.config import settings
from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.main import app
from app.models.audio_asset import AudioAsset
from app.models.audio_blob import AudioBlob
from app.models.user import User
from app.services.audio import sha256_hex
from app.services.storage import audio_storage_key

MAX_AUDIO_BYTES = 60 * 1024 * 1024


async def _make_user(email: str) -> User:
    async with async_session_factory() as session:
        user = (await session.exec(select(User).where(User.email == email))).first()
        if user is not None:
            return user
        user = User(email=email, display_name=f"Upload test {email}")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _cleanup(sha256: str, *emails: str) -> None:
    async with async_session_factory() as session:
        blob = (
            await session.exec(select(AudioBlob).where(AudioBlob.sha256 == sha256))
        ).first()
        if blob is not None:
            assets = (
                await session.exec(
                    select(AudioAsset).where(AudioAsset.blob_id == blob.id)
                )
            ).all()
            for asset in assets:
                await session.delete(asset)
            await session.flush()
            disk_path = os.path.join(settings.media_root, blob.storage_key)
            await session.delete(blob)
            await session.commit()
            if os.path.exists(disk_path):
                os.remove(disk_path)
        for email in emails:
            user = (await session.exec(select(User).where(User.email == email))).first()
            if user is not None:
                await session.delete(user)
        await session.commit()


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_new_upload_creates_pending_blob_and_asset() -> None:
    owner = await _make_user("faza7-upload-owner-new@example.com")
    token = create_access_token(str(owner.id))
    payload = f"faza7 new upload fixture {uuid.uuid4()}".encode()
    sha256 = sha256_hex(payload)

    try:
        async with _client() as client:
            r = await client.post(
                "/api/uploads/audio",
                files={"file": ("clip.mp3", payload, "audio/mpeg")},
                cookies={"access_token": token},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["sha256"] == sha256
        assert body["transcript_status"] == "pending"
        assert uuid.UUID(body["asset_id"])
        assert uuid.UUID(body["blob_id"])

        key = audio_storage_key(sha256, "audio/mpeg")
        disk_path = os.path.join(settings.media_root, key)
        assert os.path.exists(disk_path), "new upload must land in storage"

        async with async_session_factory() as session:
            blobs = (
                await session.exec(select(AudioBlob).where(AudioBlob.sha256 == sha256))
            ).all()
            assert len(blobs) == 1
            assets = (
                await session.exec(
                    select(AudioAsset).where(AudioAsset.blob_id == blobs[0].id)
                )
            ).all()
            assert len(assets) == 1
            assert assets[0].owner_id == owner.id
    finally:
        await _cleanup(sha256, "faza7-upload-owner-new@example.com")


@pytest.mark.asyncio
async def test_same_bytes_dedup_across_owners_no_storage_rewrite() -> None:
    owner1 = await _make_user("faza7-upload-owner-1@example.com")
    owner2 = await _make_user("faza7-upload-owner-2@example.com")
    token1 = create_access_token(str(owner1.id))
    token2 = create_access_token(str(owner2.id))
    payload = f"faza7 dedup fixture {uuid.uuid4()}".encode()
    sha256 = sha256_hex(payload)

    try:
        async with _client() as client:
            r1 = await client.post(
                "/api/uploads/audio",
                files={"file": ("clip.mp3", payload, "audio/mpeg")},
                cookies={"access_token": token1},
            )
        assert r1.status_code == 200, r1.text
        body1 = r1.json()

        key = audio_storage_key(sha256, "audio/mpeg")
        disk_path = os.path.join(settings.media_root, key)
        mtime_after_1 = os.path.getmtime(disk_path)

        async with _client() as client:
            r2 = await client.post(
                "/api/uploads/audio",
                files={"file": ("clip-again.mp3", payload, "audio/mpeg")},
                cookies={"access_token": token2},
            )
        assert r2.status_code == 200, r2.text
        body2 = r2.json()

        assert body2["blob_id"] == body1["blob_id"], "dedup must reuse the same blob"
        assert body2["sha256"] == sha256
        assert body2["asset_id"] != body1["asset_id"], "each owner gets its own asset"

        mtime_after_2 = os.path.getmtime(disk_path)
        assert mtime_after_1 == mtime_after_2, "dedup hit must not rewrite storage"

        async with async_session_factory() as session:
            blobs = (
                await session.exec(select(AudioBlob).where(AudioBlob.sha256 == sha256))
            ).all()
            assert len(blobs) == 1, "dedup must not create a second blob"
            assets = (
                await session.exec(
                    select(AudioAsset).where(AudioAsset.blob_id == blobs[0].id)
                )
            ).all()
            assert len(assets) == 2, "two distinct owners -> two assets over one blob"
    finally:
        await _cleanup(
            sha256,
            "faza7-upload-owner-1@example.com",
            "faza7-upload-owner-2@example.com",
        )


@pytest.mark.asyncio
async def test_bad_format_is_422_no_rows_created() -> None:
    owner = await _make_user("faza7-upload-owner-badformat@example.com")
    token = create_access_token(str(owner.id))
    payload = b"not audio at all"
    sha256 = sha256_hex(payload)

    try:
        async with _client() as client:
            r = await client.post(
                "/api/uploads/audio",
                files={"file": ("clip.txt", payload, "text/plain")},
                cookies={"access_token": token},
            )
        assert r.status_code == 422, r.text

        async with async_session_factory() as session:
            blob = (
                await session.exec(select(AudioBlob).where(AudioBlob.sha256 == sha256))
            ).first()
            assert blob is None
    finally:
        await _cleanup(sha256, "faza7-upload-owner-badformat@example.com")


@pytest.mark.asyncio
async def test_oversize_content_length_header_is_422_no_rows_created() -> None:
    """Exercises the cheap Content-Length pre-check without constructing a
    real 60 MB body (slow, memory-hungry): a tiny actual multipart body with
    a lied-about, over-the-limit Content-Length header must still be
    rejected -- the pre-check reads the header, not the bytes on the wire."""
    owner = await _make_user("faza7-upload-owner-oversize@example.com")
    token = create_access_token(str(owner.id))
    small_payload = b"tiny, but the Content-Length header says otherwise"
    sha256 = sha256_hex(small_payload)

    boundary = "oversizeheadertestboundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="big.mp3"\r\n'
        f"Content-Type: audio/mpeg\r\n\r\n"
    ).encode() + small_payload + f"\r\n--{boundary}--\r\n".encode()

    try:
        async with _client() as client:
            r = await client.post(
                "/api/uploads/audio",
                content=body,
                headers={
                    "content-type": f"multipart/form-data; boundary={boundary}",
                    "content-length": str(MAX_AUDIO_BYTES + 1),
                },
                cookies={"access_token": token},
            )
        assert r.status_code == 422, r.text
        assert "60 MB" in r.text

        async with async_session_factory() as session:
            blob = (
                await session.exec(select(AudioBlob).where(AudioBlob.sha256 == sha256))
            ).first()
            assert blob is None
    finally:
        await _cleanup(sha256, "faza7-upload-owner-oversize@example.com")


@pytest.mark.asyncio
async def test_small_file_still_succeeds_under_new_limit() -> None:
    """Happy-path guard: raising the cap must not have broken small (well
    under the limit) uploads."""
    owner = await _make_user("faza7-upload-owner-smallunderlimit@example.com")
    token = create_access_token(str(owner.id))
    payload = f"small file under the 60 MB cap {uuid.uuid4()}".encode()
    sha256 = sha256_hex(payload)

    try:
        async with _client() as client:
            r = await client.post(
                "/api/uploads/audio",
                files={"file": ("clip.mp3", payload, "audio/mpeg")},
                cookies={"access_token": token},
            )
        assert r.status_code == 200, r.text
        assert r.json()["sha256"] == sha256
    finally:
        await _cleanup(sha256, "faza7-upload-owner-smallunderlimit@example.com")

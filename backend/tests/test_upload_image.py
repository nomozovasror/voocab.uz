"""Integration tests for POST /api/uploads/image — real DB, ASGI transport,
minted cookie, same pattern as tests/test_upload_audio.py. Every test seeds its
own throwaway user and deletes its own rows and files afterwards.

What is checked here is the pipeline, not the header reader (that is
tests/test_image_codec.py): that new bytes land in storage exactly once, that
identical bytes from two authors come back as one row, and that the two caps
and the format rule refuse before anything is written.
"""

import os
import struct
import uuid

import httpx
import pytest
from sqlmodel import select

from app.core.config import settings
from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.main import app
from app.models.image_blob import ImageBlob
from app.models.user import User
from app.services.storage import image_storage_key, sha256_hex

MAX_IMAGE_BYTES = 5 * 1024 * 1024


def png(width: int, height: int, *, salt: bytes = b"") -> bytes:
    """A PNG header, plus whatever it takes to make these bytes unique — the
    key is the hash, so two tests uploading "a 40x30 PNG" would otherwise be
    uploading the same object."""
    ihdr = b"IHDR" + struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + ihdr + salt


async def _make_user(email: str) -> User:
    async with async_session_factory() as session:
        user = (await session.exec(select(User).where(User.email == email))).first()
        if user is not None:
            return user
        user = User(email=email, display_name=f"Image upload test {email}")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _cleanup(sha256: str, *emails: str) -> None:
    async with async_session_factory() as session:
        blob = (
            await session.exec(select(ImageBlob).where(ImageBlob.sha256 == sha256))
        ).first()
        if blob is not None:
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
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.mark.asyncio
async def test_new_upload_stores_bytes_and_reports_its_size() -> None:
    owner = await _make_user("image-upload-owner-new@example.com")
    token = create_access_token(str(owner.id))
    payload = png(1240, 874, salt=f"{uuid.uuid4()}".encode())
    sha256 = sha256_hex(payload)

    try:
        async with _client() as client:
            r = await client.post(
                "/api/uploads/image",
                files={"file": ("castle.png", payload, "image/png")},
                cookies={"access_token": token},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["width"] == 1240
        assert body["height"] == 874
        assert body["mime_type"] == "image/png"
        assert body["size_bytes"] == len(payload)
        assert uuid.UUID(body["id"])

        key = image_storage_key(sha256, "image/png")
        assert body["url"].endswith(key), "the URL must point at the stored key"
        assert os.path.exists(os.path.join(settings.media_root, key))

        async with async_session_factory() as session:
            blobs = (
                await session.exec(select(ImageBlob).where(ImageBlob.sha256 == sha256))
            ).all()
            assert len(blobs) == 1
            assert blobs[0].width == 1240
            assert blobs[0].height == 874
    finally:
        await _cleanup(sha256, "image-upload-owner-new@example.com")


@pytest.mark.asyncio
async def test_same_bytes_dedup_across_owners_no_storage_rewrite() -> None:
    """One map, two authors, one row and one object. There is no per-owner
    asset row to differ — unlike audio, where each owner claims the blob —
    so the whole response is expected to be identical."""
    owner1 = await _make_user("image-upload-owner-1@example.com")
    owner2 = await _make_user("image-upload-owner-2@example.com")
    payload = png(600, 400, salt=f"{uuid.uuid4()}".encode())
    sha256 = sha256_hex(payload)
    key = image_storage_key(sha256, "image/png")
    disk_path = os.path.join(settings.media_root, key)

    try:
        async with _client() as client:
            r1 = await client.post(
                "/api/uploads/image",
                files={"file": ("map.png", payload, "image/png")},
                cookies={"access_token": create_access_token(str(owner1.id))},
            )
        assert r1.status_code == 200, r1.text
        mtime_after_1 = os.path.getmtime(disk_path)

        async with _client() as client:
            r2 = await client.post(
                "/api/uploads/image",
                files={"file": ("same-map-renamed.png", payload, "image/png")},
                cookies={"access_token": create_access_token(str(owner2.id))},
            )
        assert r2.status_code == 200, r2.text
        assert r2.json() == r1.json()
        assert os.path.getmtime(disk_path) == mtime_after_1, (
            "a dedup hit must not rewrite storage"
        )

        async with async_session_factory() as session:
            blobs = (
                await session.exec(select(ImageBlob).where(ImageBlob.sha256 == sha256))
            ).all()
            assert len(blobs) == 1
    finally:
        await _cleanup(
            sha256,
            "image-upload-owner-1@example.com",
            "image-upload-owner-2@example.com",
        )


@pytest.mark.asyncio
async def test_svg_renamed_to_png_is_refused_and_never_stored() -> None:
    """The reason the filename is not consulted at all. Stored, this would be
    served from our own origin as a document full of executable markup."""
    owner = await _make_user("image-upload-owner-svg@example.com")
    payload = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
        b"<script>alert(document.cookie)</script></svg>"
    )
    sha256 = sha256_hex(payload)

    try:
        async with _client() as client:
            r = await client.post(
                "/api/uploads/image",
                files={"file": ("map.png", payload, "image/png")},
                cookies={"access_token": create_access_token(str(owner.id))},
            )
        assert r.status_code == 422, r.text
        assert "PNG, JPEG or WebP" in r.text

        async with async_session_factory() as session:
            blob = (
                await session.exec(select(ImageBlob).where(ImageBlob.sha256 == sha256))
            ).first()
            assert blob is None
        for mime in ("image/png", "image/svg+xml"):
            key = image_storage_key(sha256, mime)
            assert not os.path.exists(os.path.join(settings.media_root, key))
    finally:
        await _cleanup(sha256, "image-upload-owner-svg@example.com")


@pytest.mark.asyncio
async def test_a_picture_too_large_to_paint_is_refused() -> None:
    """A few hundred bytes claiming 30000x30000. Nothing decodes it here, so
    this is refused on the reader's behalf rather than ours."""
    owner = await _make_user("image-upload-owner-huge@example.com")
    payload = png(30000, 30000, salt=f"{uuid.uuid4()}".encode())
    sha256 = sha256_hex(payload)

    try:
        async with _client() as client:
            r = await client.post(
                "/api/uploads/image",
                files={"file": ("huge.png", payload, "image/png")},
                cookies={"access_token": create_access_token(str(owner.id))},
            )
        assert r.status_code == 422, r.text
        assert "8000" in r.text

        async with async_session_factory() as session:
            blob = (
                await session.exec(select(ImageBlob).where(ImageBlob.sha256 == sha256))
            ).first()
            assert blob is None
    finally:
        await _cleanup(sha256, "image-upload-owner-huge@example.com")


@pytest.mark.asyncio
async def test_oversize_content_length_header_is_422_no_rows_created() -> None:
    """The cheap pre-check, exercised without building a real 5 MB body: a tiny
    multipart body with a lied-about Content-Length is still refused, because
    the pre-check reads the header rather than the bytes."""
    owner = await _make_user("image-upload-owner-oversize@example.com")
    payload = png(40, 30, salt=f"{uuid.uuid4()}".encode())
    sha256 = sha256_hex(payload)

    boundary = "imageoversizeheaderboundary"
    body = (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="big.png"\r\n'
            f"Content-Type: image/png\r\n\r\n"
        ).encode()
        + payload
        + f"\r\n--{boundary}--\r\n".encode()
    )

    try:
        async with _client() as client:
            r = await client.post(
                "/api/uploads/image",
                content=body,
                headers={
                    "content-type": f"multipart/form-data; boundary={boundary}",
                    "content-length": str(MAX_IMAGE_BYTES + 1),
                },
                cookies={"access_token": create_access_token(str(owner.id))},
            )
        assert r.status_code == 422, r.text
        assert "5 MB" in r.text

        async with async_session_factory() as session:
            blob = (
                await session.exec(select(ImageBlob).where(ImageBlob.sha256 == sha256))
            ).first()
            assert blob is None
    finally:
        await _cleanup(sha256, "image-upload-owner-oversize@example.com")


@pytest.mark.asyncio
async def test_empty_file_is_refused() -> None:
    owner = await _make_user("image-upload-owner-empty@example.com")
    try:
        async with _client() as client:
            r = await client.post(
                "/api/uploads/image",
                files={"file": ("nothing.png", b"", "image/png")},
                cookies={"access_token": create_access_token(str(owner.id))},
            )
        assert r.status_code == 422, r.text
    finally:
        await _cleanup(sha256_hex(b""), "image-upload-owner-empty@example.com")


@pytest.mark.asyncio
async def test_upload_requires_a_signed_in_author() -> None:
    payload = png(40, 30, salt=f"{uuid.uuid4()}".encode())
    async with _client() as client:
        r = await client.post(
            "/api/uploads/image",
            files={"file": ("map.png", payload, "image/png")},
        )
    assert r.status_code == 401, r.text

    async with async_session_factory() as session:
        blob = (
            await session.exec(
                select(ImageBlob).where(ImageBlob.sha256 == sha256_hex(payload))
            )
        ).first()
        assert blob is None

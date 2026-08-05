"""Integration tests for attaching audio (audio_asset_id) to a material and
resolving it into a playable audio_url in the author view — real DB, ASGI
transport + minted cookie (same pattern as the other authoring tests).
"""

import uuid

import httpx
import pytest
from sqlmodel import select

from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.main import app
from app.models.audio_asset import AudioAsset
from app.models.audio_blob import AudioBlob
from app.models.material import Material
from app.models.user import User


async def _make_user(email: str) -> User:
    async with async_session_factory() as session:
        user = (await session.exec(select(User).where(User.email == email))).first()
        if user is not None:
            return user
        user = User(email=email, display_name=f"Attach test {email}")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _make_blob() -> AudioBlob:
    async with async_session_factory() as session:
        blob = AudioBlob(
            sha256=f"attach-test-{uuid.uuid4().hex}",
            storage_key=f"audio/{uuid.uuid4().hex}.mp3",
            size_bytes=10,
            mime_type="audio/mpeg",
        )
        session.add(blob)
        await session.commit()
        await session.refresh(blob)
        return blob


async def _make_asset(owner_id: uuid.UUID, blob_id: uuid.UUID) -> AudioAsset:
    async with async_session_factory() as session:
        asset = AudioAsset(owner_id=owner_id, blob_id=blob_id)
        session.add(asset)
        await session.commit()
        await session.refresh(asset)
        return asset


async def _cleanup(
    *,
    material_id: uuid.UUID | None = None,
    blob_id: uuid.UUID | None = None,
    emails: tuple[str, ...] = (),
) -> None:
    async with async_session_factory() as session:
        if material_id is not None:
            material = await session.get(Material, material_id)
            if material is not None:
                await session.delete(material)
            await session.commit()
        if blob_id is not None:
            assets = (
                await session.exec(
                    select(AudioAsset).where(AudioAsset.blob_id == blob_id)
                )
            ).all()
            for asset in assets:
                await session.delete(asset)
            await session.flush()
            blob = await session.get(AudioBlob, blob_id)
            if blob is not None:
                await session.delete(blob)
            await session.commit()
        for email in emails:
            user = (await session.exec(select(User).where(User.email == email))).first()
            if user is not None:
                await session.delete(user)
        await session.commit()


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_owned_audio_asset_resolves_to_audio_url() -> None:
    email = "attach1-owner@example.com"
    owner = await _make_user(email)
    blob = await _make_blob()
    asset = await _make_asset(owner.id, blob.id)
    token = create_access_token(str(owner.id))

    material_id: uuid.UUID | None = None
    try:
        async with _client() as client:
            r = await client.post(
                "/api/materials",
                json={
                    "title": "Listening with audio",
                    "type": "listening",
                    "audio_asset_id": str(asset.id),
                },
                cookies={"access_token": token},
            )
            assert r.status_code == 201, r.text
            body = r.json()
            material_id = uuid.UUID(body["id"])
            assert body["audio_asset_id"] == str(asset.id)
            assert body["audio_url"] is not None
            assert blob.storage_key in body["audio_url"]

            r_get = await client.get(
                f"/api/materials/{material_id}", cookies={"access_token": token}
            )
            assert r_get.status_code == 200, r_get.text
            get_body = r_get.json()
            assert get_body["audio_url"] == body["audio_url"]
            assert get_body["transcript_status"] == blob.transcript_status
    finally:
        await _cleanup(material_id=material_id, blob_id=blob.id, emails=(email,))


@pytest.mark.asyncio
async def test_attaching_someone_elses_asset_is_rejected() -> None:
    owner_email = "attach2-owner@example.com"
    stranger_email = "attach2-stranger@example.com"
    owner = await _make_user(owner_email)
    stranger = await _make_user(stranger_email)
    blob = await _make_blob()
    stranger_asset = await _make_asset(stranger.id, blob.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            r = await client.post(
                "/api/materials",
                json={
                    "title": "Should not attach",
                    "type": "listening",
                    "audio_asset_id": str(stranger_asset.id),
                },
                cookies={"access_token": token},
            )
            assert r.status_code == 422, r.text

        async with async_session_factory() as session:
            leaked = (
                await session.exec(
                    select(Material).where(Material.title == "Should not attach")
                )
            ).first()
            assert leaked is None
    finally:
        await _cleanup(blob_id=blob.id, emails=(owner_email, stranger_email))

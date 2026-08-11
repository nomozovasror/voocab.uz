"""Integration tests for GET /api/audio-assets/{asset_id} (§10) — real DB,
ASGI-transport + minted-cookie approach (same pattern as the Faza 2 upload
tests). Every test seeds its own throwaway rows and tears them down again.
"""

import uuid

import httpx
import pytest
from sqlmodel import select

from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.main import app
from app.models.audio_asset import AudioAsset
from app.models.audio_blob import AudioBlob, TranscriptStatus
from app.models.audio_segment import AudioSegment
from app.models.user import User


def _sha() -> str:
    return f"test-read-{uuid.uuid4().hex}"


async def _make_user(email: str) -> User:
    async with async_session_factory() as session:
        user = (await session.exec(select(User).where(User.email == email))).first()
        if user is not None:
            return user
        user = User(email=email, display_name=f"Test {email}")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _make_blob(**overrides) -> AudioBlob:
    async with async_session_factory() as session:
        blob = AudioBlob(
            sha256=_sha(),
            storage_key=f"audio/{uuid.uuid4().hex}.mp3",
            size_bytes=10,
            mime_type="audio/mpeg",
            **overrides,
        )
        session.add(blob)
        await session.commit()
        await session.refresh(blob)
        return blob


async def _make_asset(owner_id: uuid.UUID, blob_id: uuid.UUID, title: str | None = None) -> AudioAsset:
    async with async_session_factory() as session:
        asset = AudioAsset(owner_id=owner_id, blob_id=blob_id, title=title)
        session.add(asset)
        await session.commit()
        await session.refresh(asset)
        return asset


async def _make_segment(blob_id: uuid.UUID, order_index: int, **overrides) -> AudioSegment:
    async with async_session_factory() as session:
        seg = AudioSegment(
            blob_id=blob_id,
            order_index=order_index,
            start_ms=overrides.pop("start_ms", order_index * 1000),
            end_ms=overrides.pop("end_ms", (order_index + 1) * 1000),
            text=overrides.pop("text", f"segment {order_index}"),
            words=overrides.pop(
                "words",
                [{"word": "hi", "start_ms": order_index * 1000, "end_ms": order_index * 1000 + 200}],
            ),
        )
        session.add(seg)
        await session.commit()
        await session.refresh(seg)
        return seg


async def _cleanup(*, blob_id: uuid.UUID | None = None, asset_id: uuid.UUID | None = None) -> None:
    async with async_session_factory() as session:
        if blob_id is not None:
            segments = (
                await session.exec(
                    select(AudioSegment).where(AudioSegment.blob_id == blob_id)
                )
            ).all()
            for seg in segments:
                await session.delete(seg)
            await session.flush()
        if asset_id is not None:
            asset = await session.get(AudioAsset, asset_id)
            if asset is not None:
                await session.delete(asset)
            await session.flush()
        if blob_id is not None:
            blob = await session.get(AudioBlob, blob_id)
            if blob is not None:
                await session.delete(blob)
        await session.commit()


async def _cleanup_user(email: str) -> None:
    async with async_session_factory() as session:
        user = (await session.exec(select(User).where(User.email == email))).first()
        if user is not None:
            await session.delete(user)
            await session.commit()


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_ready_asset_returns_full_segments() -> None:
    owner = await _make_user("faza5-owner-ready@example.com")
    blob = await _make_blob(transcript_status=TranscriptStatus.READY, duration_ms=3500)
    seg0 = await _make_segment(
        blob.id, 0, start_ms=0, end_ms=1800, text="Hello world.",
        words=[{"word": "Hello", "start_ms": 0, "end_ms": 500}],
    )
    seg1 = await _make_segment(
        blob.id, 1, start_ms=1800, end_ms=3500, text="This is a test.",
        words=[{"word": "This", "start_ms": 1800, "end_ms": 2000}],
    )
    asset = await _make_asset(owner.id, blob.id, title="My clip")
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            r = await client.get(
                f"/api/audio-assets/{asset.id}", cookies={"access_token": token}
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["asset_id"] == str(asset.id)
        assert body["blob_id"] == str(blob.id)
        assert body["title"] == "My clip"
        assert body["sha256"] == blob.sha256
        assert body["transcript_status"] == "ready"
        assert body["duration_ms"] == 3500
        assert body["transcript_error"] is None
        assert len(body["segments"]) == 2
        assert body["segments"][0]["order_index"] == 0
        assert body["segments"][0]["start_ms"] == 0
        assert body["segments"][0]["end_ms"] == 1800
        assert body["segments"][0]["text"] == "Hello world."
        assert body["segments"][0]["words"] == [{"word": "Hello", "start_ms": 0, "end_ms": 500}]
        assert body["segments"][1]["order_index"] == 1
        assert body["segments"][1]["text"] == "This is a test."
    finally:
        await _cleanup(blob_id=blob.id, asset_id=asset.id)
        await _cleanup_user("faza5-owner-ready@example.com")


@pytest.mark.asyncio
async def test_pending_and_processing_assets_have_no_segments() -> None:
    owner = await _make_user("faza5-owner-pending@example.com")
    for status_value in (TranscriptStatus.PENDING, TranscriptStatus.PROCESSING):
        blob = await _make_blob(transcript_status=status_value)
        asset = await _make_asset(owner.id, blob.id)
        token = create_access_token(str(owner.id))
        try:
            async with _client() as client:
                r = await client.get(
                    f"/api/audio-assets/{asset.id}", cookies={"access_token": token}
                )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["transcript_status"] == status_value
            assert body["segments"] == []
            assert body["transcript_error"] is None
            assert body["duration_ms"] is None
        finally:
            await _cleanup(blob_id=blob.id, asset_id=asset.id)
    await _cleanup_user("faza5-owner-pending@example.com")


@pytest.mark.asyncio
async def test_failed_asset_returns_error_no_segments() -> None:
    owner = await _make_user("faza5-owner-failed@example.com")
    blob = await _make_blob(
        transcript_status=TranscriptStatus.FAILED,
        transcript_error="ASR returned an empty transcript",
    )
    asset = await _make_asset(owner.id, blob.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            r = await client.get(
                f"/api/audio-assets/{asset.id}", cookies={"access_token": token}
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["transcript_status"] == "failed"
        assert body["transcript_error"] == "ASR returned an empty transcript"
        assert body["segments"] == []
    finally:
        await _cleanup(blob_id=blob.id, asset_id=asset.id)
        await _cleanup_user("faza5-owner-failed@example.com")


@pytest.mark.asyncio
async def test_other_owners_asset_and_nonexistent_asset_are_both_404() -> None:
    owner = await _make_user("faza5-owner-real@example.com")
    other = await _make_user("faza5-owner-other@example.com")
    blob = await _make_blob(transcript_status=TranscriptStatus.READY, duration_ms=1000)
    asset = await _make_asset(owner.id, blob.id)
    other_token = create_access_token(str(other.id))

    try:
        async with _client() as client:
            r_other = await client.get(
                f"/api/audio-assets/{asset.id}", cookies={"access_token": other_token}
            )
            r_missing = await client.get(
                f"/api/audio-assets/{uuid.uuid4()}", cookies={"access_token": other_token}
            )
        assert r_other.status_code == 404, r_other.text
        assert r_missing.status_code == 404, r_missing.text
    finally:
        await _cleanup(blob_id=blob.id, asset_id=asset.id)
        await _cleanup_user("faza5-owner-real@example.com")
        await _cleanup_user("faza5-owner-other@example.com")


@pytest.mark.asyncio
async def test_transcript_correction_is_per_owner_and_never_touches_the_blob() -> None:
    """The headline property of storing corrections on the asset: two owners
    share one blob (that is the whole point of content addressing), so one
    correcting a line must not rewrite the other's transcript — nor the ASR
    rows underneath either of them."""
    a_email = "override-a@example.com"
    b_email = "override-b@example.com"
    owner_a = await _make_user(a_email)
    owner_b = await _make_user(b_email)
    blob = await _make_blob(transcript_status=TranscriptStatus.READY, duration_ms=2000)
    await _make_segment(blob.id, 0, text="the cost is fourty pounds")
    await _make_segment(blob.id, 1, text="second line")
    asset_a = await _make_asset(owner_a.id, blob.id)
    asset_b = await _make_asset(owner_b.id, blob.id)

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            token_a = create_access_token(str(owner_a.id))
            token_b = create_access_token(str(owner_b.id))

            r_patch = await client.patch(
                f"/api/audio-assets/{asset_a.id}/segments/0",
                json={"text": "the cost is forty pounds"},
                cookies={"access_token": token_a},
            )
            assert r_patch.status_code == 200, r_patch.text
            assert r_patch.json()["text"] == "the cost is forty pounds"
            assert r_patch.json()["edited"] is True

            r_a = await client.get(
                f"/api/audio-assets/{asset_a.id}", cookies={"access_token": token_a}
            )
            segments_a = r_a.json()["segments"]
            assert segments_a[0]["text"] == "the cost is forty pounds"
            assert segments_a[0]["edited"] is True
            assert segments_a[1]["edited"] is False

            # The other owner of the same bytes sees the transcription as it
            # came out of the ASR.
            r_b = await client.get(
                f"/api/audio-assets/{asset_b.id}", cookies={"access_token": token_b}
            )
            segments_b = r_b.json()["segments"]
            assert segments_b[0]["text"] == "the cost is fourty pounds"
            assert segments_b[0]["edited"] is False

            async with async_session_factory() as session:
                row = (
                    await session.exec(
                        select(AudioSegment)
                        .where(AudioSegment.blob_id == blob.id)
                        .where(AudioSegment.order_index == 0)
                    )
                ).first()
                assert row is not None
                assert row.text == "the cost is fourty pounds"

            # Sending the original text back removes the correction rather
            # than storing a no-op one.
            r_undo = await client.patch(
                f"/api/audio-assets/{asset_a.id}/segments/0",
                json={"text": "the cost is fourty pounds"},
                cookies={"access_token": token_a},
            )
            assert r_undo.status_code == 200, r_undo.text
            assert r_undo.json()["edited"] is False
            async with async_session_factory() as session:
                refreshed = await session.get(AudioAsset, asset_a.id)
                assert refreshed is not None
                assert refreshed.transcript_overrides == {}
    finally:
        await _cleanup(asset_id=asset_a.id)
        await _cleanup(blob_id=blob.id, asset_id=asset_b.id)
        await _cleanup_user(a_email)
        await _cleanup_user(b_email)


@pytest.mark.asyncio
async def test_correcting_someone_elses_asset_is_404() -> None:
    owner_email = "override-owner@example.com"
    other_email = "override-other@example.com"
    owner = await _make_user(owner_email)
    other = await _make_user(other_email)
    blob = await _make_blob(transcript_status=TranscriptStatus.READY)
    await _make_segment(blob.id, 0)
    asset = await _make_asset(owner.id, blob.id)

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.patch(
                f"/api/audio-assets/{asset.id}/segments/0",
                json={"text": "not mine"},
                cookies={"access_token": create_access_token(str(other.id))},
            )
            assert r.status_code == 404, r.text

            async with async_session_factory() as session:
                refreshed = await session.get(AudioAsset, asset.id)
                assert refreshed is not None
                assert refreshed.transcript_overrides == {}
    finally:
        await _cleanup(blob_id=blob.id, asset_id=asset.id)
        await _cleanup_user(owner_email)
        await _cleanup_user(other_email)

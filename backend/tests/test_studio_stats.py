"""Integration tests for GET /api/studio/stats — real DB, ASGI transport +
minted cookie (same pattern as the other authoring/consumption tests). All
rows are created directly via the ORM (not through the authoring API) for
determinism and speed; the stats endpoint itself is exercised over HTTP.
"""

import asyncio
import uuid

import httpx
import pytest
from sqlmodel import select

from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.main import app
from app.models.attempt import Attempt
from app.models.audio_asset import AudioAsset
from app.models.audio_blob import AudioBlob
from app.models.material import Material
from app.models.part import Part
from app.models.question import Question
from app.models.question_group import QuestionGroup
from app.models.segment import Segment
from app.models.user import User


async def _make_user(email: str) -> User:
    async with async_session_factory() as session:
        user = (await session.exec(select(User).where(User.email == email))).first()
        if user is not None:
            return user
        user = User(email=email, display_name=f"Studio test {email}")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _make_blob(duration_ms: int) -> AudioBlob:
    async with async_session_factory() as session:
        blob = AudioBlob(
            sha256=f"studio-test-{uuid.uuid4().hex}",
            storage_key=f"audio/{uuid.uuid4().hex}.mp3",
            size_bytes=10,
            mime_type="audio/mpeg",
            duration_ms=duration_ms,
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


async def _make_material(
    author_id: uuid.UUID,
    *,
    type: str,
    visibility: str,
    audio_asset_id: uuid.UUID | None = None,
) -> Material:
    async with async_session_factory() as session:
        material = Material(
            author_id=author_id,
            type=type,
            title=f"Studio fixture {uuid.uuid4()}",
            visibility=visibility,
            audio_asset_id=audio_asset_id,
        )
        session.add(material)
        await session.commit()
        await session.refresh(material)
        return material


async def _add_listening_questions(material_id: uuid.UUID, n: int) -> None:
    async with async_session_factory() as session:
        part = Part(material_id=material_id, order_index=0, title="Part 1")
        session.add(part)
        await session.flush()
        group = QuestionGroup(
            part_id=part.id,
            order_index=0,
            type="form_completion",
            instructions="Complete the form.",
            config={"template": " ".join(f"{{{{{i}}}}}" for i in range(1, n + 1))},
        )
        session.add(group)
        await session.flush()
        for i in range(1, n + 1):
            session.add(
                Question(group_id=group.id, number=i, correct_answers=[f"a{i}"])
            )
        await session.commit()


async def _add_segments(material_id: uuid.UUID, n: int) -> None:
    async with async_session_factory() as session:
        for i in range(n):
            session.add(
                Segment(
                    material_id=material_id,
                    order_index=i,
                    start_ms=i * 1000,
                    end_ms=(i + 1) * 1000,
                    reference_text=f"segment {i}",
                )
            )
        await session.commit()


async def _make_attempt(
    user_id: uuid.UUID, material_id: uuid.UUID, *, status: str
) -> Attempt:
    async with async_session_factory() as session:
        attempt = Attempt(user_id=user_id, material_id=material_id, status=status)
        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)
        return attempt


async def _touch_updated_at(material_id: uuid.UUID) -> None:
    """Bump updated_at via a real UPDATE (mirrors what a PATCH does)."""
    async with async_session_factory() as session:
        material = await session.get(Material, material_id)
        assert material is not None
        material.title = material.title + " (edited)"
        session.add(material)
        await session.commit()


async def _cleanup(
    *,
    material_ids: tuple[uuid.UUID, ...] = (),
    blob_ids: tuple[uuid.UUID, ...] = (),
    emails: tuple[str, ...] = (),
) -> None:
    async with async_session_factory() as session:
        for material_id in material_ids:
            attempts = (
                await session.exec(
                    select(Attempt).where(Attempt.material_id == material_id)
                )
            ).all()
            for a in attempts:
                await session.delete(a)
            await session.flush()

            parts = (
                await session.exec(select(Part).where(Part.material_id == material_id))
            ).all()
            for part in parts:
                groups = (
                    await session.exec(
                        select(QuestionGroup).where(QuestionGroup.part_id == part.id)
                    )
                ).all()
                for group in groups:
                    questions = (
                        await session.exec(
                            select(Question).where(Question.group_id == group.id)
                        )
                    ).all()
                    for q in questions:
                        await session.delete(q)
                await session.flush()
                for group in groups:
                    await session.delete(group)
                await session.flush()
                await session.delete(part)
            await session.flush()

            segments = (
                await session.exec(
                    select(Segment).where(Segment.material_id == material_id)
                )
            ).all()
            for seg in segments:
                await session.delete(seg)
            await session.flush()

            material = await session.get(Material, material_id)
            if material is not None:
                await session.delete(material)
        await session.commit()

        for blob_id in blob_ids:
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
async def test_empty_author_gets_zeros_not_404() -> None:
    email = "studio-empty@example.com"
    author = await _make_user(email)
    token = create_access_token(str(author.id))

    try:
        async with _client() as client:
            r = await client.get(
                "/api/studio/stats", cookies={"access_token": token}
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["materials_total"] == 0
            assert body["content_ms"] == 0
            assert body["learners"] == 0
            assert body["completions"] == 0
            assert body["recent"] == []
            by_type = {row["type"]: row for row in body["by_type"]}
            assert set(by_type) == {"listening", "dictation"}
            for row in by_type.values():
                assert row["total"] == 0
                assert row["public"] == 0
                assert row["private"] == 0
                assert row["completions"] == 0
    finally:
        await _cleanup(emails=(email,))


@pytest.mark.asyncio
async def test_studio_stats_full_scenario() -> None:
    author_email = "studio-author@example.com"
    learner_email = "studio-learner@example.com"
    author = await _make_user(author_email)
    learner = await _make_user(learner_email)
    author_token = create_access_token(str(author.id))

    blob1 = await _make_blob(60_000)
    blob2 = await _make_blob(120_000)
    asset1 = await _make_asset(author.id, blob1.id)
    asset2 = await _make_asset(author.id, blob2.id)

    # Sequential creation with a small gap so updated_at strictly increases,
    # for a deterministic "recent" order assertion.
    dictation3 = await _make_material(
        author.id, type="dictation", visibility="public", audio_asset_id=asset1.id
    )
    await _add_segments(dictation3.id, 2)
    await asyncio.sleep(0.05)

    listening2 = await _make_material(
        author.id, type="listening", visibility="private", audio_asset_id=asset2.id
    )
    await _add_listening_questions(listening2.id, 3)
    await asyncio.sleep(0.05)

    listening1 = await _make_material(
        author.id, type="listening", visibility="public", audio_asset_id=asset1.id
    )
    await _add_listening_questions(listening1.id, 2)

    material_ids = (dictation3.id, listening2.id, listening1.id)
    blob_ids = (blob1.id, blob2.id)

    try:
        # completions: B+listening1 (submitted), A+listening1 (submitted,
        # self -> excluded from learners), B+dictation3 (submitted);
        # B+listening2 in_progress is NOT a completion.
        await _make_attempt(learner.id, listening1.id, status="submitted")
        await _make_attempt(author.id, listening1.id, status="submitted")
        await _make_attempt(learner.id, dictation3.id, status="submitted")
        await _make_attempt(learner.id, listening2.id, status="in_progress")

        async with _client() as client:
            r = await client.get(
                "/api/studio/stats", cookies={"access_token": author_token}
            )
            assert r.status_code == 200, r.text
            body = r.json()

            assert body["materials_total"] == 3
            assert body["content_ms"] == 180_000  # 60_000 + 120_000, deduped by blob
            assert body["completions"] == 3
            assert body["learners"] == 1  # only the learner; author excluded

            by_type = {row["type"]: row for row in body["by_type"]}
            assert by_type["listening"] == {
                "type": "listening",
                "total": 2,
                "public": 1,
                "private": 1,
                "completions": 2,
            }
            assert by_type["dictation"] == {
                "type": "dictation",
                "total": 1,
                "public": 1,
                "private": 0,
                "completions": 1,
            }

            recent = body["recent"]
            assert len(recent) == 3
            recent_ids = [r["id"] for r in recent]
            assert recent_ids == [str(listening1.id), str(listening2.id), str(dictation3.id)]

            recent_by_id = {r["id"]: r for r in recent}
            assert recent_by_id[str(listening1.id)]["item_count"] == 2
            assert recent_by_id[str(listening2.id)]["item_count"] == 3
            assert recent_by_id[str(dictation3.id)]["item_count"] == 2

        # A PATCH-style update should bump updated_at and move dictation3 to
        # the front of "recent".
        await _touch_updated_at(dictation3.id)
        async with _client() as client:
            r2 = await client.get(
                "/api/studio/stats", cookies={"access_token": author_token}
            )
            assert r2.status_code == 200, r2.text
            recent2 = r2.json()["recent"]
            assert recent2[0]["id"] == str(dictation3.id)
    finally:
        await _cleanup(
            material_ids=material_ids,
            blob_ids=blob_ids,
            emails=(author_email, learner_email),
        )


@pytest.mark.asyncio
async def test_other_authors_materials_never_appear() -> None:
    email_a = "studio-iso-a@example.com"
    email_b = "studio-iso-b@example.com"
    author_a = await _make_user(email_a)
    author_b = await _make_user(email_b)
    token_a = create_access_token(str(author_a.id))

    material_b = await _make_material(
        author_b.id, type="listening", visibility="public"
    )
    await _add_listening_questions(material_b.id, 4)
    await _make_attempt(author_a.id, material_b.id, status="submitted")

    try:
        async with _client() as client:
            r = await client.get(
                "/api/studio/stats", cookies={"access_token": token_a}
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["materials_total"] == 0
            assert body["completions"] == 0
            assert body["learners"] == 0
            assert body["recent"] == []
            by_type = {row["type"]: row for row in body["by_type"]}
            assert by_type["listening"]["total"] == 0
            assert by_type["listening"]["completions"] == 0
    finally:
        await _cleanup(
            material_ids=(material_b.id,), emails=(email_a, email_b)
        )

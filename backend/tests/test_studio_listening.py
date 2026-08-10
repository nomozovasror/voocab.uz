"""Integration tests for GET /api/studio/listening — real DB, ASGI transport
+ minted cookie (same pattern as the other studio/listening tests). Rows are
created directly via the ORM for determinism; the endpoint itself is
exercised over HTTP.
"""

import uuid

import httpx
import pytest
from sqlmodel import select

from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.main import app
from app.models.attempt import Attempt
from app.models.audio_asset import AudioAsset
from app.models.audio_blob import AudioBlob, TranscriptStatus
from app.models.material import Material
from app.models.part import Part
from app.models.question import Question
from app.models.question_group import QuestionGroup
from app.models.user import User


async def _make_user(email: str) -> User:
    async with async_session_factory() as session:
        user = (await session.exec(select(User).where(User.email == email))).first()
        if user is not None:
            return user
        user = User(email=email, display_name=f"Listening list test {email}")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _make_blob(duration_ms: int | None, status: str = TranscriptStatus.READY) -> AudioBlob:
    async with async_session_factory() as session:
        blob = AudioBlob(
            sha256=f"listlist-test-{uuid.uuid4().hex}",
            storage_key=f"audio/{uuid.uuid4().hex}.mp3",
            size_bytes=10,
            mime_type="audio/mpeg",
            duration_ms=duration_ms,
            transcript_status=status,
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
    type: str = "listening",
    visibility: str = "public",
    audio_asset_id: uuid.UUID | None = None,
) -> Material:
    async with async_session_factory() as session:
        material = Material(
            author_id=author_id,
            type=type,
            title=f"Listening list fixture {uuid.uuid4()}",
            visibility=visibility,
            audio_asset_id=audio_asset_id,
        )
        session.add(material)
        await session.commit()
        await session.refresh(material)
        return material


async def _add_group(material_id: uuid.UUID, n_questions: int, order_index: int = 0) -> None:
    async with async_session_factory() as session:
        part = Part(material_id=material_id, order_index=order_index, title="Part 1")
        session.add(part)
        await session.flush()
        group = QuestionGroup(
            part_id=part.id,
            order_index=0,
            type="form_completion",
            instructions="Complete the form.",
            config={
                "template": " ".join(f"{{{{{i}}}}}" for i in range(1, n_questions + 1))
            },
        )
        session.add(group)
        await session.flush()
        for i in range(1, n_questions + 1):
            session.add(
                Question(group_id=group.id, number=i, correct_answers=[f"a{i}"])
            )
        await session.commit()


async def _make_attempt(
    user_id: uuid.UUID,
    material_id: uuid.UUID,
    *,
    status: str,
    score: float | None = None,
    total_questions: int | None = None,
) -> Attempt:
    async with async_session_factory() as session:
        attempt = Attempt(
            user_id=user_id,
            material_id=material_id,
            status=status,
            score=score,
            total_questions=total_questions,
        )
        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)
        return attempt


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
async def test_listening_row_fields_and_avg_score() -> None:
    author_email = "listlist-author1@example.com"
    learner1_email = "listlist-learner1a@example.com"
    learner2_email = "listlist-learner1b@example.com"
    author = await _make_user(author_email)
    learner1 = await _make_user(learner1_email)
    learner2 = await _make_user(learner2_email)
    token = create_access_token(str(author.id))

    blob = await _make_blob(222_000)
    asset = await _make_asset(author.id, blob.id)
    material = await _make_material(
        author.id, visibility="public", audio_asset_id=asset.id
    )
    await _add_group(material.id, 5)

    try:
        # 80% and 60% -> avg 70.0
        await _make_attempt(
            learner1.id, material.id, status="submitted", score=4.0, total_questions=5
        )
        await _make_attempt(
            learner2.id, material.id, status="submitted", score=3.0, total_questions=5
        )
        # in_progress: not a completion, not part of the avg
        await _make_attempt(learner1.id, material.id, status="in_progress")

        async with _client() as client:
            r = await client.get(
                "/api/studio/listening", cookies={"access_token": token}
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["total"] == 1
            assert body["duration_ms"] == 222_000
            item = body["items"][0]
            assert item["id"] == str(material.id)
            assert item["visibility"] == "public"
            assert item["duration_ms"] == 222_000
            assert item["transcript_status"] == "ready"
            assert item["question_type"] == "form_completion"
            assert item["question_count"] == 5
            assert item["attempts"] == 2  # submitted only
            assert item["avg_score_pct"] == 70.0
    finally:
        await _cleanup(
            material_ids=(material.id,),
            blob_ids=(blob.id,),
            emails=(author_email, learner1_email, learner2_email),
        )


@pytest.mark.asyncio
async def test_material_without_audio_has_null_duration_and_status() -> None:
    email = "listlist-noaudio@example.com"
    author = await _make_user(email)
    token = create_access_token(str(author.id))
    material = await _make_material(author.id)
    await _add_group(material.id, 2)

    try:
        async with _client() as client:
            r = await client.get(
                "/api/studio/listening", cookies={"access_token": token}
            )
            assert r.status_code == 200, r.text
            item = r.json()["items"][0]
            assert item["duration_ms"] is None
            assert item["transcript_status"] is None
            assert item["question_type"] == "form_completion"
    finally:
        await _cleanup(material_ids=(material.id,), emails=(email,))


@pytest.mark.asyncio
async def test_material_without_group_has_null_question_type_zero_count() -> None:
    email = "listlist-nogroup@example.com"
    author = await _make_user(email)
    token = create_access_token(str(author.id))
    material = await _make_material(author.id)

    try:
        async with _client() as client:
            r = await client.get(
                "/api/studio/listening", cookies={"access_token": token}
            )
            assert r.status_code == 200, r.text
            item = r.json()["items"][0]
            assert item["question_type"] is None
            assert item["question_count"] == 0
            assert item["attempts"] == 0
            assert item["avg_score_pct"] is None
    finally:
        await _cleanup(material_ids=(material.id,), emails=(email,))


@pytest.mark.asyncio
async def test_dictation_and_other_authors_materials_never_appear() -> None:
    email_a = "listlist-iso-a@example.com"
    email_b = "listlist-iso-b@example.com"
    author_a = await _make_user(email_a)
    author_b = await _make_user(email_b)
    token_a = create_access_token(str(author_a.id))

    dictation = await _make_material(author_a.id, type="dictation")
    material_b = await _make_material(author_b.id)
    await _add_group(material_b.id, 3)

    try:
        async with _client() as client:
            r = await client.get(
                "/api/studio/listening", cookies={"access_token": token_a}
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["total"] == 0
            assert body["items"] == []
    finally:
        await _cleanup(
            material_ids=(dictation.id, material_b.id), emails=(email_a, email_b)
        )


@pytest.mark.asyncio
async def test_top_level_duration_does_not_double_count_shared_blob() -> None:
    email = "listlist-shared@example.com"
    author = await _make_user(email)
    token = create_access_token(str(author.id))

    blob = await _make_blob(90_000)
    asset = await _make_asset(author.id, blob.id)
    m1 = await _make_material(author.id, audio_asset_id=asset.id)
    m2 = await _make_material(author.id, audio_asset_id=asset.id)

    try:
        async with _client() as client:
            r = await client.get(
                "/api/studio/listening", cookies={"access_token": token}
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["total"] == 2
            assert body["duration_ms"] == 90_000  # not 180_000
    finally:
        await _cleanup(
            material_ids=(m1.id, m2.id), blob_ids=(blob.id,), emails=(email,)
        )

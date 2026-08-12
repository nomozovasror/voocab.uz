"""Integration tests for replacing a dictation material's segment set —
real DB, ASGI transport + minted cookie (same pattern as the other authoring
tests).

The case that matters here is editing a material somebody has already
practised: ``segment_attempts`` points at the segments, so a replace that
dropped and recreated them failed on the foreign key and took the author's
edit down with it.
"""

import uuid

import httpx
import pytest
from sqlmodel import select

from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.main import app
from app.models.attempt import Attempt
from app.models.material import Material
from app.models.segment import Segment
from app.models.segment_attempt import SegmentAttempt
from app.models.user import User


async def _make_user(email: str) -> User:
    async with async_session_factory() as session:
        user = (await session.exec(select(User).where(User.email == email))).first()
        if user is not None:
            return user
        user = User(email=email, display_name=f"Segments test {email}")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _cleanup(material_id: uuid.UUID, *emails: str) -> None:
    async with async_session_factory() as session:
        attempts = (
            await session.exec(select(Attempt).where(Attempt.material_id == material_id))
        ).all()
        for attempt in attempts:
            sas = (
                await session.exec(
                    select(SegmentAttempt).where(
                        SegmentAttempt.attempt_id == attempt.id
                    )
                )
            ).all()
            for sa in sas:
                await session.delete(sa)
        await session.flush()
        for attempt in attempts:
            await session.delete(attempt)
        await session.flush()

        segments = (
            await session.exec(
                select(Segment).where(Segment.material_id == material_id)
            )
        ).all()
        for segment in segments:
            await session.delete(segment)
        await session.flush()

        material = await session.get(Material, material_id)
        if material is not None:
            await session.delete(material)
        await session.commit()

        for email in emails:
            user = (await session.exec(select(User).where(User.email == email))).first()
            if user is not None:
                await session.delete(user)
        await session.commit()


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


def _segment(i: int, text: str) -> dict:
    return {"start_ms": i * 1000, "end_ms": i * 1000 + 900, "reference_text": text}


@pytest.mark.asyncio
async def test_editing_segments_after_practice_keeps_segment_ids() -> None:
    """A segment that survives an edit keeps its row — that is what makes the
    save legal at all (``segment_attempts`` still references it) and what
    keeps the learner's typing attached to what they typed it for."""
    owner_email = "seg-owner@example.com"
    student_email = "seg-student@example.com"
    owner = await _make_user(owner_email)
    student = await _make_user(student_email)
    token = create_access_token(str(owner.id))
    material_id: uuid.UUID | None = None

    try:
        async with _client() as client:
            r_create = await client.post(
                "/api/materials",
                json={
                    "type": "dictation",
                    "title": f"Segments fixture {uuid.uuid4()}",
                    "segments": [
                        _segment(0, "the first line"),
                        _segment(1, "the second line"),
                        _segment(2, "the third line"),
                    ],
                },
                cookies={"access_token": token},
            )
            assert r_create.status_code == 201, r_create.text
            body = r_create.json()
            material_id = uuid.UUID(body["id"])
            seeded = [uuid.UUID(s["id"]) for s in body["segments"]]
            assert len(seeded) == 3

            # Somebody practises it: one attempt with per-segment detail.
            async with async_session_factory() as session:
                attempt = Attempt(
                    user_id=student.id, material_id=material_id, status="submitted"
                )
                session.add(attempt)
                await session.flush()
                for segment_id in seeded:
                    session.add(
                        SegmentAttempt(
                            attempt_id=attempt.id,
                            segment_id=segment_id,
                            typed_text="the first line",
                            correct_words=3,
                            total_words=3,
                        )
                    )
                await session.commit()
                attempt_id = attempt.id

            # The edit an author actually makes: a typo fixed, a boundary
            # nudged, the last segment dropped.
            r_patch = await client.patch(
                f"/api/materials/{material_id}",
                json={
                    "segments": [
                        _segment(0, "the first line"),
                        {
                            "start_ms": 1000,
                            "end_ms": 1950,
                            "reference_text": "the second line, corrected",
                        },
                    ]
                },
                cookies={"access_token": token},
            )
            assert r_patch.status_code == 200, r_patch.text

            edited = r_patch.json()["segments"]
            assert len(edited) == 2
            # Same rows, not lookalikes: a changed id would mean the segment
            # was recreated and the practice detached from it.
            assert [uuid.UUID(s["id"]) for s in edited] == seeded[:2]
            assert edited[1]["reference_text"] == "the second line, corrected"
            assert edited[1]["end_ms"] == 1950

        async with async_session_factory() as session:
            sas = (
                await session.exec(
                    select(SegmentAttempt).where(
                        SegmentAttempt.attempt_id == attempt_id
                    )
                )
            ).all()
            # The two surviving segments keep their detail; only the dropped
            # third one took its own with it.
            assert {sa.segment_id for sa in sas} == set(seeded[:2])
    finally:
        if material_id is not None:
            await _cleanup(material_id, owner_email, student_email)


@pytest.mark.asyncio
async def test_growing_the_segment_set_appends_without_touching_the_rest() -> None:
    """The other direction: added segments are new rows appended after the
    existing ones, which are left exactly as they were."""
    owner_email = "seg-grow-owner@example.com"
    owner = await _make_user(owner_email)
    token = create_access_token(str(owner.id))
    material_id: uuid.UUID | None = None

    try:
        async with _client() as client:
            r_create = await client.post(
                "/api/materials",
                json={
                    "type": "dictation",
                    "title": f"Segments fixture {uuid.uuid4()}",
                    "segments": [_segment(0, "the first line")],
                },
                cookies={"access_token": token},
            )
            assert r_create.status_code == 201, r_create.text
            material_id = uuid.UUID(r_create.json()["id"])
            first_id = r_create.json()["segments"][0]["id"]

            r_patch = await client.patch(
                f"/api/materials/{material_id}",
                json={
                    "segments": [
                        _segment(0, "the first line"),
                        _segment(1, "the second line"),
                    ]
                },
                cookies={"access_token": token},
            )
            assert r_patch.status_code == 200, r_patch.text

            edited = r_patch.json()["segments"]
            assert len(edited) == 2
            assert edited[0]["id"] == first_id
            assert [s["order_index"] for s in edited] == [0, 1]
            assert edited[1]["reference_text"] == "the second line"
    finally:
        if material_id is not None:
            await _cleanup(material_id, owner_email)

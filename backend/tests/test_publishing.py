"""What a material must be before it can go public, and what happens when an
edit takes that away — real DB, ASGI transport + minted cookie.

The rules themselves are one thing; the reason these are integration tests is
the other. The gate used to live only in the editor, so the interesting cases
are the ones a browser never sends: publishing straight over the API, and
editing a published material until it no longer qualifies.
"""

import uuid

import httpx
import pytest
from sqlmodel import select

from app.api.materials import MATERIAL_VISIBILITY_HEADER
from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.main import app
from app.models.audio_asset import AudioAsset
from app.models.audio_blob import AudioBlob
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
        user = User(email=email, display_name=f"Publishing test {email}")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _make_audio(owner_id: uuid.UUID) -> AudioAsset:
    async with async_session_factory() as session:
        blob = AudioBlob(
            sha256=f"publish-test-{uuid.uuid4().hex}",
            storage_key=f"audio/{uuid.uuid4().hex}.mp3",
            size_bytes=10,
            mime_type="audio/mpeg",
        )
        session.add(blob)
        await session.flush()
        asset = AudioAsset(owner_id=owner_id, blob_id=blob.id)
        session.add(asset)
        await session.commit()
        await session.refresh(asset)
        return asset


async def _cleanup(material_id: uuid.UUID, *emails: str) -> None:
    async with async_session_factory() as session:
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

        for email in emails:
            user = (await session.exec(select(User).where(User.email == email))).first()
            if user is None:
                continue
            assets = (
                await session.exec(
                    select(AudioAsset).where(AudioAsset.owner_id == user.id)
                )
            ).all()
            blob_ids = [a.blob_id for a in assets]
            for asset in assets:
                await session.delete(asset)
            await session.flush()
            for blob_id in blob_ids:
                blob = await session.get(AudioBlob, blob_id)
                if blob is not None:
                    await session.delete(blob)
            await session.flush()
            await session.delete(user)
        await session.commit()


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def _ready_listening_material(
    client: httpx.AsyncClient, token: str, owner_id: uuid.UUID
) -> uuid.UUID:
    """A listening material that meets every requirement: a real title, audio,
    a part, instructions, and a question with both an answer and the place in
    the recording where it is said."""
    asset = await _make_audio(owner_id)
    r_material = await client.post(
        "/api/materials",
        json={
            "type": "listening",
            "title": f"IELTS listening {uuid.uuid4().hex[:6]}",
            "audio_asset_id": str(asset.id),
        },
        cookies={"access_token": token},
    )
    assert r_material.status_code == 201, r_material.text
    material_id = uuid.UUID(r_material.json()["id"])

    r_part = await client.post(
        f"/api/materials/{material_id}/parts",
        json={"order_index": 0, "title": "Part 1"},
        cookies={"access_token": token},
    )
    assert r_part.status_code == 201, r_part.text

    r_group = await client.post(
        f"/api/parts/{r_part.json()['id']}/question-groups",
        json={
            "type": "form_completion",
            "instructions": "Complete the form below.",
            "config": {"template": "Nationality | {{1}}"},
            "questions": [
                {
                    "number": 1,
                    "correct_answers": ["Chinese"],
                    "replay_start_ms": 12000,
                    "replay_end_ms": 14500,
                }
            ],
        },
        cookies={"access_token": token},
    )
    assert r_group.status_code == 201, r_group.text
    return material_id


@pytest.mark.asyncio
async def test_a_ready_material_publishes() -> None:
    email = "pub-ready@example.com"
    owner = await _make_user(email)
    token = create_access_token(str(owner.id))
    material_id: uuid.UUID | None = None

    try:
        async with _client() as client:
            material_id = await _ready_listening_material(client, token, owner.id)
            r = await client.patch(
                f"/api/materials/{material_id}",
                json={"visibility": "public"},
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text
            assert r.json()["visibility"] == "public"
    finally:
        if material_id is not None:
            await _cleanup(material_id, email)


@pytest.mark.asyncio
async def test_publishing_over_the_api_is_refused_and_says_why() -> None:
    """The case the editor's own gate could never cover: a request that never
    came from the editor. Every reason at once, so an author isn't sent round
    the loop once per problem."""
    email = "pub-empty@example.com"
    owner = await _make_user(email)
    token = create_access_token(str(owner.id))
    material_id: uuid.UUID | None = None

    try:
        async with _client() as client:
            r_material = await client.post(
                "/api/materials",
                json={"type": "listening", "title": "untitled listening"},
                cookies={"access_token": token},
            )
            assert r_material.status_code == 201, r_material.text
            material_id = uuid.UUID(r_material.json()["id"])

            r = await client.patch(
                f"/api/materials/{material_id}",
                json={"visibility": "public"},
                cookies={"access_token": token},
            )
            assert r.status_code == 422, r.text
            detail = r.json()["detail"]
            assert "real title" in detail
            assert "Attach the audio recording." in detail
            assert "at least one part" in detail

            # And it really didn't publish.
            r_after = await client.get(
                f"/api/materials/{material_id}", cookies={"access_token": token}
            )
            assert r_after.json()["visibility"] == "private"
    finally:
        if material_id is not None:
            await _cleanup(material_id, email)


@pytest.mark.asyncio
async def test_a_material_cannot_be_created_public() -> None:
    email = "pub-born@example.com"
    owner = await _make_user(email)
    token = create_access_token(str(owner.id))

    async with _client() as client:
        r = await client.post(
            "/api/materials",
            json={
                "type": "listening",
                "title": "Straight to public",
                "visibility": "public",
            },
            cookies={"access_token": token},
        )
        assert r.status_code == 422, r.text

    async with async_session_factory() as session:
        user = (await session.exec(select(User).where(User.email == email))).first()
        if user is not None:
            await session.delete(user)
            await session.commit()


@pytest.mark.asyncio
async def test_an_unmarked_answer_blocks_publishing() -> None:
    """Where the answer is said is a requirement, not a nicety: it is what a
    learner gets back with their result."""
    email = "pub-unmarked@example.com"
    owner = await _make_user(email)
    token = create_access_token(str(owner.id))
    material_id: uuid.UUID | None = None

    try:
        async with _client() as client:
            material_id = await _ready_listening_material(client, token, owner.id)

            # Take the mark off question 1.
            r_read = await client.get(
                f"/api/materials/{material_id}", cookies={"access_token": token}
            )
            group = r_read.json()["parts"][0]["question_groups"][0]
            r_group = await client.patch(
                f"/api/question-groups/{group['id']}",
                json={
                    "type": "form_completion",
                    "instructions": "Complete the form below.",
                    "config": {"template": "Nationality | {{1}}"},
                    "questions": [{"number": 1, "correct_answers": ["Chinese"]}],
                },
                cookies={"access_token": token},
            )
            assert r_group.status_code == 200, r_group.text

            r = await client.patch(
                f"/api/materials/{material_id}",
                json={"visibility": "public"},
                cookies={"access_token": token},
            )
            assert r.status_code == 422, r.text
            assert "not linked to the audio" in r.json()["detail"]
    finally:
        if material_id is not None:
            await _cleanup(material_id, email)


@pytest.mark.asyncio
async def test_an_edit_that_breaks_a_published_material_returns_it_to_draft() -> None:
    """Authors edit published work, and an edit can genuinely break it. The
    edit stands — it is their material — and the material stops being public
    rather than staying in front of learners in a state it can't be taken in.
    """
    email = "pub-demote@example.com"
    owner = await _make_user(email)
    token = create_access_token(str(owner.id))
    material_id: uuid.UUID | None = None

    try:
        async with _client() as client:
            material_id = await _ready_listening_material(client, token, owner.id)
            r_publish = await client.patch(
                f"/api/materials/{material_id}",
                json={"visibility": "public"},
                cookies={"access_token": token},
            )
            assert r_publish.status_code == 200, r_publish.text

            r_read = await client.get(
                f"/api/materials/{material_id}", cookies={"access_token": token}
            )
            group_id = r_read.json()["parts"][0]["question_groups"][0]["id"]

            # The author clears the form: the group goes, and with it the only
            # question in the material.
            r_delete = await client.delete(
                f"/api/question-groups/{group_id}",
                cookies={"access_token": token},
            )
            assert r_delete.status_code == 204, r_delete.text
            # The write reports the change of state, so an editor can say so
            # without re-reading the material.
            assert r_delete.headers[MATERIAL_VISIBILITY_HEADER] == "private"

            r_after = await client.get(
                f"/api/materials/{material_id}", cookies={"access_token": token}
            )
            assert r_after.json()["visibility"] == "private"
    finally:
        if material_id is not None:
            await _cleanup(material_id, email)


@pytest.mark.asyncio
async def test_an_edit_that_keeps_it_valid_leaves_it_public() -> None:
    email = "pub-stays@example.com"
    owner = await _make_user(email)
    token = create_access_token(str(owner.id))
    material_id: uuid.UUID | None = None

    try:
        async with _client() as client:
            material_id = await _ready_listening_material(client, token, owner.id)
            await client.patch(
                f"/api/materials/{material_id}",
                json={"visibility": "public"},
                cookies={"access_token": token},
            )

            r_read = await client.get(
                f"/api/materials/{material_id}", cookies={"access_token": token}
            )
            part_id = r_read.json()["parts"][0]["id"]
            r_part = await client.patch(
                f"/api/parts/{part_id}",
                json={"title": "Part 1 — enrolment form"},
                cookies={"access_token": token},
            )
            assert r_part.status_code == 200, r_part.text
            # Nothing to report: it is still public.
            assert MATERIAL_VISIBILITY_HEADER not in r_part.headers

            r_after = await client.get(
                f"/api/materials/{material_id}", cookies={"access_token": token}
            )
            assert r_after.json()["visibility"] == "public"
    finally:
        if material_id is not None:
            await _cleanup(material_id, email)

"""Optimistic concurrency for material authoring — real DB, ASGI transport +
minted cookie (same pattern as the other authoring tests).

The case these cover is one author with the editor open twice, which autosave
turns from a nuisance into silent data loss: both windows write the whole
material, so whichever typed last wins and the other's work is gone with no
sign it ever existed.
"""

import uuid

import httpx
import pytest
from sqlmodel import select

from app.api.materials import MATERIAL_VERSION_HEADER
from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.main import app
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
        user = User(email=email, display_name=f"Concurrency test {email}")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


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
            if user is not None:
                await session.delete(user)
        await session.commit()


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def _make_material(client: httpx.AsyncClient, token: str) -> dict:
    r = await client.post(
        "/api/materials",
        json={"type": "listening", "title": f"Concurrency fixture {uuid.uuid4()}"},
        cookies={"access_token": token},
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_stale_version_is_refused_and_fresh_one_accepted() -> None:
    """Two windows load the same material; the first to write wins and the
    second is told so, rather than overwriting what it never saw."""
    email = "conc-owner@example.com"
    owner = await _make_user(email)
    token = create_access_token(str(owner.id))
    material_id: uuid.UUID | None = None

    try:
        async with _client() as client:
            created = await _make_material(client, token)
            material_id = uuid.UUID(created["id"])
            # Both windows loaded this one.
            loaded_version = created["version"]

            r_part = await client.post(
                f"/api/materials/{material_id}/parts",
                json={"order_index": 0, "title": "Part 1"},
                headers={MATERIAL_VERSION_HEADER: str(loaded_version)},
                cookies={"access_token": token},
            )
            assert r_part.status_code == 201, r_part.text
            # The write says what the material is now, so a client can carry
            # on without re-reading it.
            next_version = int(r_part.headers[MATERIAL_VERSION_HEADER])
            assert next_version == loaded_version + 1
            part_id = r_part.json()["id"]

            # The second window still holds the version it loaded.
            r_stale = await client.patch(
                f"/api/parts/{part_id}",
                json={"title": "Part 1 (other window)"},
                headers={MATERIAL_VERSION_HEADER: str(loaded_version)},
                cookies={"access_token": token},
            )
            assert r_stale.status_code == 409, r_stale.text
            assert "changed somewhere else" in r_stale.json()["detail"]

            # And nothing of it landed.
            r_after = await client.get(
                f"/api/materials/{material_id}", cookies={"access_token": token}
            )
            assert r_after.json()["parts"][0]["title"] == "Part 1"
            assert r_after.json()["version"] == next_version

            # The window that is up to date writes normally.
            r_fresh = await client.patch(
                f"/api/parts/{part_id}",
                json={"title": "Part 1 renamed"},
                headers={MATERIAL_VERSION_HEADER: str(next_version)},
                cookies={"access_token": token},
            )
            assert r_fresh.status_code == 200, r_fresh.text
            assert int(r_fresh.headers[MATERIAL_VERSION_HEADER]) == next_version + 1
    finally:
        if material_id is not None:
            await _cleanup(material_id, email)


@pytest.mark.asyncio
async def test_writes_under_the_material_all_bump_the_same_version() -> None:
    """The counter covers the whole tree: a question group saved in one window
    has to invalidate the other window's view of the material, not just of
    that group."""
    email = "conc-tree@example.com"
    owner = await _make_user(email)
    token = create_access_token(str(owner.id))
    material_id: uuid.UUID | None = None

    try:
        async with _client() as client:
            created = await _make_material(client, token)
            material_id = uuid.UUID(created["id"])
            version = created["version"]

            r_part = await client.post(
                f"/api/materials/{material_id}/parts",
                json={"order_index": 0, "title": "Part 1"},
                headers={MATERIAL_VERSION_HEADER: str(version)},
                cookies={"access_token": token},
            )
            assert r_part.status_code == 201, r_part.text
            version = int(r_part.headers[MATERIAL_VERSION_HEADER])
            part_id = r_part.json()["id"]

            r_group = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json={
                    "type": "form_completion",
                    "instructions": "Complete the form.",
                    "config": {"template": "Nationality | {{1}}"},
                    "questions": [{"number": 1, "correct_answers": ["Chinese"]}],
                },
                headers={MATERIAL_VERSION_HEADER: str(version)},
                cookies={"access_token": token},
            )
            assert r_group.status_code == 201, r_group.text
            after_group = int(r_group.headers[MATERIAL_VERSION_HEADER])
            assert after_group == version + 1

            # The material's own PATCH shares the counter.
            r_material = await client.patch(
                f"/api/materials/{material_id}",
                json={"title": "Renamed"},
                headers={MATERIAL_VERSION_HEADER: str(after_group)},
                cookies={"access_token": token},
            )
            assert r_material.status_code == 200, r_material.text
            assert int(r_material.headers[MATERIAL_VERSION_HEADER]) == after_group + 1
            assert r_material.json()["version"] == after_group + 1
    finally:
        if material_id is not None:
            await _cleanup(material_id, email)


@pytest.mark.asyncio
async def test_a_client_that_sends_no_version_is_not_blocked() -> None:
    """Opting in is the client's choice. Without the header the write goes
    through as it always did — the check exists for editors that track the
    version, not as a new requirement on every caller."""
    email = "conc-optout@example.com"
    owner = await _make_user(email)
    token = create_access_token(str(owner.id))
    material_id: uuid.UUID | None = None

    try:
        async with _client() as client:
            created = await _make_material(client, token)
            material_id = uuid.UUID(created["id"])

            r_part = await client.post(
                f"/api/materials/{material_id}/parts",
                json={"order_index": 0, "title": "Part 1"},
                cookies={"access_token": token},
            )
            assert r_part.status_code == 201, r_part.text
            part_id = r_part.json()["id"]

            # Two writes with no header, the second on a version that would
            # have been stale: both land.
            for title in ("second", "third"):
                r = await client.patch(
                    f"/api/parts/{part_id}",
                    json={"title": title},
                    cookies={"access_token": token},
                )
                assert r.status_code == 200, r.text

            # The counter still moved, so a client that starts sending the
            # header later gets an accurate answer.
            r_after = await client.get(
                f"/api/materials/{material_id}", cookies={"access_token": token}
            )
            assert r_after.json()["version"] == created["version"] + 3
            assert r_after.json()["parts"][0]["title"] == "third"
    finally:
        if material_id is not None:
            await _cleanup(material_id, email)

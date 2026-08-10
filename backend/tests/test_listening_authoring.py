"""Integration tests for the listening Part-1 form-completion authoring API
(brief §5) — real DB, ASGI transport + minted cookie (same pattern as the
audio endpoint tests). Every test seeds its own throwaway user(s)/material(s)
and cleans up its own rows afterward with targeted deletes.
"""

import asyncio
import uuid

import httpx
import pytest
from sqlmodel import select

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
        user = User(email=email, display_name=f"Listening test {email}")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _make_material(
    author_id: uuid.UUID, *, visibility: str = "private"
) -> Material:
    async with async_session_factory() as session:
        material = Material(
            author_id=author_id,
            type="listening",
            title=f"Listening fixture {uuid.uuid4()}",
            visibility=visibility,
        )
        session.add(material)
        await session.commit()
        await session.refresh(material)
        return material


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
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _template_and_questions(n: int) -> tuple[str, list[dict]]:
    lines = [f"Field {i}: {{{{{i}}}}}" for i in range(1, n + 1)]
    template = "\n".join(lines)
    questions = [
        {"number": i, "correct_answers": [f"answer{i}", f"Answer {i}"]}
        for i in range(1, n + 1)
    ]
    return template, questions


@pytest.mark.asyncio
async def test_group_with_matching_tokens_saved_atomically() -> None:
    email = "l1-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            r_part = await client.post(
                f"/api/materials/{material.id}/parts",
                json={"order_index": 0, "title": "Part 1"},
                cookies={"access_token": token},
            )
            assert r_part.status_code == 201, r_part.text
            part_id = r_part.json()["id"]

            template, questions = _template_and_questions(4)
            r_group = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json={
                    "type": "form_completion",
                    "instructions": "Complete the form.",
                    "config": {"template": template},
                    "questions": questions,
                },
                cookies={"access_token": token},
            )
            assert r_group.status_code == 201, r_group.text
            body = r_group.json()
            assert len(body["questions"]) == 4
            assert {q["number"] for q in body["questions"]} == {1, 2, 3, 4}

        async with async_session_factory() as session:
            group = await session.get(QuestionGroup, uuid.UUID(body["id"]))
            assert group is not None
            saved_questions = (
                await session.exec(
                    select(Question).where(Question.group_id == group.id)
                )
            ).all()
            assert len(saved_questions) == 4
            numbers = sorted(q.number for q in saved_questions)
            assert numbers == [1, 2, 3, 4]
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_token_question_mismatch_is_422_nothing_persisted() -> None:
    email = "l2-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            r_part = await client.post(
                f"/api/materials/{material.id}/parts",
                json={"order_index": 0, "title": "Part 1"},
                cookies={"access_token": token},
            )
            assert r_part.status_code == 201, r_part.text
            part_id = r_part.json()["id"]

            template, questions = _template_and_questions(4)
            questions = questions[:3]  # 4 tokens, only 3 questions -> mismatch
            r_group = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json={
                    "type": "form_completion",
                    "instructions": "Complete the form.",
                    "config": {"template": template},
                    "questions": questions,
                },
                cookies={"access_token": token},
            )
            assert r_group.status_code == 422, r_group.text

        async with async_session_factory() as session:
            groups = (
                await session.exec(
                    select(QuestionGroup).where(QuestionGroup.part_id == uuid.UUID(part_id))
                )
            ).all()
            assert len(groups) == 0
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_non_owner_add_group_is_403() -> None:
    owner_email = "l3-owner@example.com"
    intruder_email = "l3-intruder@example.com"
    owner = await _make_user(owner_email)
    intruder = await _make_user(intruder_email)
    material = await _make_material(owner.id)
    owner_token = create_access_token(str(owner.id))
    intruder_token = create_access_token(str(intruder.id))

    try:
        async with _client() as client:
            r_part = await client.post(
                f"/api/materials/{material.id}/parts",
                json={"order_index": 0, "title": "Part 1"},
                cookies={"access_token": owner_token},
            )
            assert r_part.status_code == 201, r_part.text
            part_id = r_part.json()["id"]

            template, questions = _template_and_questions(2)
            r_group = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json={
                    "type": "form_completion",
                    "instructions": "Complete the form.",
                    "config": {"template": template},
                    "questions": questions,
                },
                cookies={"access_token": intruder_token},
            )
            assert r_group.status_code == 403, r_group.text
    finally:
        await _cleanup(material.id, owner_email, intruder_email)


@pytest.mark.asyncio
async def test_patch_fully_replaces_template_and_questions() -> None:
    email = "l4-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            r_part = await client.post(
                f"/api/materials/{material.id}/parts",
                json={"order_index": 0, "title": "Part 1"},
                cookies={"access_token": token},
            )
            part_id = r_part.json()["id"]

            template, questions = _template_and_questions(3)
            r_group = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json={
                    "type": "form_completion",
                    "instructions": "Complete the form.",
                    "config": {"template": template},
                    "questions": questions,
                },
                cookies={"access_token": token},
            )
            group_id = r_group.json()["id"]

            new_template, new_questions = _template_and_questions(2)
            r_patch = await client.patch(
                f"/api/question-groups/{group_id}",
                json={
                    "type": "form_completion",
                    "instructions": "Replaced instructions.",
                    "config": {"template": new_template},
                    "questions": new_questions,
                },
                cookies={"access_token": token},
            )
            assert r_patch.status_code == 200, r_patch.text
            body = r_patch.json()
            assert len(body["questions"]) == 2
            assert {q["number"] for q in body["questions"]} == {1, 2}

        async with async_session_factory() as session:
            saved_questions = (
                await session.exec(
                    select(Question).where(Question.group_id == uuid.UUID(group_id))
                )
            ).all()
            assert len(saved_questions) == 2
            assert sorted(q.number for q in saved_questions) == [1, 2]
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_author_get_includes_answers_non_owner_get_does_not() -> None:
    owner_email = "l5-owner@example.com"
    viewer_email = "l5-viewer@example.com"
    owner = await _make_user(owner_email)
    viewer = await _make_user(viewer_email)
    material = await _make_material(owner.id, visibility="public")
    owner_token = create_access_token(str(owner.id))
    viewer_token = create_access_token(str(viewer.id))

    try:
        async with _client() as client:
            r_part = await client.post(
                f"/api/materials/{material.id}/parts",
                json={"order_index": 0, "title": "Part 1"},
                cookies={"access_token": owner_token},
            )
            part_id = r_part.json()["id"]

            template, questions = _template_and_questions(2)
            await client.post(
                f"/api/parts/{part_id}/question-groups",
                json={
                    "type": "form_completion",
                    "instructions": "Complete the form.",
                    "config": {"template": template},
                    "questions": questions,
                },
                cookies={"access_token": owner_token},
            )

            r_owner_get = await client.get(
                f"/api/materials/{material.id}", cookies={"access_token": owner_token}
            )
            assert r_owner_get.status_code == 200, r_owner_get.text
            owner_body = r_owner_get.json()
            owner_questions = owner_body["parts"][0]["question_groups"][0]["questions"]
            assert all("correct_answers" in q for q in owner_questions)
            assert owner_questions[0]["correct_answers"]

            r_viewer_get = await client.get(
                f"/api/materials/{material.id}", cookies={"access_token": viewer_token}
            )
            assert r_viewer_get.status_code == 200, r_viewer_get.text
            viewer_body = r_viewer_get.json()
            viewer_questions = viewer_body["parts"][0]["question_groups"][0]["questions"]
            assert all("correct_answers" not in q for q in viewer_questions)
    finally:
        await _cleanup(material.id, owner_email, viewer_email)


@pytest.mark.asyncio
async def test_duplicate_part_order_index_is_409_not_500() -> None:
    """Sequential duplicate: caught by the app-level pre-check."""
    email = "l6-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            r1 = await client.post(
                f"/api/materials/{material.id}/parts",
                json={"order_index": 0, "title": "Part 1"},
                cookies={"access_token": token},
            )
            assert r1.status_code == 201, r1.text

            r2 = await client.post(
                f"/api/materials/{material.id}/parts",
                json={"order_index": 0, "title": "Part 1 again"},
                cookies={"access_token": token},
            )
            assert r2.status_code == 409, r2.text

        async with async_session_factory() as session:
            parts = (
                await session.exec(select(Part).where(Part.material_id == material.id))
            ).all()
            assert len(parts) == 1
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_concurrent_duplicate_part_order_index_loser_is_409_not_500() -> None:
    """Concurrent duplicate: races past the pre-check, must be caught by the
    IntegrityError handler around the DB write -- never surfaces as a 500."""
    email = "l7-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            results = await asyncio.gather(
                client.post(
                    f"/api/materials/{material.id}/parts",
                    json={"order_index": 0, "title": "Racer A"},
                    cookies={"access_token": token},
                ),
                client.post(
                    f"/api/materials/{material.id}/parts",
                    json={"order_index": 0, "title": "Racer B"},
                    cookies={"access_token": token},
                ),
            )
            statuses = sorted(r.status_code for r in results)
            # Exactly one wins (201), one loses -- and the loser is a clean
            # 409, never an unhandled 500.
            assert statuses == [201, 409], [r.text for r in results]

        async with async_session_factory() as session:
            parts = (
                await session.exec(select(Part).where(Part.material_id == material.id))
            ).all()
            assert len(parts) == 1
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_owner_can_update_part_audio_range() -> None:
    email = "l8-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            r_create = await client.post(
                f"/api/materials/{material.id}/parts",
                json={"order_index": 0, "title": "Part 1"},
                cookies={"access_token": token},
            )
            assert r_create.status_code == 201, r_create.text
            part_id = r_create.json()["id"]

            r_patch = await client.patch(
                f"/api/parts/{part_id}",
                json={
                    "title": "Part 1 (renamed)",
                    "audio_start_ms": 1000,
                    "audio_end_ms": 5000,
                },
                cookies={"access_token": token},
            )
            assert r_patch.status_code == 200, r_patch.text
            body = r_patch.json()
            assert body["title"] == "Part 1 (renamed)"
            assert body["audio_start_ms"] == 1000
            assert body["audio_end_ms"] == 5000

            # Partial update: only audio_end_ms, validated against the
            # existing audio_start_ms (1000) still on the row.
            r_patch2 = await client.patch(
                f"/api/parts/{part_id}",
                json={"audio_end_ms": 6000},
                cookies={"access_token": token},
            )
            assert r_patch2.status_code == 200, r_patch2.text
            assert r_patch2.json()["audio_end_ms"] == 6000
            assert r_patch2.json()["audio_start_ms"] == 1000
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_non_owner_update_part_is_403() -> None:
    owner_email = "l9-owner@example.com"
    intruder_email = "l9-intruder@example.com"
    owner = await _make_user(owner_email)
    intruder = await _make_user(intruder_email)
    material = await _make_material(owner.id)
    owner_token = create_access_token(str(owner.id))
    intruder_token = create_access_token(str(intruder.id))

    try:
        async with _client() as client:
            r_create = await client.post(
                f"/api/materials/{material.id}/parts",
                json={"order_index": 0, "title": "Part 1"},
                cookies={"access_token": owner_token},
            )
            part_id = r_create.json()["id"]

            r_patch = await client.patch(
                f"/api/parts/{part_id}",
                json={"title": "Hijacked"},
                cookies={"access_token": intruder_token},
            )
            assert r_patch.status_code == 403, r_patch.text
    finally:
        await _cleanup(material.id, owner_email, intruder_email)


@pytest.mark.asyncio
async def test_update_part_end_before_start_is_422() -> None:
    email = "l10-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            r_create = await client.post(
                f"/api/materials/{material.id}/parts",
                json={
                    "order_index": 0,
                    "title": "Part 1",
                    "audio_start_ms": 2000,
                    "audio_end_ms": 8000,
                },
                cookies={"access_token": token},
            )
            part_id = r_create.json()["id"]

            # Only sending a new start that's >= the existing end (8000).
            r_patch = await client.patch(
                f"/api/parts/{part_id}",
                json={"audio_start_ms": 9000},
                cookies={"access_token": token},
            )
            assert r_patch.status_code == 422, r_patch.text
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_update_unknown_part_is_404() -> None:
    email = "l11-owner@example.com"
    owner = await _make_user(email)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            r_patch = await client.patch(
                f"/api/parts/{uuid.uuid4()}",
                json={"title": "Ghost"},
                cookies={"access_token": token},
            )
            assert r_patch.status_code == 404, r_patch.text
    finally:
        await _cleanup(uuid.uuid4(), email)

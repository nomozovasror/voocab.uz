"""Integration tests for listening consumption (§7): GET /take (no-leak) and
POST /attempts (grading + persistence) — real DB, ASGI transport + minted
cookie, same pattern as the other listening tests.
"""

import json
import uuid

import httpx
import pytest
from sqlmodel import select

from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.main import app
from app.models.attempt import Attempt
from app.models.material import Material
from app.models.part import Part
from app.models.question import Question
from app.models.question_attempt import QuestionAttempt
from app.models.question_group import QuestionGroup
from app.models.user import User


async def _make_user(email: str) -> User:
    async with async_session_factory() as session:
        user = (await session.exec(select(User).where(User.email == email))).first()
        if user is not None:
            return user
        user = User(email=email, display_name=f"Consumption test {email}")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _make_material(author_id: uuid.UUID, *, visibility: str = "public") -> Material:
    async with async_session_factory() as session:
        material = Material(
            author_id=author_id,
            type="listening",
            title=f"Consumption fixture {uuid.uuid4()}",
            visibility=visibility,
        )
        session.add(material)
        await session.commit()
        await session.refresh(material)
        return material


async def _cleanup(material_id: uuid.UUID, *emails: str) -> None:
    async with async_session_factory() as session:
        attempts = (
            await session.exec(select(Attempt).where(Attempt.material_id == material_id))
        ).all()
        for attempt in attempts:
            qas = (
                await session.exec(
                    select(QuestionAttempt).where(
                        QuestionAttempt.attempt_id == attempt.id
                    )
                )
            ).all()
            for qa in qas:
                await session.delete(qa)
        await session.flush()
        for attempt in attempts:
            await session.delete(attempt)
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

        for email in emails:
            user = (await session.exec(select(User).where(User.email == email))).first()
            if user is not None:
                await session.delete(user)
        await session.commit()


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _seed_group(
    client: httpx.AsyncClient, token: str, material_id: uuid.UUID
) -> tuple[uuid.UUID, list[dict]]:
    """One part + one group with 5 gaps, covering the grading matrix cases:
    1 exact, 2 variant, 3 whitespace/case, 4 misspelling (wrong), 5 exact-
    spelling-with-extra-word (wrong)."""
    r_part = await client.post(
        f"/api/materials/{material_id}/parts",
        json={"order_index": 0, "title": "Part 1"},
        cookies={"access_token": token},
    )
    assert r_part.status_code == 201, r_part.text
    part_id = r_part.json()["id"]

    template = "1: {{1}}\n2: {{2}}\n3: {{3}}\n4: {{4}}\n5: {{5}}"
    questions = [
        {"number": 1, "correct_answers": ["colour"]},
        {"number": 2, "correct_answers": ["colour", "color"]},
        {"number": 3, "correct_answers": ["blue sky"]},
        {"number": 4, "correct_answers": ["colour"]},
        {"number": 5, "correct_answers": ["photography"]},
    ]
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
    return part_id, r_group.json()["questions"]


@pytest.mark.asyncio
async def test_take_response_never_contains_correct_answers() -> None:
    owner_email = "c1-owner@example.com"
    owner = await _make_user(owner_email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            await _seed_group(client, token, material.id)

            r_take = await client.get(
                f"/api/materials/{material.id}/take", cookies={"access_token": token}
            )
            assert r_take.status_code == 200, r_take.text
            raw_text = r_take.text
            # Headline security assertion: the raw JSON text must never
            # contain the key, in any nesting -- not just "the parsed dict
            # happens to lack a field".
            assert "correct_answers" not in raw_text

            body = r_take.json()
            assert body["title"] == material.title
            questions = body["parts"][0]["question_groups"][0]["questions"]
            assert len(questions) == 5
            for q in questions:
                assert set(q.keys()) == {"id", "number"}
    finally:
        await _cleanup(material.id, owner_email)


@pytest.mark.asyncio
async def test_grading_matrix_and_attempt_persistence() -> None:
    owner_email = "c2-owner@example.com"
    student_email = "c2-student@example.com"
    owner = await _make_user(owner_email)
    student = await _make_user(student_email)
    material = await _make_material(owner.id)
    owner_token = create_access_token(str(owner.id))
    student_token = create_access_token(str(student.id))

    try:
        async with _client() as client:
            _part_id, questions = await _seed_group(client, owner_token, material.id)
            by_number = {q["number"]: q["id"] for q in questions}

            answers = [
                {"question_id": by_number[1], "given_answer": "colour"},  # exact
                {"question_id": by_number[2], "given_answer": "color"},  # variant
                {
                    "question_id": by_number[3],
                    "given_answer": "  Blue   SKY  ",
                },  # whitespace+case
                {"question_id": by_number[4], "given_answer": "collour"},  # misspelling
                {
                    "question_id": by_number[5],
                    "given_answer": "photography course",
                },  # exact-spelling extra word
            ]
            r_submit = await client.post(
                f"/api/materials/{material.id}/attempts",
                json={"answers": answers},
                cookies={"access_token": student_token},
            )
            assert r_submit.status_code == 200, r_submit.text
            body = r_submit.json()
            assert body["total_questions"] == 5
            assert body["score"] == 3  # 1, 2, 3 correct; 4, 5 wrong

            results_by_id = {r["question_id"]: r for r in body["results"]}
            assert results_by_id[by_number[1]]["is_correct"] is True
            assert results_by_id[by_number[2]]["is_correct"] is True
            assert results_by_id[by_number[3]]["is_correct"] is True
            assert results_by_id[by_number[4]]["is_correct"] is False
            assert results_by_id[by_number[5]]["is_correct"] is False
            assert results_by_id[by_number[5]]["correct_answers"] == ["photography"]

        async with async_session_factory() as session:
            attempts = (
                await session.exec(
                    select(Attempt).where(
                        Attempt.material_id == material.id,
                        Attempt.user_id == student.id,
                    )
                )
            ).all()
            assert len(attempts) == 1
            attempt = attempts[0]
            assert attempt.status == "submitted"
            assert attempt.submitted_at is not None
            assert attempt.score == 3
            assert attempt.total_questions == 5

            qas = (
                await session.exec(
                    select(QuestionAttempt).where(
                        QuestionAttempt.attempt_id == attempt.id
                    )
                )
            ).all()
            assert len(qas) == 5
            correct = [qa for qa in qas if qa.is_correct]
            assert len(correct) == 3
    finally:
        await _cleanup(material.id, owner_email, student_email)


@pytest.mark.asyncio
async def test_foreign_question_id_is_ignored_not_graded() -> None:
    owner_email = "c3-owner@example.com"
    owner = await _make_user(owner_email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            _part_id, questions = await _seed_group(client, token, material.id)
            foreign_id = str(uuid.uuid4())

            answers = [
                {"question_id": foreign_id, "given_answer": "irrelevant"},
                {"question_id": questions[0]["id"], "given_answer": "colour"},
            ]
            r_submit = await client.post(
                f"/api/materials/{material.id}/attempts",
                json={"answers": answers},
                cookies={"access_token": token},
            )
            assert r_submit.status_code == 200, r_submit.text
            body = r_submit.json()
            # Only the material's real 5 questions get graded/persisted; the
            # foreign id is silently dropped, not a crash and not a phantom
            # 6th result.
            assert body["total_questions"] == 5
            assert len(body["results"]) == 5
            assert all(r["question_id"] != foreign_id for r in body["results"])
    finally:
        await _cleanup(material.id, owner_email)


@pytest.mark.asyncio
async def test_submit_resumes_existing_in_progress_attempt_no_dupes() -> None:
    """§7: an attempt is "created OR resumed". Pre-seed an in_progress
    Attempt for this (user, material) directly, then submit -- the submit
    must reuse that row (not create a second Attempt) and leave exactly one
    QuestionAttempt per question, not duplicates from an old + new set."""
    owner_email = "c4-owner@example.com"
    student_email = "c4-student@example.com"
    owner = await _make_user(owner_email)
    student = await _make_user(student_email)
    material = await _make_material(owner.id)
    owner_token = create_access_token(str(owner.id))
    student_token = create_access_token(str(student.id))

    try:
        async with _client() as client:
            _part_id, questions = await _seed_group(client, owner_token, material.id)

        async with async_session_factory() as session:
            pre_existing = Attempt(
                user_id=student.id,
                material_id=material.id,
                status="in_progress",
            )
            session.add(pre_existing)
            await session.commit()
            await session.refresh(pre_existing)
            pre_existing_id = pre_existing.id

        async with _client() as client:
            by_number = {q["number"]: q["id"] for q in questions}
            answers = [
                {"question_id": by_number[1], "given_answer": "colour"},
                {"question_id": by_number[2], "given_answer": "color"},
            ]
            r_submit = await client.post(
                f"/api/materials/{material.id}/attempts",
                json={"answers": answers},
                cookies={"access_token": student_token},
            )
            assert r_submit.status_code == 200, r_submit.text
            body = r_submit.json()
            assert body["total_questions"] == 5
            assert body["score"] == 2

        async with async_session_factory() as session:
            attempts = (
                await session.exec(
                    select(Attempt).where(
                        Attempt.material_id == material.id,
                        Attempt.user_id == student.id,
                    )
                )
            ).all()
            # Exactly one Attempt row: the pre-existing in_progress one,
            # resumed and transitioned -- not a second, separate row.
            assert len(attempts) == 1
            assert attempts[0].id == pre_existing_id
            assert attempts[0].status == "submitted"
            assert attempts[0].submitted_at is not None

            qas = (
                await session.exec(
                    select(QuestionAttempt).where(
                        QuestionAttempt.attempt_id == pre_existing_id
                    )
                )
            ).all()
            # Exactly one QuestionAttempt per material question -- no
            # duplicates from a stale set left over from "resuming".
            assert len(qas) == 5
    finally:
        await _cleanup(material.id, owner_email, student_email)

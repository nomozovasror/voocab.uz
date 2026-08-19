"""GET /api/listening/practice — what a learner can sit, and what they have
already done with it.

The two things worth pinning down here are both about what the catalogue
REFUSES to show: an author's unfinished drafts, which belong in the Studio,
and anybody else's attempt history, which belongs to them.
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
        user = User(email=email, display_name=f"Catalogue test {email}")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _make_material(author_id: uuid.UUID, title: str, visibility: str) -> Material:
    async with async_session_factory() as session:
        material = Material(
            author_id=author_id,
            type="listening",
            title=title,
            visibility=visibility,
        )
        session.add(material)
        await session.commit()
        await session.refresh(material)
        return material


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def _publish(material_id: uuid.UUID) -> None:
    """Authoring writes re-check the publishing rules and would demote a
    half-built fixture, so the flag is set after the seeding."""
    async with async_session_factory() as session:
        material = await session.get(Material, material_id)
        assert material is not None
        material.visibility = "public"
        session.add(material)
        await session.commit()


async def _seed(
    client: httpx.AsyncClient, token: str, material_id: uuid.UUID
) -> list[dict]:
    """Two parts. Three gaps, then a "choose TWO" — four rows, five numbers."""
    parts = []
    for index in range(2):
        r = await client.post(
            f"/api/materials/{material_id}/parts",
            json={"order_index": index, "title": f"Part {index + 1}"},
            cookies={"access_token": token},
        )
        assert r.status_code == 201, r.text
        parts.append(r.json()["id"])

    r_form = await client.post(
        f"/api/parts/{parts[0]}/question-groups",
        json={
            "type": "form_completion",
            "instructions": "Complete the form.",
            "config": {"template": "a {{1}}\nb {{2}}\nc {{3}}"},
            "questions": [
                {"number": n, "correct_answers": [f"x{n}"]} for n in (1, 2, 3)
            ],
        },
        cookies={"access_token": token},
    )
    assert r_form.status_code == 201, r_form.text

    r_choice = await client.post(
        f"/api/parts/{parts[1]}/question-groups",
        json={
            "type": "multiple_choice",
            "instructions": "Choose TWO letters.",
            "config": {"answers_per_question": 2},
            "questions": [
                {
                    "number": 1,
                    "prompt": "Which two?",
                    "options": ["one", "two", "three"],
                    "correct_answers": ["a", "b"],
                }
            ],
        },
        cookies={"access_token": token},
    )
    assert r_choice.status_code == 201, r_choice.text
    return r_form.json()["questions"]


async def _cleanup(material_ids: list[uuid.UUID], *emails: str) -> None:
    async with async_session_factory() as session:
        for material_id in material_ids:
            attempts = (
                await session.exec(
                    select(Attempt).where(Attempt.material_id == material_id)
                )
            ).all()
            for attempt in attempts:
                for qa in (
                    await session.exec(
                        select(QuestionAttempt).where(
                            QuestionAttempt.attempt_id == attempt.id
                        )
                    )
                ).all():
                    await session.delete(qa)
            await session.flush()
            for attempt in attempts:
                await session.delete(attempt)
            await session.flush()

            for part in (
                await session.exec(
                    select(Part).where(Part.material_id == material_id)
                )
            ).all():
                groups = (
                    await session.exec(
                        select(QuestionGroup).where(QuestionGroup.part_id == part.id)
                    )
                ).all()
                for group in groups:
                    for question in (
                        await session.exec(
                            select(Question).where(Question.group_id == group.id)
                        )
                    ).all():
                        await session.delete(question)
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
            user = (
                await session.exec(select(User).where(User.email == email))
            ).first()
            if user is not None:
                await session.delete(user)
        await session.commit()


@pytest.mark.asyncio
async def test_the_catalogue_says_how_big_each_paper_is() -> None:
    email = "cat1@example.com"
    user = await _make_user(email)
    material = await _make_material(user.id, f"Catalogue {uuid.uuid4()}", "private")
    token = create_access_token(str(user.id))

    try:
        async with _client() as client:
            await _seed(client, token, material.id)
            await _publish(material.id)

            r = await client.get(
                "/api/listening/practice", cookies={"access_token": token}
            )
            assert r.status_code == 200, r.text
            row = next(x for x in r.json() if x["id"] == str(material.id))

            assert row["part_count"] == 2
            # Four rows, five numbers: the "choose TWO" takes two of them, and
            # the count has to be the one a score is out of.
            assert row["question_count"] == 5
            assert row["attempts"] == 0
            assert row["best_score"] is None
            assert row["last_attempt_id"] is None
    finally:
        await _cleanup([material.id], email)


@pytest.mark.asyncio
async def test_a_private_draft_is_not_offered_to_practise() -> None:
    """It belongs to its author and it isn't finished. Listing it put
    "untitled listening" in front of the person who came to practise, beside
    a button that opened a paper with no questions on it."""
    email = "cat2@example.com"
    user = await _make_user(email)
    draft = await _make_material(user.id, f"Draft {uuid.uuid4()}", "private")
    token = create_access_token(str(user.id))

    try:
        async with _client() as client:
            await _seed(client, token, draft.id)  # left private on purpose

            r = await client.get(
                "/api/listening/practice", cookies={"access_token": token}
            )
            assert r.status_code == 200, r.text
            # Not even to its own author.
            assert all(x["id"] != str(draft.id) for x in r.json())
    finally:
        await _cleanup([draft.id], email)


@pytest.mark.asyncio
async def test_the_history_in_a_row_is_the_callers_own() -> None:
    """Two people sit the same paper. Each sees their own score and no sign
    that the other was ever there."""
    mine, theirs = "cat3-mine@example.com", "cat3-theirs@example.com"
    author = await _make_user(mine)
    other = await _make_user(theirs)
    material = await _make_material(author.id, f"Shared {uuid.uuid4()}", "private")
    my_token = create_access_token(str(author.id))
    their_token = create_access_token(str(other.id))

    try:
        async with _client() as client:
            questions = await _seed(client, my_token, material.id)
            await _publish(material.id)

            # I sit it twice: once badly, once better. The catalogue keeps my
            # best, and points at my most recent.
            for answers in ([], [{"question_id": questions[0]["id"], "given_answer": "x1"}]):
                r = await client.post(
                    f"/api/materials/{material.id}/attempts",
                    json={"answers": answers},
                    cookies={"access_token": my_token},
                )
                assert r.status_code == 200, r.text
            last_id = r.json()["attempt_id"]

            # They sit it once, and get more right than I did.
            r_theirs = await client.post(
                f"/api/materials/{material.id}/attempts",
                json={
                    "answers": [
                        {"question_id": q["id"], "given_answer": f"x{i + 1}"}
                        for i, q in enumerate(questions)
                    ]
                },
                cookies={"access_token": their_token},
            )
            assert r_theirs.status_code == 200, r_theirs.text
            assert r_theirs.json()["score"] == 3

            r = await client.get(
                "/api/listening/practice", cookies={"access_token": my_token}
            )
            row = next(x for x in r.json() if x["id"] == str(material.id))
            assert row["attempts"] == 2
            # Mine, not the better score somebody else got.
            assert row["best_score"] == 1
            assert row["last_attempt_id"] == last_id
            assert row["last_attempt_at"] is not None

            r_other = await client.get(
                "/api/listening/practice", cookies={"access_token": their_token}
            )
            row_other = next(
                x for x in r_other.json() if x["id"] == str(material.id)
            )
            assert row_other["attempts"] == 1
            assert row_other["best_score"] == 3
    finally:
        await _cleanup([material.id], mine, theirs)

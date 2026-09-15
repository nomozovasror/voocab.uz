"""What the review screen is handed on top of the marked paper.

A score is a number and a review is a sentence, and the difference between
them is everything in this file. ``43%`` says nothing anybody can act on;
"your 2nd try, the first was 14%, the average here is 61%, and the two you
lost were spelling" is four things they can. All of it is assembled server-
side (:func:`app.services.grading.attempt_result`) rather than in the browser
— particularly the mistake kind, which the practice page's "Where you lose
marks" is counted from too. One classifier, so a review of one paper and a
pattern across many cannot name the same slip two different things.
"""

import uuid

import httpx
import pytest
from sqlmodel import select

from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.main import app
from app.models.attempt import Attempt
from app.models.collection import Collection, CollectionItem
from app.models.material import Material
from app.models.part import Part
from app.models.question import Question
from app.models.question_attempt import QuestionAttempt
from app.models.question_group import QuestionGroup
from app.models.user import User


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def _user(email: str) -> User:
    async with async_session_factory() as session:
        user = User(email=email, display_name="Review test")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _material(author_id: uuid.UUID, title: str) -> Material:
    async with async_session_factory() as session:
        material = Material(
            author_id=author_id, type="listening", title=title, visibility="public"
        )
        session.add(material)
        await session.commit()
        await session.refresh(material)
        return material


async def _publish(material_id: uuid.UUID) -> None:
    """Authoring writes re-check the publishing rules and would demote a
    half-built material, so the flag goes on after the seeding."""
    async with async_session_factory() as session:
        material = await session.get(Material, material_id)
        assert material is not None
        material.visibility = "public"
        session.add(material)
        await session.commit()


async def _seed(
    client: httpx.AsyncClient, token: str, material_id: uuid.UUID
) -> tuple[list[dict], list[dict]]:
    """Three gaps and one multiple-choice question.

    The gaps are what the classifier has anything to say about; the choice is
    there to prove it stays quiet about a letter.
    """
    r_part = await client.post(
        f"/api/materials/{material_id}/parts",
        json={"order_index": 0, "title": "Part 1"},
        cookies={"access_token": token},
    )
    assert r_part.status_code == 201, r_part.text
    part_id = r_part.json()["id"]

    r_gaps = await client.post(
        f"/api/parts/{part_id}/question-groups",
        json={
            "type": "form_completion",
            "instructions": "Complete the form.",
            "config": {"template": "a: {{1}}\nb: {{2}}\nc: {{3}}"},
            "questions": [
                {"number": 1, "correct_answers": ["accommodation"]},
                {"number": 2, "correct_answers": ["Preston"]},
                {"number": 3, "correct_answers": ["tickets"]},
            ],
        },
        cookies={"access_token": token},
    )
    assert r_gaps.status_code == 201, r_gaps.text

    r_choice = await client.post(
        f"/api/parts/{part_id}/question-groups",
        json={
            "type": "multiple_choice",
            "instructions": "Choose the correct letter.",
            "config": {"answers_per_question": 1},
            "questions": [
                {
                    "number": 1,
                    "prompt": "Which one?",
                    "options": ["first", "second", "third"],
                    "correct_answers": ["a"],
                    "option_replay": {},
                }
            ],
        },
        cookies={"access_token": token},
    )
    assert r_choice.status_code == 201, r_choice.text
    await _publish(material_id)
    return r_gaps.json()["questions"], r_choice.json()["questions"]


async def _cleanup(*material_ids: uuid.UUID, emails: tuple[str, ...] = ()) -> None:
    async with async_session_factory() as session:
        for material_id in material_ids:
            for item in (
                await session.exec(
                    select(CollectionItem).where(
                        CollectionItem.material_id == material_id
                    )
                )
            ).all():
                await session.delete(item)
            await session.flush()

            attempts = (
                await session.exec(
                    select(Attempt).where(Attempt.material_id == material_id)
                )
            ).all()
            for attempt in attempts:
                for row in (
                    await session.exec(
                        select(QuestionAttempt).where(
                            QuestionAttempt.attempt_id == attempt.id
                        )
                    )
                ).all():
                    await session.delete(row)
            await session.flush()
            for attempt in attempts:
                await session.delete(attempt)
            await session.flush()

            for part in (
                await session.exec(select(Part).where(Part.material_id == material_id))
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
                for collection in (
                    await session.exec(
                        select(Collection).where(Collection.author_id == user.id)
                    )
                ).all():
                    await session.delete(collection)
                await session.flush()
                await session.delete(user)
        await session.commit()


@pytest.mark.asyncio
async def test_every_wrong_answer_comes_back_with_what_kind_of_wrong_it_was() -> None:
    """The whole point of the screen: three wrong answers, three different
    evenings' work behind them.

    And a letter has no kind. There is no spelling in "b", and which
    distractor pulled somebody is a different analysis for a page with room
    for it — so multiple choice comes back with ``None`` rather than with
    "wrong answer", which would quietly inflate one bar of the breakdown.
    """
    email = f"review-kinds-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    token = create_access_token(str(user.id))
    material = await _material(user.id, f"Kinds {uuid.uuid4()}")

    try:
        async with _client() as client:
            gaps, choices = await _seed(client, token, material.id)

            r = await client.post(
                f"/api/materials/{material.id}/attempts",
                json={
                    "answers": [
                        # Heard it, wrote it badly.
                        {"question_id": gaps[0]["id"], "given_answer": "accomodation"},
                        # Never heard it at all.
                        {"question_id": gaps[1]["id"], "given_answer": ""},
                        # Right, so nothing to say.
                        {"question_id": gaps[2]["id"], "given_answer": "tickets"},
                        # Wrong, and answered by letter.
                        {"question_id": choices[0]["id"], "given_answer": "c"},
                    ]
                },
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text
            by_id = {row["question_id"]: row for row in r.json()["results"]}

            assert by_id[gaps[0]["id"]]["mistake"] == "spelling"
            assert by_id[gaps[1]["id"]]["mistake"] == "missed"
            assert by_id[gaps[2]["id"]]["is_correct"] is True
            assert by_id[gaps[2]["id"]]["mistake"] is None
            assert by_id[choices[0]["id"]]["is_correct"] is False
            assert by_id[choices[0]["id"]]["mistake"] is None
    finally:
        await _cleanup(material.id, emails=(email,))


@pytest.mark.asyncio
async def test_a_retake_is_told_apart_from_a_first_sitting() -> None:
    """``first_try_pct`` is what makes a retake readable as progress.

    Withheld on a first try rather than repeated: the same number under a
    second name is a panel padding itself out, and a reader who sees "first
    try was 33%" beside "33%" learns nothing and distrusts both.
    """
    email = f"review-retake-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    token = create_access_token(str(user.id))
    material = await _material(user.id, f"Retake {uuid.uuid4()}")

    try:
        async with _client() as client:
            gaps, choices = await _seed(client, token, material.id)

            def answers(*given: str) -> dict:
                ids = [q["id"] for q in gaps] + [choices[0]["id"]]
                return {
                    "answers": [
                        {"question_id": qid, "given_answer": value}
                        for qid, value in zip(ids, given)
                    ]
                }

            first = await client.post(
                f"/api/materials/{material.id}/attempts",
                json=answers("accomodation", "", "tickets", "c"),
                cookies={"access_token": token},
            )
            assert first.status_code == 200, first.text
            body = first.json()
            assert body["attempt_no"] == 1
            assert body["first_try_pct"] is None
            first_pct = round(body["score"] / body["total_questions"] * 100)

            second = await client.post(
                f"/api/materials/{material.id}/attempts",
                json=answers("accommodation", "Preston", "tickets", "a"),
                cookies={"access_token": token},
            )
            assert second.status_code == 200, second.text
            body = second.json()
            assert body["attempt_no"] == 2
            assert body["first_try_pct"] == first_pct
            assert body["score"] == body["total_questions"]

            # And the same both ways round: a page reached by refreshing the
            # URL is the same page as one reached by pressing submit.
            again = await client.get(
                f"/api/attempts/{body['attempt_id']}",
                cookies={"access_token": token},
            )
            assert again.status_code == 200
            assert again.json()["attempt_no"] == 2
            assert again.json()["first_try_pct"] == first_pct
    finally:
        await _cleanup(material.id, emails=(email,))


@pytest.mark.asyncio
async def test_a_paper_inside_a_course_points_at_the_next_lesson() -> None:
    """And "next" is the course's next, not the one after this.

    A learner who skipped lesson two is sent back to lesson two. The sequence
    is somebody's judgement about what to do when, and a review that offered
    lesson four to somebody who never sat two would be a collection behaving
    like a filter — see app/services/collections.py.
    """
    email = f"review-course-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    token = create_access_token(str(user.id))
    lessons = [
        await _material(user.id, f"Lesson {i} {uuid.uuid4()}") for i in range(3)
    ]

    try:
        async with _client() as client:
            gaps, choices = await _seed(client, token, lessons[1].id)

            r = await client.post(
                "/api/collections",
                json={"title": "A short course", "description": ""},
                cookies={"access_token": token},
            )
            assert r.status_code == 201, r.text
            collection_id = r.json()["id"]
            r = await client.put(
                f"/api/collections/{collection_id}/items",
                json={"material_ids": [str(m.id) for m in lessons]},
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text
            r = await client.patch(
                f"/api/collections/{collection_id}",
                json={"visibility": "public"},
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text

            # They sit the SECOND lesson, having never sat the first.
            r = await client.post(
                f"/api/materials/{lessons[1].id}/attempts",
                json={
                    "answers": [
                        {"question_id": q["id"], "given_answer": ""}
                        for q in gaps + choices
                    ]
                },
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text
            course = r.json()["course"]
            assert course is not None
            assert course["collection_title"] == "A short course"
            assert course["next_material_id"] == str(lessons[0].id)
            assert course["next_position"] == 1
            assert (course["done"], course["total"]) == (1, 3)
    finally:
        await _cleanup(*[m.id for m in lessons], emails=(email,))


@pytest.mark.asyncio
async def test_a_paper_in_no_course_says_so_rather_than_guessing() -> None:
    email = f"review-loose-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    token = create_access_token(str(user.id))
    material = await _material(user.id, f"Loose {uuid.uuid4()}")

    try:
        async with _client() as client:
            gaps, choices = await _seed(client, token, material.id)
            r = await client.post(
                f"/api/materials/{material.id}/attempts",
                json={
                    "answers": [
                        {"question_id": q["id"], "given_answer": ""}
                        for q in gaps + choices
                    ]
                },
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text
            assert r.json()["course"] is None
            # And no average until the paper has been answered enough times
            # for one to mean anything — a fabricated 25% from one sitting is
            # exactly what difficulty.MIN_ANSWERS exists to refuse.
            assert r.json()["material_avg_pct"] is None
    finally:
        await _cleanup(material.id, emails=(email,))


@pytest.mark.asyncio
async def test_a_paper_already_sat_offers_its_review_from_the_take_page() -> None:
    """The way back to a marked paper without sitting it again.

    Without this the only route to a review was through a fresh attempt —
    which writes a SECOND attempt, and every ability figure on the platform
    counts first attempts. Going back to analyse your mistakes would have
    quietly cost you the measurement of them.

    Most recent, not best or first: the question a page asks when somebody
    opens a material they have done is "what happened last time".
    """
    email = f"review-return-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    token = create_access_token(str(user.id))
    material = await _material(user.id, f"Return {uuid.uuid4()}")

    try:
        async with _client() as client:
            gaps, choices = await _seed(client, token, material.id)
            ids = [q["id"] for q in gaps] + [choices[0]["id"]]

            # Never sat: nothing to offer, and the page must not invent one.
            r = await client.get(
                f"/api/materials/{material.id}/take",
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text
            assert r.json()["last_attempt"] is None

            def sit(*given: str) -> dict:
                return {
                    "answers": [
                        {"question_id": qid, "given_answer": value}
                        for qid, value in zip(ids, given)
                    ]
                }

            await client.post(
                f"/api/materials/{material.id}/attempts",
                json=sit("", "", "", ""),
                cookies={"access_token": token},
            )
            second = await client.post(
                f"/api/materials/{material.id}/attempts",
                json=sit("accommodation", "Preston", "tickets", "a"),
                cookies={"access_token": token},
            )
            assert second.status_code == 200, second.text

            r = await client.get(
                f"/api/materials/{material.id}/take",
                cookies={"access_token": token},
            )
            last = r.json()["last_attempt"]
            assert last is not None
            # The SECOND sitting, not the first.
            assert last["attempt_id"] == second.json()["attempt_id"]
            assert last["score"] == last["total_questions"]

            # And the take payload still carries no answer key — the reason
            # only an id goes in it.
            assert "correct_answers" not in r.text
    finally:
        await _cleanup(material.id, emails=(email,))


@pytest.mark.asyncio
async def test_somebody_elses_sitting_is_not_offered() -> None:
    """The link is to a record of one person's mistakes. Another learner
    opening the same paper is opening it for the first time."""
    mine = f"review-mine-{uuid.uuid4().hex[:8]}@example.com"
    theirs = f"review-theirs-{uuid.uuid4().hex[:8]}@example.com"
    author = await _user(mine)
    other = await _user(theirs)
    token = create_access_token(str(author.id))
    other_token = create_access_token(str(other.id))
    material = await _material(author.id, f"Shared {uuid.uuid4()}")

    try:
        async with _client() as client:
            gaps, choices = await _seed(client, token, material.id)
            await client.post(
                f"/api/materials/{material.id}/attempts",
                json={
                    "answers": [
                        {"question_id": q["id"], "given_answer": ""}
                        for q in gaps + choices
                    ]
                },
                cookies={"access_token": token},
            )

            r = await client.get(
                f"/api/materials/{material.id}/take",
                cookies={"access_token": other_token},
            )
            assert r.status_code == 200, r.text
            assert r.json()["last_attempt"] is None
    finally:
        await _cleanup(material.id, emails=(mine, theirs))

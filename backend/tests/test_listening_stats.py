"""GET /api/listening/stats and the catalogue's measured difficulty.

Both read the same event table (``question_attempts``) and both are built
around one refusal: **not enough answers means no number**. A percentage over
three answers moves two bands when one candidate has a bad morning, so what
these tests pin down is mostly what the API declines to claim.

Attempt rows are written straight to the DB rather than through the submit
endpoint. Twenty answers is the interesting threshold and seven round trips
through grading to reach it would be testing grading, which has its own file.
"""

import uuid

import httpx
import pytest
from sqlmodel import select

from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.main import app
from app.models.attempt import Attempt, AttemptStatus
from app.models.material import Material
from app.models.part import Part
from app.models.question import Question
from app.models.question_attempt import QuestionAttempt
from app.models.question_group import QuestionGroup
from app.models.user import User
from app.services import difficulty as difficulty_service
from app.services.difficulty import MIN_ANSWERS


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def _make_user(email: str, display_name: str = "Stats test") -> User:
    async with async_session_factory() as session:
        user = (await session.exec(select(User).where(User.email == email))).first()
        if user is not None:
            return user
        user = User(email=email, display_name=display_name)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _make_material(author_id: uuid.UUID, title: str) -> Material:
    async with async_session_factory() as session:
        material = Material(
            author_id=author_id, type="listening", title=title, visibility="private"
        )
        session.add(material)
        await session.commit()
        await session.refresh(material)
        return material


async def _publish(material_id: uuid.UUID) -> None:
    """Authoring writes re-check the publishing rules and would demote a
    half-built fixture, so the flag is set after the seeding."""
    async with async_session_factory() as session:
        material = await session.get(Material, material_id)
        assert material is not None
        material.visibility = "public"
        session.add(material)
        await session.commit()


async def _seed_part(
    client: httpx.AsyncClient,
    token: str,
    material_id: uuid.UUID,
    order_index: int,
    group_type: str,
) -> list[dict]:
    """One part, at the index that makes it "Part N", holding one group of
    three gaps. Returns the questions so a test can answer them."""
    r = await client.post(
        f"/api/materials/{material_id}/parts",
        json={"order_index": order_index, "title": f"Part {order_index + 1}"},
        cookies={"access_token": token},
    )
    assert r.status_code == 201, r.text
    part_id = r.json()["id"]

    # A completion group is a template plus its gaps; a multiple-choice group
    # is a list of self-contained questions answered by letter. Two shapes,
    # not one with half its fields optional — see app/schemas/listening.py.
    if group_type == "multiple_choice":
        body = {
            "type": group_type,
            "instructions": "Choose ONE letter.",
            "config": {"answers_per_question": 1},
            "questions": [
                {
                    "number": n,
                    "prompt": f"Question {n}?",
                    "options": ["one", "two", "three"],
                    "correct_answers": ["a"],
                }
                for n in (1, 2, 3)
            ],
        }
    else:
        body = {
            "type": group_type,
            "instructions": "Complete it.",
            "config": {"template": "a {{1}}\nb {{2}}\nc {{3}}"},
            "questions": [
                {"number": n, "correct_answers": [f"x{n}"]} for n in (1, 2, 3)
            ],
        }

    r_group = await client.post(
        f"/api/parts/{part_id}/question-groups",
        json=body,
        cookies={"access_token": token},
    )
    assert r_group.status_code == 201, r_group.text
    return r_group.json()["questions"]


async def _answer(
    user_id: uuid.UUID,
    material_id: uuid.UUID,
    question_ids: list[str],
    *,
    answers: int,
    correct: int,
) -> None:
    """``answers`` graded answers against those questions, ``correct`` of them
    right — spread over the questions round-robin, all under one submitted
    attempt."""
    async with async_session_factory() as session:
        attempt = Attempt(
            user_id=user_id,
            material_id=material_id,
            status=AttemptStatus.SUBMITTED,
            score=correct,
            total_questions=answers,
        )
        from datetime import datetime, timezone

        attempt.submitted_at = datetime.now(timezone.utc)
        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)

        for i in range(answers):
            session.add(
                QuestionAttempt(
                    attempt_id=attempt.id,
                    question_id=uuid.UUID(question_ids[i % len(question_ids)]),
                    given_answer="whatever",
                    is_correct=i < correct,
                )
            )
        await session.commit()


async def _recompute() -> None:
    """What the worker does on its timer, done here on demand.

    The catalogue reads difficulty out of a projection rather than
    aggregating on the spot, so a test that answers questions and then asks
    the API what it thinks is asking about a table nothing has written yet.
    That the call is needed at all IS the contract these tests are pinning
    down: a band is as fresh as the last refresh.
    """
    async with async_session_factory() as session:
        await difficulty_service.recompute(session)


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
            user = (await session.exec(select(User).where(User.email == email))).first()
            if user is not None:
                await session.delete(user)
        await session.commit()


# --- The catalogue row ------------------------------------------------------


@pytest.mark.asyncio
async def test_a_row_says_which_parts_it_holds_and_who_wrote_it() -> None:
    """Which parts, not how many. A material seeded at index 2 is Part 3 even
    though it is the only part there is, and "1 part" could never say that."""
    email = "stats-row@example.com"
    user = await _make_user(email, display_name="Nodira")
    material = await _make_material(user.id, f"Row {uuid.uuid4()}")
    token = create_access_token(str(user.id))

    try:
        async with _client() as client:
            await _seed_part(client, token, material.id, 2, "multiple_choice")
            await _publish(material.id)

            r = await client.get(
                "/api/listening/practice",
                # Nothing has been sat here, so the default list is the one
                # that holds it: `done=true` asks for the finished ones and
                # this material is not one of them.
                params={"limit": 100},
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text
            row = next(x for x in r.json()["items"] if x["id"] == str(material.id))

            assert row["part_numbers"] == [3]
            assert row["part_count"] == 1
            assert row["question_types"] == ["multiple_choice"]
            assert row["author"]["display_name"] == "Nodira"
            assert "email" not in row["author"]
    finally:
        await _cleanup([material.id], email)


@pytest.mark.asyncio
async def test_difficulty_stays_new_until_there_is_enough_evidence() -> None:
    """One answer is not a difficulty. The band only appears once the
    threshold is cleared, and never a percentage before it."""
    email = "stats-diff@example.com"
    user = await _make_user(email)
    material = await _make_material(user.id, f"Difficulty {uuid.uuid4()}")
    token = create_access_token(str(user.id))

    try:
        async with _client() as client:
            questions = await _seed_part(client, token, material.id, 0, "form_completion")
            await _publish(material.id)
            ids = [q["id"] for q in questions]

            await _answer(
                user.id, material.id, ids, answers=MIN_ANSWERS - 1, correct=0
            )
            await _recompute()
            r = await client.get(
                "/api/listening/practice",
                params={"done": "true", "limit": 100},
                cookies={"access_token": token},
            )
            row = next(x for x in r.json()["items"] if x["id"] == str(material.id))
            # Nineteen answers, every one of them wrong, and the API still
            # refuses to call it hard.
            assert row["difficulty"]["band"] == "new"
            assert row["difficulty"]["correct_pct"] is None
            assert row["difficulty"]["answered"] == MIN_ANSWERS - 1

            # One more crosses the line.
            await _answer(user.id, material.id, ids, answers=1, correct=0)
            await _recompute()
            r = await client.get(
                "/api/listening/practice",
                params={"done": "true", "limit": 100},
                cookies={"access_token": token},
            )
            row = next(x for x in r.json()["items"] if x["id"] == str(material.id))
            assert row["difficulty"]["band"] == "hard"
            assert row["difficulty"]["correct_pct"] == 0
            assert row["difficulty"]["answered"] == MIN_ANSWERS
    finally:
        await _cleanup([material.id], email)


@pytest.mark.asyncio
async def test_difficulty_is_everybody_s_answers_not_the_readers() -> None:
    """A paper doesn't get easier because you personally did well on it."""
    mine, theirs = "stats-pop-mine@example.com", "stats-pop-theirs@example.com"
    author = await _make_user(mine)
    other = await _make_user(theirs)
    material = await _make_material(author.id, f"Population {uuid.uuid4()}")
    my_token = create_access_token(str(author.id))

    try:
        async with _client() as client:
            questions = await _seed_part(client, token=my_token, material_id=material.id, order_index=0, group_type="form_completion")
            await _publish(material.id)
            ids = [q["id"] for q in questions]

            # I get everything right; they get everything wrong. Between us
            # the paper is a coin toss, and that is what the band reads.
            await _answer(author.id, material.id, ids, answers=15, correct=15)
            await _answer(other.id, material.id, ids, answers=15, correct=0)
            await _recompute()

            r = await client.get(
                "/api/listening/practice",
                params={"done": "true", "limit": 100},
                cookies={"access_token": my_token},
            )
            row = next(x for x in r.json()["items"] if x["id"] == str(material.id))
            assert row["difficulty"]["answered"] == 30
            assert row["difficulty"]["correct_pct"] == 50
            assert row["difficulty"]["band"] == "medium"
            # My own perfect history sits in its own columns of the same row
            # and does not touch the band: how hard the paper is and how I
            # did on it are two different facts.
            assert row["attempts"] == 1
            assert row["best_score"] == 15
    finally:
        await _cleanup([material.id], mine, theirs)


# --- The statistics panel ---------------------------------------------------


@pytest.mark.asyncio
async def test_a_thin_part_gets_a_dash_rather_than_a_percentage() -> None:
    """Ten answers in Part 1 is not evidence of anything. The row reports how
    much has been done and declines to score it — and with nothing scored,
    there is no weakest part to send anyone to."""
    email = "stats-thin@example.com"
    user = await _make_user(email)
    material = await _make_material(user.id, f"Thin {uuid.uuid4()}")
    token = create_access_token(str(user.id))

    try:
        async with _client() as client:
            questions = await _seed_part(client, token, material.id, 0, "form_completion")
            await _publish(material.id)
            await _answer(
                user.id, material.id, [q["id"] for q in questions], answers=10, correct=5
            )

            r = await client.get(
                "/api/listening/stats", cookies={"access_token": token}
            )
            assert r.status_code == 200, r.text
            stats = r.json()

            part1 = next(row for row in stats["by_part"] if row["part"] == 1)
            assert part1["answered"] == 10
            assert part1["accuracy_pct"] is None
            # Ten answers is not a pattern either: the breakdown is withheld
            # rather than drawn from five mistakes.
            assert stats["mistakes"] is None
            # And one attempt is not a trend.
            assert stats["trend"] is None
            # All four parts are always listed; a missing one would read as a
            # hole rather than as "not started".
            assert [row["part"] for row in stats["by_part"]] == [1, 2, 3, 4]
            assert stats["materials_done"] == 1

            # And a reading paper has THREE. The count used to be a constant
            # of four for both, so the reading page reported a fourth passage
            # that no reading paper has, sitting at the bottom of every
            # distribution with nothing in it for ever.
            reading = await client.get(
                "/api/reading/stats", cookies={"access_token": token}
            )
            assert reading.status_code == 200, reading.text
            assert [
                row["part"] for row in reading.json()["by_part"]
            ] == [1, 2, 3]
    finally:
        await _cleanup([material.id], email)


@pytest.mark.asyncio
async def test_a_part_is_scored_once_there_is_enough_of_it() -> None:
    """And the answers counted are the ones from a FIRST sitting.

    Two materials rather than two attempts at one, and that is the point being
    pinned: a second run at the same paper is answering questions you have
    already seen, so it stays out of every figure that claims to describe
    ability.
    """
    email = "stats-parts@example.com"
    user = await _make_user(email)
    one = await _make_material(user.id, f"Part one {uuid.uuid4()}")
    three = await _make_material(user.id, f"Part three {uuid.uuid4()}")
    token = create_access_token(str(user.id))

    try:
        async with _client() as client:
            p1 = await _seed_part(client, token, one.id, 0, "form_completion")
            p3 = await _seed_part(client, token, three.id, 2, "multiple_choice")
            await _publish(one.id)
            await _publish(three.id)

            ids1 = [q["id"] for q in p1]
            ids3 = [q["id"] for q in p3]
            await _answer(user.id, one.id, ids1, answers=20, correct=18)  # 90%
            await _answer(user.id, three.id, ids3, answers=20, correct=11)  # 55%
            # A second run at Part 1, and a perfect one. It moves the best-of
            # average and nothing else.
            await _answer(user.id, one.id, ids1, answers=20, correct=20)

            r = await client.get(
                "/api/listening/stats", cookies={"access_token": token}
            )
            stats = r.json()

            by_part = {row["part"]: row for row in stats["by_part"]}
            assert by_part[1]["accuracy_pct"] == 90  # not 95, which is the mean
            assert by_part[3]["accuracy_pct"] == 55
            # Never sat, so left unscored rather than called this learner's
            # weakest area on the strength of nothing.
            assert by_part[2]["accuracy_pct"] is None

            # (90 + 55) / 2 on first sittings; (100 + 55) / 2 at their best.
            assert stats["first_try_avg_pct"] == 73
            assert stats["best_avg_pct"] == 78
            assert stats["materials_done"] == 2

            # The last thing sat was the retry, and the panel says which try
            # it was rather than letting 100% stand as a first impression.
            assert stats["resume"]["title"] == one.title
            assert stats["resume"]["attempt_number"] == 2
            assert stats["resume"]["score_pct"] == 100
    finally:
        await _cleanup([one.id, three.id], email)


@pytest.mark.asyncio
async def test_the_statistics_are_the_callers_own() -> None:
    """A record of what somebody keeps getting wrong belongs to them."""
    mine, theirs = "stats-mine@example.com", "stats-theirs@example.com"
    me = await _make_user(mine)
    them = await _make_user(theirs)
    material = await _make_material(me.id, f"Private history {uuid.uuid4()}")
    my_token = create_access_token(str(me.id))
    their_token = create_access_token(str(them.id))

    try:
        async with _client() as client:
            questions = await _seed_part(client, my_token, material.id, 0, "form_completion")
            await _publish(material.id)
            await _answer(
                me.id, material.id, [q["id"] for q in questions], answers=20, correct=4
            )

            r_theirs = await client.get(
                "/api/listening/stats", cookies={"access_token": their_token}
            )
            stats = r_theirs.json()
            assert stats["materials_done"] == 0
            assert all(row["answered"] == 0 for row in stats["by_part"])
            assert stats["resume"] is None
            assert stats["mistakes"] is None
            assert stats["trend"] is None
            assert stats["first_try_avg_pct"] is None

            r_mine = await client.get(
                "/api/listening/stats", cookies={"access_token": my_token}
            )
            assert r_mine.json()["by_part"][0]["accuracy_pct"] == 20
    finally:
        await _cleanup([material.id], mine, theirs)

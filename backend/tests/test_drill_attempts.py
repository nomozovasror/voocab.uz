"""Drills: one question group worked on its own, and what it must not disturb.

A drill exists because a map group is never alone in a material — all 23 in
the corpus sit beside another task — so "practise only maps" has to cut a
group out of a paper rather than find a better paper.

Cutting it out is the easy half. The hard half is that the platform is full of
readers that mean "has this learner sat this material" and ask it by comparing
``Attempt.status == 'submitted'``: the catalogue's ``done`` clause, the
recommender, every collection's progress bar, every ability figure, the
author's studio counts. Twenty of them, across five services. A drill is none
of those things — somebody who worked the map out of Part 2 has not sat Part 2
— and counting it as one would mark the paper done, withdraw it from
recommendation, and become the FIRST attempt every ability figure is measured
from. Silently, because nothing about the row would be malformed.

That is why a drill is its own ``AttemptStatus`` rather than a flag beside
``SUBMITTED``: every one of the twenty compares for equality, so a third value
excludes drills from all of them at once. The census below is what keeps that
true — it does not check twenty things individually, it photographs every
reader before and after a drill and demands the picture be identical.
"""

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlmodel import select

from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.main import app
from app.models.attempt import Attempt, AttemptStatus
from app.models.collection import Collection, CollectionItem
from app.models.material import Material
from app.models.part import Part
from app.models.question_group import QuestionGroup
from app.models.user import User


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


def _fresh() -> str:
    """An email nobody has used before.

    The helper above deliberately reuses a user by email, which suits the
    tests that check one figure. The carry-on tests read the whole ladder —
    every attempt this learner has ever made decides which rung answers — so
    a user left over from the last run answers a different question than the
    one being asked.
    """
    return f"drill-{uuid.uuid4().hex[:12]}@example.com"


async def _user(email: str) -> User:
    async with async_session_factory() as session:
        user = (await session.exec(select(User).where(User.email == email))).first()
        if user is not None:
            return user
        user = User(email=email, display_name=f"Drill test {email}")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _publish(material_id: uuid.UUID) -> None:
    async with async_session_factory() as session:
        material = await session.get(Material, material_id)
        assert material is not None
        material.visibility = "public"
        session.add(material)
        await session.commit()


async def _paper(client: httpx.AsyncClient, token: str, title: str) -> dict:
    """One Part 2: four multiple-choice numbers, then a six-gap map.

    Shaped like the real thing on purpose — a map group is what a drill is
    for, and it is never the only group in its part. Replay marks on every
    question, because a group whose questions are not all marked is not
    drillable at all.
    """
    r = await client.post(
        "/api/materials",
        json={"type": "listening", "title": title},
        cookies={"access_token": token},
    )
    assert r.status_code == 201, r.text
    material_id = r.json()["id"]

    r = await client.post(
        f"/api/materials/{material_id}/parts",
        json={"order_index": 0, "title": "Part 2"},
        cookies={"access_token": token},
    )
    assert r.status_code == 201, r.text
    part_id = r.json()["id"]

    r = await client.post(
        f"/api/parts/{part_id}/question-groups",
        json={
            "type": "multiple_choice",
            "instructions": "Choose the correct letter.",
            "questions": [
                {
                    "number": n,
                    "prompt": f"Question {n}?",
                    "options": ["one", "two", "three"],
                    "correct_answers": ["a"],
                    "replay_start_ms": 10_000 + n * 10_000,
                    "replay_end_ms": 15_000 + n * 10_000,
                }
                for n in (1, 2, 3, 4)
            ],
        },
        cookies={"access_token": token},
    )
    assert r.status_code == 201, r.text
    choice_id = r.json()["id"]

    r = await client.post(
        f"/api/parts/{part_id}/question-groups",
        json={
            "type": "map_labelling",
            "instructions": "Label the map below.",
            "config": {"template": "\n".join(f"place {n} | {{{{{n}}}}}" for n in range(1, 7))},
            "questions": [
                {
                    "number": n,
                    "correct_answers": [f"spot{n}"],
                    "replay_start_ms": 200_000 + n * 10_000,
                    "replay_end_ms": 205_000 + n * 10_000,
                }
                for n in range(1, 7)
            ],
        },
        cookies={"access_token": token},
    )
    assert r.status_code == 201, r.text
    map_id = r.json()["id"]

    # The part's numbering, as the printed paper has it: Part 2 is Questions
    # 11-20, so the map that follows four multiple-choice numbers is 15-20.
    async with async_session_factory() as session:
        part = await session.get(Part, uuid.UUID(part_id))
        assert part is not None
        part.first_number = 11
        session.add(part)
        await session.commit()

    await _publish(uuid.UUID(material_id))
    return {
        "material_id": material_id,
        "part_id": part_id,
        "choice_id": choice_id,
        "map_id": map_id,
    }


async def _census(client: httpx.AsyncClient, token: str, material_id: str) -> dict:
    """Every reader that means "a whole sitting", photographed at once.

    A dict rather than a list of assertions: what has to hold is that a drill
    moves NOTHING here, and comparing the whole picture catches the reader
    nobody thought to list — including the one added next year.
    """
    cookies = {"access_token": token}
    picture: dict = {}

    # Two calls, because they answer different questions. The default list
    # puts sat materials away, so it is where "is this paper still on offer"
    # lives; ``done=true`` is the only view in which a sat row can be read at
    # all, and the row's own history is half of what a drill must not touch.
    r = await client.get(
        "/api/listening/practice",
        params={"limit": 100, "q": "Drill census"},
        cookies=cookies,
    )
    assert r.status_code == 200, r.text
    picture["done_hidden"] = r.json()["done_hidden"]
    picture["on_offer"] = [item["id"] for item in r.json()["items"]]

    r = await client.get(
        "/api/listening/practice",
        params={"limit": 100, "q": "Drill census", "done": "true"},
        cookies=cookies,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    picture["row"] = next(
        (
            {
                k: v
                for k, v in item.items()
                if k
                in (
                    "attempts",
                    "best_score",
                    "first_score",
                    "last_attempt_id",
                    "difficulty",
                )
            }
            for item in body["items"]
            if item["id"] == material_id
        ),
        None,
    )

    r = await client.get("/api/listening/stats", cookies=cookies)
    assert r.status_code == 200, r.text
    picture["stats"] = r.json()

    r = await client.get("/api/collections", params={"limit": 50}, cookies=cookies)
    assert r.status_code == 200, r.text
    picture["collections"] = r.json()["items"]

    r = await client.get(f"/api/materials/{material_id}/take", cookies=cookies)
    assert r.status_code == 200, r.text
    picture["last_attempt"] = r.json()["last_attempt"]

    return picture


@pytest.mark.asyncio
async def test_a_drill_is_invisible_to_every_reader_of_a_sitting():
    author = await _user("drill-author@example.com")
    learner = await _user("drill-learner@example.com")
    author_token = create_access_token(str(author.id))
    token = create_access_token(str(learner.id))

    async with _client() as client:
        ids = await _paper(client, author_token, "Drill census — Test 1, Part 2")

        # A course holding it, so the collection readers have something to say.
        async with async_session_factory() as session:
            collection = Collection(
                author_id=author.id, title="Drill census course", visibility="public"
            )
            session.add(collection)
            await session.commit()
            await session.refresh(collection)
            session.add(
                CollectionItem(
                    collection_id=collection.id,
                    material_id=uuid.UUID(ids["material_id"]),
                    order_index=0,
                )
            )
            await session.commit()

        before = await _census(client, token, ids["material_id"])

        # --- the drill -------------------------------------------------------
        r = await client.get(
            f"/api/listening/drills/{ids['map_id']}", cookies={"access_token": token}
        )
        assert r.status_code == 200, r.text
        drill = r.json()
        questions = drill["parts"][0]["question_groups"][0]["questions"]
        r = await client.post(
            f"/api/listening/drills/{ids['map_id']}/attempts",
            json={
                "answers": [
                    {"question_id": q["id"], "given_answer": f"spot{q['number']}"}
                    for q in questions
                ]
            },
            cookies={"access_token": token},
        )
        assert r.status_code == 200, r.text
        result = r.json()
        assert result["score"] == 6
        assert result["total_questions"] == 6, "a drill is marked out of its own group"

        after = await _census(client, token, ids["material_id"])
        assert after == before, (
            "a drill moved a figure that measures a whole sitting"
        )

        # --- and a real sitting still moves them ----------------------------
        # Without this the census would pass just as happily against a fixture
        # where no reader was ever wired to an attempt at all.
        r = await client.get(
            f"/api/materials/{ids['material_id']}/take", cookies={"access_token": token}
        )
        assert r.status_code == 200, r.text
        every = [
            q
            for part in r.json()["parts"]
            for group in part["question_groups"]
            for q in group["questions"]
        ]
        r = await client.post(
            f"/api/materials/{ids['material_id']}/attempts",
            json={
                "answers": [
                    {"question_id": q["id"], "given_answer": ""} for q in every
                ]
            },
            cookies={"access_token": token},
        )
        assert r.status_code == 200, r.text

        sat = await _census(client, token, ids["material_id"])
        assert sat != before, "a real sitting must be visible where a drill is not"
        assert sat["last_attempt"] is not None
        assert sat["row"]["attempts"] == 1


@pytest.mark.asyncio
async def test_a_drill_reads_the_numbers_the_paper_prints():
    """The map after four multiple-choice numbers in a Part 2 is Questions
    15-20 — on the page and in the recording, which says them aloud."""
    author = await _user("drill-author@example.com")
    learner = await _user("drill-numbering@example.com")
    author_token = create_access_token(str(author.id))
    token = create_access_token(str(learner.id))

    async with _client() as client:
        ids = await _paper(client, author_token, "Drill numbering — Test 1, Part 2")

        r = await client.get(
            f"/api/listening/drills/{ids['map_id']}", cookies={"access_token": token}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["parts"][0]["first_number"] == 15
        assert body["drill"]["first_number"] == 15
        assert body["drill"]["last_number"] == 20
        assert body["drill"]["part_number"] == 2

        # And the review agrees, because it walks the whole paper and skips
        # what is out of scope rather than starting a second count.
        questions = body["parts"][0]["question_groups"][0]["questions"]
        r = await client.post(
            f"/api/listening/drills/{ids['map_id']}/attempts",
            json={
                "answers": [
                    {"question_id": q["id"], "given_answer": ""} for q in questions
                ]
            },
            cookies={"access_token": token},
        )
        assert r.status_code == 200, r.text
        assert [row["number"] for row in r.json()["results"]] == [15, 16, 17, 18, 19, 20]


@pytest.mark.asyncio
async def test_the_take_tree_of_a_drill_carries_no_answers():
    """The same guarantee ``/take`` carries, for the same reason."""
    author = await _user("drill-author@example.com")
    learner = await _user("drill-leak@example.com")
    author_token = create_access_token(str(author.id))
    token = create_access_token(str(learner.id))

    async with _client() as client:
        ids = await _paper(client, author_token, "Drill leak — Test 1, Part 2")
        r = await client.get(
            f"/api/listening/drills/{ids['map_id']}", cookies={"access_token": token}
        )
        assert r.status_code == 200, r.text
        raw = r.text
        assert "correct_answers" not in raw
        assert "spot1" not in raw
        # Where each individual answer is said stays out too — the clip is an
        # envelope around all of them, which is what the printed paper's
        # "Questions 15-20" already says.
        assert "replay_start_ms" not in raw


@pytest.mark.asyncio
async def test_the_clip_opens_before_the_first_answer_and_closes_after_the_last():
    author = await _user("drill-author@example.com")
    learner = await _user("drill-clip@example.com")
    author_token = create_access_token(str(author.id))
    token = create_access_token(str(learner.id))

    async with _client() as client:
        ids = await _paper(client, author_token, "Drill clip — Test 1, Part 2")
        r = await client.get(
            f"/api/listening/drills/{ids['map_id']}", cookies={"access_token": token}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # The map's answers run 210s-265s; the multiple choice before it ends
        # at 55s. The lead-in lives in that gap, and the cap takes the last 45
        # seconds of it rather than the whole thing.
        assert body["clip_start_ms"] == 210_000 - 45_000
        assert body["clip_end_ms"] == 265_000 + 5_000

        # The group that OPENS the part has nothing before it to run into, so
        # the cap never binds and the clip starts at the top of the file — its
        # first answer is only 20s in, and those 20s are its own lead-in.
        r = await client.get(
            f"/api/listening/drills/{ids['choice_id']}",
            cookies={"access_token": token},
        )
        assert r.status_code == 200, r.text
        assert r.json()["clip_start_ms"] == 0


@pytest.mark.asyncio
async def test_deleting_a_drilled_group_does_not_500():
    """``attempts.group_id`` is a plain FK, so a drilled group could not be
    deleted — and the editor autosaves the whole group, which is how the same
    failure one level down used to make every subsequent save fail."""
    author = await _user("drill-author@example.com")
    learner = await _user("drill-delete@example.com")
    author_token = create_access_token(str(author.id))
    token = create_access_token(str(learner.id))

    async with _client() as client:
        ids = await _paper(client, author_token, "Drill delete — Test 1, Part 2")
        r = await client.get(
            f"/api/listening/drills/{ids['map_id']}", cookies={"access_token": token}
        )
        questions = r.json()["parts"][0]["question_groups"][0]["questions"]
        r = await client.post(
            f"/api/listening/drills/{ids['map_id']}/attempts",
            json={
                "answers": [
                    {"question_id": q["id"], "given_answer": "x"} for q in questions
                ]
            },
            cookies={"access_token": token},
        )
        assert r.status_code == 200, r.text

        r = await client.delete(
            f"/api/question-groups/{ids['map_id']}",
            cookies={"access_token": author_token},
        )
        assert r.status_code in (200, 204), r.text

        async with async_session_factory() as session:
            left = (
                await session.exec(
                    select(Attempt).where(
                        Attempt.group_id == uuid.UUID(ids["map_id"])
                    )
                )
            ).all()
            assert left == []


async def _drill(client: httpx.AsyncClient, token: str, group_id: str) -> None:
    r = await client.get(
        f"/api/listening/drills/{group_id}", cookies={"access_token": token}
    )
    assert r.status_code == 200, r.text
    questions = r.json()["parts"][0]["question_groups"][0]["questions"]
    r = await client.post(
        f"/api/listening/drills/{group_id}/attempts",
        json={
            "answers": [
                {"question_id": q["id"], "given_answer": ""} for q in questions
            ]
        },
        cookies={"access_token": token},
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_carrying_on_with_a_kind_of_question_needs_two_and_recently():
    """"Carry on" is a report of what somebody was doing, so it has to be
    true on both counts: one exercise is not a habit, and a kind of question
    is not a commitment anybody enrolled in — a month later there is no plan
    to carry on with."""
    author = await _user("drill-author@example.com")
    learner = await _user(_fresh())
    author_token = create_access_token(str(author.id))
    token = create_access_token(str(learner.id))

    async with _client() as client:
        papers = [
            await _paper(client, author_token, f"Carry on {n} — Test {n}, Part 2")
            for n in range(1, 4)
        ]
        # The block is silent until three materials are done, and that gate is
        # checked before every branch — so the reader needs a history before
        # any of this is reachable at all.
        for paper in papers:
            r = await client.get(
                f"/api/materials/{paper['material_id']}/take",
                cookies={"access_token": token},
            )
            every = [
                q
                for part in r.json()["parts"]
                for group in part["question_groups"]
                for q in group["questions"]
            ]
            r = await client.post(
                f"/api/materials/{paper['material_id']}/attempts",
                json={
                    "answers": [
                        {"question_id": q["id"], "given_answer": ""} for q in every
                    ]
                },
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text

        async def reason() -> dict:
            r = await client.get(
                "/api/listening/next", cookies={"access_token": token}
            )
            assert r.status_code == 200, r.text
            return r.json()

        # One is not a habit.
        await _drill(client, token, papers[0]["map_id"])
        assert (await reason())["reason"] != "task_type"

        # Two is.
        await _drill(client, token, papers[1]["map_id"])
        body = await reason()
        assert body["reason"] == "task_type"
        assert body["task_type"] == "map_labelling"
        assert body["done"] == 2
        assert body["next_group_id"] is not None
        # And it points at one they have NOT done.
        assert body["next_group_id"] not in {
            papers[0]["map_id"],
            papers[1]["map_id"],
        }

        # Stale work is not something to carry on with.
        async with async_session_factory() as session:
            for attempt in (
                await session.exec(
                    select(Attempt).where(
                        Attempt.user_id == learner.id,
                        Attempt.status == AttemptStatus.DRILLED,
                    )
                )
            ).all():
                attempt.submitted_at = datetime.now(timezone.utc) - timedelta(days=30)
                session.add(attempt)
            await session.commit()
        assert (await reason())["reason"] != "task_type"


@pytest.mark.asyncio
async def test_between_two_carry_ons_the_later_one_wins():
    """A course and a kind of question are both facts about what somebody was
    doing, and between two facts the honest one is the later.

    Not a fixed ladder, and it cannot be one: every material in a seeded
    library belongs to a book of sixteen to thirty-two, so one material sat
    leaves a course in progress for weeks. Ranked under that, a kind of
    question worked every day would never be offered at all.
    """
    author = await _user("drill-author@example.com")
    learner = await _user(_fresh())
    author_token = create_access_token(str(author.id))
    token = create_access_token(str(learner.id))

    async with _client() as client:
        # Five, so sitting the fourth leaves the course part-way through.
        # With four it completed, and `finished_course` is a third fact that
        # outranks both of these — said at the moment it is true, which is
        # right, and not what this test is about.
        papers = [
            await _paper(client, author_token, f"Rank {n} — Test {n}, Part 2")
            for n in range(1, 6)
        ]

        async with async_session_factory() as session:
            collection = Collection(
                author_id=author.id, title="Rank course", visibility="public"
            )
            session.add(collection)
            await session.commit()
            await session.refresh(collection)
            for index, paper in enumerate(papers):
                session.add(
                    CollectionItem(
                        collection_id=collection.id,
                        material_id=uuid.UUID(paper["material_id"]),
                        order_index=index,
                    )
                )
            await session.commit()

        # Three sat, which both opens the block and leaves the course
        # part-way through.
        for paper in papers[:3]:
            r = await client.get(
                f"/api/materials/{paper['material_id']}/take",
                cookies={"access_token": token},
            )
            every = [
                q
                for part in r.json()["parts"]
                for group in part["question_groups"]
                for q in group["questions"]
            ]
            await client.post(
                f"/api/materials/{paper['material_id']}/attempts",
                json={
                    "answers": [
                        {"question_id": q["id"], "given_answer": ""} for q in every
                    ]
                },
                cookies={"access_token": token},
            )

        await _drill(client, token, papers[0]["map_id"])
        await _drill(client, token, papers[1]["map_id"])

        async def reason() -> str:
            r = await client.get(
                "/api/listening/next", cookies={"access_token": token}
            )
            assert r.status_code == 200, r.text
            return r.json()["reason"]

        # The drills came last, so they are what to carry on with.
        assert await reason() == "task_type"

        # Sit another lesson and the course is the later fact again.
        r = await client.get(
            f"/api/materials/{papers[3]['material_id']}/take",
            cookies={"access_token": token},
        )
        every = [
            q
            for part in r.json()["parts"]
            for group in part["question_groups"]
            for q in group["questions"]
        ]
        await client.post(
            f"/api/materials/{papers[3]['material_id']}/attempts",
            json={
                "answers": [
                    {"question_id": q["id"], "given_answer": ""} for q in every
                ]
            },
            cookies={"access_token": token},
        )
        assert await reason() == "course"

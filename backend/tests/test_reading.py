"""Integration tests for reading papers, against a real DB and the ASGI app —
the same pattern as the listening files beside this one.

What is worth testing about reading is precisely what is NOT a copy of
listening, since almost everything else is literally the same code:

* a part carries a passage, and it reaches the candidate on ``/take``;
* the take payload still has no ``correct_answers`` anywhere in it, which is
  the one guarantee that must hold on every paper and not just the one it was
  written for;
* a true/false set is answered in WORDS, graded case-insensitively, and its
  three options are derived from its type rather than stored — so a group that
  somehow acquired an ``options`` list is still graded as words;
* matching headings letters its box in roman numerals, and an answer naming a
  numeral the box doesn't have is refused;
* publishing does not demand a recording of a paper that is read, and does
  demand the passage text;
* ``/api/reading/practice`` and ``/api/listening/practice`` are the same
  endpoint under two prefixes, and each shows only its own paper.
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
from app.services import publishing as publishing_service

PASSAGE = {
    "paragraphs": [
        {"label": "A", "text": "The beaver was hunted to extinction in Britain."},
        {"label": "B", "text": "Reintroduction began at Knapdale in 2009."},
        {"label": "C", "text": "Its dams slow the passage of rainfall off the hills."},
    ],
    "subtitle": None,
    "source": "Adapted from a magazine feature",
}

HEADINGS = ["What was lost", "How it came back", "What the dams do"]


async def _make_user(email: str) -> User:
    async with async_session_factory() as session:
        user = (await session.exec(select(User).where(User.email == email))).first()
        if user is not None:
            return user
        user = User(email=email, display_name=f"Reading test {email}")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _make_material(author_id: uuid.UUID, *, skill: str = "reading") -> Material:
    async with async_session_factory() as session:
        material = Material(
            author_id=author_id,
            type=skill,
            title=f"Reading fixture {uuid.uuid4()}",
            visibility="private",
        )
        session.add(material)
        await session.commit()
        await session.refresh(material)
        return material


async def _make_public(material_id: uuid.UUID) -> None:
    async with async_session_factory() as session:
        material = await session.get(Material, material_id)
        assert material is not None
        material.visibility = "public"
        session.add(material)
        await session.commit()


async def _cleanup(material_id: uuid.UUID, *emails: str) -> None:
    async with async_session_factory() as session:
        attempts = (
            await session.exec(select(Attempt).where(Attempt.material_id == material_id))
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


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def _passage_part(client, material_id, headers, *, passage=PASSAGE) -> dict:
    r = await client.post(
        f"/api/materials/{material_id}/parts",
        json={"order_index": 0, "title": "Reading Passage 1", "passage": passage},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_a_part_carries_its_passage_and_hands_it_to_the_candidate():
    email = f"reading-passage-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material = await _make_material(user.id)
    headers = {"Cookie": f"access_token={create_access_token(str(user.id))}"}
    try:
        async with _client() as client:
            part = await _passage_part(client, material.id, headers)
            assert [p["label"] for p in part["passage"]["paragraphs"]] == ["A", "B", "C"]
            assert part["passage"]["source"] == "Adapted from a magazine feature"

            r = await client.post(
                f"/api/parts/{part['id']}/question-groups",
                json={
                    "type": "true_false_not_given",
                    "instructions": "Write TRUE, FALSE or NOT GIVEN.",
                    "questions": [
                        {"number": 1, "correct_answers": ["TRUE"],
                         "prompt": "The beaver was hunted to extinction."},
                    ],
                },
                headers=headers,
            )
            assert r.status_code == 201, r.text

            await _make_public(material.id)
            r = await client.get(f"/api/materials/{material.id}/take", headers=headers)
            assert r.status_code == 200, r.text
            body = r.json()
            take_part = body["parts"][0]
            assert take_part["passage"]["paragraphs"][2]["text"].startswith("Its dams")
            # The candidate reads the passage and never the key, on this paper
            # as on any other.
            assert "correct_answers" not in r.text
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_a_true_false_set_is_answered_in_words_the_type_supplies():
    email = f"reading-tfng-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material = await _make_material(user.id)
    headers = {"Cookie": f"access_token={create_access_token(str(user.id))}"}
    try:
        async with _client() as client:
            part = await _passage_part(client, material.id, headers)
            r = await client.post(
                f"/api/parts/{part['id']}/question-groups",
                json={
                    "type": "true_false_not_given",
                    "instructions": "Write TRUE, FALSE or NOT GIVEN.",
                    "questions": [
                        {"number": 1, "correct_answers": ["TRUE"], "prompt": "One."},
                        {"number": 2, "correct_answers": ["NOT GIVEN"], "prompt": "Two."},
                    ],
                },
                headers=headers,
            )
            assert r.status_code == 201, r.text
            group = r.json()
            # The author sees the three words, because the editor has to draw
            # them...
            assert group["config"]["options"] == ["TRUE", "FALSE", "NOT GIVEN"]
            # ...and nothing was STORED, because they belong to the type. This
            # is the distinction the whole design rests on: a stored copy
            # could disagree with the one grading compares against, and a
            # group with options in its config is graded as letters.
            async with async_session_factory() as session:
                stored = (
                    await session.exec(
                        select(QuestionGroup).where(QuestionGroup.id == uuid.UUID(group["id"]))
                    )
                ).one()
                assert stored.config == {}

            await _make_public(material.id)
            take = (
                await client.get(f"/api/materials/{material.id}/take", headers=headers)
            ).json()
            take_group = take["parts"][0]["question_groups"][0]
            # ...and they reach the candidate all the same, on the group, the
            # way matching's box does.
            assert take_group["config"]["options"] == ["TRUE", "FALSE", "NOT GIVEN"]

            ids = [q["id"] for q in take_group["questions"]]
            r = await client.post(
                f"/api/materials/{material.id}/attempts",
                json={
                    "answers": [
                        # Typed in the candidate's own case, which is not the
                        # key's. normalize_answer is what makes these one
                        # answer rather than two.
                        {"question_id": ids[0], "given_answer": "true"},
                        {"question_id": ids[1], "given_answer": "not given"},
                    ]
                },
                headers=headers,
            )
            assert r.status_code == 200, r.text
            result = r.json()
            assert result["score"] == 2
            assert all(row["is_correct"] for row in result["results"])
            # Answered by picking, so it is not graded as a letter set...
            assert {row["answered_by"] for row in result["results"]} == {"words"}
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_matching_headings_is_lettered_in_roman_numerals():
    email = f"reading-headings-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material = await _make_material(user.id)
    headers = {"Cookie": f"access_token={create_access_token(str(user.id))}"}
    try:
        async with _client() as client:
            part = await _passage_part(client, material.id, headers)
            payload = {
                "type": "matching_headings",
                "instructions": "Choose the correct heading, i-iii.",
                "config": {"options": HEADINGS, "label_style": "roman"},
                "questions": [
                    {"number": 1, "correct_answers": ["ii"], "prompt": "Paragraph B"},
                    {"number": 2, "correct_answers": ["iii"], "prompt": "Paragraph C"},
                ],
            }
            r = await client.post(
                f"/api/parts/{part['id']}/question-groups", json=payload, headers=headers
            )
            assert r.status_code == 201, r.text
            assert r.json()["config"]["label_style"] == "roman"

            # A letter is not a numeral. The box has i, ii and iii; "b" names
            # nothing in it, and is refused for the same reason a matching
            # answer of "z" is.
            bad = {**payload, "questions": [
                {"number": 1, "correct_answers": ["b"], "prompt": "Paragraph B"}
            ]}
            r = await client.post(
                f"/api/parts/{part['id']}/question-groups", json=bad, headers=headers
            )
            assert r.status_code == 422, r.text

            await _make_public(material.id)
            take = (
                await client.get(f"/api/materials/{material.id}/take", headers=headers)
            ).json()
            ids = [q["id"] for q in take["parts"][0]["question_groups"][0]["questions"]]
            r = await client.post(
                f"/api/materials/{material.id}/attempts",
                json={
                    "answers": [
                        {"question_id": ids[0], "given_answer": "ii"},
                        {"question_id": ids[1], "given_answer": "i"},
                    ]
                },
                headers=headers,
            )
            assert r.status_code == 200, r.text
            result = r.json()
            assert result["score"] == 1
            assert {row["answered_by"] for row in result["results"]} == {"letters"}
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_publishing_asks_a_reading_paper_for_its_passage_not_a_recording():
    email = f"reading-publish-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material = await _make_material(user.id)
    headers = {"Cookie": f"access_token={create_access_token(str(user.id))}"}
    try:
        async with _client() as client:
            # A passage-less part with questions under it is not publishable...
            r = await client.post(
                f"/api/materials/{material.id}/parts",
                json={"order_index": 0, "title": "Reading Passage 1"},
                headers=headers,
            )
            assert r.status_code == 201, r.text
            part = r.json()
            await client.post(
                f"/api/parts/{part['id']}/question-groups",
                json={
                    "type": "true_false_not_given",
                    "instructions": "Write TRUE, FALSE or NOT GIVEN.",
                    "questions": [
                        {"number": 1, "correct_answers": ["TRUE"], "prompt": "One."}
                    ],
                },
                headers=headers,
            )

            async with async_session_factory() as session:
                fresh = await session.get(Material, material.id)
                blockers = await publishing_service.publish_blockers(session, fresh)
            # ...and what it is missing is the passage. Never the recording:
            # this check was unconditional once, and would have made every
            # reading paper unpublishable with nothing to attach.
            assert any("passage" in b for b in blockers), blockers
            assert not any("recording" in b for b in blockers), blockers

            r = await client.patch(
                f"/api/parts/{part['id']}",
                json={"passage": PASSAGE},
                headers=headers,
            )
            assert r.status_code == 200, r.text

            async with async_session_factory() as session:
                fresh = await session.get(Material, material.id)
                blockers = await publishing_service.publish_blockers(session, fresh)
            assert blockers == [], blockers
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_a_sidebar_counts_its_own_paper_and_not_the_other():
    """The bug reading found the moment it existed.

    Every ability figure comes off `_submitted`, which read EVERY finished
    attempt regardless of what the material was. With only dictation beside
    listening that stayed hidden — a dictation attempt has no
    `total_questions` and falls out of most of the sums by itself — and the
    first reading paper anybody sat put its title under "Your last result" on
    the listening page.
    """
    email = f"reading-sidebar-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    reading = await _make_material(user.id, skill="reading")
    headers = {"Cookie": f"access_token={create_access_token(str(user.id))}"}
    try:
        async with _client() as client:
            part = await _passage_part(client, reading.id, headers)
            r = await client.post(
                f"/api/parts/{part['id']}/question-groups",
                json={
                    "type": "true_false_not_given",
                    "instructions": "Write TRUE, FALSE or NOT GIVEN.",
                    "questions": [
                        {"number": 1, "correct_answers": ["TRUE"], "prompt": "One."}
                    ],
                },
                headers=headers,
            )
            assert r.status_code == 201, r.text
            await _make_public(reading.id)

            take = (
                await client.get(f"/api/materials/{reading.id}/take", headers=headers)
            ).json()
            qid = take["parts"][0]["question_groups"][0]["questions"][0]["id"]
            r = await client.post(
                f"/api/materials/{reading.id}/attempts",
                json={"answers": [{"question_id": qid, "given_answer": "TRUE"}]},
                headers=headers,
            )
            assert r.status_code == 200, r.text

            # The reading sidebar has it...
            r = await client.get("/api/reading/stats", headers=headers)
            assert r.status_code == 200, r.text
            assert r.json()["materials_done"] == 1
            # ...and the listening one has never heard of it.
            r = await client.get("/api/listening/stats", headers=headers)
            assert r.status_code == 200, r.text
            assert r.json()["materials_done"] == 0
            assert r.json()["resume"] is None
    finally:
        await _cleanup(reading.id, email)


@pytest.mark.asyncio
async def test_a_course_shelf_holds_one_paper_s_courses():
    """The second half of the same bug the sidebar had.

    A collection is one paper's by construction, and nothing filtered on it:
    the reading page offered a LISTENING course to carry on with, which is a
    recommendation the reader cannot act on without leaving the page that
    made it.
    """
    email = f"reading-courses-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    reading = await _make_material(user.id, skill="reading")
    listening = await _make_material(user.id, skill="listening")
    headers = {"Cookie": f"access_token={create_access_token(str(user.id))}"}
    made: list[uuid.UUID] = []
    try:
        await _make_public(reading.id)
        await _make_public(listening.id)
        async with _client() as client:
            async with async_session_factory() as session:
                for skill, material_id in (
                    ("reading", reading.id),
                    ("listening", listening.id),
                ):
                    collection = Collection(
                        author_id=user.id,
                        skill=skill,
                        title=f"{skill} course {uuid.uuid4()}",
                        visibility="public",
                    )
                    session.add(collection)
                    await session.flush()
                    session.add(
                        CollectionItem(
                            collection_id=collection.id,
                            material_id=material_id,
                            order_index=0,
                        )
                    )
                    made.append(collection.id)
                await session.commit()

            r = await client.get(
                "/api/collections", params={"skill": "reading"}, headers=headers
            )
            assert r.status_code == 200, r.text
            titles = {row["title"] for row in r.json()["items"]}
            assert any(t.startswith("reading course") for t in titles)
            assert not any(t.startswith("listening course") for t in titles)

            r = await client.get(
                "/api/collections", params={"skill": "listening"}, headers=headers
            )
            titles = {row["title"] for row in r.json()["items"]}
            assert any(t.startswith("listening course") for t in titles)
            assert not any(t.startswith("reading course") for t in titles)
    finally:
        async with async_session_factory() as session:
            for collection_id in made:
                for item in (
                    await session.exec(
                        select(CollectionItem).where(
                            CollectionItem.collection_id == collection_id
                        )
                    )
                ).all():
                    await session.delete(item)
                await session.flush()
                found = await session.get(Collection, collection_id)
                if found is not None:
                    await session.delete(found)
            await session.commit()
        await _cleanup(reading.id)
        await _cleanup(listening.id, email)


@pytest.mark.asyncio
async def test_each_paper_s_catalogue_shows_only_its_own():
    email = f"reading-catalogue-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    reading = await _make_material(user.id, skill="reading")
    listening = await _make_material(user.id, skill="listening")
    headers = {"Cookie": f"access_token={create_access_token(str(user.id))}"}
    try:
        await _make_public(reading.id)
        await _make_public(listening.id)
        async with _client() as client:
            r = await client.get("/api/reading/practice", headers=headers)
            assert r.status_code == 200, r.text
            titles = {row["title"] for row in r.json()["items"]}
            assert reading.title in titles
            assert listening.title not in titles

            r = await client.get("/api/listening/practice", headers=headers)
            assert r.status_code == 200, r.text
            titles = {row["title"] for row in r.json()["items"]}
            assert listening.title in titles
            assert reading.title not in titles
    finally:
        await _cleanup(reading.id)
        await _cleanup(listening.id, email)


@pytest.mark.asyncio
async def test_evidence_reaches_the_review_and_never_the_take():
    """Where in the passage the answer is: released with the marking, and
    withheld while the paper is open.

    The same bargain as a listening replay range, and the same reason —
    knowing where to look is most of the question. What has to hold beyond
    that is the part id: a reading paper can hold three passages, each
    lettering its paragraphs from A, so a span that said only "paragraph 1"
    would name three different paragraphs. It is stamped on by the serializer
    from the question's own group, because nothing the extraction writes
    knows that parts exist.
    """
    email = f"reading-evidence-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material = await _make_material(user.id)
    headers = {"Cookie": f"access_token={create_access_token(str(user.id))}"}
    try:
        async with _client() as client:
            part = await _passage_part(client, material.id, headers)
            r = await client.post(
                f"/api/parts/{part['id']}/question-groups",
                json={
                    "type": "true_false_not_given",
                    "instructions": "Write TRUE, FALSE or NOT GIVEN.",
                    "questions": [
                        {"number": 1, "correct_answers": ["TRUE"],
                         "prompt": "The beaver was hunted to extinction."},
                        {"number": 2, "correct_answers": ["NOT GIVEN"],
                         "prompt": "Knapdale is in the Highlands."},
                    ],
                },
                headers=headers,
            )
            assert r.status_code == 201, r.text
            group_id = uuid.UUID(r.json()["id"])

            # Placed the way the seed places it: a paragraph and two offsets
            # into that paragraph's plain text. Question 2 gets none, which
            # is what a NOT GIVEN the model would not invent a place for
            # looks like — and the review has to survive it.
            async with async_session_factory() as session:
                first = (await session.exec(
                    select(Question).where(Question.group_id == group_id,
                                           Question.number == 1))).one()
                first.evidence = [{"index": 0, "start": 4, "end": 10}]
                session.add(first)
                await session.commit()

            await _make_public(material.id)

            r = await client.get(f"/api/materials/{material.id}/take", headers=headers)
            assert r.status_code == 200, r.text
            # Not a word of it before the paper is answered.
            assert "evidence" not in r.text

            questions = r.json()["parts"][0]["question_groups"][0]["questions"]
            r = await client.post(
                f"/api/materials/{material.id}/attempts",
                json={"answers": [
                    {"question_id": questions[0]["id"], "given_answer": "FALSE"},
                    {"question_id": questions[1]["id"], "given_answer": "TRUE"},
                ]},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            results = {row["number"]: row for row in r.json()["results"]}

            assert results[1]["evidence"] == [
                {"part_id": part["id"], "paragraph_index": 0,
                 "start": 4, "end": 10}
            ]
            # An empty list rather than a missing key: a review that has to
            # check whether the field is there before reading it is a review
            # with two ways of saying "nothing".
            assert results[2]["evidence"] == []
    finally:
        await _cleanup(material.id, email)

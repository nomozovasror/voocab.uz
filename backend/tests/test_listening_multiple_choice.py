"""Integration tests for multiple-choice question groups — authoring,
consumption and grading — against a real DB, ASGI transport + minted cookie,
the same pattern as the other listening tests.

Three things are being pinned down here, and they are the three things that
would be expensive to get wrong:

* the write endpoint accepts an UNFINISHED question (that is what autosave
  sends all day) but refuses an INCOHERENT one;
* ``/take`` hands over the options and how many to pick, and nothing else;
* a "choose two" is graded as a set — exactly right or wrong, never half.
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
        user = User(email=email, display_name=f"MCQ test {email}")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _make_material(author_id: uuid.UUID) -> Material:
    async with async_session_factory() as session:
        material = Material(
            author_id=author_id,
            type="listening",
            title=f"MCQ fixture {uuid.uuid4()}",
            visibility="private",
        )
        session.add(material)
        await session.commit()
        await session.refresh(material)
        return material


async def _make_public(material_id: uuid.UUID) -> None:
    """Flip the flag directly — these tests are about choice questions, not
    about the publishing rules, which have their own tests."""
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


def _choice_group(questions: list[dict]) -> dict:
    return {
        "type": "multiple_choice",
        "instructions": "Choose the correct letter, A, B or C.",
        "config": {},
        "questions": questions,
    }


#: A finished pair: one single-answer question and one "choose two".
FINISHED_QUESTIONS = [
    {
        "number": 1,
        "prompt": "Why did the speaker move to Bristol?",
        "options": ["for a job", "to study", "for the weather"],
        "mode": "one",
        "correct_answers": ["b"],
    },
    {
        "number": 2,
        "prompt": "Which TWO facilities are free?",
        "options": ["the pool", "the gym", "the car park", "the sauna"],
        "mode": "multiple",
        "correct_answers": ["a", "c"],
    },
]


async def _seed_part(
    client: httpx.AsyncClient, token: str, material_id: uuid.UUID
) -> str:
    r_part = await client.post(
        f"/api/materials/{material_id}/parts",
        json={"order_index": 0, "title": "Part 1"},
        cookies={"access_token": token},
    )
    assert r_part.status_code == 201, r_part.text
    return r_part.json()["id"]


# --- Authoring ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_choice_group_is_stored_with_its_prompts_options_and_key() -> None:
    email = "mcq1-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, token, material.id)

            r = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_choice_group(FINISHED_QUESTIONS),
                cookies={"access_token": token},
            )
            assert r.status_code == 201, r.text
            body = r.json()
            assert body["type"] == "multiple_choice"
            # Nothing at group level: the prompt and options belong to each
            # question, so there is no shared resource to keep here.
            assert body["config"] == {}

            first, second = body["questions"]
            assert first["prompt"] == "Why did the speaker move to Bristol?"
            assert first["options"] == ["for a job", "to study", "for the weather"]
            assert first["mode"] == "one"
            assert first["correct_answers"] == ["b"]
            assert second["mode"] == "multiple"
            assert second["correct_answers"] == ["a", "c"]

            # The author's own view of the material carries all of it back,
            # which is what the editor reopens from.
            r_author = await client.get(
                f"/api/materials/{material.id}", cookies={"access_token": token}
            )
            assert r_author.status_code == 200, r_author.text
            group = r_author.json()["parts"][0]["question_groups"][0]
            assert [q["correct_answers"] for q in group["questions"]] == [
                ["b"],
                ["a", "c"],
            ]
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_an_unfinished_question_is_saved_and_an_incoherent_one_is_not() -> None:
    """Autosave runs while the author is still typing, so a question with no
    text, no options and no answer has to be storable. What is refused is a
    payload that contradicts itself."""
    email = "mcq2-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, token, material.id)

            blank = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_choice_group(
                    [
                        {
                            "number": 1,
                            "prompt": "",
                            "options": ["", "", ""],
                            "mode": "one",
                            "correct_answers": [],
                        }
                    ]
                ),
                cookies={"access_token": token},
            )
            assert blank.status_code == 201, blank.text
            group_id = blank.json()["id"]

            for questions, why in [
                (
                    [
                        {
                            "number": 1,
                            "options": ["a", "b"],
                            "correct_answers": ["c"],
                        }
                    ],
                    "an answer naming an option that doesn't exist",
                ),
                (
                    [
                        {
                            "number": 1,
                            "options": ["a", "b"],
                            "mode": "one",
                            "correct_answers": ["a", "b"],
                        }
                    ],
                    "two answers on a single-answer question",
                ),
                (
                    [
                        {
                            "number": 1,
                            "options": ["a", "b"],
                            "correct_answers": ["a", "a"],
                        }
                    ],
                    "the same option marked twice",
                ),
                (
                    [
                        {"number": 1, "options": ["a", "b"], "correct_answers": []},
                        {"number": 3, "options": ["a", "b"], "correct_answers": []},
                    ],
                    "a hole in the numbering",
                ),
            ]:
                r = await client.patch(
                    f"/api/question-groups/{group_id}",
                    json=_choice_group(questions),
                    cookies={"access_token": token},
                )
                assert r.status_code == 422, f"{why} should be refused: {r.text}"

            # And none of it landed: the group is still the blank one.
            r_after = await client.get(
                f"/api/materials/{material.id}", cookies={"access_token": token}
            )
            questions = r_after.json()["parts"][0]["question_groups"][0]["questions"]
            assert len(questions) == 1
            assert questions[0]["options"] == ["", "", ""]
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_groups_reorder_together_and_a_partial_order_is_refused() -> None:
    email = "mcq3-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, token, material.id)

            r_form = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json={
                    "type": "form_completion",
                    "instructions": "Complete the form below.",
                    "config": {"template": "Name: {{1}}"},
                    "questions": [{"number": 1, "correct_answers": ["Bristol"]}],
                },
                cookies={"access_token": token},
            )
            assert r_form.status_code == 201, r_form.text
            form_id = r_form.json()["id"]

            r_choice = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_choice_group(FINISHED_QUESTIONS),
                cookies={"access_token": token},
            )
            assert r_choice.status_code == 201, r_choice.text
            choice_id = r_choice.json()["id"]
            assert r_choice.json()["order_index"] == 1

            r_order = await client.put(
                f"/api/parts/{part_id}/question-groups/order",
                json={"group_ids": [choice_id, form_id]},
                cookies={"access_token": token},
            )
            assert r_order.status_code == 200, r_order.text
            assert [g["id"] for g in r_order.json()] == [choice_id, form_id]
            assert [g["order_index"] for g in r_order.json()] == [0, 1]

            # An order built from a stale picture of the part is refused
            # rather than half-applied.
            r_partial = await client.put(
                f"/api/parts/{part_id}/question-groups/order",
                json={"group_ids": [choice_id]},
                cookies={"access_token": token},
            )
            assert r_partial.status_code == 422, r_partial.text

            # Deleting from the middle and adding again doesn't collide on
            # the (part, order_index) constraint.
            r_delete = await client.delete(
                f"/api/question-groups/{choice_id}",
                cookies={"access_token": token},
            )
            assert r_delete.status_code == 204, r_delete.text
            r_again = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_choice_group(FINISHED_QUESTIONS),
                cookies={"access_token": token},
            )
            assert r_again.status_code == 201, r_again.text
    finally:
        await _cleanup(material.id, email)


# --- Consumption -------------------------------------------------------------


@pytest.mark.asyncio
async def test_take_carries_the_options_but_never_the_key() -> None:
    email = "mcq4-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, token, material.id)
            r = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_choice_group(FINISHED_QUESTIONS),
                cookies={"access_token": token},
            )
            assert r.status_code == 201, r.text
            await _make_public(material.id)

            r_take = await client.get(
                f"/api/materials/{material.id}/take",
                cookies={"access_token": token},
            )
            assert r_take.status_code == 200, r_take.text
            # Headline security assertion: the key isn't in the JSON text at
            # any depth, under any name it is stored by.
            assert "correct_answers" not in r_take.text
            assert '"mode"' not in r_take.text

            questions = r_take.json()["parts"][0]["question_groups"][0]["questions"]
            assert [q["options"] for q in questions] == [
                ["for a job", "to study", "for the weather"],
                ["the pool", "the gym", "the car park", "the sauna"],
            ]
            # How many to pick is public — it is printed on the paper — and
            # says nothing about which.
            assert [q["select_count"] for q in questions] == [1, 2]
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_a_stranger_reading_a_public_material_gets_no_answer_key() -> None:
    """``/take`` is not the only way to read a material: the author endpoint
    serves anyone who can see it, and gates the key on ownership. A choice
    question keeps the rest of itself in ``config``, which passes through
    that endpoint — so the gate is worth pinning down for this shape too."""
    owner_email = "mcq7-owner@example.com"
    stranger_email = "mcq7-stranger@example.com"
    owner = await _make_user(owner_email)
    stranger = await _make_user(stranger_email)
    material = await _make_material(owner.id)
    owner_token = create_access_token(str(owner.id))
    stranger_token = create_access_token(str(stranger.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, owner_token, material.id)
            r = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_choice_group(FINISHED_QUESTIONS),
                cookies={"access_token": owner_token},
            )
            assert r.status_code == 201, r.text
            await _make_public(material.id)

            r_stranger = await client.get(
                f"/api/materials/{material.id}",
                cookies={"access_token": stranger_token},
            )
            assert r_stranger.status_code == 200, r_stranger.text
            assert "correct_answers" not in r_stranger.text
            # And the question is still readable — the key is what's withheld,
            # not the question.
            questions = r_stranger.json()["parts"][0]["question_groups"][0][
                "questions"
            ]
            assert questions[0]["prompt"] == "Why did the speaker move to Bristol?"

            # The owner, on the same endpoint, gets all of it.
            r_owner = await client.get(
                f"/api/materials/{material.id}",
                cookies={"access_token": owner_token},
            )
            assert "correct_answers" in r_owner.text
    finally:
        await _cleanup(material.id, owner_email, stranger_email)


@pytest.mark.asyncio
async def test_changing_a_group_type_replaces_its_questions_outright() -> None:
    """Number 1 of a form and number 1 of a choice set are not the same
    question in different clothes — the answer key means something else — so
    nothing is reconciled across the change. Deliberate, and destructive
    enough to be worth holding in place."""
    email = "mcq8-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, token, material.id)
            r = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json={
                    "type": "form_completion",
                    "instructions": "Complete the form below.",
                    "config": {"template": "Name: {{1}}"},
                    "questions": [{"number": 1, "correct_answers": ["Bristol"]}],
                },
                cookies={"access_token": token},
            )
            assert r.status_code == 201, r.text
            group_id = r.json()["id"]
            was = r.json()["questions"][0]["id"]

            r_retyped = await client.patch(
                f"/api/question-groups/{group_id}",
                json=_choice_group(FINISHED_QUESTIONS[:1]),
                cookies={"access_token": token},
            )
            assert r_retyped.status_code == 200, r_retyped.text
            question = r_retyped.json()["questions"][0]
            # A new row, not the old one carrying a form answer into a set of
            # letters.
            assert question["id"] != was
            assert question["correct_answers"] == ["b"]
            assert question["options"] == [
                "for a job",
                "to study",
                "for the weather",
            ]
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_deleting_a_material_takes_everything_pointing_at_it() -> None:
    """Including the attempts. Every FK into a material is a plain one with
    no ON DELETE, so anything left behind isn't an orphan — it's a 500."""
    owner_email = "mcq10-owner@example.com"
    student_email = "mcq10-student@example.com"
    owner = await _make_user(owner_email)
    student = await _make_user(student_email)
    material = await _make_material(owner.id)
    owner_token = create_access_token(str(owner.id))
    student_token = create_access_token(str(student.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, owner_token, material.id)
            r = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_choice_group(FINISHED_QUESTIONS),
                cookies={"access_token": owner_token},
            )
            assert r.status_code == 201, r.text
            question_id = r.json()["questions"][0]["id"]
            await _make_public(material.id)

            r_attempt = await client.post(
                f"/api/materials/{material.id}/attempts",
                json={
                    "answers": [
                        {"question_id": question_id, "given_answer": "b"}
                    ]
                },
                cookies={"access_token": student_token},
            )
            assert r_attempt.status_code == 200, r_attempt.text

            # This used to 500: the material had been sat, and nothing cleared
            # the attempt rows pointing at it.
            r_delete = await client.delete(
                f"/api/materials/{material.id}",
                cookies={"access_token": owner_token},
            )
            assert r_delete.status_code == 204, r_delete.text

            async with async_session_factory() as session:
                assert await session.get(Material, material.id) is None
                assert (
                    await session.exec(
                        select(Attempt).where(Attempt.material_id == material.id)
                    )
                ).all() == []
                assert (
                    await session.exec(
                        select(Part).where(Part.material_id == material.id)
                    )
                ).all() == []
                assert (
                    await session.exec(
                        select(Question).where(Question.id == question_id)
                    )
                ).all() == []
                assert (
                    await session.exec(
                        select(QuestionAttempt).where(
                            QuestionAttempt.question_id == question_id
                        )
                    )
                ).all() == []
    finally:
        await _cleanup(material.id, owner_email, student_email)


@pytest.mark.asyncio
async def test_deleting_a_part_takes_groups_of_both_types_with_it() -> None:
    email = "mcq9-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, token, material.id)
            await client.post(
                f"/api/parts/{part_id}/question-groups",
                json={
                    "type": "form_completion",
                    "instructions": "Complete the form below.",
                    "config": {"template": "Name: {{1}}"},
                    "questions": [{"number": 1, "correct_answers": ["Bristol"]}],
                },
                cookies={"access_token": token},
            )
            await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_choice_group(FINISHED_QUESTIONS),
                cookies={"access_token": token},
            )

            r = await client.delete(
                f"/api/parts/{part_id}", cookies={"access_token": token}
            )
            assert r.status_code == 204, r.text

            async with async_session_factory() as session:
                assert (
                    await session.exec(
                        select(QuestionGroup).where(QuestionGroup.part_id == part_id)
                    )
                ).all() == []
                # And nothing orphaned behind them.
                assert (
                    await session.exec(
                        select(Part).where(Part.material_id == material.id)
                    )
                ).all() == []
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_a_choice_is_graded_as_a_set_with_no_partial_credit() -> None:
    owner_email = "mcq5-owner@example.com"
    student_email = "mcq5-student@example.com"
    owner = await _make_user(owner_email)
    student = await _make_user(student_email)
    material = await _make_material(owner.id)
    owner_token = create_access_token(str(owner.id))
    student_token = create_access_token(str(student.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, owner_token, material.id)
            r = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_choice_group(FINISHED_QUESTIONS),
                cookies={"access_token": owner_token},
            )
            assert r.status_code == 201, r.text
            by_number = {q["number"]: q["id"] for q in r.json()["questions"]}
            await _make_public(material.id)

            async def submit(single: str, several: str) -> dict:
                response = await client.post(
                    f"/api/materials/{material.id}/attempts",
                    json={
                        "answers": [
                            {"question_id": by_number[1], "given_answer": single},
                            {"question_id": by_number[2], "given_answer": several},
                        ]
                    },
                    cookies={"access_token": student_token},
                )
                assert response.status_code == 200, response.text
                return {r["question_id"]: r["is_correct"] for r in response.json()["results"]}

            # Right, and right in the other order, with the spacing and case
            # a UI might send.
            marks = await submit(" B ", "c, a")
            assert marks[by_number[1]] is True
            assert marks[by_number[2]] is True

            # Half of a "choose two" is not half a mark.
            marks = await submit("a", "a")
            assert marks[by_number[1]] is False
            assert marks[by_number[2]] is False

            # Nor is all of it plus one more.
            marks = await submit("", "a,b,c")
            assert marks[by_number[1]] is False
            assert marks[by_number[2]] is False

            # Each submit is its own attempt, and each one kept what was
            # actually chosen — raw, spacing and all — rather than a verdict.
            async with async_session_factory() as session:
                attempts = (
                    await session.exec(
                        select(Attempt).where(Attempt.material_id == material.id)
                    )
                ).all()
                assert sorted(a.score or 0 for a in attempts) == [0, 0, 2]
                assert {a.total_questions for a in attempts} == {2}
                given = {
                    row.given_answer
                    for row in (
                        await session.exec(
                            select(QuestionAttempt).where(
                                QuestionAttempt.attempt_id.in_(  # type: ignore[attr-defined]
                                    [a.id for a in attempts]
                                )
                            )
                        )
                    ).all()
                }
                assert {" B ", "c, a", "a,b,c"} <= given
    finally:
        await _cleanup(material.id, owner_email, student_email)


# --- Publishing ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_publishing_names_what_a_choice_group_still_needs() -> None:
    """And names it by the number on the page: the group's own numbering
    restarts at 1, the candidate's doesn't."""
    email = "mcq6-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, token, material.id)
            await client.post(
                f"/api/parts/{part_id}/question-groups",
                json={
                    "type": "form_completion",
                    "instructions": "Complete the form below.",
                    "config": {"template": "Name: {{1}}\nTown: {{2}}"},
                    "questions": [
                        {
                            "number": 1,
                            "correct_answers": ["Bristol"],
                            "replay_start_ms": 0,
                            "replay_end_ms": 900,
                        },
                        {
                            "number": 2,
                            "correct_answers": ["Bath"],
                            "replay_start_ms": 900,
                            "replay_end_ms": 1800,
                        },
                    ],
                },
                cookies={"access_token": token},
            )
            await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_choice_group(
                    [
                        {
                            "number": 1,
                            "prompt": "Why Bristol?",
                            "options": ["work", "study"],
                            "mode": "one",
                            "correct_answers": [],
                        },
                        {
                            "number": 2,
                            "prompt": "",
                            "options": ["work", "study"],
                            "mode": "one",
                            "correct_answers": ["a"],
                        },
                    ]
                ),
                cookies={"access_token": token},
            )

            r = await client.patch(
                f"/api/materials/{material.id}",
                json={"visibility": "public"},
                cookies={"access_token": token},
            )
            assert r.status_code == 422, r.text
            reasons = r.json()["detail"]
            # Third and fourth on the page, not first and second of the group.
            assert "Question 4 is without any question text" in reasons
            assert "Question 3 is without a correct answer" in reasons
            # A choice question is answered from the whole of what was said,
            # so it is never asked to be linked to a moment.
            assert "not linked to the audio" not in reasons
    finally:
        await _cleanup(material.id, email)

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


def _choice_group(questions: list[dict], wanted: int = 1) -> dict:
    """A group payload. ``wanted`` is how many letters every question in it
    asks for — the group's business, because the instruction line is."""
    return {
        "type": "multiple_choice",
        "instructions": (
            "Choose the correct letter, A, B or C."
            if wanted == 1
            else f"Choose {wanted} letters, A-E."
        ),
        "config": {"answers_per_question": wanted},
        "questions": questions,
    }


#: A finished pair of ordinary single-answer questions.
FINISHED_QUESTIONS = [
    {
        "number": 1,
        "prompt": "Why did the speaker move to Bristol?",
        "options": ["for a job", "to study", "for the weather"],
        "correct_answers": ["b"],
    },
    {
        "number": 2,
        "prompt": "Where does the club meet?",
        "options": ["the library", "the town hall", "the sports centre"],
        "correct_answers": ["c"],
    },
]

#: The other form, which is its own group because its instruction line is its
#: own: "Choose TWO letters, A-E."
CHOOSE_TWO_QUESTIONS = [
    {
        "number": 1,
        "prompt": "Which TWO facilities are free?",
        "options": ["the pool", "the gym", "the car park", "the sauna"],
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
            # How many letters to pick is the group's, said once. The prompt
            # and options are each question's, so nothing else lives here.
            assert body["config"] == {"answers_per_question": 1}

            first, second = body["questions"]
            assert first["prompt"] == "Why did the speaker move to Bristol?"
            assert first["options"] == ["for a job", "to study", "for the weather"]
            assert first["correct_answers"] == ["b"]
            assert second["correct_answers"] == ["c"]

            # The other form is a second group under its own instruction line,
            # which is how a real paper prints it.
            r_two = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_choice_group(CHOOSE_TWO_QUESTIONS, wanted=2),
                cookies={"access_token": token},
            )
            assert r_two.status_code == 201, r_two.text
            assert r_two.json()["config"] == {"answers_per_question": 2}

            # The author's own view of the material carries all of it back,
            # which is what the editor reopens from.
            r_author = await client.get(
                f"/api/materials/{material.id}", cookies={"access_token": token}
            )
            assert r_author.status_code == 200, r_author.text
            groups = r_author.json()["parts"][0]["question_groups"]
            assert [g["config"]["answers_per_question"] for g in groups] == [1, 2]
            assert [
                [q["correct_answers"] for q in g["questions"]] for g in groups
            ] == [[["b"], ["c"]], [["a", "c"]]]
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
                            "correct_answers": [],
                        }
                    ]
                ),
                cookies={"access_token": token},
            )
            assert blank.status_code == 201, blank.text
            group_id = blank.json()["id"]

            for questions, wanted, why in [
                (
                    [
                        {
                            "number": 1,
                            "options": ["a", "b"],
                            "correct_answers": ["c"],
                        }
                    ],
                    1,
                    "an answer naming an option that doesn't exist",
                ),
                (
                    [
                        {
                            "number": 1,
                            "options": ["a", "b"],
                            "correct_answers": ["a", "b"],
                        }
                    ],
                    1,
                    "two answers where the group asks for one",
                ),
                (
                    [
                        {
                            "number": 1,
                            "options": ["a", "b", "c"],
                            "correct_answers": ["a", "b", "c"],
                        }
                    ],
                    2,
                    "three answers where the group asks for two",
                ),
                (
                    [
                        {
                            "number": 1,
                            "options": ["a", "b"],
                            "correct_answers": ["a", "a"],
                        }
                    ],
                    1,
                    "the same option marked twice",
                ),
                (
                    [
                        {"number": 1, "options": ["a", "b"], "correct_answers": []},
                        {"number": 3, "options": ["a", "b"], "correct_answers": []},
                    ],
                    1,
                    "a hole in the numbering",
                ),
            ]:
                r = await client.patch(
                    f"/api/question-groups/{group_id}",
                    json=_choice_group(questions, wanted=wanted),
                    cookies={"access_token": token},
                )
                assert r.status_code == 422, f"{why} should be refused: {r.text}"

            # Short of what the group asks for is not incoherent, only
            # unfinished — that is autosave a few seconds into a "choose two".
            r_short = await client.patch(
                f"/api/question-groups/{group_id}",
                json=_choice_group(
                    [
                        {
                            "number": 1,
                            "options": ["a", "b", "c"],
                            "correct_answers": ["a"],
                        }
                    ],
                    wanted=2,
                ),
                cookies={"access_token": token},
            )
            assert r_short.status_code == 200, r_short.text
            # Put the blank group back for the assertion below.
            await client.patch(
                f"/api/question-groups/{group_id}",
                json=_choice_group(
                    [{"number": 1, "options": ["", "", ""], "correct_answers": []}]
                ),
                cookies={"access_token": token},
            )

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
async def test_where_a_choice_answer_is_said_round_trips_but_never_reaches_take() -> None:
    """Marking the moment is optional for a choice question — publishing
    never asks for it — but an author who has one should keep it, and the
    learner should get it back with their result.

    Not before, though: where the answer is said is most of the question."""
    email = "mcq-replay-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, token, material.id)
            r = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_choice_group(
                    [
                        {
                            **CHOOSE_TWO_QUESTIONS[0],
                            # One per right option, at two different moments,
                            # which is the whole reason this isn't on the
                            # question: "choose two" is answered twice.
                            "option_replay": {
                                "a": [12_000, 15_500],
                                "c": [96_000, 99_000],
                            },
                        }
                    ],
                    wanted=2,
                ),
                cookies={"access_token": token},
            )
            assert r.status_code == 201, r.text
            question_id = r.json()["questions"][0]["id"]

            # Reopened by the editor, which is what it is stored for.
            r_author = await client.get(
                f"/api/materials/{material.id}", cookies={"access_token": token}
            )
            question = r_author.json()["parts"][0]["question_groups"][0]["questions"][0]
            assert question["option_replay"] == {
                "a": [12_000, 15_500],
                "c": [96_000, 99_000],
            }

            await _make_public(material.id)
            r_take = await client.get(
                f"/api/materials/{material.id}/take",
                cookies={"access_token": token},
            )
            assert "replay" not in r_take.text

            # And handed over with the marking, which is when it stops being
            # a clue and starts being the explanation. Both moments, since
            # both are why the answer is what it is.
            r_attempt = await client.post(
                f"/api/materials/{material.id}/attempts",
                json={"answers": [{"question_id": question_id, "given_answer": "a"}]},
                cookies={"access_token": token},
            )
            assert r_attempt.status_code == 200, r_attempt.text
            assert r_attempt.json()["results"][0]["option_replay"] == {
                "a": [12_000, 15_500],
                "c": [96_000, 99_000],
            }
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_a_group_that_is_only_a_type_survives_being_saved() -> None:
    """The earliest thing an author settles about a group is what kind of
    questions it holds — before the instructions, before a single question.

    That state used to have no representation here: ``instructions`` was
    required and so was at least one question, so the group was never sent,
    so choosing "multiple choice" and coming back the next day meant being
    asked all over again. Both kinds have to survive it, and publishing —
    not this endpoint — is what insists on the rest.
    """
    email = "mcq-bare-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, token, material.id)

            for payload, kind in [
                ({"type": "multiple_choice", "config": {}, "questions": []},
                 "multiple_choice"),
                ({"type": "form_completion", "config": {"template": ""},
                  "questions": []}, "form_completion"),
            ]:
                r = await client.post(
                    f"/api/parts/{part_id}/question-groups",
                    json=payload,
                    cookies={"access_token": token},
                )
                assert r.status_code == 201, f"{kind}: {r.text}"
                assert r.json()["type"] == kind
                assert r.json()["instructions"] == ""
                assert r.json()["questions"] == []

            # Reopened, the material still knows what each group was going to
            # be — which is the whole point of storing it.
            r_after = await client.get(
                f"/api/materials/{material.id}", cookies={"access_token": token}
            )
            groups = r_after.json()["parts"][0]["question_groups"]
            assert [g["type"] for g in groups] == [
                "multiple_choice",
                "form_completion",
            ]

            # And none of it is publishable, so nothing incomplete escapes by
            # being storable.
            r_publish = await client.patch(
                f"/api/materials/{material.id}",
                json={"visibility": "public"},
                cookies={"access_token": token},
            )
            assert r_publish.status_code == 422, r_publish.text
            assert "add the instructions" in r_publish.text
            assert "add at least one question" in r_publish.text
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
            r_two = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_choice_group(CHOOSE_TWO_QUESTIONS, wanted=2),
                cookies={"access_token": token},
            )
            assert r_two.status_code == 201, r_two.text
            await _make_public(material.id)

            r_take = await client.get(
                f"/api/materials/{material.id}/take",
                cookies={"access_token": token},
            )
            assert r_take.status_code == 200, r_take.text
            # Headline security assertion: the key isn't in the JSON text at
            # any depth, under any name it is stored by.
            assert "correct_answers" not in r_take.text

            groups = r_take.json()["parts"][0]["question_groups"]
            assert [q["options"] for q in groups[0]["questions"]] == [
                ["for a job", "to study", "for the weather"],
                ["the library", "the town hall", "the sports centre"],
            ]
            # How many to pick is public — it is printed on the paper — and
            # says nothing about which. It comes off the group, so every
            # question under one instruction line agrees with it.
            assert [q["select_count"] for q in groups[0]["questions"]] == [1, 1]
            assert [q["select_count"] for q in groups[1]["questions"]] == [2]
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
            # The two forms are two groups, because their instruction lines
            # differ — which is the whole point of the setting being per
            # group. Both are graded the same way.
            part_id = await _seed_part(client, owner_token, material.id)
            r_one = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_choice_group(FINISHED_QUESTIONS[:1]),
                cookies={"access_token": owner_token},
            )
            assert r_one.status_code == 201, r_one.text
            r_two = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_choice_group(CHOOSE_TWO_QUESTIONS, wanted=2),
                cookies={"access_token": owner_token},
            )
            assert r_two.status_code == 201, r_two.text
            single_id = r_one.json()["questions"][0]["id"]
            several_id = r_two.json()["questions"][0]["id"]
            await _make_public(material.id)

            async def submit(single: str, several: str) -> dict:
                response = await client.post(
                    f"/api/materials/{material.id}/attempts",
                    json={
                        "answers": [
                            {"question_id": single_id, "given_answer": single},
                            {"question_id": several_id, "given_answer": several},
                        ]
                    },
                    cookies={"access_token": student_token},
                )
                assert response.status_code == 200, response.text
                return {r["question_id"]: r["is_correct"] for r in response.json()["results"]}

            # Right, and right in the other order, with the spacing and case
            # a UI might send.
            marks = await submit(" B ", "c, a")
            assert marks[single_id] is True
            assert marks[several_id] is True

            # Half of a "choose two" is not half a mark.
            marks = await submit("a", "a")
            assert marks[single_id] is False
            assert marks[several_id] is False

            # Nor is all of it plus one more.
            marks = await submit("", "a,b,c")
            assert marks[single_id] is False
            assert marks[several_id] is False

            # Each submit is its own attempt, and each one kept what was
            # actually chosen — raw, spacing and all — rather than a verdict.
            async with async_session_factory() as session:
                attempts = (
                    await session.exec(
                        select(Attempt).where(Attempt.material_id == material.id)
                    )
                ).all()
                # Out of three marks, not two questions: the "choose two"
                # is two of the numbers on the paper and two of the marks,
                # exactly as it is printed. Both right earns all three.
                assert sorted(a.score or 0 for a in attempts) == [0, 0, 3]
                assert {a.total_questions for a in attempts} == {3}
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
                            "correct_answers": [],
                        },
                        {
                            "number": 2,
                            "prompt": "",
                            "options": ["work", "study"],
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
            # Linked to the audio like a gap. The option's wording is
            # rarely spoken, but the answer always is: some sentence makes b
            # right rather than a, and that is what a learner who got it
            # wrong is sent back to.
            #
            # Only question 4, though it is question 3 that has no mark
            # either: 3 has no right option yet, so there is nothing to link
            # and nothing to say beyond the missing answer already listed.
            assert "Question 4 is not linked to the audio" in reasons
            assert "Questions 3, 4 are not linked" not in reasons

            # A "choose two" group wants exactly two marked on every question,
            # not merely one — the candidate is told to pick two, so a key of
            # one would mark a correct pair wrong.
            r_two = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_choice_group(
                    [
                        {
                            "number": 1,
                            "prompt": "Which TWO are free?",
                            "options": ["pool", "gym", "sauna"],
                            "correct_answers": ["a"],
                        }
                    ],
                    wanted=2,
                ),
                cookies={"access_token": token},
            )
            assert r_two.status_code == 201, r_two.text
            r = await client.patch(
                f"/api/materials/{material.id}",
                json={"visibility": "public"},
                cookies={"access_token": token},
            )
            assert r.status_code == 422, r.text
            assert "Question 5 is without 2 answers marked" in r.json()["detail"]

            # And it took TWO of the numbers with it: the next group starts at
            # 7, not 6. This is the whole reason the count is the group's —
            # everything after a "choose two" shifts by two, exactly as it
            # does on a printed paper.
            r_after = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_choice_group(
                    [
                        {
                            "number": 1,
                            "prompt": "",
                            "options": ["a", "b"],
                            "correct_answers": [],
                        }
                    ]
                ),
                cookies={"access_token": token},
            )
            assert r_after.status_code == 201, r_after.text
            r = await client.patch(
                f"/api/materials/{material.id}",
                json={"visibility": "public"},
                cookies={"access_token": token},
            )
            assert r.status_code == 422, r.text
            assert "Question 7 is without any question text" in r.json()["detail"]
    finally:
        await _cleanup(material.id, email)

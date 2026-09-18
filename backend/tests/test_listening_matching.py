"""Integration tests for matching question groups — authoring, consumption,
grading and publishing — against a real DB, ASGI transport + minted cookie,
the same pattern as the other listening tests.

What makes matching worth its own file is where its parts live. The box of
options is the GROUP's: printed once above the set, answered from by every
item under it. That one decision is what these tests are mostly about —

* the box round-trips on the group, and each item stores only its own text;
* an answer naming a letter the box doesn't have is refused, while an item
  with no answer yet is stored, because autosave sends the latter all day;
* ``/take`` hands the box over on the group and the prompts on the questions,
  and nothing that says which letter is right;
* the answer is graded as a letter — the same set match multiple choice gets
  — even though the row carries no options of its own to say so;
* "each letter once" is a publishing rule, not a write-time one: reassigning
  two items is two saves, and the state in between has both on one letter.
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
        user = User(email=email, display_name=f"Matching test {email}")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _make_material(author_id: uuid.UUID) -> Material:
    async with async_session_factory() as session:
        material = Material(
            author_id=author_id,
            type="listening",
            title=f"Matching fixture {uuid.uuid4()}",
            visibility="private",
        )
        session.add(material)
        await session.commit()
        await session.refresh(material)
        return material


async def _make_public(material_id: uuid.UUID) -> None:
    """Flip the flag directly — the tests that take a material are about
    matching, not about the publishing rules, which are tested below on their
    own terms."""
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


#: The box the items are answered from. Three options, so the letters run
#: a, b, c — which is what the answer keys below name.
OPTIONS = ["a holiday cottage", "a hotel", "a campsite"]


def _matching_group(
    questions: list[dict],
    options: list[str] | None = None,
    allow_reuse: bool = False,
) -> dict:
    return {
        "type": "matching",
        "instructions": "What does the speaker say about each place?",
        "config": {
            "options": OPTIONS if options is None else options,
            "allow_reuse": allow_reuse,
        },
        "questions": questions,
    }


#: A finished pair, each linked to where its answer is given.
FINISHED_QUESTIONS = [
    {
        "number": 1,
        "prompt": "Trelawney",
        "correct_answers": ["b"],
        "replay_start_ms": 12_000,
        "replay_end_ms": 15_500,
    },
    {
        "number": 2,
        "prompt": "Penhale",
        "correct_answers": ["c"],
        "replay_start_ms": 31_000,
        "replay_end_ms": 34_000,
    },
]


async def _seed_part(
    client: httpx.AsyncClient, token: str, material_id: uuid.UUID
) -> str:
    r_part = await client.post(
        f"/api/materials/{material_id}/parts",
        json={"order_index": 0, "title": "Part 2"},
        cookies={"access_token": token},
    )
    assert r_part.status_code == 201, r_part.text
    return r_part.json()["id"]


# --- Authoring ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_box_is_stored_on_the_group_and_each_item_holds_only_its_own_text() -> None:
    email = "match1-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, token, material.id)

            r = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_matching_group(FINISHED_QUESTIONS),
                cookies={"access_token": token},
            )
            assert r.status_code == 201, r.text
            body = r.json()
            assert body["type"] == "matching"
            assert body["config"] == {
                "options": OPTIONS,
                "allow_reuse": False,
                "label_style": "letters",
            }

            first, second = body["questions"]
            assert first["prompt"] == "Trelawney"
            assert first["correct_answers"] == ["b"]
            assert second["correct_answers"] == ["c"]
            # The item does NOT carry the box. Answering with an empty list
            # here would read as "a question whose options were deleted"
            # rather than as "a question answered from its group's".
            assert first["options"] is None

            # And the author's own view — what the editor reopens from —
            # carries all of it back the same way.
            r_author = await client.get(
                f"/api/materials/{material.id}", cookies={"access_token": token}
            )
            assert r_author.status_code == 200, r_author.text
            group = r_author.json()["parts"][0]["question_groups"][0]
            assert group["config"]["options"] == OPTIONS
            assert [q["prompt"] for q in group["questions"]] == [
                "Trelawney",
                "Penhale",
            ]
            assert [q["correct_answers"] for q in group["questions"]] == [["b"], ["c"]]
            # One item is one answer said at one moment, so the mark is the
            # question's own — the per-option ranges a "choose two" needs have
            # nothing to do here.
            assert group["questions"][0]["replay_start_ms"] == 12_000
            assert "option_replay" not in group["questions"][0]
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_an_unfinished_item_is_saved_and_an_impossible_answer_is_not() -> None:
    """Autosave runs while the author is still typing, so an item with no
    text and no letter has to be storable. What is refused is an answer the
    box cannot honour."""
    email = "match2-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, token, material.id)

            # A group that knows only what kind it is. This is the state a
            # brand-new one is in for as long as it takes to write the first
            # option, and it has to survive being saved or the author is
            # asked what kind of questions these are every time they come back.
            blank = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json={
                    "type": "matching",
                    "instructions": "",
                    "config": {"options": [], "allow_reuse": False},
                    "questions": [{"number": 1, "prompt": "", "correct_answers": []}],
                },
                cookies={"access_token": token},
            )
            assert blank.status_code == 201, blank.text
            group_id = blank.json()["id"]

            # A letter the box doesn't have. Nothing the candidate could ever
            # submit would match it, so it is refused rather than stored.
            unknown = await client.patch(
                f"/api/question-groups/{group_id}",
                json=_matching_group(
                    [{"number": 1, "prompt": "Trelawney", "correct_answers": ["f"]}]
                ),
                cookies={"access_token": token},
            )
            assert unknown.status_code == 422, unknown.text

            # Two letters on one item is not an unfinished matching question,
            # it is one that can't be sat.
            two = await client.patch(
                f"/api/question-groups/{group_id}",
                json=_matching_group(
                    [{"number": 1, "prompt": "Trelawney", "correct_answers": ["a", "b"]}]
                ),
                cookies={"access_token": token},
            )
            assert two.status_code == 422, two.text

            # Two items on ONE letter is, though — reassigning them is two
            # saves and this is the state in between. Publishing is where it
            # has to be resolved.
            shared = await client.patch(
                f"/api/question-groups/{group_id}",
                json=_matching_group(
                    [
                        {"number": 1, "prompt": "Trelawney", "correct_answers": ["b"]},
                        {"number": 2, "prompt": "Penhale", "correct_answers": ["b"]},
                    ]
                ),
                cookies={"access_token": token},
            )
            assert shared.status_code == 200, shared.text
    finally:
        await _cleanup(material.id, email)


# --- Consumption -------------------------------------------------------------


@pytest.mark.asyncio
async def test_take_carries_the_box_and_the_prompts_and_never_the_key() -> None:
    email = "match3-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, token, material.id)
            r = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_matching_group(FINISHED_QUESTIONS),
                cookies={"access_token": token},
            )
            assert r.status_code == 201, r.text
        await _make_public(material.id)

        async with _client() as client:
            r_take = await client.get(
                f"/api/materials/{material.id}/take",
                cookies={"access_token": token},
            )
            assert r_take.status_code == 200, r_take.text
            group = r_take.json()["parts"][0]["question_groups"][0]

            # The box travels once, on the group, exactly as it is printed.
            assert group["config"]["options"] == OPTIONS
            questions = group["questions"]
            assert [q["prompt"] for q in questions] == ["Trelawney", "Penhale"]
            # Nothing about which letter is right, and nothing about where it
            # is said — knowing where to listen is most of the question.
            body = r_take.text
            assert "correct_answers" not in body
            assert "replay" not in body
            for question in questions:
                assert question["options"] is None
                assert question["select_count"] is None
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_an_item_is_graded_as_a_letter_and_is_worth_one_mark() -> None:
    """The row carries no options, so nothing on it says its answer is a
    letter — that comes from its group. Get this wrong and a matching item is
    compared as free text, which happens to agree for a single letter and
    would stop agreeing the moment anything else changed."""
    owner_email = "match4-owner@example.com"
    taker_email = "match4-taker@example.com"
    owner = await _make_user(owner_email)
    taker = await _make_user(taker_email)
    material = await _make_material(owner.id)
    owner_token = create_access_token(str(owner.id))
    taker_token = create_access_token(str(taker.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, owner_token, material.id)
            r = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_matching_group(FINISHED_QUESTIONS),
                cookies={"access_token": owner_token},
            )
            assert r.status_code == 201, r.text
            ids = [q["id"] for q in r.json()["questions"]]
        await _make_public(material.id)

        async with _client() as client:
            r_attempt = await client.post(
                f"/api/materials/{material.id}/attempts",
                json={
                    "answers": [
                        # Right, in the other case and with space around it:
                        # the letter is normalized before it is compared.
                        {"question_id": ids[0], "given_answer": " B "},
                        {"question_id": ids[1], "given_answer": "a"},
                    ]
                },
                cookies={"access_token": taker_token},
            )
            assert r_attempt.status_code == 200, r_attempt.text
            result = r_attempt.json()
            # Two items, two of the numbers on the paper, two marks.
            assert result["total_questions"] == 2
            assert result["score"] == 1

            by_id = {r["question_id"]: r for r in result["results"]}
            assert by_id[ids[0]]["is_correct"] is True
            assert by_id[ids[1]]["is_correct"] is False
            # Released only now the attempt is committed, which is what makes
            # it feedback rather than a hint.
            assert by_id[ids[1]]["correct_answers"] == ["c"]
            assert by_id[ids[1]]["replay_start_ms"] == 31_000
    finally:
        await _cleanup(material.id, owner_email, taker_email)


# --- Publishing ---------------------------------------------------------------


async def _blockers(material_id: uuid.UUID) -> list[str]:
    from app.services.publishing import publish_blockers

    async with async_session_factory() as session:
        material = await session.get(Material, material_id)
        assert material is not None
        return await publish_blockers(session, material)


@pytest.mark.asyncio
async def test_publishing_asks_for_a_box_that_can_answer_every_item() -> None:
    email = "match5-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, token, material.id)
            r = await client.post(
                f"/api/parts/{part_id}/question-groups",
                # Two items and a box of one, which no amount of further work
                # could complete.
                json=_matching_group(
                    [
                        {"number": 1, "prompt": "Trelawney", "correct_answers": []},
                        {"number": 2, "prompt": "", "correct_answers": []},
                    ],
                    options=["a hotel"],
                ),
                cookies={"access_token": token},
            )
            assert r.status_code == 201, r.text
            group_id = r.json()["id"]

            said = " ".join(await _blockers(material.id))
            assert "at least two options" in said
            assert "Question 2 is without any question text" in said
            assert "Questions 1, 2 are without an answer" in said
            assert "not linked to the audio" in said

            # A box big enough to letter, but not to answer two items with
            # one letter each.
            r_two = await client.patch(
                f"/api/question-groups/{group_id}",
                json=_matching_group(
                    [
                        {"number": 1, "prompt": "Trelawney", "correct_answers": ["b"]},
                        {"number": 2, "prompt": "Penhale", "correct_answers": ["b"]},
                    ],
                    options=["a hotel", "a campsite"],
                ),
                cookies={"access_token": token},
            )
            assert r_two.status_code == 200, r_two.text
            said = " ".join(await _blockers(material.id))
            assert "already uses" in said

            # Saying letters may be reused settles both complaints at once:
            # three options and eight items is an ordinary Part 3 set.
            r_reuse = await client.patch(
                f"/api/question-groups/{group_id}",
                json=_matching_group(
                    [
                        {
                            "number": 1,
                            "prompt": "Trelawney",
                            "correct_answers": ["b"],
                            "replay_start_ms": 1_000,
                            "replay_end_ms": 4_000,
                        },
                        {
                            "number": 2,
                            "prompt": "Penhale",
                            "correct_answers": ["b"],
                            "replay_start_ms": 8_000,
                            "replay_end_ms": 11_000,
                        },
                    ],
                    options=["a hotel", "a campsite"],
                    allow_reuse=True,
                ),
                cookies={"access_token": token},
            )
            assert r_reuse.status_code == 200, r_reuse.text
            said = " ".join(await _blockers(material.id))
            assert "already uses" not in said
            assert "options to match them to" not in said
            # What is left is the material's own doing, not the group's: it
            # still has no recording.
            assert said == "Attach the audio recording."
    finally:
        await _cleanup(material.id, email)


# --- A completion task with a box --------------------------------------------


@pytest.mark.asyncio
async def test_a_summary_with_a_box_is_answered_and_graded_in_letters() -> None:
    """"Complete the summary using the list of words, A–H" is matching whose
    items are gaps in a paragraph. The same summary without the box is answered
    in words — so what decides is the box, not the group's type, and grading
    that read the type alone would compare a submitted letter against the
    words of an option and mark every answer wrong."""
    owner_email = "boxed-owner@example.com"
    taker_email = "boxed-taker@example.com"
    owner = await _make_user(owner_email)
    taker = await _make_user(taker_email)
    material = await _make_material(owner.id)
    owner_token = create_access_token(str(owner.id))
    taker_token = create_access_token(str(taker.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, owner_token, material.id)
            r = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json={
                    "type": "summary_completion",
                    "instructions": "Complete the summary using the list of words.",
                    "config": {
                        "template": "The tour leaves from the {{1}} and ends at the {{2}}.",
                        "options": ["harbour", "museum", "station"],
                        "allow_reuse": False,
                    },
                    "questions": [
                        {
                            "number": 1,
                            "correct_answers": ["a"],
                            "replay_start_ms": 1_000,
                            "replay_end_ms": 4_000,
                        },
                        {
                            "number": 2,
                            "correct_answers": ["c"],
                            "replay_start_ms": 8_000,
                            "replay_end_ms": 11_000,
                        },
                    ],
                },
                cookies={"access_token": owner_token},
            )
            assert r.status_code == 201, r.text
            body = r.json()
            assert body["config"]["options"] == ["harbour", "museum", "station"]
            ids = [q["id"] for q in body["questions"]]

            # A letter the box hasn't got is refused, the same as it is for a
            # matching item — and so is answering one gap with two letters.
            for answers in (["f"], ["a", "b"]):
                bad = await client.patch(
                    f"/api/question-groups/{body['id']}",
                    json={
                        "type": "summary_completion",
                        "instructions": "Complete the summary.",
                        "config": {
                            "template": "The tour leaves from the {{1}}.",
                            "options": ["harbour", "museum"],
                        },
                        "questions": [{"number": 1, "correct_answers": answers}],
                    },
                    cookies={"access_token": owner_token},
                )
                assert bad.status_code == 422, bad.text
        await _make_public(material.id)

        async with _client() as client:
            r_take = await client.get(
                f"/api/materials/{material.id}/take",
                cookies={"access_token": taker_token},
            )
            assert r_take.status_code == 200, r_take.text
            group = r_take.json()["parts"][0]["question_groups"][0]
            # The box reaches the candidate — they cannot answer without it —
            # and the key does not.
            assert group["config"]["options"] == ["harbour", "museum", "station"]
            assert "correct_answers" not in r_take.text

            r_attempt = await client.post(
                f"/api/materials/{material.id}/attempts",
                json={
                    "answers": [
                        {"question_id": ids[0], "given_answer": "A"},
                        {"question_id": ids[1], "given_answer": "harbour"},
                    ]
                },
                cookies={"access_token": taker_token},
            )
            assert r_attempt.status_code == 200, r_attempt.text
            result = r_attempt.json()
            by_id = {r["question_id"]: r for r in result["results"]}
            # The letter is right whatever its case; the option's own words are
            # not an answer here, because the paper asked for a letter.
            assert by_id[ids[0]]["is_correct"] is True
            assert by_id[ids[1]]["is_correct"] is False
            assert result["score"] == 1
            assert result["total_questions"] == 2
    finally:
        await _cleanup(material.id, owner_email, taker_email)


@pytest.mark.asyncio
async def test_publishing_holds_a_boxed_summary_to_the_same_rules_as_matching() -> None:
    email = "boxed-publish@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, token, material.id)
            r = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json={
                    "type": "summary_completion",
                    "instructions": "Complete the summary using the list of words.",
                    "config": {
                        "template": "It leaves the {{1}} and returns to the {{2}}.",
                        "options": ["harbour"],
                        "allow_reuse": False,
                    },
                    "questions": [
                        {"number": 1, "correct_answers": ["a"]},
                        {"number": 2, "correct_answers": []},
                    ],
                },
                cookies={"access_token": token},
            )
            assert r.status_code == 201, r.text
            group_id = r.json()["id"]

            said = " ".join(await _blockers(material.id))
            assert "at least two options" in said
            # Worded for a box: there is no field to type an answer into.
            assert "Question 2 is without a letter from the box" in said
            assert "not linked to the audio" in said

            # Two gaps on one letter, where each letter answers one gap.
            r_two = await client.patch(
                f"/api/question-groups/{group_id}",
                json={
                    "type": "summary_completion",
                    "instructions": "Complete the summary using the list of words.",
                    "config": {
                        "template": "It leaves the {{1}} and returns to the {{2}}.",
                        "options": ["harbour", "museum"],
                        "allow_reuse": False,
                    },
                    "questions": [
                        {
                            "number": 1,
                            "correct_answers": ["a"],
                            "replay_start_ms": 1_000,
                            "replay_end_ms": 4_000,
                        },
                        {
                            "number": 2,
                            "correct_answers": ["a"],
                            "replay_start_ms": 8_000,
                            "replay_end_ms": 11_000,
                        },
                    ],
                },
                cookies={"access_token": token},
            )
            assert r_two.status_code == 200, r_two.text
            said = " ".join(await _blockers(material.id))
            assert "already uses" in said

            # Letting a letter be reused settles it: the recording may well
            # name the same place twice.
            r_reuse = await client.patch(
                f"/api/question-groups/{group_id}",
                json={
                    "type": "summary_completion",
                    "instructions": "Complete the summary using the list of words.",
                    "config": {
                        "template": "It leaves the {{1}} and returns to the {{2}}.",
                        "options": ["harbour", "museum"],
                        "allow_reuse": True,
                    },
                    "questions": [
                        {
                            "number": 1,
                            "correct_answers": ["a"],
                            "replay_start_ms": 1_000,
                            "replay_end_ms": 4_000,
                        },
                        {
                            "number": 2,
                            "correct_answers": ["a"],
                            "replay_start_ms": 8_000,
                            "replay_end_ms": 11_000,
                        },
                    ],
                },
                cookies={"access_token": token},
            )
            assert r_reuse.status_code == 200, r_reuse.text
            assert await _blockers(material.id) == ["Attach the audio recording."]
    finally:
        await _cleanup(material.id, email)

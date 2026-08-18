"""Integration tests for map and diagram labelling — authoring, consumption,
grading and publishing — against a real DB, ASGI transport + minted cookie,
the same pattern as the other listening tests.

These two types are completion tasks: a list of numbered gaps, answered in
words or in letters, stored and graded exactly like a set of notes. What earns
them a file is the one thing they add — the answers are on a picture — and the
several ways that could quietly go wrong:

* the picture is stored as an id and read back as a URL and a size, so nothing
  that could go stale is kept in the group;
* a group naming a picture that isn't stored is refused, because JSONB would
  otherwise take any id at all and the author would meet a broken image with
  nothing anywhere saying why;
* letters drawn on the picture are a box like any other: the same one-letter
  rule, the same "that letter doesn't exist" refusal, the same set-match at
  grading time;
* zero letters is NOT a draft — it is the other real form of the task, where
  the candidate writes what they heard into numbered blanks;
* and the count only counts for the types that draw a picture, so renaming a
  map task to notes must not leave its gaps being graded as letters nobody can
  see.
"""

import uuid

import httpx
import pytest
from sqlmodel import select

from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.main import app
from app.models.attempt import Attempt
from app.models.image_blob import ImageBlob
from app.models.material import Material
from app.models.part import Part
from app.models.question import Question
from app.models.question_attempt import QuestionAttempt
from app.models.question_group import QuestionGroup, QuestionGroupType
from app.models.user import User
from app.services import listening as listening_service
from app.services import publishing as publishing_service


async def _make_user(email: str) -> User:
    async with async_session_factory() as session:
        user = (await session.exec(select(User).where(User.email == email))).first()
        if user is not None:
            return user
        user = User(email=email, display_name=f"Labelling test {email}")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _make_material(author_id: uuid.UUID) -> Material:
    async with async_session_factory() as session:
        material = Material(
            author_id=author_id,
            type="listening",
            title=f"Labelling fixture {uuid.uuid4()}",
            visibility="private",
        )
        session.add(material)
        await session.commit()
        await session.refresh(material)
        return material


async def _make_image(width: int = 1240, height: int = 874) -> ImageBlob:
    """A row, not an upload. What the upload endpoint does with real bytes is
    tests/test_upload_image.py's business; these tests only need a picture that
    exists to be pointed at."""
    async with async_session_factory() as session:
        blob = ImageBlob(
            sha256=f"labelling-test-{uuid.uuid4().hex}",
            storage_key=f"images/{uuid.uuid4().hex}.png",
            size_bytes=4096,
            mime_type="image/png",
            width=width,
            height=height,
        )
        session.add(blob)
        await session.commit()
        await session.refresh(blob)
        return blob


async def _make_public(material_id: uuid.UUID) -> None:
    async with async_session_factory() as session:
        material = await session.get(Material, material_id)
        assert material is not None
        material.visibility = "public"
        session.add(material)
        await session.commit()


async def _cleanup(
    material_id: uuid.UUID, *emails: str, image_id: uuid.UUID | None = None
) -> None:
    async with async_session_factory() as session:
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
        if image_id is not None:
            image = await session.get(ImageBlob, image_id)
            if image is not None:
                await session.delete(image)
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


#: A map task with three places to name, lettered A-F on the picture.
TEMPLATE = "Car park | {{1}}\nCafé | {{2}}\nGift shop | {{3}}"

LETTERED_QUESTIONS = [
    {
        "number": 1,
        "correct_answers": ["c"],
        "replay_start_ms": 12_000,
        "replay_end_ms": 15_500,
    },
    {
        "number": 2,
        "correct_answers": ["a"],
        "replay_start_ms": 31_000,
        "replay_end_ms": 34_000,
    },
    {
        "number": 3,
        "correct_answers": ["f"],
        "replay_start_ms": 48_000,
        "replay_end_ms": 51_000,
    },
]


def _labelling_group(
    image_id: uuid.UUID | None,
    questions: list[dict],
    *,
    type: str = "map_labelling",
    letters: int = 6,
    template: str = TEMPLATE,
    **config,
) -> dict:
    return {
        "type": type,
        "instructions": "Label the map below. Write the correct letter, A-F.",
        "config": {
            "template": template,
            "image": str(image_id) if image_id else None,
            "image_letters": letters,
            **config,
        },
        "questions": questions,
    }


async def _seed_part(
    client: httpx.AsyncClient, token: str, material_id: uuid.UUID
) -> str:
    r = await client.post(
        f"/api/materials/{material_id}/parts",
        json={"order_index": 0, "title": "Part 2"},
        cookies={"access_token": token},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


# --- Authoring ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_picture_is_stored_as_an_id_and_read_back_as_a_url_and_a_size() -> None:
    """The id is the only thing persisted. A URL written beside it would be a
    fact about which bucket the app pointed at that day; the size is what lets
    the take page reserve the picture's box before its bytes arrive."""
    email = "label1-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    image = await _make_image(width=1240, height=874)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, token, material.id)
            r = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_labelling_group(image.id, LETTERED_QUESTIONS),
                cookies={"access_token": token},
            )
            assert r.status_code == 201, r.text
            body = r.json()
            assert body["type"] == "map_labelling"
            assert body["config"]["image"] == str(image.id)
            assert body["config"]["image_letters"] == 6
            assert body["config"]["image_url"].endswith(image.storage_key)
            assert body["config"]["image_width"] == 1240
            assert body["config"]["image_height"] == 874

            r_author = await client.get(
                f"/api/materials/{material.id}", cookies={"access_token": token}
            )
            assert r_author.status_code == 200, r_author.text
            group = r_author.json()["parts"][0]["question_groups"][0]
            assert group["config"]["image"] == str(image.id)
            assert group["config"]["image_width"] == 1240
            assert [q["correct_answers"] for q in group["questions"]] == [
                ["c"],
                ["a"],
                ["f"],
            ]

        async with async_session_factory() as session:
            stored = (
                await session.exec(
                    select(QuestionGroup).where(QuestionGroup.part_id == uuid.UUID(part_id))
                )
            ).first()
            assert stored is not None
            # Nothing derived is written down. The row holds the id and the
            # count, and that is all it can be wrong about later.
            assert "image_url" not in stored.config
            assert "image_width" not in stored.config
    finally:
        await _cleanup(material.id, email, image_id=image.id)


@pytest.mark.asyncio
async def test_a_picture_that_is_not_stored_is_refused() -> None:
    """JSONB would take any id at all, and the author would meet a broken
    picture above their questions with nothing anywhere saying why."""
    email = "label2-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, token, material.id)
            r = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_labelling_group(uuid.uuid4(), LETTERED_QUESTIONS),
                cookies={"access_token": token},
            )
            assert r.status_code == 422, r.text
            assert "upload it again" in r.text

        async with async_session_factory() as session:
            groups = (
                await session.exec(
                    select(QuestionGroup).where(
                        QuestionGroup.part_id == uuid.UUID(part_id)
                    )
                )
            ).all()
            assert groups == []
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_a_group_with_no_picture_yet_is_saved() -> None:
    """The picture is uploaded at some point during the writing, not before it
    starts. Refusing a group without one would mean the task can't be drafted
    at all — publishing is where it becomes required."""
    email = "label3-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, token, material.id)
            r = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json={
                    "type": "diagram_labelling",
                    "instructions": "",
                    "config": {"template": ""},
                    "questions": [],
                },
                cookies={"access_token": token},
            )
            assert r.status_code == 201, r.text
            assert r.json()["config"]["image"] is None
            assert "image_url" not in r.json()["config"]
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_an_answer_naming_a_letter_the_picture_does_not_have_is_refused() -> None:
    email = "label4-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    image = await _make_image()
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, token, material.id)

            # Six letters are drawn, so "g" is on no part of the picture.
            r = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_labelling_group(
                    image.id,
                    [{"number": 1, "correct_answers": ["g"]}],
                    letters=6,
                    template="Car park | {{1}}",
                ),
                cookies={"access_token": token},
            )
            assert r.status_code == 422, r.text
            assert "the picture doesn't have" in r.text

            # And one gap takes one letter: two is not an unfinished answer,
            # it is one that can't be sat.
            r_two = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_labelling_group(
                    image.id,
                    [{"number": 1, "correct_answers": ["a", "b"]}],
                    template="Car park | {{1}}",
                ),
                cookies={"access_token": token},
            )
            assert r_two.status_code == 422, r_two.text
            assert "takes one letter" in r_two.text

            # An unanswered gap, though, is what autosave sends all day.
            r_draft = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_labelling_group(
                    image.id,
                    [{"number": 1, "correct_answers": []}],
                    template="Car park | {{1}}",
                ),
                cookies={"access_token": token},
            )
            assert r_draft.status_code == 201, r_draft.text
    finally:
        await _cleanup(material.id, email, image_id=image.id)


@pytest.mark.asyncio
async def test_a_word_list_and_a_lettered_picture_at_once_is_refused() -> None:
    """Not a task with two ways in — a group where nobody, the author
    included, can say what letter B means."""
    email = "label5-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    image = await _make_image()
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, token, material.id)
            r = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_labelling_group(
                    image.id,
                    [{"number": 1, "correct_answers": ["a"]}],
                    template="Car park | {{1}}",
                    options=["the north gate", "the lake"],
                ),
                cookies={"access_token": token},
            )
            assert r.status_code == 422, r.text
            assert "not from both" in r.text
    finally:
        await _cleanup(material.id, email, image_id=image.id)


@pytest.mark.asyncio
async def test_a_labelling_task_answered_in_words_is_an_ordinary_completion() -> None:
    """Zero letters is the other real form of the task: numbered blanks on the
    picture and "write no more than two words". Nothing about it is a draft, so
    the words go through the same accepted-variants path as a set of notes."""
    email = "label6-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    image = await _make_image()
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, token, material.id)
            r = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_labelling_group(
                    image.id,
                    [{"number": 1, "correct_answers": ["ticket office", "ticket hall"]}],
                    letters=0,
                    template="Building A | {{1}}",
                ),
                cookies={"access_token": token},
            )
            assert r.status_code == 201, r.text
            assert r.json()["questions"][0]["correct_answers"] == [
                "ticket office",
                "ticket hall",
            ]

        async with async_session_factory() as session:
            group = (
                await session.exec(
                    select(QuestionGroup).where(
                        QuestionGroup.part_id == uuid.UUID(part_id)
                    )
                )
            ).first()
            assert group is not None
            assert listening_service.letter_count(group) == 0
            assert not listening_service.answers_are_letters(group)
    finally:
        await _cleanup(material.id, email, image_id=image.id)


@pytest.mark.asyncio
async def test_renaming_a_map_task_to_notes_stops_its_letters_counting() -> None:
    """The count stays in config across the rename — an author who renames back
    should find their picture and its letters where they left them — but a set of
    notes draws no picture, so grading its gaps as letters would be grading
    against something nobody can see."""
    email = "label7-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    image = await _make_image()
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, token, material.id)
            r = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_labelling_group(image.id, LETTERED_QUESTIONS),
                cookies={"access_token": token},
            )
            assert r.status_code == 201, r.text
            group_id = r.json()["id"]
            question_ids = [q["id"] for q in r.json()["questions"]]

            r_rename = await client.patch(
                f"/api/question-groups/{group_id}",
                json=_labelling_group(
                    image.id, LETTERED_QUESTIONS, type="note_completion"
                ),
                cookies={"access_token": token},
            )
            assert r_rename.status_code == 200, r_rename.text
            body = r_rename.json()
            # A rename keeps the questions: gap 3 of a map and gap 3 of the
            # notes it becomes are the same question.
            assert [q["id"] for q in body["questions"]] == question_ids
            # And keeps the picture, drawable: an editor that reloaded it as
            # an id with nothing behind it would have no choice but to drop it
            # on the next save, and renaming back is meant to find it there.
            assert body["config"]["image"] == str(image.id)
            assert body["config"]["image_url"].endswith(image.storage_key)

        async with async_session_factory() as session:
            group = await session.get(QuestionGroup, uuid.UUID(group_id))
            assert group is not None
            assert group.config["image_letters"] == 6
            assert listening_service.image_letter_count(group) == 0
            assert listening_service.group_image(group) is None
            assert not listening_service.answers_are_letters(group)
    finally:
        await _cleanup(material.id, email, image_id=image.id)


@pytest.mark.asyncio
async def test_a_map_can_become_a_diagram_and_keep_everything() -> None:
    email = "label8-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    image = await _make_image()
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, token, material.id)
            r = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_labelling_group(image.id, LETTERED_QUESTIONS),
                cookies={"access_token": token},
            )
            group_id = r.json()["id"]
            before = [q["id"] for q in r.json()["questions"]]

            r_rename = await client.patch(
                f"/api/question-groups/{group_id}",
                json=_labelling_group(
                    image.id, LETTERED_QUESTIONS, type="diagram_labelling"
                ),
                cookies={"access_token": token},
            )
            assert r_rename.status_code == 200, r_rename.text
            assert [q["id"] for q in r_rename.json()["questions"]] == before
            assert r_rename.json()["config"]["image_width"] == 1240
    finally:
        await _cleanup(material.id, email, image_id=image.id)


# --- Consumption -------------------------------------------------------------


@pytest.mark.asyncio
async def test_take_hands_over_the_picture_and_never_the_answers() -> None:
    email = "label9-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    image = await _make_image()
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, token, material.id)
            await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_labelling_group(image.id, LETTERED_QUESTIONS),
                cookies={"access_token": token},
            )
            await _make_public(material.id)

            r = await client.get(
                f"/api/materials/{material.id}/take",
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text
            group = r.json()["parts"][0]["question_groups"][0]
            assert group["config"]["image_url"].endswith(image.storage_key)
            assert group["config"]["image_height"] == 874
            assert group["config"]["image_letters"] == 6
            assert "correct_answers" not in r.text
            for question in group["questions"]:
                assert set(question) <= {"id", "number", "prompt", "options",
                                         "select_count"}
    finally:
        await _cleanup(material.id, email, image_id=image.id)


@pytest.mark.asyncio
async def test_a_letter_on_a_picture_is_graded_as_a_letter() -> None:
    """The row carries no options to say so — the letters are drawn on an
    image, not stored anywhere — so this only works because grading asks the
    group rather than the question."""
    email = "label10-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    image = await _make_image()
    token = create_access_token(str(owner.id))

    try:
        async with _client() as client:
            part_id = await _seed_part(client, token, material.id)
            r = await client.post(
                f"/api/parts/{part_id}/question-groups",
                json=_labelling_group(image.id, LETTERED_QUESTIONS),
                cookies={"access_token": token},
            )
            questions = r.json()["questions"]
            await _make_public(material.id)

            r_submit = await client.post(
                f"/api/materials/{material.id}/attempts",
                json={
                    "answers": [
                        # Right in the other case, right, and a letter that
                        # isn't the one drawn at the gift shop.
                        {"question_id": questions[0]["id"], "given_answer": " C "},
                        {"question_id": questions[1]["id"], "given_answer": "a"},
                        {"question_id": questions[2]["id"], "given_answer": "b"},
                    ]
                },
                cookies={"access_token": token},
            )
            assert r_submit.status_code == 200, r_submit.text
            body = r_submit.json()
            assert body["score"] == 2
            assert body["total_questions"] == 3
            assert [r["is_correct"] for r in body["results"]] == [True, True, False]
    finally:
        await _cleanup(material.id, email, image_id=image.id)


# --- Publishing --------------------------------------------------------------


async def _blockers(material_id: uuid.UUID) -> list[str]:
    async with async_session_factory() as session:
        material = await session.get(Material, material_id)
        assert material is not None
        return await publishing_service.publish_blockers(session, material)


async def _write_group(
    material_id: uuid.UUID, token: str, payload: dict
) -> tuple[str, list[dict]]:
    async with _client() as client:
        part_id = await _seed_part(client, token, material_id)
        r = await client.post(
            f"/api/parts/{part_id}/question-groups",
            json=payload,
            cookies={"access_token": token},
        )
        assert r.status_code == 201, r.text
        return r.json()["id"], r.json()["questions"]


@pytest.mark.asyncio
async def test_publishing_insists_on_the_picture() -> None:
    """"Label the map below" with no map below is not an unfinished question,
    it is an instruction to look at nothing."""
    email = "label11-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        await _write_group(
            material.id, token, _labelling_group(None, LETTERED_QUESTIONS)
        )
        blockers = await _blockers(material.id)
        assert any("attach the picture the labels go on" in b for b in blockers), blockers
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_publishing_counts_the_letters_against_the_questions() -> None:
    email = "label12-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    image = await _make_image()
    token = create_access_token(str(owner.id))

    try:
        # Three gaps, two letters drawn: a task that cannot be completed
        # however long the author works at it, since each letter marks one
        # place and answers one question.
        await _write_group(
            material.id,
            token,
            _labelling_group(
                image.id,
                [
                    {"number": 1, "correct_answers": ["a"]},
                    {"number": 2, "correct_answers": ["b"]},
                    {"number": 3, "correct_answers": []},
                ],
                letters=2,
            ),
        )
        blockers = await _blockers(material.id)
        assert any(
            "3 questions and only 2 letters on the picture" in b for b in blockers
        ), blockers
    finally:
        await _cleanup(material.id, email, image_id=image.id)


@pytest.mark.asyncio
async def test_publishing_refuses_one_letter_and_repeated_letters() -> None:
    email = "label13-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    image = await _make_image()
    token = create_access_token(str(owner.id))

    try:
        await _write_group(
            material.id,
            token,
            _labelling_group(
                image.id,
                [
                    {"number": 1, "correct_answers": ["a"], "replay_start_ms": 1,
                     "replay_end_ms": 2},
                ],
                letters=1,
                template="Car park | {{1}}",
            ),
        )
        blockers = await _blockers(material.id)
        assert any("nothing to choose between" in b for b in blockers), blockers
    finally:
        await _cleanup(material.id, email, image_id=image.id)


@pytest.mark.asyncio
async def test_two_gaps_cannot_share_a_letter_on_a_picture() -> None:
    """A word box can be told that a letter may be used again; a picture
    cannot. A letter on a map marks one place on it, so two gaps answered "C"
    is a mistake in the key and not a task that permits reuse — which is why
    allow_reuse being set makes no difference here."""
    email = "label14-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    image = await _make_image()
    token = create_access_token(str(owner.id))

    try:
        await _write_group(
            material.id,
            token,
            _labelling_group(
                image.id,
                [
                    {"number": 1, "correct_answers": ["c"], "replay_start_ms": 1,
                     "replay_end_ms": 2},
                    {"number": 2, "correct_answers": ["c"], "replay_start_ms": 3,
                     "replay_end_ms": 4},
                ],
                template="Car park | {{1}}\nCafé | {{2}}",
                allow_reuse=True,
            ),
        )
        blockers = await _blockers(material.id)
        assert any("a letter another question already uses" in b for b in blockers), (
            blockers
        )
    finally:
        await _cleanup(material.id, email, image_id=image.id)


@pytest.mark.asyncio
async def test_an_unanswered_gap_on_a_lettered_picture_asks_for_a_letter() -> None:
    """Not "an accepted answer" — that would send the author looking for a
    field to type words into."""
    email = "label15-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    image = await _make_image()
    token = create_access_token(str(owner.id))

    try:
        await _write_group(
            material.id,
            token,
            _labelling_group(
                image.id,
                [{"number": 1, "correct_answers": []}],
                template="Car park | {{1}}",
            ),
        )
        blockers = await _blockers(material.id)
        assert any("without a letter from the picture" in b for b in blockers), blockers
    finally:
        await _cleanup(material.id, email, image_id=image.id)


@pytest.mark.asyncio
async def test_a_labelling_task_with_its_picture_and_letters_has_nothing_left() -> None:
    """The whole set of rules, satisfied: the picture attached, six letters for
    three gaps, none of them repeated, each linked to the audio. What is left
    blocking publication is only what every material needs."""
    email = "label16-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    image = await _make_image()
    token = create_access_token(str(owner.id))

    try:
        await _write_group(
            material.id, token, _labelling_group(image.id, LETTERED_QUESTIONS)
        )
        blockers = await _blockers(material.id)
        assert not [b for b in blockers if "Part 2" in b], blockers
        # Still not publishable, for reasons that have nothing to do with the
        # picture: no recording is attached to the material.
        assert any("audio" in b for b in blockers), blockers
    finally:
        await _cleanup(material.id, email, image_id=image.id)


@pytest.mark.asyncio
async def test_a_picture_is_only_required_of_the_types_that_draw_one() -> None:
    """The rule is the labelling types', not every completion task's. A set of
    notes with no picture is a set of notes."""
    email = "label17-owner@example.com"
    owner = await _make_user(email)
    material = await _make_material(owner.id)
    token = create_access_token(str(owner.id))

    try:
        await _write_group(
            material.id,
            token,
            _labelling_group(
                None,
                [
                    {"number": 1, "correct_answers": ["9.30"], "replay_start_ms": 1,
                     "replay_end_ms": 2}
                ],
                type="note_completion",
                letters=0,
                template="Opening time | {{1}}",
            ),
        )
        blockers = await _blockers(material.id)
        assert not any("picture" in b for b in blockers), blockers
    finally:
        await _cleanup(material.id, email)


# --- The types themselves ----------------------------------------------------


def test_both_labelling_types_are_completion_tasks() -> None:
    """Which is what lets them share the template, the gap tokens, the
    reconciliation by number and the grading path with the other seven."""
    from app.models.question_group import COMPLETION_TYPES, LABELLING_TYPES

    assert LABELLING_TYPES <= COMPLETION_TYPES
    assert QuestionGroupType.MAP_LABELLING in LABELLING_TYPES
    assert QuestionGroupType.DIAGRAM_LABELLING in LABELLING_TYPES

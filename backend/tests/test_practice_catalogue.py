"""GET /api/listening/practice — what a learner can sit, and what they have
already done with it.

Two things worth pinning down are about what the catalogue REFUSES to show:
an author's unfinished drafts, which belong in the Studio, and anybody else's
attempt history, which belongs to them.

The rest are about the endpoint having become a query. Filtering, ordering
and paging moved out of the browser and into SQL, because at a thousand
materials sending the whole library so the page can hide most of it is half a
megabyte of JSON to show somebody thirty titles. What that makes worth
testing is the seams: that a filter narrows the COUNT and not just the page,
that the facet counts describe the library rather than the page, and that
paging cannot show a row twice or lose one.
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


async def _rows(client: httpx.AsyncClient, token: str, **params) -> list[dict]:
    """One page of the catalogue, as a list.

    ``done=true`` by default because the endpoint now puts materials the
    caller has already sat away, and half of these tests are about what a row
    says once it HAS been sat. ``limit`` is raised for the same reason a test
    looks its material up by id rather than taking the first row: the test
    database holds whatever every other test left behind.
    """
    query = {"done": "true", "limit": 100, **params}
    r = await client.get(
        "/api/listening/practice", params=query, cookies={"access_token": token}
    )
    assert r.status_code == 200, r.text
    return r.json()["items"]


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

            rows = await _rows(client, token)
            row = next(x for x in rows if x["id"] == str(material.id))

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

            rows = await _rows(client, token)
            # Not even to its own author.
            assert all(x["id"] != str(draft.id) for x in rows)
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

            rows = await _rows(client, my_token)
            row = next(x for x in rows if x["id"] == str(material.id))
            assert row["attempts"] == 2
            # Mine, not the better score somebody else got.
            assert row["best_score"] == 1
            assert row["last_attempt_id"] == last_id
            assert row["last_attempt_at"] is not None

            their_rows = await _rows(client, their_token)
            row_other = next(
                x for x in their_rows if x["id"] == str(material.id)
            )
            assert row_other["attempts"] == 1
            assert row_other["best_score"] == 3
    finally:
        await _cleanup([material.id], mine, theirs)


# --- The endpoint as a query ------------------------------------------------


async def _catalogue(client: httpx.AsyncClient, token: str, **params) -> dict:
    """The whole envelope, not just the rows: total, facets and done_hidden
    are the parts a page cannot say about itself."""
    r = await client.get(
        "/api/listening/practice", params=params, cookies={"access_token": token}
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _family(user_id: uuid.UUID, prefix: str, count: int) -> list[Material]:
    """``count`` public listening materials sharing a searchable prefix, so a
    test can find its own rows in a database full of other tests' leftovers."""
    made = []
    for index in range(count):
        material = await _make_material(
            user_id, f"{prefix} number {index}", "public"
        )
        made.append(material)
    return made


@pytest.mark.asyncio
async def test_a_page_is_a_page_and_the_total_is_the_whole_answer() -> None:
    """``limit`` bounds the rows and nothing else. ``total`` counts what
    matched, which is what tells the reader there is more below — a total
    that only counted the page would say "5 materials" over every page of a
    hundred."""
    email = "cat-page@example.com"
    user = await _make_user(email)
    prefix = f"Paging{uuid.uuid4().hex[:8]}"
    made = await _family(user.id, prefix, 5)
    token = create_access_token(str(user.id))

    try:
        async with _client() as client:
            page = await _catalogue(client, token, q=prefix, limit=2)
            assert page["total"] == 5
            assert len(page["items"]) == 2

            # Every row, across three pages, exactly once — the guarantee
            # that makes an infinite scroll not lie.
            seen = []
            for offset in (0, 2, 4):
                page = await _catalogue(
                    client, token, q=prefix, limit=2, offset=offset
                )
                seen.extend(x["id"] for x in page["items"])
            assert len(seen) == 5
            assert len(set(seen)) == 5
            assert set(seen) == {str(m.id) for m in made}
    finally:
        await _cleanup([m.id for m in made], email)


@pytest.mark.asyncio
async def test_search_matches_the_title_and_the_author() -> None:
    """Both, and every term has to hit. The chips above the field select
    part and question type exactly, so the field is for the two things only
    it can find."""
    email = "cat-search@example.com"
    user = await _make_user(email)
    tag = uuid.uuid4().hex[:8]
    mine = await _make_material(user.id, f"Riverside {tag} consultation", "public")
    other = await _make_material(user.id, f"Museum {tag} tour", "public")
    token = create_access_token(str(user.id))

    try:
        async with _client() as client:
            both = await _catalogue(client, token, q=tag)
            assert both["total"] == 2

            # Two terms narrow rather than widen.
            one = await _catalogue(client, token, q=f"{tag} riverside")
            assert [x["id"] for x in one["items"]] == [str(mine.id)]

            # The author's name finds their work without their name being in
            # the title of it.
            by_author = await _catalogue(
                client, token, q=f"{tag} Catalogue"
            )
            assert by_author["total"] == 2

            assert (await _catalogue(client, token, q=f"{tag} nobody"))["total"] == 0
    finally:
        await _cleanup([mine.id, other.id], email)


@pytest.mark.asyncio
async def test_done_materials_are_put_away_and_counted() -> None:
    """The one filter that starts on. It is not silent about it: what it
    holds back comes back as a number, because a list quietly shorter than
    the reader knows the library to be is a list that looks broken."""
    email = "cat-done@example.com"
    user = await _make_user(email)
    prefix = f"Done{uuid.uuid4().hex[:8]}"
    sat = await _make_material(user.id, f"{prefix} sat", "private")
    fresh = await _make_material(user.id, f"{prefix} fresh", "public")
    token = create_access_token(str(user.id))

    try:
        async with _client() as client:
            await _seed(client, token, sat.id)
            await _publish(sat.id)
            r = await client.post(
                f"/api/materials/{sat.id}/attempts",
                json={"answers": []},
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text

            default = await _catalogue(client, token, q=prefix)
            assert [x["id"] for x in default["items"]] == [str(fresh.id)]
            assert default["total"] == 1
            assert default["done_hidden"] == 1

            asked = await _catalogue(client, token, q=prefix, done="true")
            assert asked["total"] == 2
            # Nothing is being held back once they have been asked for, so
            # the line above the list has nothing to say.
            assert asked["done_hidden"] == 0
    finally:
        await _cleanup([sat.id, fresh.id], email)


@pytest.mark.asyncio
async def test_a_part_chip_matches_a_material_that_holds_that_part() -> None:
    """Not "is only that part". Somebody practising their weakest section
    wants material with that part in it, whole papers included."""
    email = "cat-scope@example.com"
    user = await _make_user(email)
    prefix = f"Scope{uuid.uuid4().hex[:8]}"
    material = await _make_material(user.id, f"{prefix} two parts", "private")
    token = create_access_token(str(user.id))

    try:
        async with _client() as client:
            await _seed(client, token, material.id)  # parts 1 and 2
            await _publish(material.id)

            assert (await _catalogue(client, token, q=prefix, scope="1"))["total"] == 1
            assert (await _catalogue(client, token, q=prefix, scope="2"))["total"] == 1
            assert (await _catalogue(client, token, q=prefix, scope="3"))["total"] == 0
            # Two parts is not a full test.
            assert (
                await _catalogue(client, token, q=prefix, scope="full")
            )["total"] == 0
    finally:
        await _cleanup([material.id], email)


@pytest.mark.asyncio
async def test_a_type_filter_matches_a_material_that_asks_that_kind() -> None:
    """A material holding several matches on any one of them — somebody
    looking for multiple choice wants the paper that has some in it."""
    email = "cat-type@example.com"
    user = await _make_user(email)
    prefix = f"Type{uuid.uuid4().hex[:8]}"
    material = await _make_material(user.id, f"{prefix} mixed", "private")
    token = create_access_token(str(user.id))

    try:
        async with _client() as client:
            await _seed(client, token, material.id)  # form completion + choice
            await _publish(material.id)

            for group_type in ("form_completion", "multiple_choice"):
                page = await _catalogue(
                    client, token, q=prefix, types=group_type
                )
                assert page["total"] == 1, group_type

            assert (
                await _catalogue(client, token, q=prefix, types="matching")
            )["total"] == 0
    finally:
        await _cleanup([material.id], email)


@pytest.mark.asyncio
async def test_an_unrefreshed_material_filters_as_new() -> None:
    """The band comes from a projection, and a material created since the
    last refresh has no row in it. Filtering by New has to find exactly those
    — the alternative is a filter that silently drops the newest materials in
    the library, which are the ones most likely to be wanted."""
    email = "cat-band@example.com"
    user = await _make_user(email)
    prefix = f"Band{uuid.uuid4().hex[:8]}"
    material = await _make_material(user.id, f"{prefix} unrated", "public")
    token = create_access_token(str(user.id))

    try:
        async with _client() as client:
            page = await _catalogue(client, token, q=prefix, bands="new")
            assert [x["id"] for x in page["items"]] == [str(material.id)]
            assert page["items"][0]["difficulty"]["band"] == "new"

            assert (
                await _catalogue(client, token, q=prefix, bands="easy")
            )["total"] == 0
    finally:
        await _cleanup([material.id], email)


@pytest.mark.asyncio
async def test_the_facets_describe_the_library_not_the_page() -> None:
    """A count that described the thirty rows in hand is a number nobody can
    act on, and an option that vanishes as you filter is one nobody can aim
    at. So the facets ignore both the page and the filters."""
    email = "cat-facet@example.com"
    user = await _make_user(email)
    prefix = f"Facet{uuid.uuid4().hex[:8]}"
    material = await _make_material(user.id, f"{prefix} mixed", "private")
    token = create_access_token(str(user.id))

    try:
        async with _client() as client:
            await _seed(client, token, material.id)
            await _publish(material.id)

            wide = await _catalogue(client, token)
            narrow = await _catalogue(client, token, q=prefix, limit=1)

            assert narrow["types"] == wide["types"]
            assert narrow["bands"] == wide["bands"]

            counts = {row["value"]: row["count"] for row in wide["types"]}
            assert counts.get("form_completion", 0) >= 1
            assert counts.get("multiple_choice", 0) >= 1
    finally:
        await _cleanup([material.id], email)


@pytest.mark.asyncio
async def test_an_order_the_endpoint_does_not_have_is_refused() -> None:
    """A client asking for a sort that doesn't exist is a client bug, and
    quietly serving it newest-first would hide it."""
    email = "cat-sort@example.com"
    user = await _make_user(email)
    token = create_access_token(str(user.id))

    async with _client() as client:
        r = await client.get(
            "/api/listening/practice",
            params={"sort": "alphabetical"},
            cookies={"access_token": token},
        )
        assert r.status_code == 422

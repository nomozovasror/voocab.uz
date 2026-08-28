"""Collections — what to practise, in what order.

The catalogue answers what exists and the recommendation answers what to do
tonight. A collection is the third question: what a route through the library
looks like when somebody who knows the exam lays one out.

What is worth pinning down is mostly about what a collection REFUSES. It
cannot be published empty, because a published course that opens onto a blank
page is worse than no course. It cannot quietly drop a material on save. It
cannot be edited by anyone but its author, and until it is published it cannot
be seen by them either. And the order it is saved in is the order it comes
back in — a collection whose sequence is not stable is a tag with extra steps.
"""

import uuid

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
from app.models.user import User


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def _user(email: str) -> User:
    async with async_session_factory() as session:
        user = (await session.exec(select(User).where(User.email == email))).first()
        if user is not None:
            return user
        user = User(email=email, display_name=f"Collections {email}")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _material(author_id: uuid.UUID, title: str, visibility: str) -> Material:
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


async def _sit(user_id: uuid.UUID, material_id: uuid.UUID) -> None:
    """A submitted attempt, which is the only kind that counts as done."""
    from datetime import datetime, timezone

    async with async_session_factory() as session:
        session.add(
            Attempt(
                user_id=user_id,
                material_id=material_id,
                status=AttemptStatus.SUBMITTED,
                score=1,
                total_questions=1,
                submitted_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()


async def _cleanup(material_ids: list[uuid.UUID], *emails: str) -> None:
    async with async_session_factory() as session:
        for material_id in material_ids:
            for attempt in (
                await session.exec(
                    select(Attempt).where(Attempt.material_id == material_id)
                )
            ).all():
                await session.delete(attempt)
            await session.flush()
            for item in (
                await session.exec(
                    select(CollectionItem).where(
                        CollectionItem.material_id == material_id
                    )
                )
            ).all():
                await session.delete(item)
            await session.flush()
            # Parts, where a test gave the material any. Nothing here builds
            # question groups, so a part is the deepest this ever goes.
            for part in (
                await session.exec(
                    select(Part).where(Part.material_id == material_id)
                )
            ).all():
                await session.delete(part)
            await session.flush()
            material = await session.get(Material, material_id)
            if material is not None:
                await session.delete(material)
        await session.flush()

        for email in emails:
            user = (
                await session.exec(select(User).where(User.email == email))
            ).first()
            if user is None:
                continue
            for collection in (
                await session.exec(
                    select(Collection).where(Collection.author_id == user.id)
                )
            ).all():
                for item in (
                    await session.exec(
                        select(CollectionItem).where(
                            CollectionItem.collection_id == collection.id
                        )
                    )
                ).all():
                    await session.delete(item)
                await session.flush()
                await session.delete(collection)
            await session.flush()
            await session.delete(user)
        await session.commit()


async def _make(
    client: httpx.AsyncClient, token: str, title: str, summary: str = ""
) -> str:
    r = await client.post(
        "/api/collections",
        json={"title": title, "summary": summary},
        cookies={"access_token": token},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.asyncio
async def test_an_empty_collection_cannot_be_published() -> None:
    """And the refusal says what to do about it. "Cannot publish" without a
    because is a dead end; the author is being told what to fix."""
    email = f"coll-empty-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    token = create_access_token(str(user.id))

    try:
        async with _client() as client:
            collection_id = await _make(client, token, "Empty course")
            r = await client.patch(
                f"/api/collections/{collection_id}",
                json={"visibility": "public"},
                cookies={"access_token": token},
            )
            assert r.status_code == 422
            assert "at least one" in r.json()["detail"]

            # And it is still private, not half-published.
            r = await client.get(
                "/api/studio/collections", cookies={"access_token": token}
            )
            assert r.json()[0]["visibility"] == "private"
    finally:
        await _cleanup([], email)


@pytest.mark.asyncio
async def test_the_order_saved_is_the_order_returned() -> None:
    """The sequence IS the content. A collection whose order is not stable is
    a tag with extra steps."""
    email = f"coll-order-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    token = create_access_token(str(user.id))
    made = [
        await _material(user.id, f"Ordered {i} {uuid.uuid4()}", "public")
        for i in range(3)
    ]

    try:
        async with _client() as client:
            collection_id = await _make(client, token, "Ordered course")
            wanted = [str(made[2].id), str(made[0].id), str(made[1].id)]
            r = await client.put(
                f"/api/collections/{collection_id}/items",
                json={"material_ids": wanted},
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text

            r = await client.get(
                f"/api/collections/{collection_id}",
                cookies={"access_token": token},
            )
            assert [x["id"] for x in r.json()["items"]] == wanted

            # Reversed, in one save. Rewriting the whole list is what lets an
            # arbitrary reorder pass a unique index on the position: at no
            # point do two rows hold the same one.
            r = await client.put(
                f"/api/collections/{collection_id}/items",
                json={"material_ids": list(reversed(wanted))},
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text
            r = await client.get(
                f"/api/collections/{collection_id}",
                cookies={"access_token": token},
            )
            assert [x["id"] for x in r.json()["items"]] == list(reversed(wanted))
    finally:
        await _cleanup([m.id for m in made], email)


@pytest.mark.asyncio
async def test_a_material_appears_once_however_often_it_is_sent() -> None:
    """A drag that lands something where it already is should be a no-op, not
    an error message."""
    email = f"coll-dupe-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    token = create_access_token(str(user.id))
    material = await _material(user.id, f"Dupe {uuid.uuid4()}", "public")

    try:
        async with _client() as client:
            collection_id = await _make(client, token, "Duplicating course")
            r = await client.put(
                f"/api/collections/{collection_id}/items",
                json={"material_ids": [str(material.id)] * 3},
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text
            assert r.json()["item_count"] == 1
    finally:
        await _cleanup([material.id], email)


@pytest.mark.asyncio
async def test_somebody_elses_draft_cannot_be_put_in_a_collection() -> None:
    """Anybody's PUBLISHED material may go in — that is what makes a curated
    route through the library possible — but an unpublished one belongs to its
    author alone, and a collection is not a way around that.

    Refused rather than silently dropped: a save that quietly loses a material
    is a save button nobody trusts again.
    """
    mine = f"coll-mine-{uuid.uuid4().hex[:8]}@example.com"
    theirs = f"coll-theirs-{uuid.uuid4().hex[:8]}@example.com"
    me = await _user(mine)
    them = await _user(theirs)
    token = create_access_token(str(me.id))
    their_draft = await _material(them.id, f"Draft {uuid.uuid4()}", "private")
    their_public = await _material(them.id, f"Public {uuid.uuid4()}", "public")

    try:
        async with _client() as client:
            collection_id = await _make(client, token, "Curated course")

            r = await client.put(
                f"/api/collections/{collection_id}/items",
                json={"material_ids": [str(their_draft.id)]},
                cookies={"access_token": token},
            )
            assert r.status_code == 422
            assert "not yours and not published" in r.json()["detail"]

            # Their published one is fine.
            r = await client.put(
                f"/api/collections/{collection_id}/items",
                json={"material_ids": [str(their_public.id)]},
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text
            assert r.json()["item_count"] == 1
    finally:
        await _cleanup([their_draft.id, their_public.id], mine, theirs)


@pytest.mark.asyncio
async def test_a_learner_sees_only_the_published_materials_in_it() -> None:
    """An author may build a course beside their drafts — refusing that would
    make the two halves of the job impossible to do in one sitting — but a
    draft is not shown to anybody else, in a collection or out of it.

    So the two counts differ, and the author is told both rather than the
    difference being hidden until somebody asks why their course looks short.
    """
    email = f"coll-mixed-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    token = create_access_token(str(user.id))
    published = await _material(user.id, f"Shown {uuid.uuid4()}", "public")
    draft = await _material(user.id, f"Hidden {uuid.uuid4()}", "private")

    try:
        async with _client() as client:
            collection_id = await _make(client, token, "Mixed course")
            r = await client.put(
                f"/api/collections/{collection_id}/items",
                json={"material_ids": [str(published.id), str(draft.id)]},
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text
            assert r.json()["item_count"] == 2
            assert r.json()["public_item_count"] == 1

            r = await client.get(
                f"/api/collections/{collection_id}",
                cookies={"access_token": token},
            )
            assert [x["id"] for x in r.json()["items"]] == [str(published.id)]
    finally:
        await _cleanup([published.id, draft.id], email)


@pytest.mark.asyncio
async def test_progress_is_counted_from_attempts_not_from_enrolment() -> None:
    """Nothing is stored when somebody opens a collection, so there is no
    enrolment row that can disagree with what they have actually sat.

    ``next_material_id`` is the first UNSAT one in order, not the nearest: the
    sequence is somebody's judgement about what to do when, and picking up in
    the middle means picking up where the sequence says.
    """
    email = f"coll-progress-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    token = create_access_token(str(user.id))
    made = [
        await _material(user.id, f"Progress {i} {uuid.uuid4()}", "public")
        for i in range(3)
    ]

    try:
        async with _client() as client:
            collection_id = await _make(client, token, "Progress course")
            await client.put(
                f"/api/collections/{collection_id}/items",
                json={"material_ids": [str(m.id) for m in made]},
                cookies={"access_token": token},
            )

            r = await client.get(
                f"/api/collections/{collection_id}",
                cookies={"access_token": token},
            )
            assert r.json()["progress"] == {
                "total": 3,
                "done": 0,
                "next_material_id": str(made[0].id),
            }

            # Sitting the FIRST one moves the marker to the second.
            await _sit(user.id, made[0].id)
            r = await client.get(
                f"/api/collections/{collection_id}",
                cookies={"access_token": token},
            )
            assert r.json()["progress"]["done"] == 1
            assert r.json()["progress"]["next_material_id"] == str(made[1].id)

            # Skipping ahead to the third leaves the marker on the second: the
            # order is the point.
            await _sit(user.id, made[2].id)
            r = await client.get(
                f"/api/collections/{collection_id}",
                cookies={"access_token": token},
            )
            assert r.json()["progress"]["done"] == 2
            assert r.json()["progress"]["next_material_id"] == str(made[1].id)

            await _sit(user.id, made[1].id)
            r = await client.get(
                f"/api/collections/{collection_id}",
                cookies={"access_token": token},
            )
            assert r.json()["progress"]["done"] == 3
            assert r.json()["progress"]["next_material_id"] is None
    finally:
        await _cleanup([m.id for m in made], email)


@pytest.mark.asyncio
async def test_an_unpublished_collection_is_invisible_to_everyone_else() -> None:
    """A 404 rather than a 403, for the same reason a private material is:
    confirming which ids exist leaks what somebody is working on."""
    mine = f"coll-priv-{uuid.uuid4().hex[:8]}@example.com"
    theirs = f"coll-nosy-{uuid.uuid4().hex[:8]}@example.com"
    me = await _user(mine)
    them = await _user(theirs)
    my_token = create_access_token(str(me.id))
    their_token = create_access_token(str(them.id))

    try:
        async with _client() as client:
            collection_id = await _make(client, my_token, "Unfinished course")

            # Its author can see it — that is how they check what they built.
            r = await client.get(
                f"/api/collections/{collection_id}",
                cookies={"access_token": my_token},
            )
            assert r.status_code == 200

            r = await client.get(
                f"/api/collections/{collection_id}",
                cookies={"access_token": their_token},
            )
            assert r.status_code == 404

            # And it is not in anybody's listing, including its author's — the
            # public list is what is published, and the studio list is where
            # an author finds their own.
            r = await client.get("/api/collections", cookies={"access_token": my_token})
            assert all(x["id"] != collection_id for x in r.json()["items"])
    finally:
        await _cleanup([], mine, theirs)


@pytest.mark.asyncio
async def test_only_the_author_can_change_it() -> None:
    """A 403 here rather than a 404, because a published collection's
    existence is not a secret — what is refused is the write."""
    mine = f"coll-owner-{uuid.uuid4().hex[:8]}@example.com"
    theirs = f"coll-other-{uuid.uuid4().hex[:8]}@example.com"
    me = await _user(mine)
    them = await _user(theirs)
    my_token = create_access_token(str(me.id))
    their_token = create_access_token(str(them.id))
    material = await _material(me.id, f"Owned {uuid.uuid4()}", "public")

    try:
        async with _client() as client:
            collection_id = await _make(client, my_token, "Owned course")
            await client.put(
                f"/api/collections/{collection_id}/items",
                json={"material_ids": [str(material.id)]},
                cookies={"access_token": my_token},
            )
            await client.patch(
                f"/api/collections/{collection_id}",
                json={"visibility": "public"},
                cookies={"access_token": my_token},
            )

            for call in (
                client.patch(
                    f"/api/collections/{collection_id}",
                    json={"title": "Mine now"},
                    cookies={"access_token": their_token},
                ),
                client.put(
                    f"/api/collections/{collection_id}/items",
                    json={"material_ids": []},
                    cookies={"access_token": their_token},
                ),
                client.delete(
                    f"/api/collections/{collection_id}",
                    cookies={"access_token": their_token},
                ),
            ):
                r = await call
                assert r.status_code == 403, r.text
    finally:
        await _cleanup([material.id], mine, theirs)


@pytest.mark.asyncio
async def test_emptying_a_published_collection_withdraws_it() -> None:
    """Rather than refusing the save. The author's work is never rejected to
    protect a flag — but a published course with nothing in it is a promise on
    the catalogue page that opens onto a blank screen, so it goes back to
    being a draft.
    """
    email = f"coll-withdraw-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    token = create_access_token(str(user.id))
    material = await _material(user.id, f"Only one {uuid.uuid4()}", "public")

    try:
        async with _client() as client:
            collection_id = await _make(client, token, "Shrinking course")
            await client.put(
                f"/api/collections/{collection_id}/items",
                json={"material_ids": [str(material.id)]},
                cookies={"access_token": token},
            )
            r = await client.patch(
                f"/api/collections/{collection_id}",
                json={"visibility": "public"},
                cookies={"access_token": token},
            )
            assert r.json()["visibility"] == "public"

            r = await client.put(
                f"/api/collections/{collection_id}/items",
                json={"material_ids": []},
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text
            assert r.json()["visibility"] == "private"
            assert r.json()["blocker"] is not None
    finally:
        await _cleanup([material.id], email)


@pytest.mark.asyncio
async def test_deleting_a_collection_leaves_its_materials_alone() -> None:
    """The whole point of a collection being a list of references rather than
    a container. It is also why deleting one needs no are-you-sure about
    content that is not going anywhere."""
    email = f"coll-del-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    token = create_access_token(str(user.id))
    material = await _material(user.id, f"Survivor {uuid.uuid4()}", "public")

    try:
        async with _client() as client:
            collection_id = await _make(client, token, "Doomed course")
            await client.put(
                f"/api/collections/{collection_id}/items",
                json={"material_ids": [str(material.id)]},
                cookies={"access_token": token},
            )
            r = await client.delete(
                f"/api/collections/{collection_id}",
                cookies={"access_token": token},
            )
            assert r.status_code == 204

        async with async_session_factory() as session:
            assert await session.get(Material, material.id) is not None
            assert await session.get(Collection, uuid.UUID(collection_id)) is None
            items = (
                await session.exec(
                    select(CollectionItem).where(
                        CollectionItem.collection_id == uuid.UUID(collection_id)
                    )
                )
            ).all()
            assert items == []
    finally:
        await _cleanup([material.id], email)


@pytest.mark.asyncio
async def test_the_list_leads_with_what_is_half_finished() -> None:
    """In progress, then untouched, then finished.

    Not newest-first, and the difference is the point: what somebody wants
    from a list of courses is the one they were in the middle of, and only
    after that the one that is new. Finished ones go last rather than being
    hidden — they are the record of what has been worked through.
    """
    email = f"coll-rank-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    token = create_access_token(str(user.id))
    made = [
        await _material(user.id, f"Rank {i} {uuid.uuid4()}", "public")
        for i in range(3)
    ]

    try:
        async with _client() as client:
            # Created oldest to newest: finished, untouched, half-done. If the
            # order were by date this would come back exactly reversed.
            finished = await _make(client, token, f"ZZfinished {uuid.uuid4().hex[:6]}")
            untouched = await _make(client, token, f"ZZuntouched {uuid.uuid4().hex[:6]}")
            halfway = await _make(client, token, f"ZZhalfway {uuid.uuid4().hex[:6]}")

            for collection_id, ids in (
                (finished, [made[0].id]),
                (untouched, [made[1].id]),
                (halfway, [made[1].id, made[2].id]),
            ):
                await client.put(
                    f"/api/collections/{collection_id}/items",
                    json={"material_ids": [str(m) for m in ids]},
                    cookies={"access_token": token},
                )
                await client.patch(
                    f"/api/collections/{collection_id}",
                    json={"visibility": "public"},
                    cookies={"access_token": token},
                )

            await _sit(user.id, made[0].id)  # finishes the first
            await _sit(user.id, made[2].id)  # one of the two in `halfway`

            r = await client.get(
                "/api/collections",
                params={"q": "ZZ"},
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["total"] == 3
            assert [x["id"] for x in body["items"]] == [halfway, untouched, finished]
    finally:
        await _cleanup([m.id for m in made], email)


@pytest.mark.asyncio
async def test_a_page_of_collections_still_says_how_many_there_are() -> None:
    """The strip on the practice page shows a handful. A handful with no idea
    how many it is a handful OF looks truncated by accident."""
    email = f"coll-page-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    token = create_access_token(str(user.id))
    material = await _material(user.id, f"Paged {uuid.uuid4()}", "public")
    tag = f"YY{uuid.uuid4().hex[:6]}"

    try:
        async with _client() as client:
            for i in range(3):
                collection_id = await _make(client, token, f"{tag} course {i}")
                await client.put(
                    f"/api/collections/{collection_id}/items",
                    json={"material_ids": [str(material.id)]},
                    cookies={"access_token": token},
                )
                await client.patch(
                    f"/api/collections/{collection_id}",
                    json={"visibility": "public"},
                    cookies={"access_token": token},
                )

            r = await client.get(
                "/api/collections",
                params={"q": tag, "limit": 2},
                cookies={"access_token": token},
            )
            assert len(r.json()["items"]) == 2
            assert r.json()["total"] == 3

            seen = []
            for offset in (0, 2):
                r = await client.get(
                    "/api/collections",
                    params={"q": tag, "limit": 2, "offset": offset},
                    cookies={"access_token": token},
                )
                seen += [x["id"] for x in r.json()["items"]]
            assert len(set(seen)) == 3
    finally:
        await _cleanup([material.id], email)


@pytest.mark.asyncio
async def test_collections_are_searchable_by_title_and_by_author() -> None:
    """The same field searches both lists, so it had better find a course the
    way it finds a material."""
    email = f"coll-search-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    token = create_access_token(str(user.id))
    material = await _material(user.id, f"Searchable {uuid.uuid4()}", "public")
    tag = uuid.uuid4().hex[:8]

    try:
        async with _client() as client:
            collection_id = await _make(client, token, f"Riverside {tag} set")
            await client.put(
                f"/api/collections/{collection_id}/items",
                json={"material_ids": [str(material.id)]},
                cookies={"access_token": token},
            )
            await client.patch(
                f"/api/collections/{collection_id}",
                json={"visibility": "public"},
                cookies={"access_token": token},
            )

            for query in (tag, f"{tag} riverside", f"{tag} Collections"):
                r = await client.get(
                    "/api/collections",
                    params={"q": query},
                    cookies={"access_token": token},
                )
                assert r.json()["total"] == 1, query

            r = await client.get(
                "/api/collections",
                params={"q": f"{tag} nothing"},
                cookies={"access_token": token},
            )
            assert r.json()["total"] == 0
    finally:
        await _cleanup([material.id], email)


@pytest.mark.asyncio
async def test_the_status_filter_narrows_the_count_as_well_as_the_page() -> None:
    """The same computation the ordering uses, asked as a question.

    ``total`` has to count what survives it: a filtered list reporting the
    unfiltered total is a list that looks like it lost something between the
    header and the rows.
    """
    email = f"coll-status-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    token = create_access_token(str(user.id))
    made = [
        await _material(user.id, f"Status {i} {uuid.uuid4()}", "public")
        for i in range(3)
    ]
    tag = f"XX{uuid.uuid4().hex[:6]}"

    try:
        async with _client() as client:
            finished = await _make(client, token, f"{tag} finished")
            untouched = await _make(client, token, f"{tag} untouched")
            halfway = await _make(client, token, f"{tag} halfway")

            for collection_id, ids in (
                (finished, [made[0].id]),
                (untouched, [made[1].id]),
                (halfway, [made[1].id, made[2].id]),
            ):
                await client.put(
                    f"/api/collections/{collection_id}/items",
                    json={"material_ids": [str(m) for m in ids]},
                    cookies={"access_token": token},
                )
                await client.patch(
                    f"/api/collections/{collection_id}",
                    json={"visibility": "public"},
                    cookies={"access_token": token},
                )

            await _sit(user.id, made[0].id)
            await _sit(user.id, made[2].id)

            async def ids_for(status: str) -> tuple[list[str], int]:
                r = await client.get(
                    "/api/collections",
                    params={"q": tag, "status": status},
                    cookies={"access_token": token},
                )
                assert r.status_code == 200, r.text
                return [x["id"] for x in r.json()["items"]], r.json()["total"]

            assert await ids_for("in_progress") == ([halfway], 1)
            assert await ids_for("not_started") == ([untouched], 1)
            assert await ids_for("finished") == ([finished], 1)
            everything, total = await ids_for("all")
            assert total == 3
            assert len(everything) == 3
    finally:
        await _cleanup([m.id for m in made], email)


@pytest.mark.asyncio
async def test_a_status_the_endpoint_does_not_have_is_refused() -> None:
    email = f"coll-badstatus-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    token = create_access_token(str(user.id))
    async with _client() as client:
        r = await client.get(
            "/api/collections",
            params={"status": "abandoned"},
            cookies={"access_token": token},
        )
        assert r.status_code == 422
    await _cleanup([], email)


async def _material_with_parts(
    author_id: uuid.UUID, title: str, parts: list[int]
) -> Material:
    """A public material holding exactly the named parts. Built directly: what
    is under test is which collections cover what, not the authoring flow."""
    from app.models.part import Part

    material = await _material(author_id, title, "public")
    async with async_session_factory() as session:
        for number in parts:
            session.add(
                Part(
                    material_id=material.id,
                    order_index=number - 1,
                    title=f"Part {number}",
                )
            )
        await session.commit()
    return material


@pytest.mark.asyncio
async def test_covers_finds_the_course_that_drills_a_part() -> None:
    """The catalogue's own part filter, asked of a route through several
    papers: does this course have Part 3 in it. A whole paper answers to its
    parts AND to "full", because a mock-test set and a Part 3 drill are two
    different things somebody might be looking for."""
    email = f"coll-covers-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    token = create_access_token(str(user.id))
    part_three = await _material_with_parts(user.id, f"P3 {uuid.uuid4()}", [3])
    whole = await _material_with_parts(user.id, f"Whole {uuid.uuid4()}", [1, 2, 3, 4])
    made = [part_three, whole]
    tag = f"CV{uuid.uuid4().hex[:6]}"

    try:
        async with _client() as client:
            drill = await _make(client, token, f"{tag} part three drill")
            mocks = await _make(client, token, f"{tag} mock tests")
            for collection_id, ids in ((drill, [part_three.id]), (mocks, [whole.id])):
                await client.put(
                    f"/api/collections/{collection_id}/items",
                    json={"material_ids": [str(m) for m in ids]},
                    cookies={"access_token": token},
                )
                await client.patch(
                    f"/api/collections/{collection_id}",
                    json={"visibility": "public"},
                    cookies={"access_token": token},
                )

            async def ids_for(**params) -> list[str]:
                r = await client.get(
                    "/api/collections",
                    params={"q": tag, **params},
                    cookies={"access_token": token},
                )
                assert r.status_code == 200, r.text
                return [x["id"] for x in r.json()["items"]]

            assert sorted(await ids_for(covers="3")) == sorted([drill, mocks])
            assert await ids_for(covers="1") == [mocks]
            # Only the whole paper is a full test; a Part 3 drill is not one.
            assert await ids_for(covers="full") == [mocks]
    finally:
        await _cleanup([m.id for m in made], email)


@pytest.mark.asyncio
async def test_length_bands_and_their_counts() -> None:
    """How much of somebody's life a course wants, at a glance. The facet
    counts come from every published collection rather than from what the
    other filters left, so a menu can never offer an option that returns
    nothing."""
    email = f"coll-length-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    token = create_access_token(str(user.id))
    made = [
        await _material(user.id, f"Len {i} {uuid.uuid4()}", "public")
        for i in range(7)
    ]
    tag = f"LN{uuid.uuid4().hex[:6]}"

    try:
        async with _client() as client:
            short = await _make(client, token, f"{tag} short")
            medium = await _make(client, token, f"{tag} medium")
            for collection_id, ids in (
                (short, [m.id for m in made[:3]]),
                (medium, [m.id for m in made]),
            ):
                await client.put(
                    f"/api/collections/{collection_id}/items",
                    json={"material_ids": [str(m) for m in ids]},
                    cookies={"access_token": token},
                )
                await client.patch(
                    f"/api/collections/{collection_id}",
                    json={"visibility": "public"},
                    cookies={"access_token": token},
                )

            r = await client.get(
                "/api/collections",
                params={"q": tag, "length": "short"},
                cookies={"access_token": token},
            )
            assert [x["id"] for x in r.json()["items"]] == [short]
            assert r.json()["total"] == 1
            # A menu's own dimension is excluded from its own counts, so
            # picking Short does not collapse the length menu to Short: every
            # option still reports the list it would give.
            lengths = {row["value"]: row["count"] for row in r.json()["lengths"]}
            assert lengths["short"] >= 1 and lengths["medium"] >= 1

            r = await client.get(
                "/api/collections",
                params={"q": tag, "length": "long"},
                cookies={"access_token": token},
            )
            assert r.json()["total"] == 0
    finally:
        await _cleanup([m.id for m in made], email)


@pytest.mark.asyncio
async def test_a_filter_value_the_endpoint_does_not_have_is_refused() -> None:
    email = f"coll-badfilter-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    token = create_access_token(str(user.id))
    async with _client() as client:
        for params in ({"covers": "9"}, {"length": "epic"}):
            r = await client.get(
                "/api/collections", params=params, cookies={"access_token": token}
            )
            assert r.status_code == 422, params
    await _cleanup([], email)


@pytest.mark.asyncio
async def test_a_facet_count_is_the_list_one_click_away() -> None:
    """Each count is what that option would leave GIVEN what else is set.

    The alternative — counting over the whole library — is what the catalogue
    does, and it is wrong here: with a dozen courses and three menus over
    them, a count that promised twelve and delivered none would be worse than
    no count at all.
    """
    email = f"coll-facet-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    token = create_access_token(str(user.id))
    part_one = await _material_with_parts(user.id, f"F1 {uuid.uuid4()}", [1])
    part_two = await _material_with_parts(user.id, f"F2 {uuid.uuid4()}", [2])
    made = [part_one, part_two]
    tag = f"FC{uuid.uuid4().hex[:6]}"

    try:
        async with _client() as client:
            ones = await _make(client, token, f"{tag} part ones")
            twos = await _make(client, token, f"{tag} part twos")
            for collection_id, ids in ((ones, [part_one.id]), (twos, [part_two.id])):
                await client.put(
                    f"/api/collections/{collection_id}/items",
                    json={"material_ids": [str(m) for m in ids]},
                    cookies={"access_token": token},
                )
                await client.patch(
                    f"/api/collections/{collection_id}",
                    json={"visibility": "public"},
                    cookies={"access_token": token},
                )

            # Unfiltered, both parts are on offer.
            r = await client.get(
                "/api/collections",
                params={"q": tag},
                cookies={"access_token": token},
            )
            covers = {row["value"]: row["count"] for row in r.json()["covers"]}
            assert covers["1"] == 1 and covers["2"] == 1

            # Narrowed to Finished — nothing has been sat — every option
            # honestly reports nothing, rather than still advertising two.
            r = await client.get(
                "/api/collections",
                params={"q": tag, "status": "finished"},
                cookies={"access_token": token},
            )
            covers = {row["value"]: row["count"] for row in r.json()["covers"]}
            assert covers["1"] == 0 and covers["2"] == 0
            assert r.json()["total"] == 0
    finally:
        await _cleanup([m.id for m in made], email)


@pytest.mark.asyncio
async def test_a_published_collection_that_became_empty_is_not_listed() -> None:
    """Publishing an empty one is refused, but one can become empty
    afterwards — the last material in it is withdrawn, or deleted and the item
    cascades away. What is left is a published promise that opens onto a blank
    page, which is the thing the publish rule exists to prevent.

    Its author still sees it in the studio, with the reason it cannot go out.
    """
    email = f"coll-hollow-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    token = create_access_token(str(user.id))
    material = await _material(user.id, f"Hollow {uuid.uuid4()}", "public")
    tag = f"HL{uuid.uuid4().hex[:6]}"

    try:
        async with _client() as client:
            collection_id = await _make(client, token, f"{tag} course")
            await client.put(
                f"/api/collections/{collection_id}/items",
                json={"material_ids": [str(material.id)]},
                cookies={"access_token": token},
            )
            await client.patch(
                f"/api/collections/{collection_id}",
                json={"visibility": "public"},
                cookies={"access_token": token},
            )
            r = await client.get(
                "/api/collections", params={"q": tag}, cookies={"access_token": token}
            )
            assert r.json()["total"] == 1

            # The material goes, and its place in the course goes with it.
            async with async_session_factory() as session:
                for item in (
                    await session.exec(
                        select(CollectionItem).where(
                            CollectionItem.material_id == material.id
                        )
                    )
                ).all():
                    await session.delete(item)
                await session.commit()

            r = await client.get(
                "/api/collections", params={"q": tag}, cookies={"access_token": token}
            )
            assert r.json()["total"] == 0

            # Still the author's, and still explained.
            r = await client.get(
                "/api/studio/collections", cookies={"access_token": token}
            )
            mine = next(x for x in r.json() if x["id"] == collection_id)
            assert mine["item_count"] == 0
            assert mine["blocker"] is not None
    finally:
        await _cleanup([material.id], email)


@pytest.mark.asyncio
async def test_a_collection_reports_how_the_caller_has_done_in_it() -> None:
    """First-try average is the headline; best-of is absent until something
    has actually been sat twice.

    With no retries the two are the same number under different names, and
    two identical figures labelled differently is a panel asking to be
    decoded rather than read.
    """
    from datetime import datetime, timezone

    email = f"coll-stats-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    token = create_access_token(str(user.id))
    made = [
        await _material(user.id, f"Stat {i} {uuid.uuid4()}", "public")
        for i in range(2)
    ]

    async def sit(material_id, score, total, spent_ms):
        async with async_session_factory() as session:
            session.add(
                Attempt(
                    user_id=user.id,
                    material_id=material_id,
                    status=AttemptStatus.SUBMITTED,
                    score=score,
                    total_questions=total,
                    time_spent_ms=spent_ms,
                    submitted_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()

    try:
        async with _client() as client:
            collection_id = await _make(client, token, f"Stats {uuid.uuid4().hex[:6]}")
            await client.put(
                f"/api/collections/{collection_id}/items",
                json={"material_ids": [str(m.id) for m in made]},
                cookies={"access_token": token},
            )

            await sit(made[0].id, 6, 10, 600_000)   # 60% on the first try
            await sit(made[1].id, 8, 10, 300_000)   # 80% on the first try

            r = await client.get(
                f"/api/collections/{collection_id}",
                cookies={"access_token": token},
            )
            stats = r.json()["stats"]
            assert stats["first_try_avg_pct"] == 70
            assert stats["best_avg_pct"] is None  # nothing sat twice yet
            assert stats["time_spent_ms"] == 900_000

            # A retake: the first-try average is untouched, the best-of
            # appears, and the time counts the second evening too.
            await sit(made[0].id, 10, 10, 200_000)
            r = await client.get(
                f"/api/collections/{collection_id}",
                cookies={"access_token": token},
            )
            stats = r.json()["stats"]
            assert stats["first_try_avg_pct"] == 70
            assert stats["best_avg_pct"] == 90
            assert stats["time_spent_ms"] == 1_100_000

            # And the row carries the FIRST score alongside the best, which is
            # what the grid on that page colours by.
            row = next(
                x for x in r.json()["items"] if x["id"] == str(made[0].id)
            )
            assert row["first_score"] == 6
            assert row["best_score"] == 10
    finally:
        await _cleanup([m.id for m in made], email)

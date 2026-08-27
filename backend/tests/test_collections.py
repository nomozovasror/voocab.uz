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

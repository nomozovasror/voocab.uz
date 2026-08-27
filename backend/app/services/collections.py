"""Collections: what to do, in what order.

The catalogue answers "what exists" and the recommendation answers "what
should I do tonight". This answers the question neither can: what a sequence
of study looks like when somebody who knows the exam has laid one out.

Three decisions worth knowing before changing anything here.

**Progress is derived, never stored.** How far somebody is through a
collection is counted from the attempts they have already made, so opening one
commits them to nothing, abandoning it leaves nothing behind, and there is no
enrolment row that can disagree with the attempts. It is the same argument as
difficulty being a measurement: state you can recompute is state that cannot
rot. Unlike difficulty it is also cheap — a collection is ten materials, not a
library — so it is computed per request with no projection behind it.

**The item list is written whole.** Reordering rows one at a time through a
unique index is a dance of temporary values that has to be got exactly right;
replacing the list has no intermediate state to get wrong. Same reason a
question group and its questions are written as one unit.

**A learner sees only the public materials in a public collection.** An author
building a course beside their drafts can add them as they go — refusing that
would make the two halves of the job impossible to do in one sitting — but a
draft is not offered to anybody else, in a collection or out of it. What that
costs is a course that can look shorter to a learner than to its author, so
the author is told the count both ways (:func:`for_author`).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlmodel import select

from app.core.database import AsyncSession
from app.models.attempt import Attempt, AttemptStatus
from app.models.collection import Collection, CollectionItem
from app.models.material import Material
from app.models.user import User
from app.services import listening as listening_service

#: A collection can be published once it has this many public materials in it.
#: One, and the number is not the interesting part — what matters is that an
#: EMPTY collection cannot be published. A course with nothing in it is a
#: promise on the catalogue page that opens onto a blank screen.
MIN_PUBLIC_ITEMS = 1


async def get(
    session: AsyncSession, collection_id: uuid.UUID
) -> Collection | None:
    return await session.get(Collection, collection_id)


async def create(
    session: AsyncSession, author_id: uuid.UUID, *, title: str, summary: str = ""
) -> Collection:
    collection = Collection(author_id=author_id, title=title, summary=summary)
    session.add(collection)
    await session.commit()
    await session.refresh(collection)
    return collection


async def update(
    session: AsyncSession,
    collection: Collection,
    *,
    title: str | None = None,
    summary: str | None = None,
    visibility: str | None = None,
) -> Collection:
    """Rename, re-describe, publish or withdraw.

    Publishing is the only one that can be refused, and it is refused here
    rather than at the API so that nothing can reach the database having
    skipped the check — see :func:`can_publish`.
    """
    if title is not None:
        collection.title = title
    if summary is not None:
        collection.summary = summary
    if visibility is not None:
        collection.visibility = visibility
    collection.updated_at = datetime.now(timezone.utc)
    session.add(collection)
    await session.commit()
    await session.refresh(collection)
    return collection


async def delete(session: AsyncSession, collection: Collection) -> None:
    """Remove the collection. The items go with it at the database level —
    an item is not a fact about anything once its collection is gone — and
    the materials themselves are untouched, which is the whole point of a
    collection being a list of references rather than a container."""
    await session.delete(collection)
    await session.commit()


async def public_item_count(
    session: AsyncSession, collection_id: uuid.UUID
) -> int:
    return int(
        (
            await session.exec(
                select(func.count(CollectionItem.material_id))
                .select_from(CollectionItem)
                .join(Material, Material.id == CollectionItem.material_id)  # type: ignore[arg-type]
                .where(
                    CollectionItem.collection_id == collection_id,
                    Material.visibility == "public",
                )
            )
        ).one()
    )


async def can_publish(session: AsyncSession, collection: Collection) -> str | None:
    """``None`` if it may be published, or the reason it may not.

    A sentence rather than a boolean, because the studio has to tell the
    author what to fix and a boolean makes it guess. The same shape as the
    publishing rules for materials.
    """
    if not collection.title.strip():
        return "Give it a title first."
    if await public_item_count(session, collection.id) < MIN_PUBLIC_ITEMS:
        return (
            "Add at least one published material. A collection with nothing "
            "in it opens onto a blank page."
        )
    return None


async def set_items(
    session: AsyncSession,
    collection: Collection,
    material_ids: list[uuid.UUID],
) -> None:
    """Replace the whole ordered list.

    Duplicates are dropped rather than refused, keeping the first position of
    each: a drag that lands a material where it already is should not be an
    error message, it should be a no-op.

    Delete-then-insert in one transaction, which is what makes the unique
    index on (collection_id, order_index) survive an arbitrary reorder — at no
    point do two rows hold the same position.
    """
    seen: list[uuid.UUID] = []
    for material_id in material_ids:
        if material_id not in seen:
            seen.append(material_id)

    for item in (
        await session.exec(
            select(CollectionItem).where(
                CollectionItem.collection_id == collection.id
            )
        )
    ).all():
        await session.delete(item)
    await session.flush()

    for index, material_id in enumerate(seen):
        session.add(
            CollectionItem(
                collection_id=collection.id,
                material_id=material_id,
                order_index=index,
            )
        )
    collection.updated_at = datetime.now(timezone.utc)
    session.add(collection)
    await session.commit()


async def _item_ids(
    session: AsyncSession, collection_id: uuid.UUID, *, public_only: bool
) -> list[uuid.UUID]:
    """The materials in this collection, in order."""
    statement = (
        select(CollectionItem.material_id)
        .select_from(CollectionItem)
        .join(Material, Material.id == CollectionItem.material_id)  # type: ignore[arg-type]
        .where(CollectionItem.collection_id == collection_id)
        .order_by(CollectionItem.order_index)  # type: ignore[arg-type]
    )
    if public_only:
        statement = statement.where(Material.visibility == "public")
    return list((await session.exec(statement)).all())


async def progress(
    session: AsyncSession, user_id: uuid.UUID, material_ids: list[uuid.UUID]
) -> dict:
    """How far one learner is through one ordered list.

    ``done`` counts materials with at least one SUBMITTED attempt — the same
    rule the catalogue's tick and the statistics panel use, so the three
    cannot disagree about what "done" means. Started and abandoned is not
    done.

    ``next_material_id`` is the first one they have not sat, IN ORDER, which
    is the difference between a collection and a filter: the sequence is
    somebody's judgement about what to do when, and picking up in the middle
    should mean picking up where the sequence says, not wherever is nearest.
    ``None`` means finished.
    """
    if not material_ids:
        return {"total": 0, "done": 0, "next_material_id": None}

    sat = set(
        (
            await session.exec(
                select(Attempt.material_id)
                .where(
                    Attempt.user_id == user_id,
                    Attempt.material_id.in_(material_ids),  # type: ignore[attr-defined]
                    Attempt.status == AttemptStatus.SUBMITTED,
                )
                .distinct()
            )
        ).all()
    )
    unsat = [mid for mid in material_ids if mid not in sat]
    return {
        "total": len(material_ids),
        "done": len(material_ids) - len(unsat),
        "next_material_id": unsat[0] if unsat else None,
    }


def _summarise(collection: Collection, author: User | None) -> dict:
    return {
        "id": collection.id,
        "title": collection.title,
        "summary": collection.summary,
        "visibility": collection.visibility,
        "created_at": collection.created_at,
        "author": (
            {
                "id": author.id,
                "display_name": author.display_name,
                "avatar_url": author.avatar_url,
            }
            if author is not None
            else None
        ),
    }


async def _authors(
    session: AsyncSession, collections: list[Collection]
) -> dict[uuid.UUID, User]:
    if not collections:
        return {}
    return {
        user.id: user
        for user in (
            await session.exec(
                select(User).where(
                    User.id.in_({c.author_id for c in collections})  # type: ignore[attr-defined]
                )
            )
        ).all()
    }


#: Where a collection sits in the list, by what the reader has done with it.
#:
#: This is the whole of the ordering, and it is deliberately not newest-first:
#: the question a list of courses answers is "carry on with what I was doing",
#: and a course somebody is halfway through is a better answer to that than
#: one published yesterday. Finished ones go last rather than being hidden —
#: they are the record of what has been worked through, and hiding that hides
#: the reward.
IN_PROGRESS, NOT_STARTED, FINISHED = 0, 1, 2

#: The same three states, as the filter above the list names them. They are
#: the ranking read as a question rather than as an order — which is why the
#: list needs no sort control and does need this: the order says where
#: everything is, and this says "only show me that part of it".
STATUSES = {
    "in_progress": IN_PROGRESS,
    "not_started": NOT_STARTED,
    "finished": FINISHED,
}


def _rank(done: int, total: int) -> int:
    if total == 0 or done == 0:
        return NOT_STARTED
    return FINISHED if done >= total else IN_PROGRESS


async def _progress_for_many(
    session: AsyncSession,
    user_id: uuid.UUID,
    collection_ids: list[uuid.UUID],
) -> dict[uuid.UUID, dict]:
    """Everybody's progress through every collection, in two queries.

    It used to be two queries EACH, which is fine at five collections and is
    2N+2 at any number — the sort of cost that stays invisible until somebody
    publishes forty courses and the practice page starts taking a second to
    draw.

    Flat instead: one pass for the ordered items of every collection asked
    about, one for which of those materials the caller has submitted. The rest
    is arithmetic.
    """
    if not collection_ids:
        return {}

    ordered: dict[uuid.UUID, list[uuid.UUID]] = {cid: [] for cid in collection_ids}
    material_ids: set[uuid.UUID] = set()
    for collection_id, material_id in (
        await session.exec(
            select(CollectionItem.collection_id, CollectionItem.material_id)
            .select_from(CollectionItem)
            .join(Material, Material.id == CollectionItem.material_id)  # type: ignore[arg-type]
            .where(
                CollectionItem.collection_id.in_(collection_ids),  # type: ignore[attr-defined]
                Material.visibility == "public",
            )
            .order_by(CollectionItem.collection_id, CollectionItem.order_index)  # type: ignore[arg-type]
        )
    ).all():
        ordered[collection_id].append(material_id)
        material_ids.add(material_id)

    sat: set[uuid.UUID] = set()
    if material_ids:
        sat = set(
            (
                await session.exec(
                    select(Attempt.material_id)
                    .where(
                        Attempt.user_id == user_id,
                        Attempt.material_id.in_(material_ids),  # type: ignore[attr-defined]
                        Attempt.status == AttemptStatus.SUBMITTED,
                    )
                    .distinct()
                )
            ).all()
        )

    out: dict[uuid.UUID, dict] = {}
    for collection_id, ids in ordered.items():
        unsat = [mid for mid in ids if mid not in sat]
        out[collection_id] = {
            "total": len(ids),
            "done": len(ids) - len(unsat),
            "next_material_id": unsat[0] if unsat else None,
        }
    return out


async def list_public(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    query: str = "",
    status: str = "all",
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """Published collections, ordered by what the reader has done with them.

    In progress first, then untouched, then finished — see :func:`_rank`.
    Newest-first is the tiebreak inside each group rather than the sort.

    ``status`` narrows to one of those three. It is the same computation the
    ordering uses, asked as a question instead of as an order, and ``total``
    counts what SURVIVES it — a filtered list reporting the unfiltered total
    is a list that looks like it lost something.

    Sorted and paged in Python rather than in SQL, which is a considered
    exception to how the catalogue works. The rank depends on the caller's
    attempts crossed with each collection's contents, so ordering by it in SQL
    means that join in the ORDER BY of every page. Collections are curated by
    hand and number in the tens where materials number in the thousands, so
    holding the whole set is cheap and the ordering is exact. The day that
    stops being true, the shape of this answer — items plus a total — is
    already the shape the catalogue uses, and the fix is the same one.
    """
    statement = select(Collection).where(Collection.visibility == "public")
    # Title, summary and author, every term having to hit. The same field
    # searches both lists on the practice page, so it had better find a course
    # the way it finds a material.
    for term in query.split():
        pattern = f"%{term.lower()}%"
        statement = statement.where(
            func.lower(Collection.title).like(pattern)
            | func.lower(Collection.summary).like(pattern)
            | select(User.id)
            .where(
                User.id == Collection.author_id,
                func.lower(User.display_name).like(pattern),
            )
            .exists()
        )

    collections = list((await session.exec(statement)).all())
    progress_by_id = await _progress_for_many(
        session, user_id, [c.id for c in collections]
    )
    authors = await _authors(session, collections)

    def sort_key(collection: Collection):
        row = progress_by_id.get(collection.id, {"done": 0, "total": 0})
        # Negated timestamp for newest-first inside a rank, so one key sorts
        # both without a second pass.
        return (
            _rank(row["done"], row["total"]),
            -(collection.created_at.timestamp() if collection.created_at else 0),
        )

    wanted = STATUSES.get(status)
    if wanted is not None:
        collections = [
            c
            for c in collections
            if _rank(
                progress_by_id.get(c.id, {"done": 0})["done"],
                progress_by_id.get(c.id, {"total": 0})["total"],
            )
            == wanted
        ]

    collections.sort(key=sort_key)

    return {
        "items": [
            {
                **_summarise(collection, authors.get(collection.author_id)),
                "progress": progress_by_id.get(
                    collection.id,
                    {"total": 0, "done": 0, "next_material_id": None},
                ),
            }
            for collection in collections[offset : offset + limit]
        ],
        "total": len(collections),
    }


async def for_learner(
    session: AsyncSession, user_id: uuid.UUID, collection: Collection
) -> dict:
    """One collection, opened: its materials as catalogue rows, in order.

    The rows are the catalogue's own (:func:`app.services.listening._catalogue_rows`),
    so a material looks the same here as it does in the list — same
    difficulty band, same history, same byline. A collection is a different
    route to the same thing, not a different thing.
    """
    ids = await _item_ids(session, collection.id, public_only=True)
    author = await session.get(User, collection.author_id)
    materials = await listening_service.materials_in_order(session, ids)
    return {
        **_summarise(collection, author),
        "progress": await progress(session, user_id, ids),
        "items": await listening_service._catalogue_rows(
            session, user_id, materials
        ),
    }


async def for_author(
    session: AsyncSession, author_id: uuid.UUID
) -> list[dict]:
    """The author's own collections, published or not.

    ``item_count`` counts everything they have put in; ``public_item_count``
    counts what a learner would actually see. They differ exactly when a
    course contains the author's own drafts, which is a normal state to be in
    halfway through building one and a confusing one to discover later — so
    both numbers are reported rather than the difference being hidden.
    """
    collections = list(
        (
            await session.exec(
                select(Collection)
                .where(Collection.author_id == author_id)
                .order_by(Collection.updated_at.desc())  # type: ignore[attr-defined]
            )
        ).all()
    )
    author = await session.get(User, author_id)

    rows = []
    for collection in collections:
        every = await _item_ids(session, collection.id, public_only=False)
        rows.append(
            {
                **_summarise(collection, author),
                "item_count": len(every),
                "public_item_count": await public_item_count(
                    session, collection.id
                ),
                "blocker": await can_publish(session, collection),
            }
        )
    return rows

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


async def list_public(
    session: AsyncSession, user_id: uuid.UUID, *, limit: int = 20
) -> list[dict]:
    """Published collections, newest first, each with the caller's progress.

    Progress per collection is two queries over a handful of ids, and there
    are a handful of collections — no projection, no N+1 worth worrying
    about. The moment there are hundreds of these this wants the same
    treatment the catalogue got; it is not close.
    """
    collections = list(
        (
            await session.exec(
                select(Collection)
                .where(Collection.visibility == "public")
                .order_by(Collection.created_at.desc())  # type: ignore[attr-defined]
                .limit(limit)
            )
        ).all()
    )
    authors = await _authors(session, collections)

    rows = []
    for collection in collections:
        ids = await _item_ids(session, collection.id, public_only=True)
        rows.append(
            {
                **_summarise(collection, authors.get(collection.author_id)),
                "progress": await progress(session, user_id, ids),
            }
        )
    return rows


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

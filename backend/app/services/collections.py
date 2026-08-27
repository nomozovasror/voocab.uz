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
from app.models.part import Part
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


async def _items_for_many(
    session: AsyncSession, collection_ids: list[uuid.UUID]
) -> tuple[dict[uuid.UUID, list[uuid.UUID]], set[uuid.UUID]]:
    """The ordered public materials of every collection asked about, in one
    query, plus the flat set of material ids they mention.

    Loaded once and handed to everything that needs it. Progress, length and
    which parts a course covers are three questions about the same list, and
    fetching it three times is how a page ends up doing thirty queries to draw
    twelve rows.
    """
    ordered: dict[uuid.UUID, list[uuid.UUID]] = {cid: [] for cid in collection_ids}
    material_ids: set[uuid.UUID] = set()
    if not collection_ids:
        return ordered, material_ids

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
    return ordered, material_ids


async def _progress_for_many(
    session: AsyncSession,
    user_id: uuid.UUID,
    ordered: dict[uuid.UUID, list[uuid.UUID]],
    material_ids: set[uuid.UUID],
) -> dict[uuid.UUID, dict]:
    """Everybody's progress through every collection, in one more query.

    It used to be two queries EACH, which is fine at five collections and is
    2N+2 at any number — the sort of cost that stays invisible until somebody
    publishes forty courses and the practice page starts taking a second to
    draw. Flat instead: which of these materials the caller has submitted, and
    then arithmetic.
    """
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


async def _covers_for_many(
    session: AsyncSession,
    ordered: dict[uuid.UUID, list[uuid.UUID]],
    material_ids: set[uuid.UUID],
) -> dict[uuid.UUID, set[str]]:
    """Which parts each collection drills, as filter values.

    A set per collection rather than a single answer, because a course is
    several papers and the useful question is "does it have Part 3 in it" —
    the same question the catalogue's own part filter asks of one material,
    asked of a route through several.

    ``"full"`` sits in the same set as the part numbers because it is the same
    kind of answer: a mock-test set and a Part 3 drill are two things somebody
    might be looking for, and making them two menus would mean asking twice.
    """
    covers: dict[uuid.UUID, set[str]] = {cid: set() for cid in ordered}
    if not material_ids:
        return covers

    parts_by_material: dict[uuid.UUID, set[int]] = {}
    for material_id, order_index in (
        await session.exec(
            select(Part.material_id, Part.order_index).where(
                Part.material_id.in_(material_ids)  # type: ignore[attr-defined]
            )
        )
    ).all():
        parts_by_material.setdefault(material_id, set()).add(int(order_index) + 1)

    for collection_id, ids in ordered.items():
        for material_id in ids:
            parts = parts_by_material.get(material_id, set())
            covers[collection_id].update(str(n) for n in parts)
            if len(parts) >= FULL_TEST_PARTS:
                covers[collection_id].add("full")
    return covers


#: Four parts is a whole paper; anything less is an excerpt from one. The same
#: number the catalogue calls FULL_TEST_PARTS.
FULL_TEST_PARTS = 4

#: The options the "Covers" filter offers, in menu order.
COVER_OPTIONS = ["1", "2", "3", "4", "full"]

#: How long a course is, in materials. Inclusive bounds; ``None`` is open.
#:
#: The first question anybody has about a course is how much of their life it
#: wants, and "eleven materials" only answers that once you have seen a few.
#: Three bands answer it at a glance: an evening, a fortnight, a syllabus.
LENGTH_BANDS: dict[str, tuple[int, int | None]] = {
    "short": (1, 5),
    "medium": (6, 15),
    "long": (16, None),
}


def _length_band(size: int) -> str | None:
    for name, (low, high) in LENGTH_BANDS.items():
        if size >= low and (high is None or size <= high):
            return name
    return None


async def list_public(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    query: str = "",
    status: str = "all",
    covers: str = "all",
    length: str = "all",
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """Published collections, ordered by what the reader has done with them.

    In progress first, then untouched, then finished — see :func:`_rank`.
    Newest-first is the tiebreak inside each group rather than the sort.

    Three filters, each a different question and each one the courses list can
    answer honestly from what it already loads: where the reader is with it
    (``status``), which part of the paper it drills (``covers``), and how much
    of their life it wants (``length``). ``total`` counts what survives them —
    a filtered list reporting the unfiltered total is a list that looks like
    it lost something between the header and the rows.

    Deliberately absent: a difficulty. A course's "level" would be an average
    over its materials' measured bands, and calling a mix of Easy and Hard
    "Medium" is not a measurement, it is an invention — the same claim this
    codebase refuses everywhere else.

    Sorted and paged in Python rather than in SQL, which is a considered
    exception to how the catalogue works. Every one of these predicates
    depends on the collection's contents crossed with the caller's attempts,
    so doing it in SQL means those joins in the WHERE and ORDER BY of every
    page. Collections are curated by hand and number in the tens where
    materials number in the thousands, so holding the whole set is cheap and
    the answers are exact. The day that stops being true, the shape of this
    answer — items, a total and facet counts — is already the catalogue's, and
    the fix is the one already written.
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
    ids = [c.id for c in collections]
    ordered, material_ids = await _items_for_many(session, ids)
    progress_by_id = await _progress_for_many(
        session, user_id, ordered, material_ids
    )
    covers_by_id = await _covers_for_many(session, ordered, material_ids)
    authors = await _authors(session, collections)

    wanted_rank = STATUSES.get(status)

    def matches_status(collection: Collection) -> bool:
        row = progress_by_id[collection.id]
        return (
            wanted_rank is None or _rank(row["done"], row["total"]) == wanted_rank
        )

    def matches_covers(collection: Collection) -> bool:
        return covers == "all" or covers in covers_by_id.get(collection.id, set())

    def matches_length(collection: Collection) -> bool:
        return (
            length == "all"
            or _length_band(progress_by_id[collection.id]["total"]) == length
        )

    # Each count is what THAT option would leave, given whatever else is
    # already set — so a menu's own dimension is excluded from its own counts,
    # and every number is the size of the list one click away.
    #
    # Stricter than the catalogue's facets, which describe the whole library
    # and never move. The difference is scale: there, a menu almost never
    # empties, and a stable menu is worth more than an exact number. Here
    # there are a dozen courses and three menus over them, so a list is
    # genuinely one click from nothing — and a count that promised twelve and
    # delivered none would be worse than no count at all.
    countable = [c for c in collections if progress_by_id[c.id]["total"] > 0]
    for_covers = [
        c for c in countable if matches_status(c) and matches_length(c)
    ]
    for_lengths = [
        c for c in countable if matches_status(c) and matches_covers(c)
    ]
    facets = {
        "covers": [
            {
                "value": option,
                "count": sum(
                    1 for c in for_covers if option in covers_by_id.get(c.id, set())
                ),
            }
            for option in COVER_OPTIONS
        ],
        "lengths": [
            {
                "value": name,
                "count": sum(
                    1
                    for c in for_lengths
                    if _length_band(progress_by_id[c.id]["total"]) == name
                ),
            }
            for name in LENGTH_BANDS
        ],
    }

    kept = [
        c
        for c in collections
        # Nothing empty. Publishing an empty collection is refused, but one
        # can still become empty afterwards — its author withdraws the last
        # material in it, or deletes it and the item cascades away. What is
        # left is a published promise that opens onto a blank page, which is
        # the thing the publish rule exists to prevent. Its author still sees
        # it in the studio, with the reason it cannot go out.
        if progress_by_id[c.id]["total"] > 0
        and matches_status(c)
        and matches_covers(c)
        and matches_length(c)
    ]

    def sort_key(collection: Collection):
        row = progress_by_id[collection.id]
        # Negated timestamp for newest-first inside a rank, so one key sorts
        # both without a second pass.
        return (
            _rank(row["done"], row["total"]),
            -(collection.created_at.timestamp() if collection.created_at else 0),
        )

    kept.sort(key=sort_key)

    return {
        "items": [
            {
                **_summarise(collection, authors.get(collection.author_id)),
                "progress": progress_by_id[collection.id],
            }
            for collection in kept[offset : offset + limit]
        ],
        "total": len(kept),
        **facets,
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

"""Collections: what to practise, in what order.

Authorization follows the same two rules as materials — anyone may read a
public one, only its author may change it — and the same disguise: a private
collection is a 404 to everybody else rather than a 403, because confirming
which ids exist leaks what somebody is working on.

The learner-facing reads and the authoring writes live in one module rather
than being split across a studio router. They are four endpoints over one
table, and the interesting rules (what may be published, what may be put in)
are shared between them.
"""

import uuid

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlmodel import select

from app.api.deps import CurrentUser
from app.api.listening import SessionDep
from app.core.database import AsyncSession
from app.models.collection import Collection
from app.models.material import Material
from app.schemas.collection import (
    AuthorCollectionOut,
    CollectionCreate,
    CollectionDetailOut,
    CollectionItemsIn,
    CollectionListOut,
    CollectionOut,
    CollectionUpdate,
)
from app.services import collections as collections_service

router = APIRouter(prefix="/api", tags=["collections"])


async def _load_readable(
    session: AsyncSession, collection_id: uuid.UUID, user_id: uuid.UUID
) -> Collection:
    collection = await collections_service.get(session, collection_id)
    if collection is None or (
        collection.author_id != user_id and collection.visibility != "public"
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Collection not found")
    return collection


async def _load_owned(
    session: AsyncSession, collection_id: uuid.UUID, user_id: uuid.UUID
) -> Collection:
    collection = await collections_service.get(session, collection_id)
    if collection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Collection not found")
    if collection.author_id != user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your collection")
    return collection


# --- Reading ----------------------------------------------------------------


@router.get("/collections", response_model=CollectionListOut)
async def list_collections(
    user: CurrentUser,
    session: SessionDep,
    # Which paper's shelf. A collection is one paper's by construction, and
    # the list sits on one paper's page; defaulted rather than required
    # because every caller that existed before reading did was asking about
    # listening.
    skill: Annotated[str, Query(pattern="^(listening|reading)$")] = "listening",
    q: Annotated[str, Query(max_length=200)] = "",
    status: Annotated[
        str, Query(pattern="^(all|in_progress|not_started|finished)$")
    ] = "all",
    covers: Annotated[str, Query(pattern="^(all|[1-4]|full)$")] = "all",
    length: Annotated[str, Query(pattern="^(all|short|medium|long)$")] = "all",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CollectionListOut:
    """Published collections, ordered by what the caller has done with them.

    In progress first, then untouched, then finished. Not newest-first, and
    that is the whole point of the ordering: what somebody wants from a list
    of courses is the one they were in the middle of, and only after that the
    one that is new.

    ``covers`` narrows to courses that drill one part of the paper, or to
    mock-test sets; ``length`` to how much of somebody's life a course wants.
    Both come back as facet counts, and each count is what that option would
    leave given whatever else is set — so a menu can never offer an option
    that returns nothing.

    ``total`` is what makes the small version of this list honest. The
    practice page shows a handful above the catalogue, and a handful with no
    idea how many it is a handful OF is a list that looks truncated by
    accident.
    """
    page = await collections_service.list_public(
        session,
        user.id,
        skill=skill,
        query=q.strip(),
        status=status,
        covers=covers,
        length=length,
        limit=limit,
        offset=offset,
    )
    return CollectionListOut(
        items=[CollectionOut(**row) for row in page["items"]],
        total=page["total"],
        covers=page["covers"],
        lengths=page["lengths"],
    )


@router.get("/collections/{collection_id}", response_model=CollectionDetailOut)
async def get_collection(
    collection_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> CollectionDetailOut:
    """One collection and its materials, in order.

    Its author sees it before it is published — that is how they check what
    they have built — and everybody else gets a 404 until it is.
    """
    collection = await _load_readable(session, collection_id, user.id)
    return CollectionDetailOut(
        **await collections_service.for_learner(session, user.id, collection)
    )


@router.get("/studio/collections", response_model=list[AuthorCollectionOut])
async def my_collections(
    user: CurrentUser, session: SessionDep
) -> list[AuthorCollectionOut]:
    """The caller's own, published or not, most recently touched first."""
    return [
        AuthorCollectionOut(**row)
        for row in await collections_service.for_author(session, user.id)
    ]


# --- Authoring --------------------------------------------------------------


@router.post(
    "/collections",
    response_model=AuthorCollectionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_collection(
    data: CollectionCreate, user: CurrentUser, session: SessionDep
) -> AuthorCollectionOut:
    """A new, empty, private collection.

    Private on creation and empty is a legal state to be in: an author starts
    by naming the thing they are about to build, and a create that demanded
    its contents up front would be a form nobody could fill in.
    """
    collection = await collections_service.create(
        session, user.id, title=data.title, summary=data.summary,
        skill=data.skill,
    )
    return await _author_row(session, collection)


@router.patch(
    "/collections/{collection_id}", response_model=AuthorCollectionOut
)
async def update_collection(
    collection_id: uuid.UUID,
    data: CollectionUpdate,
    user: CurrentUser,
    session: SessionDep,
) -> AuthorCollectionOut:
    """Rename, re-describe, publish or withdraw.

    Publishing is the one that can be refused, and it comes back as a 422 with
    the reason in it rather than a bare rejection: the author is being told
    what to fix, and "cannot publish" without a because is a dead end.
    Withdrawing is never refused — taking your own work back is not something
    to argue with.
    """
    collection = await _load_owned(session, collection_id, user.id)
    if data.visibility == "public":
        # Checked against what the collection will BE, so a rename to a
        # non-blank title and a publish can arrive in the same request.
        prospective = Collection(
            id=collection.id,
            author_id=collection.author_id,
            title=data.title if data.title is not None else collection.title,
            summary=collection.summary,
            visibility="public",
        )
        blocker = await collections_service.can_publish(session, prospective)
        if blocker is not None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, blocker)

    collection = await collections_service.update(
        session,
        collection,
        title=data.title,
        summary=data.summary,
        visibility=data.visibility,
        cover_seed=data.cover_seed,
    )
    return await _author_row(session, collection)


@router.put("/collections/{collection_id}/items", response_model=AuthorCollectionOut)
async def set_collection_items(
    collection_id: uuid.UUID,
    data: CollectionItemsIn,
    user: CurrentUser,
    session: SessionDep,
) -> AuthorCollectionOut:
    """Replace the whole ordered list.

    The whole list every time, rather than add/remove/move: reordering rows
    individually through a unique index is a sequence of temporary states that
    all have to be legal, and there is no reason a client should have to think
    about that.

    What may go in: the author's own materials, and anybody's published ones.
    The second is what makes a collection worth having — somebody who knows
    the exam laying out a route through the library, not just through their
    own work. An id that is neither is refused rather than dropped: a course
    that silently loses a material when it is saved is a course whose author
    stops trusting the save button.

    A public collection that loses its last public material would be a
    published course opening onto a blank page, so that save withdraws it and
    says so. The author's work is never rejected to protect a flag.
    """
    collection = await _load_owned(session, collection_id, user.id)

    if data.material_ids:
        allowed = {
            material_id
            for material_id, author_id, visibility in (
                await session.exec(
                    select(Material.id, Material.author_id, Material.visibility).where(
                        Material.id.in_(data.material_ids),  # type: ignore[attr-defined]
                        # A course is in ONE paper. Mixing a reading passage
                        # into a listening course would give the sequence two
                        # numberings and the recommendation engine two
                        # different questions to reason about.
                        Material.type == collection.skill,
                    )
                )
            ).all()
            if author_id == user.id or visibility == "public"
        }
        missing = [m for m in data.material_ids if m not in allowed]
        if missing:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"{len(missing)} of those materials are not yours and not published.",
            )

    await collections_service.set_items(session, collection, data.material_ids)

    if collection.visibility == "public":
        blocker = await collections_service.can_publish(session, collection)
        if blocker is not None:
            collection = await collections_service.update(
                session, collection, visibility="private"
            )

    return await _author_row(session, collection)


@router.delete(
    "/collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_collection(
    collection_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> None:
    """Delete the collection. The materials in it are untouched — that is the
    whole point of a collection being a list of references rather than a
    container, and it is why this needs no are-you-sure about content that
    isn't going anywhere."""
    collection = await _load_owned(session, collection_id, user.id)
    await collections_service.delete(session, collection)


async def _author_row(
    session: AsyncSession, collection: Collection
) -> AuthorCollectionOut:
    """One collection in the author's own shape. Read back through the same
    listing the studio uses, so a write and a refresh cannot disagree."""
    rows = await collections_service.for_author(session, collection.author_id)
    row = next(r for r in rows if r["id"] == collection.id)
    return AuthorCollectionOut(**row)

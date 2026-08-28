"""Request/response schemas for collections.

A collection is a title, a line of explanation and an ordered list of material
ids. What makes the shapes here worth a module of their own is what they
deliberately do NOT carry: no enrolment, no completion flag, no schedule.
Progress is derived from attempts that already exist, so it arrives on the way
out and is never sent in.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.listening import (
    CatalogueAuthorOut,
    PracticeFacetOut,
    PracticeMaterialOut,
)


class CollectionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=300)

    @field_validator("title", "summary")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, v: str) -> str:
        if not v:
            raise ValueError("title must not be blank")
        return v


class CollectionUpdate(BaseModel):
    """All optional (PATCH). ``visibility`` is how a collection is published
    and withdrawn; publishing is refused with a reason where the collection
    isn't ready (see app/services/collections.can_publish)."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=300)
    visibility: str | None = Field(default=None, pattern="^(private|public)$")

    @field_validator("title", "summary")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else v


class CollectionItemsIn(BaseModel):
    """The whole ordered list, every time.

    Not "add this one" and "move that one": reordering rows individually
    through a unique index is a sequence of temporary states that all have to
    be legal, and there is no reason for the client to have to think about
    that. It sends what the list should now be.
    """

    material_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)


class CollectionProgressOut(BaseModel):
    """How far the caller is through it, derived from their attempts.

    ``next_material_id`` is the first one they have not sat IN ORDER, which is
    the difference between a collection and a filter — the sequence is
    somebody's judgement about what to do when. ``None`` means finished.
    """

    total: int
    done: int
    next_material_id: uuid.UUID | None = None


class CollectionOut(BaseModel):
    """A collection as a learner sees it listed."""

    id: uuid.UUID
    title: str
    summary: str = ""
    visibility: str
    created_at: datetime | None = None
    author: CatalogueAuthorOut | None = None
    progress: CollectionProgressOut


class CollectionListOut(BaseModel):
    """One page of collections, and how many there are.

    A total rather than just the rows, for the same reason the catalogue
    carries one: a list quietly shorter than the library is a list that looks
    broken, and the strip on the practice page shows a handful and has to be
    able to say how many it is a handful OF.
    """

    items: list[CollectionOut] = []
    total: int
    #: What there is to filter by. Each count is what that option would
    #: leave given whatever else is already set — the size of the list one
    #: click away. With a dozen courses and three menus over them a list is
    #: genuinely one click from empty, and a count that promised twelve and
    #: delivered none would be worse than no count at all.
    covers: list[PracticeFacetOut] = []
    lengths: list[PracticeFacetOut] = []


class CollectionStatsOut(BaseModel):
    """How the caller has done across one collection.

    First-try average is the headline for the reason it always is here.
    ``best_avg_pct`` is ``None`` until something in the course has been sat
    twice: with no retries it is the same number under a second name, and two
    identical figures labelled differently is a panel asking to be decoded.
    """

    first_try_avg_pct: int | None = None
    best_avg_pct: int | None = None
    time_spent_ms: int = 0


class CollectionDetailOut(CollectionOut):
    """One collection, opened.

    ``items`` are the catalogue's own rows, so a material looks the same here
    as it does in the list — same measured difficulty, same history, same
    byline. A collection is a different route to the same thing.
    """

    stats: CollectionStatsOut = CollectionStatsOut()
    items: list[PracticeMaterialOut] = []


class AuthorCollectionOut(BaseModel):
    """A collection as its author sees it listed.

    Two counts rather than one: ``item_count`` is what they put in,
    ``public_item_count`` is what a learner would actually see. They differ
    exactly when the course contains the author's own drafts — normal halfway
    through building one, confusing to discover afterwards.

    ``blocker`` is why it cannot be published yet, or null. A sentence rather
    than a boolean, so the studio can say what to fix instead of guessing.
    """

    id: uuid.UUID
    title: str
    summary: str = ""
    visibility: str
    created_at: datetime | None = None
    author: CatalogueAuthorOut | None = None
    item_count: int
    public_item_count: int
    blocker: str | None = None

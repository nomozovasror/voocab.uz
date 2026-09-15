import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel


class Collection(SQLModel, table=True):
    """An ordered set of materials somebody put together on purpose.

    A course, a mock-test set, "the ten Part 3s worth doing first" — the
    catalogue answers what exists and this answers what to do in what order,
    which is the thing a library of a thousand papers cannot say about itself.

    Deliberately thin. No enrolment, no completion certificate, no schedule: a
    learner's progress through one is derived from the attempts they have
    already made (:func:`app.services.collections.progress`), so opening a
    collection commits them to nothing and there is no state that can go stale
    if they wander off. Enrolment is a row that exists to be forgotten about;
    an attempt is a row that already had to exist.

    ``visibility`` uses the same two words as :class:`Material` on purpose —
    an author's half-built course is private for the same reason their
    half-built paper is, and one vocabulary for "not finished yet" is one
    fewer thing to look up.
    """

    __tablename__ = "collections"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    author_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    title: str
    #: One line, printed under the title wherever the collection appears. Not
    #: a description field with a rich-text editor behind it: what a learner
    #: needs before opening one is what it is for, and that fits on a line.
    summary: str = Field(default="")
    visibility: str = Field(default="private")  # "private" | "public"
    #: The string the cover is generated from, or null to use the id.
    #:
    #: A cover is a pure function of one string (stock, pattern and cut all
    #: fall out of one hash), and the id was that string — which made the
    #: cover permanent and also made it the one thing about a collection its
    #: author could not change. This is how they change it: a new seed is a
    #: new book. Null rather than backfilled, so every collection that
    #: existed before keeps the cover it has always had.
    cover_seed: str | None = Field(default=None, max_length=32)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class CollectionItem(SQLModel, table=True):
    """One material's place in one collection.

    The order is the point — a collection is a sequence, not a tag — so
    ``order_index`` is unique within the collection and the whole list is
    rewritten as a unit rather than patched a row at a time
    (:func:`app.services.collections.set_items`). Reordering by moving one row
    at a time through a unique index is a dance of temporary values that has
    to be got exactly right; replacing the list has no intermediate state to
    get wrong.

    A material can sit in any number of collections and appears at most once
    in each, which is what the composite key says.
    """

    __tablename__ = "collection_items"
    __table_args__ = (
        UniqueConstraint(
            "collection_id", "order_index", name="uq_collection_items_order"
        ),
    )

    collection_id: uuid.UUID = Field(
        foreign_key="collections.id", primary_key=True
    )
    material_id: uuid.UUID = Field(foreign_key="materials.id", primary_key=True)
    order_index: int

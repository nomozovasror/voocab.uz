"""Curated word lists a learner can draw new words from.

A list is a SOURCE, not a store. Starting "Business English" writes one
:class:`UserWordList` row and nothing else: no :class:`~app.models.vocabulary
.SavedWord` is created for any of its words until the learner first answers
one (see ``backend/app/services/CLAUDE.md``, "Word lists"). It is not a
``Deck``: a deck is the learner's own grouping of words they already hold.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as SA_UUID
from sqlmodel import Field, SQLModel

#: The five lists, in the order the product shows them.
LIST_KEYS: tuple[str, ...] = ("core", "business", "academic", "medical", "toeic")

#: Where an entry's ``rank`` came from -- the first source that had a number
#: for it, in this order (``sfi31k``: the NGSL project's 31K-lemma frequency
#: table, for a list with no rank of its own). Never alphabetical.
RANK_SOURCES: tuple[str, ...] = ("list", "sfi31k", "semcor", "ngsl", "cefr")


class WordList(SQLModel, table=True):
    __tablename__ = "word_lists"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    key: str = Field(max_length=16, unique=True, index=True)
    title: str = Field(max_length=80)
    #: One sentence: why this list is worth a learner's time.
    description: str = Field(default="", max_length=300)
    source_title: str = Field(default="", max_length=160)
    source_authors: str = Field(default="", max_length=160)
    licence_name: str = Field(default="", max_length=60)
    licence_url: str = Field(default="", max_length=200)
    #: The one-line credit shown at the bottom of the list's page.
    attribution: str = Field(default="", max_length=300)
    sort_order: int = Field(default=0)


class WordListEntry(SQLModel, table=True):
    """One card of one list: a lemma, and the ONE sense THIS list means by it."""

    __tablename__ = "word_list_entries"
    __table_args__ = (
        UniqueConstraint("list_id", "lemma", name="uq_word_list_entry_lemma"),
        Index("ix_word_list_entries_list_rank", "list_id", "rank"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    list_id: uuid.UUID = Field(
        sa_column=Column(
            SA_UUID(as_uuid=True),
            ForeignKey("word_lists.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    lemma: str = Field(max_length=80)
    #: 1..n, the list's teaching order (most frequent first).
    rank: int
    rank_source: str = Field(default="list", max_length=8)
    #: Null only while the build job has not resolved the entry yet; an
    #: entry without a sense is never offered and not counted.
    lexeme_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SA_UUID(as_uuid=True), ForeignKey("lexemes.id"), nullable=True, index=True
        ),
    )
    #: The sense this list means -- chosen per list, not globally.
    sense_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SA_UUID(as_uuid=True),
            ForeignKey("lexeme_senses.id"),
            nullable=True,
            index=True,
        ),
    )


class UserWordList(SQLModel, table=True):
    """A learner started this list. ``active`` False is "stopped"."""

    __tablename__ = "user_word_lists"

    user_id: uuid.UUID = Field(
        sa_column=Column(
            SA_UUID(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    list_id: uuid.UUID = Field(
        sa_column=Column(
            SA_UUID(as_uuid=True),
            ForeignKey("word_lists.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    added_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    active: bool = Field(default=True)

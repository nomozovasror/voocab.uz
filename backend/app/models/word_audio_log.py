import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as SA_UUID
from sqlmodel import Field, SQLModel


class OnTheGoExposure(SQLModel, table=True):
    """The WORD part of an On the go item played -- one row per hearing.

    Decision 14: hearing a word is not recalling it. FSRS models retrieval, and
    writing an exposure as a review would raise a card's stability with no
    evidence, so the schedule would start to lie. This table is the whole of
    what On the go records, and nothing reads it to schedule anything: it is
    for the learner's own history and for the day somebody asks how often a
    word was heard before it was known. ``mode`` is a plain string for the
    same reason ``exercise_type`` is -- a second audio mode is a value, not a
    migration.

    ``saved_word_id`` is ``ON DELETE SET NULL`` and ``lemma`` is copied onto
    the row, exactly as ``VocabularyReviewLog`` does: forgetting a word is a
    decision about a list, not about the history of what was heard, and the
    row must still say which word it was once the pointer is null."""

    __tablename__ = "on_the_go_exposures"
    __table_args__ = (Index("ix_on_the_go_exposures_user_played", "user_id", "played_at"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        sa_column=Column(
            SA_UUID(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    saved_word_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SA_UUID(as_uuid=True),
            ForeignKey("saved_words.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    lemma: str = Field(
        default="", max_length=80, sa_column_kwargs={"server_default": ""}
    )
    played_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    mode: str = Field(default="on_the_go", max_length=16)


class SpeakMiss(SQLModel, table=True):
    """The speech recogniser did not catch a word, attempt 1 to 3.

    Decision 18, and the brief's "two outcomes, never mixed": three
    unrecognised attempts are OUR miss, not the learner's, so nothing is
    written to FSRS or the review log -- this row is the only trace. It keeps
    the browser's alternatives verbatim (up to five strings) so the matcher's
    rules can be tuned against what recognition really returned for a word,
    which is the one thing nobody can guess in advance. ``saved_word_id`` /
    ``lemma``: as on :class:`OnTheGoExposure` -- the miss outlives the word."""

    __tablename__ = "speak_misses"
    __table_args__ = (Index("ix_speak_misses_user_created", "user_id", "created_at"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        sa_column=Column(
            SA_UUID(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    saved_word_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SA_UUID(as_uuid=True),
            ForeignKey("saved_words.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    lemma: str = Field(
        default="", max_length=80, sa_column_kwargs={"server_default": ""}
    )
    attempt: int
    alternatives: list[str] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False, server_default="[]")
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

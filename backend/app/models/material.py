import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, func
from sqlmodel import Field, SQLModel


class Material(SQLModel, table=True):
    """A piece of practice content authored by a user. Today only ``dictation``
    exists; ``type`` leaves room for reading/listening/etc. later."""

    __tablename__ = "materials"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    author_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    type: str = Field(default="dictation")
    title: str
    # Optional because non-audio material types (grammar/vocab/reading) won't
    # have a clip. Readiness (pending/processing/ready) is NOT stored here —
    # it's derived from audio_asset -> audio_blob.transcript_status at read
    # time, to avoid a duplicated column drifting out of sync.
    audio_asset_id: uuid.UUID | None = Field(
        default=None, foreign_key="audio_asset.id", index=True
    )
    case_sensitive: bool = Field(default=False)
    punctuation_sensitive: bool = Field(default=False)
    visibility: str = Field(default="private")  # "private" | "public"
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    # Auto-bumped by the DB driver on every UPDATE of this row (SQLAlchemy's
    # client-side `onupdate`, not just a DDL trigger) -- callers never need
    # to set it themselves. Powers "Edited X" vs "Created X" in the Studio
    # activity feed and `recent` ordering.
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        ),
    )

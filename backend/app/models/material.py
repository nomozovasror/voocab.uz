import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel


class Material(SQLModel, table=True):
    """A piece of practice content authored by a user. Today only ``dictation``
    exists; ``type`` leaves room for reading/listening/etc. later."""

    __tablename__ = "materials"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    author_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    type: str = Field(default="dictation")
    title: str
    # Optional because non-audio material types won't have a clip.
    audio_url: str | None = Field(default=None)
    case_sensitive: bool = Field(default=False)
    punctuation_sensitive: bool = Field(default=False)
    visibility: str = Field(default="private")  # "private" | "public"
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

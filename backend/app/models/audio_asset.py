import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel


class AudioAsset(SQLModel, table=True):
    """A per-owner claim on a shared :class:`AudioBlob`.

    ``AudioBlob`` is content-addressed and ownerless; ``AudioAsset`` is where
    ownership lives. Two users uploading identical bytes get two assets over
    one blob (one shared transcript). One owner's asset can be referenced by
    several materials (e.g. the same clip used for both a listening and a
    dictation material)."""

    __tablename__ = "audio_asset"
    __table_args__ = (
        UniqueConstraint("owner_id", "blob_id", name="uq_audio_asset_owner_blob"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    blob_id: uuid.UUID = Field(foreign_key="audio_blob.id", index=True)
    title: str | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

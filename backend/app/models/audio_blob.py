import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel


class TranscriptStatus(enum.StrEnum):
    """Lifecycle of the (async) ASR job for an :class:`AudioBlob`.

    Stored as a plain string column (not a native Postgres ENUM) so adding a
    new status later is a data-only change, not a migration on the type."""

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class AudioBlob(SQLModel, table=True):
    """Shared, content-addressed audio bytes. One row per unique file (by
    SHA-256), regardless of how many owners/materials reference it — this is
    where the (expensive, one-time) ASR transcript lives."""

    __tablename__ = "audio_blob"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    sha256: str = Field(unique=True, index=True)
    storage_key: str
    size_bytes: int
    mime_type: str
    # Nullable: filled in once the ASR/probe step reports it.
    duration_ms: int | None = Field(default=None)
    # Always NULL today; a future perceptual-dedup pass will populate this.
    fingerprint: str | None = Field(default=None)
    transcript_status: str = Field(default=TranscriptStatus.PENDING)
    transcript_attempts: int = Field(default=0)
    transcript_error: str | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

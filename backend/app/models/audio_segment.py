import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel


class AudioSegment(SQLModel, table=True):
    """One ASR-native segment of an :class:`AudioBlob`'s transcript.

    Segmentation boundaries and text come straight from the ASR provider's
    ``verbose_json`` output — no custom segmentation logic. ``words`` carries
    word-level timing (``[{"word", "start_ms", "end_ms"}, ...]``), which is
    the data future consumption features (word/sentence/paragraph grouping)
    will build on; that grouping logic itself is out of scope here."""

    __tablename__ = "audio_segment"
    __table_args__ = (
        UniqueConstraint("blob_id", "order_index", name="uq_audio_segment_blob_order"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    blob_id: uuid.UUID = Field(foreign_key="audio_blob.id", index=True)
    order_index: int
    start_ms: int
    end_ms: int
    text: str
    words: list[dict] = Field(sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

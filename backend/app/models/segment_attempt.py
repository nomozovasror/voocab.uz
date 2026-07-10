import uuid

from sqlmodel import Field, SQLModel


class SegmentAttempt(SQLModel, table=True):
    """Per-segment detail of an attempt: what the learner typed (raw) and the
    word-level scoring for that segment."""

    __tablename__ = "segment_attempts"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    attempt_id: uuid.UUID = Field(foreign_key="attempts.id", index=True)
    segment_id: uuid.UUID = Field(foreign_key="segments.id", index=True)
    typed_text: str  # exactly what the learner typed, unmodified
    correct_words: int
    total_words: int

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel


class QuestionAttempt(SQLModel, table=True):
    """Per-question detail of a listening :class:`Attempt`: what the learner
    typed (raw) and the grading result for that question. The listening
    analog of :class:`SegmentAttempt` (dictation's per-segment event) — the
    event-sourcing atom for listening."""

    __tablename__ = "question_attempts"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    attempt_id: uuid.UUID = Field(foreign_key="attempts.id", index=True)
    question_id: uuid.UUID = Field(foreign_key="questions.id", index=True)
    given_answer: str  # exactly what the learner typed, unmodified
    is_correct: bool
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

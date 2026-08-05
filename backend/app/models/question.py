import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class Question(SQLModel, table=True):
    """One gradeable gap within a :class:`QuestionGroup` (normalized, not
    embedded in the group's JSON config, so each answer stays individually
    gradeable and event-sourceable). ``replay_start_ms``/``replay_end_ms`` are
    a future hook (per-question audio replay range) — nullable and unused
    today."""

    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint("group_id", "number", name="uq_questions_group_number"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    group_id: uuid.UUID = Field(foreign_key="question_groups.id", index=True)
    number: int
    correct_answers: list[str] = Field(sa_column=Column(JSONB, nullable=False))
    replay_start_ms: int | None = Field(default=None)
    replay_end_ms: int | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class QuestionGroupType(enum.StrEnum):
    """Kind of question group. The enum is intentionally open to grow
    (matching, map labelling, table/flow-chart completion, ...) without a type
    migration — new members are a data-only change since this is stored as a
    plain string column."""

    FORM_COMPLETION = "form_completion"
    MULTIPLE_CHOICE = "multiple_choice"


class QuestionGroup(SQLModel, table=True):
    """A set of questions sharing one instruction line, and — where the type
    has one — one presentational resource: for ``form_completion`` the
    gap-fill template, which lives in ``config``. ``multiple_choice`` has no
    such shared resource; each of its questions carries its own prompt and
    options, so its ``config`` is empty.

    A part holds an ordered list of these, which is how one Part 1 comes to
    be "Questions 1–6, form completion" followed by "Questions 7–10, multiple
    choice". ``order_index`` is that order.

    The questions themselves are normalized rows in :class:`Question`, never
    embedded in this JSON, so they stay individually gradeable and
    event-sourceable."""

    __tablename__ = "question_groups"
    __table_args__ = (
        UniqueConstraint("part_id", "order_index", name="uq_question_groups_part_order"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    part_id: uuid.UUID = Field(foreign_key="parts.id", index=True)
    order_index: int
    type: str = Field(default=QuestionGroupType.FORM_COMPLETION)
    instructions: str
    word_limit: int | None = Field(default=None)
    config: dict = Field(sa_column=Column(JSONB, nullable=False))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

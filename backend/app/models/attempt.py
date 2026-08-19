import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel


class AttemptStatus(enum.StrEnum):
    """Lifecycle of an :class:`Attempt`.

    Stored as a plain string column (not a native Postgres ENUM) so adding a
    new status later is a data-only change, not a migration on the type."""

    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"


class Attempt(SQLModel, table=True):
    """An activity EVENT: one time a user worked through a material. Statistics,
    XP and achievements are derived from these events rather than stored as
    standalone counters.

    General across material types: dictation attempts fill ``time_spent_ms``/
    ``completed_at`` (score = accuracy %); listening attempts fill
    ``started_at``/``submitted_at``/``total_questions`` (score = correct-answer
    count). See the listening-form-completion migration for the reconciliation
    that reshaped this table from a dictation-only origin.
    """

    __tablename__ = "attempts"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    material_id: uuid.UUID = Field(foreign_key="materials.id", index=True)
    status: str = Field(default=AttemptStatus.IN_PROGRESS)
    score: float | None = Field(default=None)
    total_questions: int | None = Field(default=None)
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    submitted_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    time_spent_ms: int | None = Field(default=None)
    completed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    # --- How the recording was used (listening) ------------------------------
    #
    # Nullable rather than defaulting to 0, and that distinction is the point:
    # NULL means the attempt predates this measurement, 0 means the learner
    # genuinely never pressed play. A statistic built on "0 for everything
    # before August" would be a lie told by a DEFAULT clause.

    #: Total audio actually played, overlaps counted once — listening to the
    #: same minute three times is one minute of recording, three times heard.
    #: Derived server-side from the spans the client reports, never taken as a
    #: number of its own: two numbers that must agree eventually won't.
    listened_ms: int | None = Field(default=None)
    #: How many times the learner dragged the playhead backwards. The plainest
    #: signal of "I missed that" there is.
    seeks_back: int | None = Field(default=None)

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
    #: A finished DRILL: one question group worked on its own, not a sitting of
    #: the material it was cut from.
    #:
    #: A separate status rather than a flag beside ``SUBMITTED``, and that is
    #: load-bearing. Twenty queries across five services ask "has this learner
    #: sat this material" as ``status == SUBMITTED`` — the catalogue's ``done``
    #: clause, the recommender, collection progress, every ability figure, the
    #: author's studio counts. A drill is none of those things: somebody who
    #: worked the map out of Part 2 has not sat Part 2, and counting it as a
    #: sitting would mark the paper done, withdraw it from recommendation and
    #: become the FIRST attempt that every ability figure is measured from.
    #:
    #: Adding a third value excludes drills from all twenty at once, because
    #: every one of them compares for equality. A boolean column would have
    #: needed twenty edits and would have been wrong the first time somebody
    #: wrote the twenty-first.
    DRILLED = "drilled"


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
    #: The one question group this attempt worked, for a drill; NULL for a
    #: sitting of the whole material, which is every row written before drills
    #: existed. What makes an attempt a drill is its STATUS (see
    #: :class:`AttemptStatus`); this says WHICH group, so the drill list can
    #: mark one done and the review can find the next.
    group_id: uuid.UUID | None = Field(
        default=None, foreign_key="question_groups.id", index=True
    )
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
    #: The part of ``time_spent_ms`` somebody was actually present for -- the
    #: tab in front of them, and something moving.
    #:
    #: Two columns rather than one, because they answer two questions. How
    #: long the paper was OUT is a fact about the session; how long it was
    #: being SAT is the only one of the two worth measuring a learner by. A
    #: candidate who opens a passage, leaves for twenty minutes and comes back
    #: did not read for twenty-three of them, and every figure built on
    #: ``time_spent_ms`` -- time spent, pace, the per-question timings behind
    #: "where you lose marks" -- believed that they did.
    #:
    #: Nullable, and null means the attempt predates the measurement rather
    #: than that nobody was there. Anything reading it falls back to
    #: ``time_spent_ms``.
    active_ms: int | None = Field(default=None)
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

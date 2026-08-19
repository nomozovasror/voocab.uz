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

    # --- How the answer was arrived at ---------------------------------------
    #
    # None throughout means "not measured" — an attempt from before these
    # columns existed, or a client that didn't report. Zero means measured and
    # zero. Difficulty scoring has to be able to tell those apart, so none of
    # these gets a DEFAULT 0.
    #
    # Milliseconds are counted from the start of the session, not the wall
    # clock: the client's clock is frequently wrong and never worth trusting,
    # but the distance between two of its own readings is fine.

    #: When the question first got a non-empty answer. How long the learner
    #: waited before they could answer at all.
    first_answered_ms: int | None = Field(default=None)
    #: When they last touched it. Far from ``first_answered_ms`` means they
    #: came back to it, which is the interesting case.
    last_changed_ms: int | None = Field(default=None)
    #: How many VISITS to this question left it holding a different answer
    #: than it had on arrival. Second-guessing, counted — and counted per
    #: visit rather than per keystroke, because typing "engineer" is eight
    #: keystrokes and one answer, and a per-keystroke counter would be
    #: measuring how long the word is.
    changes: int | None = Field(default=None)
    #: Accumulated time the question's input held focus. Only meaningful for
    #: typed answers — a letter or a radio button is chosen in one click, and
    #: the time spent deciding was spent looking elsewhere.
    focus_ms: int | None = Field(default=None)
    #: How many times the learner played the stretch of audio where this
    #: answer is said. Computed on the server, by crossing the spans the
    #: client played against the moment the AUTHOR marked — the client is
    #: never told where the answers are, so it could not count this itself.
    hearings: int | None = Field(default=None)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

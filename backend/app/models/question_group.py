import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class QuestionGroupType(enum.StrEnum):
    """Kind of question group, in the exam's own names. The enum is
    intentionally open to grow (map labelling, table completion, ...) without a
    type migration — new members are a data-only change since this is stored as
    a plain string column, which is how ``matching`` and the completion tasks
    below were added."""

    FORM_COMPLETION = "form_completion"
    NOTE_COMPLETION = "note_completion"
    SENTENCE_COMPLETION = "sentence_completion"
    SUMMARY_COMPLETION = "summary_completion"
    SHORT_ANSWER = "short_answer"
    TABLE_COMPLETION = "table_completion"
    MULTIPLE_CHOICE = "multiple_choice"
    MATCHING = "matching"


#: The tasks that are answered by writing the missing words. They are one
#: thing to the server — a template with ``{{N}}`` gaps, graded against
#: accepted phrasings — and six things to the author, because a candidate is
#: told to "complete the notes" or "answer the questions" and an author works
#: from a paper that says so. Keeping them apart is what stops one name
#: standing for six tasks and making five of them look unavailable.
COMPLETION_TYPES = frozenset(
    {
        QuestionGroupType.FORM_COMPLETION,
        QuestionGroupType.NOTE_COMPLETION,
        QuestionGroupType.SENTENCE_COMPLETION,
        QuestionGroupType.SUMMARY_COMPLETION,
        QuestionGroupType.SHORT_ANSWER,
        QuestionGroupType.TABLE_COMPLETION,
    }
)


def same_question_kind(before: str, after: str) -> bool:
    """Whether a group changing type keeps the questions it already has.

    Renaming the task does: gap 3 of a form and gap 3 of the notes it becomes
    are the same question, with the same answers, said at the same moment. A
    form turning into multiple choice is not — the answer key means something
    else entirely — and nothing is kept across that.
    """
    return before == after or (before in COMPLETION_TYPES and after in COMPLETION_TYPES)


class QuestionGroup(SQLModel, table=True):
    """A set of questions sharing one instruction line, and — where the type
    has one — one presentational resource, which lives in ``config``:

    * the completion tasks (``form_completion``, ``note_completion``,
      ``sentence_completion``, ``summary_completion``, ``short_answer``,
      ``table_completion``): the
      gap-fill template. They differ in what the paper calls them and in the
      shape the template takes — a form has a label column, notes and
      sentences run the full width, a table is a grid — and in nothing else.
    * ``matching``: the box of lettered options every question under it is
      answered from. The box is the group's because the paper prints it once
      above the whole set, and because "you may use any letter more than once"
      is a statement about the set rather than about any one question.
    * ``multiple_choice``: nothing. Each of its questions carries its own
      prompt and options, so its ``config`` holds only how many letters to
      pick.

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

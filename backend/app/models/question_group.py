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
    FLOW_CHART_COMPLETION = "flow_chart_completion"
    MAP_LABELLING = "map_labelling"
    DIAGRAM_LABELLING = "diagram_labelling"
    MULTIPLE_CHOICE = "multiple_choice"
    MATCHING = "matching"
    #: Reading's own. The first two are answered in words the exam fixes; the
    #: four below are matching under the names the Reading paper prints, which
    #: is the same reason there are nine completion types rather than one.
    TRUE_FALSE_NOT_GIVEN = "true_false_not_given"
    YES_NO_NOT_GIVEN = "yes_no_not_given"
    MATCHING_HEADINGS = "matching_headings"
    MATCHING_INFORMATION = "matching_information"
    MATCHING_FEATURES = "matching_features"
    MATCHING_SENTENCE_ENDINGS = "matching_sentence_endings"


#: The tasks that are answered by filling in what's missing. They are one
#: thing to the server — a template with ``{{N}}`` gaps, graded against
#: accepted phrasings or against letters — and nine things to the author,
#: because a candidate is told to "complete the notes" or "label the map" and
#: an author works from a paper that says so. Keeping them apart is what stops
#: one name standing for nine tasks and making eight of them look unavailable.
COMPLETION_TYPES = frozenset(
    {
        QuestionGroupType.FORM_COMPLETION,
        QuestionGroupType.NOTE_COMPLETION,
        QuestionGroupType.SENTENCE_COMPLETION,
        QuestionGroupType.SUMMARY_COMPLETION,
        QuestionGroupType.SHORT_ANSWER,
        QuestionGroupType.TABLE_COMPLETION,
        QuestionGroupType.FLOW_CHART_COMPLETION,
        QuestionGroupType.MAP_LABELLING,
        QuestionGroupType.DIAGRAM_LABELLING,
    }
)

#: The two that are answered on a picture. They are completion tasks in every
#: way that matters to the server — a list of gaps, numbered, answered in words
#: or in letters — and what makes them their own pair is that the thing being
#: labelled is an uploaded image rather than typed text, so ``config`` carries a
#: picture and publishing insists on it.
#:
#: Two names rather than one for the same reason the seven above are seven: a
#: paper says "Label the map below" in Part 2 and "Label the diagram below" in
#: Part 4, and an author looking for the second should not have to know it is
#: the first wearing a different hat.
LABELLING_TYPES = frozenset(
    {QuestionGroupType.MAP_LABELLING, QuestionGroupType.DIAGRAM_LABELLING}
)


#: The two whose options the EXAM fixes rather than the author. A candidate
#: answers them in words — "TRUE", "NOT GIVEN" — which is what the answer key
#: prints and therefore what ``correct_answers`` holds, so they are graded by
#: :func:`app.services.grading.grade_answer` like any other written answer and
#: need no special case there.
#:
#: Their options are deliberately NOT stored in ``config``. Writing them down
#: would make them look authored, would let two groups of the same type offer
#: different words, and — because a group with options in its config is a
#: lettered group (:func:`app.services.listening.answers_are_letters`) — would
#: silently switch grading to set-matching letters against the word "TRUE".
FIXED_CHOICE_OPTIONS: dict[str, tuple[str, ...]] = {
    QuestionGroupType.TRUE_FALSE_NOT_GIVEN: ("TRUE", "FALSE", "NOT GIVEN"),
    QuestionGroupType.YES_NO_NOT_GIVEN: ("YES", "NO", "NOT GIVEN"),
}

FIXED_CHOICE_TYPES = frozenset(FIXED_CHOICE_OPTIONS)

#: Every task that is a box of options answering a list of items. The Reading
#: paper gives four of them their own names and their own instruction lines —
#: headings against paragraphs, information against paragraphs, features
#: against statements, sentence beginnings against endings — and underneath
#: they are one task, exactly as the nine completion types are one task.
#:
#: What differs between them is where the box comes from and how it is
#: lettered, and both of those live in the group's config rather than here.
MATCHING_TYPES = frozenset(
    {
        QuestionGroupType.MATCHING,
        QuestionGroupType.MATCHING_HEADINGS,
        QuestionGroupType.MATCHING_INFORMATION,
        QuestionGroupType.MATCHING_FEATURES,
        QuestionGroupType.MATCHING_SENTENCE_ENDINGS,
    }
)


def same_question_kind(before: str, after: str) -> bool:
    """Whether a group changing type keeps the questions it already has.

    Renaming the task does: gap 3 of a form and gap 3 of the notes it becomes
    are the same question, with the same answers, said at the same moment. A
    form turning into multiple choice is not — the answer key means something
    else entirely — and nothing is kept across that.
    """
    return (
        before == after
        or (before in COMPLETION_TYPES and after in COMPLETION_TYPES)
        # The same for matching under its four Reading names: headings and
        # features are one box of letters answering one list of items, and
        # renaming the task no more changes its answers than renaming a form
        # to a set of notes does.
        or (before in MATCHING_TYPES and after in MATCHING_TYPES)
        or (before in FIXED_CHOICE_TYPES and after in FIXED_CHOICE_TYPES)
    )


class QuestionGroup(SQLModel, table=True):
    """A set of questions sharing one instruction line, and — where the type
    has one — one presentational resource, which lives in ``config``:

    * the completion tasks (``form_completion``, ``note_completion``,
      ``sentence_completion``, ``summary_completion``, ``short_answer``,
      ``table_completion``): the
      gap-fill template. They differ in what the paper calls them and in the
      shape the template takes — a form has a label column, notes and
      sentences run the full width, a table is a grid, a flow chart is a chain
      of boxes — and in nothing else.
    * ``map_labelling`` / ``diagram_labelling``: the same template, plus the
      picture the labels are on and how many letters are drawn on it. The
      picture is the group's because the paper prints it once, above the whole
      set, which is the same reason matching's box is.
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

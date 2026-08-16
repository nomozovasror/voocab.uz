import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class Question(SQLModel, table=True):
    """One gradeable question within a :class:`QuestionGroup` (normalized, not
    embedded in the group's JSON config, so each answer stays individually
    gradeable and event-sourceable).

    ``number`` is the question's place **within its group**, always 1..N. The
    number a candidate reads runs across the whole material ("Questions
    7–10"), but that is a view of the ordered tree, not a stored value: it
    would otherwise have to be rewritten on every row of every later group
    each time a group was added, removed or moved.

    ``correct_answers`` means two subtly different things, and which one is
    decided by the question's GROUP (see
    :func:`app.services.listening.answers_are_letters`):

    * a gap-fill question holds the ACCEPTED VARIANTS — any one of them,
      matched exactly after normalization, is right;
    * a lettered question — multiple choice, matching — holds THE ANSWER KEY:
      the set of option letters that must be selected, all of them and nothing
      else (IELTS gives no partial credit for a "choose two").

    It used to be read off this row alone, on the reasoning that a question
    with options is a choice question. A matching item's options are its
    group's, so the row no longer knows.

    ``replay_start_ms``/``replay_end_ms`` mark where in the recording this
    answer is said, so a student reviewing a finished attempt can hear the
    moment they missed. Nullable: an author may never mark it, and a gap with
    no mark simply offers no replay. Never sent before an attempt is
    submitted — knowing where to listen is most of the question."""

    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint("group_id", "number", name="uq_questions_group_number"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    group_id: uuid.UUID = Field(foreign_key="question_groups.id", index=True)
    number: int
    correct_answers: list[str] = Field(sa_column=Column(JSONB, nullable=False))
    #: Per-question presentation, for the types that have any — the same
    #: division of labour as :attr:`QuestionGroup.config`, one level down.
    #: NULL for form completion, whose prompt is the group's template.
    #: ``matching``: ``{"prompt": str}`` — the item to be matched. What it may
    #: be matched TO is the group's box of options, so there is no ``options``
    #: key here and :attr:`options` below answers ``None``.
    #: ``multiple_choice``: ``{"prompt": str, "options": [str, ...],
    #: "option_replay": {letter: [start_ms, end_ms]}}``. How many of those
    #: options the candidate picks is the group's business, not the
    #: question's — see :class:`app.schemas.listening.MultipleChoiceConfig`.
    #: Where each answer is given is the OPTION's, since a "choose two" has
    #: two of them at two moments; the ``replay_*`` columns below carry a
    #: form gap's, where one question is one answer.
    #: Nothing gradeable lives in here: the answer key is ``correct_answers``,
    #: so the take tree can hand over the whole of a question's presentation
    #: without deciding what to strip.
    config: dict | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    replay_start_ms: int | None = Field(default=None)
    replay_end_ms: int | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    @property
    def options(self) -> list[str] | None:
        """The answer options this question carries ITSELF. ``None`` — not an
        empty list — for a gap-fill, which has none, and for a matching item,
        whose options belong to its group. Only multiple choice answers with a
        list, which is what the take serializer sends alongside the prompt."""
        if self.config is None:
            return None
        options = self.config.get("options")
        return list(options) if isinstance(options, list) else None

    @property
    def option_replay(self) -> dict[str, tuple[int, int]]:
        """Where each of this question's answers is given, by option letter.

        Empty for a gap, and for a choice question nobody has marked yet.
        Read through a property so every caller sees the same shape whatever
        happens to be in the JSON — a half-written entry is no entry."""
        raw = (self.config or {}).get("option_replay")
        if not isinstance(raw, dict):
            return {}
        spans: dict[str, tuple[int, int]] = {}
        for letter, span in raw.items():
            if (
                isinstance(span, (list, tuple))
                and len(span) == 2
                and all(isinstance(n, int) for n in span)
            ):
                spans[str(letter)] = (span[0], span[1])
        return spans

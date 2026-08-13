"""Request/response schemas for listening authoring (brief §5). Validation
happens here so a malformed group/template/question set raises 422 before any
DB write — the router/service never see a half-valid payload.

Two group types exist, and the split runs all the way through this module: a
form-completion group is a template plus its gaps, a multiple-choice group is
a list of self-contained questions. They share an instruction line and
nothing else, so they are two schemas under a tagged union rather than one
schema with half its fields optional — which is also what makes
"a template is required" and "options are required" enforceable at all.

What each of them will and won't refuse is a deliberate line. These payloads
are written by an editor that autosaves while the author is still typing, so
anything that is merely *unfinished* — no instructions yet, no questions yet,
a question with no text, an option left blank, no correct answer marked — has
to be storable. Those are publishing requirements
(app/services/publishing.py), not write-time errors. The earliest draft of a
group is one that knows only what kind it is, and that has to survive being
saved, or the author is asked the same question every time they come back.

What is refused here is what would be *incoherent*: an answer key pointing at
an option that doesn't exist, question numbers with holes in them, a template
whose gaps and questions disagree, a gap with no accepted answer at all.
"""

import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

QuestionGroupType = Literal["form_completion", "multiple_choice"]

_TOKEN_RE = re.compile(r"\{\{(\d+)\}\}")

#: Option labels, in the order the options are listed. A choice question's
#: answer key is written in these rather than in indices or option text: it is
#: what the paper says ("Choose the correct letter, A, B or C"), what the
#: candidate submits, and what a ``question_attempts`` row is still readable
#: as years later. Twenty-six is where single letters run out, not a limit
#: anyone will meet.
OPTION_LETTERS = "abcdefghijklmnopqrstuvwxyz"
MAX_OPTIONS = len(OPTION_LETTERS)


def option_letter(index: int) -> str:
    """The label for the option at ``index`` (0 -> "a")."""
    return OPTION_LETTERS[index]


# --- Part -------------------------------------------------------------------


class PartCreate(BaseModel):
    order_index: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=200)
    audio_start_ms: int | None = Field(default=None, ge=0)
    audio_end_ms: int | None = Field(default=None, ge=0)

    @field_validator("title")
    @classmethod
    def _strip_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title must not be blank")
        return v

    @model_validator(mode="after")
    def _ordered_range(self) -> "PartCreate":
        if (
            self.audio_start_ms is not None
            and self.audio_end_ms is not None
            and self.audio_end_ms <= self.audio_start_ms
        ):
            raise ValueError("The part's end must come after its start")
        return self


class PartUpdate(BaseModel):
    """All fields optional (PATCH). ``audio_end_ms > audio_start_ms`` is
    validated against the MERGED result (existing + incoming), in
    app/services/listening.py, since either bound may be omitted here and
    still need to be checked against the other's existing DB value."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    audio_start_ms: int | None = Field(default=None, ge=0)
    audio_end_ms: int | None = Field(default=None, ge=0)

    @field_validator("title")
    @classmethod
    def _strip_title(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("title must not be blank")
        return v


class PartOut(BaseModel):
    id: uuid.UUID
    material_id: uuid.UUID
    order_index: int
    title: str
    audio_start_ms: int | None
    audio_end_ms: int | None
    created_at: datetime


# --- QuestionGroup + Question -------------------------------------------------


#: The rubric printed above a completion task. IELTS uses a small closed set
#: of these, and the two axes that vary — how many words, and whether a number
#: counts — don't compose into free text an author should be typing by hand.
#: Kept in ``config`` rather than as a column: it is presentation, and config
#: is already JSONB, so no migration.
AnswerRubric = Literal[
    "one_word",
    "one_word_number",
    "two_words",
    "two_words_number",
    "three_words",
    "three_words_number",
]


class QuestionGroupConfig(BaseModel):
    """``form_completion`` presentation payload: the gap-fill template. Gaps
    are ``{{N}}`` tokens, 1-indexed and contiguous — validated against the
    question set on :class:`FormCompletionGroupIn`."""

    #: Blank means an empty form — one the author has opened and not yet
    #: written into. Refusing it made the first save of a new group fail,
    #: which is the save that records what kind of group it is.
    #: :class:`FormCompletionGroupIn` is where a template and its questions
    #: are held to agreeing with each other, blank included.
    template: str = ""
    answer_rubric: AnswerRubric | None = None


class MultipleChoiceConfig(BaseModel):
    """``multiple_choice`` at group level: how many letters the candidate
    picks. The prompt and options belong to each question, not to the set.

    This is a property of the set because the instruction line is a property
    of the set, and the instruction line is what states it — "Choose the
    correct letter, A, B or C" against "Choose TWO letters, A–E". Held per
    question, as it was, a group could be built whose instructions said one
    thing and whose questions did another, and nothing anywhere would object.
    In a real paper the two forms are printed under separate instructions,
    which is exactly what a second group is."""

    #: 1 is the ordinary single-answer question. Above that, every question in
    #: the group asks for that many — a count rather than a "several" flag,
    #: because "several" doesn't tell the candidate what to do and doesn't
    #: stop one question in the group asking for two while the next asks for
    #: three under the same instruction line.
    answers_per_question: int = Field(default=1, ge=1, le=MAX_OPTIONS)


class _QuestionInBase(BaseModel):
    number: int = Field(ge=1)
    #: Where in the recording this answer is said (§ replay). Optional — an
    #: author can publish without marking any of them.
    replay_start_ms: int | None = Field(default=None, ge=0)
    replay_end_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _replay_range_ordered(self) -> "_QuestionInBase":
        if (
            self.replay_start_ms is not None
            and self.replay_end_ms is not None
            and self.replay_end_ms <= self.replay_start_ms
        ):
            raise ValueError("the replay range's end must come after its start")
        return self


class QuestionIn(_QuestionInBase):
    """One gap in a form. ``correct_answers`` is the list of accepted
    variants, and at least one is required: a gap nobody can answer isn't a
    draft of anything, and the editor holds a half-written form back rather
    than sending one."""

    correct_answers: list[str] = Field(min_length=1)

    @field_validator("correct_answers")
    @classmethod
    def _clean_answers(cls, v: list[str]) -> list[str]:
        cleaned = [a.strip() for a in v]
        if not cleaned or any(not a for a in cleaned):
            raise ValueError(
                "correct_answers must be non-empty and contain no blank entries"
            )
        return cleaned


class ChoiceQuestionIn(_QuestionInBase):
    """One multiple-choice question: its text, its options, and which of them
    are right.

    Almost everything here is optional, because almost everything here is
    typed over several minutes and autosaved throughout. What isn't optional
    is coherence: ``correct_answers`` may only name options that exist, and
    may not run past what the group asks for (checked on the group, which is
    the only place both are in view). An empty or short answer key is a
    question the author hasn't finished, which publishing refuses and this
    doesn't."""

    prompt: str = ""
    options: list[str] = Field(default_factory=list, max_length=MAX_OPTIONS)
    #: The answer key, as option letters. Not accepted variants — the set has
    #: to be matched exactly (see :class:`app.models.question.Question`).
    correct_answers: list[str] = Field(default_factory=list)

    @field_validator("prompt")
    @classmethod
    def _clean_prompt(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def _answers_name_real_options(self) -> "ChoiceQuestionIn":
        letters = [a.strip().lower() for a in self.correct_answers]
        if len(letters) != len(set(letters)):
            raise ValueError("correct_answers must not repeat an option")
        available = {option_letter(i) for i in range(len(self.options))}
        unknown = [letter for letter in letters if letter not in available]
        if unknown:
            raise ValueError(
                f"correct_answers name options that don't exist: {', '.join(unknown)}"
            )
        # Stored in the options' own order, so the key reads the way the
        # question does and two equivalent keys can't be written two ways.
        self.correct_answers = sorted(letters, key=OPTION_LETTERS.index)
        return self


class _QuestionGroupInBase(BaseModel):
    #: Blank is allowed, and means the author hasn't written them yet.
    #:
    #: This used to be required, which read as a sensible invariant and was
    #: in fact a way to lose work: the first thing an author settles about a
    #: group is what kind of questions it holds, and a group with a kind and
    #: nothing else had no representation here at all. It could not be saved,
    #: so it was not saved, so choosing "multiple choice" and coming back the
    #: next day meant being asked again.
    #:
    #: Publishing still requires them (services/publishing.py), which is
    #: where a requirement about finished work belongs. What this schema
    #: refuses is incoherence, not incompleteness — same line the
    #: multiple-choice questions above draw.
    instructions: str = ""
    #: Form completion's answer length. Carried on the base so both group
    #: types have one shape; multiple choice never sets it — how long an
    #: answer may be is not a question you can ask about a letter.
    word_limit: int | None = Field(default=None, ge=1)


def _contiguous_numbers(questions: list[_QuestionInBase]) -> set[int]:
    """The question numbers, checked to be 1..N with no holes and no repeats.

    Numbers are the question's place inside its group, so they are always
    1..N however the group is numbered on the page — the run a candidate
    reads ("Questions 7–10") is worked out from the material's order."""
    numbers = [q.number for q in questions]
    if len(numbers) != len(set(numbers)):
        raise ValueError("question numbers must be unique")
    if set(numbers) != set(range(1, len(numbers) + 1)):
        raise ValueError(
            f"question numbers must be contiguous 1..{len(numbers)}, starting at 1"
        )
    return set(numbers)


class FormCompletionGroupIn(_QuestionGroupInBase):
    """Full authoring payload for a form-completion group: template + its
    questions, authored and validated as one atomic unit (§5 — no per-gap
    endpoint)."""

    type: Literal["form_completion"] = "form_completion"
    config: QuestionGroupConfig
    #: A form with no gaps in it yet is a form being written — the labels
    #: typically go in before the answers do. Empty is a draft, not an error;
    #: publishing is where "add at least one question" is enforced.
    questions: list[QuestionIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _tokens_match_questions(self) -> "FormCompletionGroupIn":
        tokens = [int(n) for n in _TOKEN_RE.findall(self.config.template)]
        if not tokens:
            # No gaps and no questions is coherent — the two agree that this
            # form has nothing to answer yet. Questions without tokens to
            # sit in is not.
            if self.questions:
                raise ValueError("template must contain at least one {{N}} gap token")
            return self
        if len(tokens) != len(set(tokens)):
            raise ValueError("template gap tokens must not repeat")
        token_set = set(tokens)
        expected = set(range(1, len(tokens) + 1))
        if token_set != expected:
            raise ValueError(
                f"template gap tokens must be contiguous 1..{len(tokens)} with no "
                "gaps, starting at 1"
            )

        if _contiguous_numbers(list(self.questions)) != token_set:
            raise ValueError(
                "question numbers must exactly match the template's gap tokens"
            )
        return self


class MultipleChoiceGroupIn(_QuestionGroupInBase):
    """Full authoring payload for a multiple-choice group: the instruction
    line and the questions under it, replaced as one unit like any other
    group."""

    type: Literal["multiple_choice"]
    config: MultipleChoiceConfig = Field(default_factory=MultipleChoiceConfig)
    #: Empty for the same reason as a form's: this is what a group looks like
    #: between being given a kind and being given a question.
    questions: list[ChoiceQuestionIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _numbers_contiguous(self) -> "MultipleChoiceGroupIn":
        _contiguous_numbers(list(self.questions))
        return self

    @model_validator(mode="after")
    def _keys_fit_what_the_group_asks(self) -> "MultipleChoiceGroupIn":
        """A key may be short — that question isn't finished — but never
        longer than the number of letters the candidate is told to pick. A
        group asking for two with three marked right is not gradeable: the
        candidate can only ever submit two, so the answer would be wrong
        however well they listened."""
        wanted = self.config.answers_per_question
        over = [
            q.number for q in self.questions if len(q.correct_answers) > wanted
        ]
        if over:
            raise ValueError(
                f"this group asks for {wanted} answer(s) per question, but "
                f"question(s) {', '.join(str(n) for n in over)} mark more"
            )
        return self


#: What the create/replace endpoints accept. Tagged on ``type`` so the request
#: is validated against the group it claims to be — a multiple-choice payload
#: is never checked for a template it shouldn't have, and a form-completion
#: one can't quietly arrive without questions for its gaps.
QuestionGroupIn = Annotated[
    FormCompletionGroupIn | MultipleChoiceGroupIn,
    Field(discriminator="type"),
]


class QuestionOut(BaseModel):
    """The author's view of a question — everything, answer key included.
    Only ever reached through an ownership check (see
    ``app/api/listening.py``); the candidate's view is
    :class:`TakeQuestionOut`, which is a different model on purpose."""

    id: uuid.UUID
    number: int
    correct_answers: list[str]
    replay_start_ms: int | None
    replay_end_ms: int | None
    #: Multiple choice only; ``None`` for a gap in a form. How many answers
    #: the question wants isn't here — it is the group's, so the editor reads
    #: it once from :class:`MultipleChoiceConfig` rather than off whichever
    #: question happens to be first.
    prompt: str | None = None
    options: list[str] | None = None


class QuestionGroupOut(BaseModel):
    id: uuid.UUID
    part_id: uuid.UUID
    order_index: int
    type: str
    instructions: str
    word_limit: int | None
    config: dict
    questions: list[QuestionOut]


class QuestionGroupOrderIn(BaseModel):
    """The part's groups, in the order the author has put them. Every one of
    them, by id: a move is expressed as the whole new order rather than as
    "up"/"down", so two windows can't interleave two half-moves into an order
    neither of them asked for."""

    group_ids: list[uuid.UUID] = Field(min_length=1)

    @field_validator("group_ids")
    @classmethod
    def _no_repeats(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(v) != len(set(v)):
            raise ValueError("group_ids must not repeat")
        return v


# --- Consumption: take (§7, §3.4 — MUST NEVER carry correct_answers) --------


class TakeQuestionOut(BaseModel):
    """The student's view of a question: only what's needed to render it and
    submit an answer. No ``correct_answers`` field exists on this model at
    all — even if a caller mistakenly fed it a dict that had the key, pydantic
    drops unknown fields, so this is a second, structural guarantee on top of
    the take-serializer in app/services/listening.py never adding it in the
    first place.

    The choice fields below are the reason this model names its fields one by
    one instead of passing a question's ``config`` through the way the group
    does: a candidate may see the prompt and the options, and nothing else
    that might one day be put in there."""

    id: uuid.UUID
    number: int
    #: Multiple choice only. ``options`` is the option TEXT, in order — which
    #: of them is right is not expressible here.
    prompt: str | None = None
    options: list[str] | None = None
    #: How many options to pick. Public by design: "Choose TWO letters" is
    #: printed on the paper, and knowing how many are right tells the
    #: candidate nothing about which.
    select_count: int | None = None


class TakeQuestionGroupOut(BaseModel):
    id: uuid.UUID
    order_index: int
    type: str
    instructions: str
    word_limit: int | None
    config: dict
    questions: list[TakeQuestionOut]


class TakePartOut(BaseModel):
    id: uuid.UUID
    order_index: int
    title: str
    audio_start_ms: int | None
    audio_end_ms: int | None
    question_groups: list[TakeQuestionGroupOut]


class MaterialTakeOut(BaseModel):
    id: uuid.UUID
    title: str
    audio_url: str | None
    duration_ms: int | None
    parts: list[TakePartOut]


# --- Consumption: submit + grade (§7) ---------------------------------------


class AnswerIn(BaseModel):
    """One submitted answer. ``given_answer`` is stored raw (unmodified) —
    normalization happens only for comparison, in app/services/grading.py,
    never mutating what's persisted."""

    question_id: uuid.UUID
    given_answer: str = ""


class AttemptSubmit(BaseModel):
    answers: list[AnswerIn] = Field(default_factory=list)


class QuestionResultOut(BaseModel):
    """Post-submit feedback. Unlike the take response, correct_answers here
    is intentional and correct (§7): the student has already committed their
    answers, so revealing the accepted set is the whole point of grading
    feedback."""

    question_id: uuid.UUID
    is_correct: bool
    correct_answers: list[str]
    #: Safe to send here for the same reason as ``correct_answers``: the
    #: attempt is already committed, so pointing at the moment in the
    #: recording is feedback rather than a hint.
    replay_start_ms: int | None
    replay_end_ms: int | None


class AttemptResultOut(BaseModel):
    score: int
    total_questions: int
    results: list[QuestionResultOut]

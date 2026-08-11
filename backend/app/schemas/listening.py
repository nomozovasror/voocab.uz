"""Request/response schemas for listening Part-1 form-completion authoring
(brief §5). Validation happens here so a malformed group/template/question
set raises 422 before any DB write — the router/service never see a
half-valid payload.
"""

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

QuestionGroupType = Literal["form_completion"]

_TOKEN_RE = re.compile(r"\{\{(\d+)\}\}")


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
    question set on :class:`QuestionGroupIn`."""

    template: str
    answer_rubric: AnswerRubric | None = None

    @field_validator("template")
    @classmethod
    def _nonblank_template(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("template must not be blank")
        return v


class QuestionIn(BaseModel):
    number: int = Field(ge=1)
    correct_answers: list[str] = Field(min_length=1)
    #: Where in the recording this answer is said (§ replay). Optional — an
    #: author can publish without marking any of them.
    replay_start_ms: int | None = Field(default=None, ge=0)
    replay_end_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _replay_range_ordered(self) -> "QuestionIn":
        if (
            self.replay_start_ms is not None
            and self.replay_end_ms is not None
            and self.replay_end_ms <= self.replay_start_ms
        ):
            raise ValueError("the replay range's end must come after its start")
        return self

    @field_validator("correct_answers")
    @classmethod
    def _clean_answers(cls, v: list[str]) -> list[str]:
        cleaned = [a.strip() for a in v]
        if not cleaned or any(not a for a in cleaned):
            raise ValueError(
                "correct_answers must be non-empty and contain no blank entries"
            )
        return cleaned


class QuestionGroupIn(BaseModel):
    """Full authoring payload for a group: template + its questions, authored
    and validated as one atomic unit (§5 — no per-gap endpoint)."""

    type: QuestionGroupType = "form_completion"
    instructions: str = Field(min_length=1)
    word_limit: int | None = Field(default=None, ge=1)
    config: QuestionGroupConfig
    questions: list[QuestionIn] = Field(min_length=1)

    @field_validator("instructions")
    @classmethod
    def _nonblank_instructions(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("instructions must not be blank")
        return v

    @model_validator(mode="after")
    def _tokens_match_questions(self) -> "QuestionGroupIn":
        tokens = [int(n) for n in _TOKEN_RE.findall(self.config.template)]
        if not tokens:
            raise ValueError("template must contain at least one {{N}} gap token")
        if len(tokens) != len(set(tokens)):
            raise ValueError("template gap tokens must not repeat")
        token_set = set(tokens)
        expected = set(range(1, len(tokens) + 1))
        if token_set != expected:
            raise ValueError(
                f"template gap tokens must be contiguous 1..{len(tokens)} with no "
                "gaps, starting at 1"
            )

        numbers = [q.number for q in self.questions]
        if len(numbers) != len(set(numbers)):
            raise ValueError("question numbers must be unique")
        if set(numbers) != token_set:
            raise ValueError(
                "question numbers must exactly match the template's gap tokens"
            )
        return self


class QuestionOut(BaseModel):
    id: uuid.UUID
    number: int
    correct_answers: list[str]
    replay_start_ms: int | None
    replay_end_ms: int | None


class QuestionGroupOut(BaseModel):
    id: uuid.UUID
    part_id: uuid.UUID
    order_index: int
    type: str
    instructions: str
    word_limit: int | None
    config: dict
    questions: list[QuestionOut]


# --- Consumption: take (§7, §3.4 — MUST NEVER carry correct_answers) --------


class TakeQuestionOut(BaseModel):
    """The student's view of a gap: only what's needed to render an input
    and submit an answer. No ``correct_answers`` field exists on this model
    at all — even if a caller mistakenly fed it a dict that had the key,
    pydantic drops unknown fields, so this is a second, structural guarantee
    on top of the take-serializer in app/services/listening.py never adding
    it in the first place."""

    id: uuid.UUID
    number: int


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

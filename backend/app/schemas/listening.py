"""Request/response schemas for listening authoring (brief §5). Validation
happens here so a malformed group/template/question set raises 422 before any
DB write — the router/service never see a half-valid payload.

Three group types exist, and the split runs all the way through this module:
a form-completion group is a template plus its gaps, a multiple-choice group
is a list of self-contained questions, and a matching group is one box of
lettered options with a list of items answered from it. They share an
instruction line and nothing else, so they are three schemas under a tagged
union rather than one schema with most of its fields optional — which is also
what makes "a template is required" and "an answer must name an option that
exists" enforceable at all.

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

#: The tasks answered by filling in what's missing. One payload shape, nine
#: names, because that is how the paper prints them and how an author thinks
#: about them — see :data:`app.models.question_group.COMPLETION_TYPES`.
CompletionType = Literal[
    "form_completion",
    "note_completion",
    "sentence_completion",
    "summary_completion",
    "short_answer",
    "table_completion",
    "flow_chart_completion",
    "map_labelling",
    "diagram_labelling",
]

#: The two of those that are answered on an uploaded picture.
LABELLING_TYPES = frozenset({"map_labelling", "diagram_labelling"})

QuestionGroupType = Literal[
    "form_completion",
    "note_completion",
    "sentence_completion",
    "summary_completion",
    "short_answer",
    "table_completion",
    "flow_chart_completion",
    "map_labelling",
    "diagram_labelling",
    "multiple_choice",
    "matching",
]

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
    """A completion task's presentation payload: the gap-fill template, plus
    whatever the gaps are answered from where they aren't answered in words —
    the box of a word list, or the letters drawn on a picture. Gaps are
    ``{{N}}`` tokens, 1-indexed and contiguous — validated against the question
    set on :class:`FormCompletionGroupIn`."""

    #: Blank means an empty form — one the author has opened and not yet
    #: written into. Refusing it made the first save of a new group fail,
    #: which is the save that records what kind of group it is.
    #: :class:`FormCompletionGroupIn` is where a template and its questions
    #: are held to agreeing with each other, blank included.
    template: str = ""
    answer_rubric: AnswerRubric | None = None
    #: "Complete the summary using the list of words, A–H." Empty is the
    #: ordinary completion task, where the candidate writes the words they
    #: heard; non-empty turns every gap in this group into a letter, and the
    #: answer key with it.
    #:
    #: Same two fields, same names, as :class:`MatchingConfig` — because it is
    #: the same thing. A boxed summary is matching whose items are gaps in a
    #: paragraph instead of a list, and reading them through one accessor
    #: (``app.services.listening.group_options``) is what keeps grading from
    #: having to know which of the two it is looking at.
    options: list[str] = Field(default_factory=list, max_length=MAX_OPTIONS)
    allow_reuse: bool = False

    #: The picture a map or diagram task is labelled on: an
    #: :class:`app.models.image_blob.ImageBlob` id, from a prior POST
    #: /api/uploads/image. That the id names a picture which exists is checked
    #: where a session is in view (app/services/listening.py) — a schema can't
    #: ask the database.
    #:
    #: Carried on the shared config rather than on a labelling-only one, and
    #: kept across a change of type rather than refused: an author who renames
    #: a map task to notes and back should find their picture still attached,
    #: the same way an unmarked option keeps the moment it was marked at. Only
    #: the two labelling types draw it, so a stray picture on a set of notes is
    #: dead weight in JSONB and nothing more.
    image: uuid.UUID | None = None
    #: Whether to fit the picture to the page's colours instead of printing it
    #: as uploaded. Almost every map is black line art on white, which in dark
    #: mode is a lit sheet punched into the page; inverting it gives our own ink
    #: on our own background. The bytes can't tell us whether that will help —
    #: a photographed page wants it, a coloured plan does not — so it is the
    #: author's switch, per picture.
    image_adapt: bool = True
    #: How many letters are drawn on the picture. Zero is the ordinary labelling
    #: task, where the candidate writes what they heard into numbered blanks;
    #: above zero, the picture IS the box — the letters are on it, and every gap
    #: in this group is answered by one of them.
    #:
    #: A count and not a list, because unlike a word box there is nothing to
    #: type: the letters were drawn by whoever drew the map, and all the server
    #: needs to know is how far up the alphabet they run.
    image_letters: int = Field(default=0, ge=0, le=MAX_OPTIONS)


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


class MatchingConfig(BaseModel):
    """``matching`` at group level: the box of options every question under it
    is answered from, and whether an option may answer more than one of them.

    The box is the group's because the paper prints it once, above the whole
    set — *A holiday cottage, B a hotel, C a campsite* — and the items
    underneath are answered by pointing at it. Held per question, as multiple
    choice holds its options, the same five lines would be stored once per
    item and could be edited into five different boxes under one heading.
    """

    #: In the order they are lettered, so ``options[2]`` is C. Empty is a box
    #: the author has opened and not yet written into — a draft, like every
    #: other emptiness in this module.
    options: list[str] = Field(default_factory=list, max_length=MAX_OPTIONS)
    #: "You may use any letter more than once", which a real paper prints as
    #: an NB line under the instructions. False is the ordinary case: as many
    #: options as items, each used once, and two items sharing a letter is
    #: then something publishing objects to.
    allow_reuse: bool = False


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
    """One gap in a completion task. ``correct_answers`` is the list of
    accepted variants — or, where the group has a box, the one letter the gap
    is answered by.

    Empty is allowed, and that is a change: a gap with no answer used to be
    refused here, on the reasoning that nobody could answer it and so it was
    not a draft of anything. A boxed task makes that plainly untrue. There the
    gap is made first and the letter chosen afterwards, so every gap is
    unanswered for as long as it takes to reach for the box — and refusing it
    meant a whole summary went unsaved while it was being written.

    Blank entries are still refused. An empty list is a gap nobody has
    answered yet; a list holding ``""`` is a claim that the answer is nothing.
    Publishing requires an answer either way (services/publishing.py)."""

    correct_answers: list[str] = Field(default_factory=list)

    @field_validator("correct_answers")
    @classmethod
    def _clean_answers(cls, v: list[str]) -> list[str]:
        cleaned = [a.strip() for a in v]
        if any(not a for a in cleaned):
            raise ValueError("correct_answers must contain no blank entries")
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
    #: Where each answer is given, per OPTION rather than per question:
    #: ``{"b": [12000, 15500]}``.
    #:
    #: A "Choose TWO letters" has two answers and they are almost never said
    #: in the same breath — one at 0:57, the other two minutes later. A
    #: single range on the question could only ever point at one of them,
    #: which is why the mark belongs where the answer does. It is the same
    #: shape the form has: there, one gap is one answer and carries its own
    #: range; here, one right option is one answer and carries its own.
    #:
    #: Keyed by letter for the same reason ``correct_answers`` is — that is
    #: what identifies an option once it is stored. Marks on options that
    #: aren't currently right are kept rather than dropped: an author who
    #: unmarks an option and marks it again should not have to find the
    #: moment twice.
    option_replay: dict[str, tuple[int, int]] = Field(default_factory=dict)

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

    @model_validator(mode="after")
    def _marks_name_real_options(self) -> "ChoiceQuestionIn":
        cleaned: dict[str, tuple[int, int]] = {}
        available = {option_letter(i) for i in range(len(self.options))}
        for letter, span in self.option_replay.items():
            key = letter.strip().lower()
            if key not in available:
                raise ValueError(
                    f"option_replay names an option that doesn't exist: {letter}"
                )
            start, end = span
            if start < 0 or end <= start:
                raise ValueError(
                    f"option {key}'s replay range must end after it starts"
                )
            cleaned[key] = (start, end)
        self.option_replay = cleaned
        return self


class MatchingQuestionIn(_QuestionInBase):
    """One item to be matched: its text, and the letter it is answered by.

    The letter is checked against the group's box of options, not against
    anything here — this model can't see it. An item with no answer yet is a
    draft, like everything else that is merely unfinished; publishing is where
    every item is required to have one.

    Where the answer is given lives on the question's own ``replay_*``
    columns, the way a form gap's does, because one item is one answer said at
    one moment. Multiple choice needed a range per option only because a
    "choose two" has two of them.
    """

    prompt: str = ""
    #: At most one letter. An item matched to two options isn't a matching
    #: question that hasn't been finished — it is one that can't be sat.
    correct_answers: list[str] = Field(default_factory=list, max_length=1)

    @field_validator("prompt")
    @classmethod
    def _clean_prompt(cls, v: str) -> str:
        return v.strip()

    @field_validator("correct_answers")
    @classmethod
    def _clean_letters(cls, v: list[str]) -> list[str]:
        return [letter.strip().lower() for letter in v if letter.strip()]


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
    """Full authoring payload for a completion group: template + its
    questions, authored and validated as one atomic unit (§5 — no per-gap
    endpoint).

    One schema for all nine completion tasks. They carry the same fields and
    are checked the same way — what differs between a form and a set of notes
    is the shape of the template, which is the author's business and not
    something to validate. The discriminator accepts all nine so a payload is
    still routed here by name rather than by trial."""

    type: CompletionType = "form_completion"
    config: QuestionGroupConfig
    #: A form with no gaps in it yet is a form being written — the labels
    #: typically go in before the answers do. Empty is a draft, not an error;
    #: publishing is where "add at least one question" is enforced.
    questions: list[QuestionIn] = Field(default_factory=list)

    @property
    def letter_count(self) -> int:
        """How many letters this group's gaps are answered from, or 0 where
        they are answered in words.

        Two places it can come from and they are the same statement: a word box
        printed above the task, or letters drawn on the picture. A picture only
        counts for the types that draw one — a leftover count on a set of notes
        would otherwise turn its gaps into letters nobody can see."""
        if self.config.options:
            return len(self.config.options)
        if self.type in LABELLING_TYPES:
            return self.config.image_letters
        return 0

    @model_validator(mode="after")
    def _one_thing_to_answer_from(self) -> "FormCompletionGroupIn":
        """A word box and lettered picture at once is not a task with two ways
        in — it is a group where nobody, the author included, can say what
        letter B means."""
        if (
            self.config.options
            and self.config.image_letters
            and self.type in LABELLING_TYPES
        ):
            raise ValueError(
                "a labelling task is answered either from a list of words or "
                "from the letters on the picture, not from both"
            )
        return self

    @model_validator(mode="after")
    def _answers_name_letters_that_exist(self) -> "FormCompletionGroupIn":
        """Where the gaps are answered by letter, each takes one — and one that
        is actually there to pick. Where they are answered in words this says
        nothing: which words are acceptable is the author's business.

        A gap with no letter yet is fine, as everywhere else here: unfinished
        is stored, incoherent is refused."""
        count = self.letter_count
        if not count:
            return self
        available = {option_letter(i) for i in range(count)}
        # "the box" or "the picture", because an author told their answer names
        # an option that doesn't exist should not have to work out which of the
        # two the task has.
        source = "the picture" if not self.config.options else "the box"
        for question in self.questions:
            letters = [a.strip().lower() for a in question.correct_answers]
            if len(letters) > 1:
                raise ValueError(
                    f"gap {question.number} is answered from {source}, so it "
                    "takes one letter"
                )
            unknown = [letter for letter in letters if letter not in available]
            if unknown:
                raise ValueError(
                    f"gap {question.number} names a letter {source} doesn't "
                    f"have: {', '.join(unknown)}"
                )
            question.correct_answers = letters
        return self

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


class MatchingGroupIn(_QuestionGroupInBase):
    """Full authoring payload for a matching group: the box of options, and
    the items answered from it, replaced as one unit like any other group."""

    type: Literal["matching"]
    config: MatchingConfig = Field(default_factory=MatchingConfig)
    #: Empty for the same reason as the other two: this is what a group looks
    #: like between being given a kind and being given a question.
    questions: list[MatchingQuestionIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _numbers_contiguous(self) -> "MatchingGroupIn":
        _contiguous_numbers(list(self.questions))
        return self

    @model_validator(mode="after")
    def _answers_name_real_options(self) -> "MatchingGroupIn":
        """An answer may be missing — that item isn't finished — but never a
        letter the box doesn't have. That is the same line
        :class:`ChoiceQuestionIn` draws, one level up: incoherent is refused,
        incomplete is stored.

        Reusing a letter is NOT refused here even where the group says each is
        used once. Reassigning two items is two saves, and the state between
        them has both pointing at the same option; publishing is where that
        has to be resolved."""
        available = {option_letter(i) for i in range(len(self.config.options))}
        unknown = sorted(
            {
                letter
                for question in self.questions
                for letter in question.correct_answers
                if letter not in available
            }
        )
        if unknown:
            raise ValueError(
                f"answers name options that don't exist: {', '.join(unknown)}"
            )
        return self


#: What the create/replace endpoints accept. Tagged on ``type`` so the request
#: is validated against the group it claims to be — a multiple-choice payload
#: is never checked for a template it shouldn't have, and a form-completion
#: one can't quietly arrive without questions for its gaps.
QuestionGroupIn = Annotated[
    FormCompletionGroupIn | MultipleChoiceGroupIn | MatchingGroupIn,
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
    #: The question's own text: a choice question's, a matching item's.
    #: ``None`` for a gap in a form, whose prompt is the template around it.
    prompt: str | None = None
    #: Multiple choice only. A matching item is answered from its group's box,
    #: and how many answers a choice question wants is the group's too — the
    #: editor reads both once from the group rather than off whichever
    #: question happens to be first.
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
    #: The question's own text — a choice question's, a matching item's.
    prompt: str | None = None
    #: Multiple choice only: the option TEXT, in order. Which of them is right
    #: is not expressible here. A matching item's options are its group's, and
    #: reach the candidate in the group's ``config`` — the same box the paper
    #: prints once above the set.
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


class AnswerTimingIn(BaseModel):
    """How one answer was arrived at, as the page watched it happen.

    Every field is optional and every field is a measurement, not an input to
    grading: nothing here can make a wrong answer right, so a client that
    reports nothing (or nonsense) costs the statistics and not the mark. That
    is why there is no attempt to verify any of it.

    Times are milliseconds since the session started, never wall-clock — the
    browser's clock is often wrong, but the distance between two of its own
    readings isn't."""

    first_answered_ms: int | None = Field(default=None, ge=0)
    last_changed_ms: int | None = Field(default=None, ge=0)
    changes: int | None = Field(default=None, ge=0)
    focus_ms: int | None = Field(default=None, ge=0)


class AnswerIn(BaseModel):
    """One submitted answer. ``given_answer`` is stored raw (unmodified) —
    normalization happens only for comparison, in app/services/grading.py,
    never mutating what's persisted."""

    question_id: uuid.UUID
    given_answer: str = ""
    #: Optional. Travels with the answer because it is a fact about this
    #: answer; a parallel list keyed by question id would be the same data
    #: with one more way to get out of step.
    timing: AnswerTimingIn | None = None


class ListenedSpanIn(BaseModel):
    """One continuous run of playback: from where the learner pressed play (or
    landed after a seek) to where the audio stopped.

    Deliberately NOT merged by the client. Two identical spans mean the same
    stretch was played twice, and that repetition is the whole signal — merged
    into one span it would be indistinguishable from playing it once."""

    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def _forwards(self) -> "ListenedSpanIn":
        if self.end_ms < self.start_ms:
            raise ValueError("end_ms must not precede start_ms")
        return self


class AttemptSubmit(BaseModel):
    answers: list[AnswerIn] = Field(default_factory=list)
    #: Every stretch of audio the learner played, in the order they played it.
    #: Capped: a session that produced more than this many separate plays has
    #: told us what it had to tell us, and the cap is what keeps a broken
    #: client from posting a megabyte of spans.
    listened: list[ListenedSpanIn] = Field(default_factory=list, max_length=500)
    #: Backward drags of the playhead. A count rather than a list of jumps:
    #: where they jumped FROM is already recoverable from ``listened``.
    seeks_back: int | None = Field(default=None, ge=0)
    #: How long the page has been open, in milliseconds. A duration and not a
    #: start timestamp on purpose — the server subtracts it from its own clock
    #: rather than believing the client's, so a device set to next year still
    #: records a sane attempt.
    elapsed_ms: int | None = Field(default=None, ge=0)


class TranscriptLineOut(BaseModel):
    """One line of the transcript, as the AUTHOR left it: the ASR's
    segmentation with the author's corrections laid over the top. The ASR's
    raw guess is never what a learner is shown — if the author fixed a
    misheard word, the review has to agree with the answer key."""

    start_ms: int
    end_ms: int
    text: str


class QuestionResultOut(BaseModel):
    """Post-submit feedback. Unlike the take response, correct_answers here
    is intentional and correct (§7): the student has already committed their
    answers, so revealing the accepted set is the whole point of grading
    feedback."""

    question_id: uuid.UUID
    #: The number printed beside it, so a results page loaded on its own —
    #: from a link, after a refresh — can name the questions without also
    #: fetching the material.
    number: int
    #: What the learner actually put. Stored on the attempt, so a review
    #: opened days later still shows it.
    given_answer: str
    is_correct: bool
    correct_answers: list[str]
    #: Safe to send here for the same reason as ``correct_answers``: the
    #: attempt is already committed, so pointing at the moment in the
    #: recording is feedback rather than a hint.
    #:
    #: A form gap has one answer and so one range. A choice question has one
    #: per right option — "Choose TWO letters" is answered in two places, and
    #: sending back one of them would send the learner to half of why they
    #: were wrong.
    replay_start_ms: int | None
    replay_end_ms: int | None
    option_replay: dict[str, list[int]] = Field(default_factory=dict)
    #: The transcript across this answer's moment — every line the marked
    #: range touches, in playback order. Empty when the author marked no
    #: range, or when the recording has no transcript yet (practice doesn't
    #: wait for one; the review just has less to show).
    transcript: list[TranscriptLineOut] = Field(default_factory=list)


class AttemptResultOut(BaseModel):
    """The whole result of one attempt, and the same object whether it was
    just submitted or fetched back later by id. One shape, one serializer:
    a results page that survives a refresh is not allowed to be a slightly
    different page."""

    attempt_id: uuid.UUID
    material_id: uuid.UUID
    material_title: str
    #: The recording, so the review can play the moment an answer was said
    #: without also fetching the whole take payload for one string. There are
    #: no clips: "hear it" is the same file, seeked.
    audio_url: str | None = None
    duration_ms: int | None = None
    score: int
    total_questions: int
    submitted_at: datetime | None = None
    results: list[QuestionResultOut]

"""What the vocabulary endpoints send and accept.

One entry shape, used by all three screens that show a word — the lookup
panel mid-paper, the review's list, the learner's saved words — because they
are showing the same thing and a second shape would be a second set of
fields to keep in step.

What the wire deliberately does NOT carry is ``frequency_band``. It is the
figure the difficulty arithmetic reads and it means nothing to a learner:
"NGSL rank 2400" is a fact about a corpus. ``cefr_level`` is the one that
travels, because B2 is a scale they already have a feel for.

``unusual`` has left it for a related reason. The column still exists and
still means what it meant -- a COMMON word in an unexpected sense, which is
the disagreement between the two difficulty measures and the input to
arithmetic over passages -- but what a reader is shown is
``sense_differs``, which is the same question asked of every entry rather
than only of the common ones. Two nearly-identical flags on one row is how
one of them quietly stops being maintained.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, model_validator

#: Rebuilt on almost every request by the practice endpoints, so named once
#: rather than repeated as a bare ``Literal`` in five schemas that would
#: then have to be kept in step by hand.
Direction = Literal["passive", "active"]
ExerciseType = Literal["recognise", "recall", "produce", "listen", "speak"]
Verdict = Literal["correct", "close", "wrong"]
#: What `PracticeItemOut`/`PracticeAnswerIn` call a level (`exercise_type`,
#: `planned_exercise`) and what the settings screen's exercise type is drawn
#: from: the ladder's rungs (passive `recognise`/`recall`/`listen`, active
#: `recognise`/`produce`) and `speak`, which is on no ladder but is planned
#: and chosen like one. `PracticeAnswerOut.level` is only ever a rung.
Level = Literal["recognise", "recall", "produce", "listen", "speak"]
Mode = Literal["auto", "recognise", "recall", "produce", "listen", "speak"]


SenseLabel = Literal["most common", "common", "less common"]


class AudioOut(BaseModel):
    """One word's audio. ``url`` is the word alone; ``context_url`` the same
    word with its neighbours, for a clip cut from a recording (never for TTS).
    ``source`` says which -- only a clip has a context press. Wherever a field
    of this type may be ``null`` it means "not ready yet", and the server has
    already queued it (``app.services.word_audio``)."""

    url: str
    context_url: str | None = None
    source: Literal["clip", "tts"]


class LookupSenseOut(BaseModel):
    """One sense of the tapped word's lemma, in display order. ``label`` is
    from SemCor counts relative to the word's top sense and is null where we
    have no data (never a guess); no count or percentage is ever sent."""

    sense_id: uuid.UUID
    pos: str
    definition_en: str
    meaning_uz: str
    cefr: str | None = None
    label: SenseLabel | None = None
    #: The sense this passage uses (the material row's). At most one, first.
    used_here: bool = False


class WordSenseOut(BaseModel):
    """:class:`LookupSenseOut` for the word page: ``saved`` marks the
    learner's saved sense (first) instead of ``used_here``."""

    sense_id: uuid.UUID
    pos: str
    definition_en: str
    meaning_uz: str
    cefr: str | None = None
    label: SenseLabel | None = None
    saved: bool = False


class VocabularyEntryOut(BaseModel):
    """One word or phrase, in this passage's sense."""

    id: uuid.UUID
    #: This row's place in the global lexicon (P4) -- null only for a row
    #: some path outside the ordinary writers left unlinked (should not
    #: happen; see `app.services.lexicon.link_row`). What "saved" below asks
    #: about is `sense_id`, not `lemma`: `bank` the river and `bank` the
    #: financial institution are two different answers to "is this saved".
    lexeme_id: uuid.UUID | None = None
    sense_id: uuid.UUID | None = None
    lemma: str
    #: The form as it stands in the passage. Not printed on its own — the
    #: reader can see it — and carried so the client can mark the right
    #: occurrence without asking again.
    surface: str
    pos: str
    #: What the word USUALLY means, and the line every screen shows first.
    #:
    #: The contextual meaning below it is still the one this whole feature
    #: exists to produce, and it is still where the value is. What it could
    #: not do on its own is teach the LANGUAGE: `learn`, glossed from a
    #: passage about artificial intelligence as "a computer process of
    #: finding patterns in data", is a true sentence about `machine
    #: learning` and a false one about the verb somebody then studied.
    #:
    #: Empty on an entry written before the field existed. Readers fall
    #: back to `meaning_en`, because a missing usual sense is narrower help
    #: and a missing contextual sense is none.
    meaning_core_en: str = ""
    meaning_core_uz: str = ""
    meaning_en: str
    meaning_uz: str
    #: Whether this passage's sense is genuinely not the usual one — the
    #: switch that decides whether a reader is shown one meaning or two.
    #: Most words in most passages are used ordinarily, and a second line
    #: under those would be the same sentence twice.
    sense_differs: bool = False
    #: The sentence from the passage that contains it. Absent from the lookup
    #: panel by design (the reader is looking at it) and the whole value of a
    #: saved word on the review page.
    example: str
    cefr_level: str
    is_phrase: bool
    #: Where it stands, in the coordinates the reading highlights use.
    #:
    #: The part as well as the paragraph, because a reading paper can hold
    #: three passages: "paragraph 1" names three of them, and a review that
    #: marks the word where it stands has to know which. Seeded materials
    #: have one part and the client used to assume so — an assumption that
    #: is true today, costs one field to stop relying on, and would have
    #: gone wrong silently on the first whole paper anybody imported.
    part_id: uuid.UUID
    paragraph_index: int
    offset_start: int
    offset_end: int
    #: Everywhere else the same word stands in this passage, as
    #: ``[paragraph_index, start, end]``. One entry per lemma is what makes
    #: a tapped word have one answer; marking only one of its occurrences
    #: is what made the list look incomplete. Empty where the gloss is
    #: about one USE rather than about the word.
    also_at: list[list[int]] = []
    #: Whether the passage has been edited since this was glossed, so the
    #: offsets may no longer point at the right words. Derived, never stored.
    stale: bool = False
    #: Whether THIS SENSE (P4) is already on the learner's list -- the row's
    #: own `sense_id`, not its `lemma`. Absent (false) for a caller asking
    #: about somebody else's material.
    saved: bool = False
    #: The saved word this sense IS, when `saved` is true -- what the ✕ on
    #: the popover/review row deletes. Null when not saved.
    saved_word_id: uuid.UUID | None = None
    #: A DIFFERENT sense of the same lexeme is on the learner's list, while
    #: this one is not -- the popover's quiet line ("You've saved another
    #: meaning of this word.") shows exactly when this is true AND `saved`
    #: is false.
    other_sense_saved: bool = False
    #: Every sense we hold for the lemma, display order, `used_here` first.
    senses: list[LookupSenseOut] = []


class LookupIn(BaseModel):
    """One word a reader tapped.

    ``paragraph_index`` and ``offset`` are optional but nearly always sent,
    and they are what makes the answer exact: an entry whose span contains
    that point needs no string matching at all, and a phrase is recognised
    by exactly the same test. Without them the word is matched by its
    spelling, which is right most of the time and cannot tell which
    occurrence was meant.
    """

    word: str = Field(min_length=1, max_length=80)
    paragraph_index: int | None = Field(default=None, ge=0)
    offset: int | None = Field(default=None, ge=0)
    #: ``take`` while the paper is open, ``review`` afterwards. Logged
    #: rather than enforced -- the budget that makes the difference matter
    #: lives in the browser, and always has -- and it also decides what a
    #: newly generated entry is filed under. Defaults to ``take`` so a
    #: client written before this field existed keeps meaning what it meant.
    context: Literal["take", "review"] = "take"


class LookupOut(BaseModel):
    """What to show for one tapped word.

    Both may be filled, and where they are the phrase is shown first: a
    reader who tapped ``rise`` inside ``give rise to`` is reading the phrase
    whatever their finger landed on. Both may be empty, which is an ordinary
    answer — a name, a number, or a morning the dictionary is unreachable.
    """

    word: VocabularyEntryOut | None = None
    phrase: VocabularyEntryOut | None = None


class VocabularySummaryOut(BaseModel):
    """How much there is to learn in one material, for the page that is
    choosing between materials."""

    total: int
    #: B1 / B2 / C1 counts. A spread, not an average: "B2: 30" is something a
    #: learner can act on and "mean CEFR 2.3" is not.
    levels: dict[str, int]
    #: How many of them are common words in an unexpected sense. The one
    #: figure neither measure reports on its own, and the one an IELTS
    #: candidate most needs warning about.
    unusual: int = 0


class VocabularyListOut(BaseModel):
    """A material's whole vocabulary, for the review page."""

    material_id: uuid.UUID
    total: int
    levels: dict[str, int]
    unusual: int = 0
    entries: list[VocabularyEntryOut]


class SaveWordsIn(BaseModel):
    """Words to put on the learner's list, from one material.

    A list rather than one word, because the review offers "save all" and
    "save the ones I looked up" beside the per-row button, and three
    endpoints for one verb is three places for the rules to drift.
    """

    material_id: uuid.UUID
    lemmas: list[str] = Field(min_length=1, max_length=200)


class SavedContextOut(BaseModel):
    """One place a saved word was met, with the sense it had there."""

    material_id: uuid.UUID
    material_title: str = ""
    surface: str
    pos: str
    meaning_core_en: str = ""
    meaning_core_uz: str = ""
    meaning_en: str
    meaning_uz: str
    sense_differs: bool = False
    example: str
    cefr_level: str
    is_phrase: bool
    created_at: datetime


class SavedWordOut(BaseModel):
    """One word the learner is studying, with every passage it came from.

    The fields below ``contexts`` are additive over stage 1's shape --
    every stage-1 caller (the review page's `Saved` button) reads only
    ``lemma``/``created_at``/``contexts`` and keeps working unchanged. They
    are what the words list (plan screen 4) and the word page (screen 5)
    need to show a row or a header without a second round trip: the
    learner's own progress, not the catalogue's.

    ``id``/``lexeme_id``/``sense_id``/``definition_en``/``meaning_uz``/
    ``sense_cefr`` are P4's own additions -- a saved word is now one sense,
    addressed by ``id`` (the lemma-path routes are gone), and its usual
    meaning/definition/CEFR are read LIVE from that sense rather than a
    stored copy, so an admin's fix in Studio reaches everybody already
    studying the word. ``meaning_core_en``/``meaning_core_uz`` STAY and are
    filled with exactly the same live values, for a caller that has not
    moved onto the new field names yet -- see ``app.models.vocabulary
    .SavedWord`` for why the columns behind them are dead.
    """

    id: uuid.UUID
    #: Both are guaranteed non-null in the database (`lexeme_sense_id` is a
    #: NOT NULL FK) -- optional here only so a caller building this schema
    #: from a bare in-memory ``SavedWord`` with no sense loaded (a unit test
    #: that never touches the database) is not forced to fabricate one.
    lexeme_id: uuid.UUID | None = None
    sense_id: uuid.UUID | None = None
    lemma: str
    created_at: datetime
    contexts: list[SavedContextOut]

    status: str = "learning"
    pos: str = ""
    meaning_core_en: str = ""
    meaning_core_uz: str = ""
    #: The sense's own English definition and Uzbek meaning, read live --
    #: the same values as ``meaning_core_en``/``meaning_core_uz`` above,
    #: under the names P4's callers use.
    definition_en: str = ""
    meaning_uz: str = ""
    #: The sense's own graded level -- distinct from ``cefr_level`` below,
    #: which is the newest CONTEXT's level and unchanged in meaning.
    sense_cefr: str = ""
    #: The newest context's CEFR level -- "newest" because that is the
    #: sense most likely to still be how the learner thinks of the word.
    cefr_level: str = ""
    passive_level: Level = "recognise"
    active_level: Level | None = None
    passive_due: datetime | None = None
    active_due: datetime | None = None
    passive_stability: float | None = None
    active_stability: float | None = None
    lapses: int = 0
    #: Lifetime lapse counts, split by direction and derived from the review
    #: log's own state chain (``app.services.practice.lapse_counts_for``) --
    #: a different figure from ``lapses`` above, which is the combined,
    #: direction-agnostic count the FSRS bookkeeping already kept. The two
    #: always agree: ``passive_lapses + active_lapses == lapses``.
    passive_lapses: int = 0
    active_lapses: int = 0
    reps: int = 0
    suspended_until: datetime | None = None
    #: True when an active card exists (``active_state`` not null) and the
    #: learner's settings ``direction`` is currently ``passive`` -- the
    #: active card is paused rather than abandoned: its FSRS state and
    #: ``active_level`` are untouched, and it resumes unchanged the moment
    #: ``direction`` goes back to ``both``. See
    #: ``practice._gather_candidates``'s pause rule.
    active_paused: bool = False
    #: When a Browse card for this word was last shown (§C) -- the ONLY
    #: thing Browse ever writes (`POST /vocabulary/words/{id}/browsed`).
    #: Null for a word never browsed. Not practice: no bearing on FSRS, the
    #: ladder, or anything else on this row.
    browsed_at: datetime | None = None
    #: Word page only: every sense we hold for the lemma, the saved one
    #: first. Empty on the list and practice rows (one saved sense each).
    senses: list[WordSenseOut] = []


class SavedWordsOut(BaseModel):
    total: int
    words: list[SavedWordOut]


class WordHistoryEntryOut(BaseModel):
    """One row of a word's review history, newest first."""

    reviewed_at: datetime
    direction: Direction
    exercise_type: ExerciseType
    rating: Literal[1, 2, 3, 4]
    given: str
    elapsed_ms: int


class SavedWordDetailOut(BaseModel):
    """The word page: the word itself, plus its review history -- capped at
    100 rows (newest first) because a compact history is the brief's own
    word, and a card answered thousands of times does not need every one
    rendered."""

    word: SavedWordOut
    history: list[WordHistoryEntryOut]
    #: The word's pronunciation for the speaker beside it -- at the TOP
    #: level, beside ``word``, because that is where the frontend reads it.
    #: ``null`` = not ready (queued); the page then shows no speaker.
    audio: AudioOut | None = None


class WordBulkActionIn(BaseModel):
    """``suspend`` is "set aside for 30 days"; ``restore`` recomputes status
    from the card and clears both ``suspended_until`` and the leech
    lapse-count window; ``forget`` is stage 1's forget, unchanged (the logs
    survive). Always scoped to the caller's own words.

    ``word_ids`` (P4) -- a lemma is no longer unique to one saved word, so a
    batch action has to name the rows by id."""

    word_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    action: Literal["known", "suspend", "restore", "forget"]


class WordBulkActionOut(BaseModel):
    changed: int


class KnownCheckIn(BaseModel):
    """Exactly one of ``word_id`` (a saved word) / ``list_entry_id`` (a word-list
    item that has no word yet)."""

    word_id: uuid.UUID | None = None
    list_entry_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _one_of(self) -> "KnownCheckIn":
        if (self.word_id is None) == (self.list_entry_id is None):
            raise ValueError("send exactly one of word_id and list_entry_id")
        return self


class WordLeechChoiceIn(BaseModel):
    """The three choices offered on a leech word -- see
    ``app.services.practice.resolve_leech``."""

    choice: Literal["set_aside", "see_context", "keep"]


# --- Practice ----------------------------------------------------------------


class PracticeTotalsOut(BaseModel):
    """Home progress bar: see ``app.services.practice._totals`` for the
    partition these three numbers come from."""

    total: int
    learning: int
    mastered: int


class PracticeSummaryOut(BaseModel):
    """What the practice home screen shows before a session starts."""

    due_now: int
    new_available: int
    #: What today's session WILL contain if started now -- the exact
    #: numbers ``POST /practice/session`` will deliver, computed the same
    #: way, so the promise and the delivery cannot drift apart.
    planned_reviews: int
    planned_new: int
    daily_minutes: int
    seconds_spent_today: float
    avg_seconds: float
    next_due_at: datetime | None
    totals: PracticeTotalsOut
    #: How many words are currently set aside -- the home screen's own line
    #: ("N words set aside"), so a 30-day auto-return is never a surprise.
    set_aside: int


class PracticeSessionIn(BaseModel):
    """What to build a session over. Absent ``material_id`` means every
    saved word; present, it narrows the queue to words met in that one
    material -- "practise what I just read" rather than the whole list.

    ``mode`` forces every item in the queue to the ladder's own current
    level for that task -- it never skips the ladder, so ``produce`` shows
    nothing for a word still at active `recognise`. ``auto`` (the default)
    lets reviews and new words fall where the ladder already has them.
    """

    material_id: uuid.UUID | None = None
    mode: Mode = "auto"


class ExampleSourceOut(BaseModel):
    """Where a CORPUS example sentence came from. Set only when the sentence
    is not the learner's own meeting of the word -- the client says "Example
    from <title>", never "You saw this in"."""

    material_id: uuid.UUID
    material_title: str


class PracticePromptOut(BaseModel):
    """A gap exercise's prompt (`recall`). ``definition`` is the word's
    usual English meaning, shown as a cue above the sentence -- present
    (and masked) on BOTH ``kind``s now, not only the ``definition`` one
    that has no sentence at all (see ``app.services.practice
    .resolve_gap``/``_mask_definition``)."""

    kind: Literal["sentence", "definition"]
    before: str
    after: str
    #: The answer's first character. The only part of the answer sent
    #: before it is submitted -- see :class:`PracticeItemOut`, which
    #: otherwise carries nothing the learner could read the answer off of.
    cue: str
    definition: str | None = None
    #: Set when the sentence is a corpus example (see :class:`ExampleSourceOut`).
    example_source: ExampleSourceOut | None = None


class PracticeListenOut(BaseModel):
    """A `listen` turn: the word, only as sound. The spelling is on nothing
    here -- the audio's URL is a content hash, and ``fallback`` is the
    ordinary recall gap (with the answer left off, like any recall prompt),
    used for "Can't listen now". Served only when the audio is READY; until
    then the word is an ordinary recall item (see ``practice._listen_item``)."""

    kind: Literal["listen"] = "listen"
    audio: AudioOut
    fallback: PracticePromptOut


class PracticeSpeakOut(BaseModel):
    """A `speak` turn: the definition, masked exactly as recall masks it, and
    -- when its render is ready -- read aloud once. ``fallback`` is the
    ordinary recall gap, for a browser that cannot recognise speech."""

    kind: Literal["speak"] = "speak"
    definition: str
    definition_audio_url: str | None = None
    fallback: PracticePromptOut


class PracticeChoiceOptionOut(BaseModel):
    """One recognise option. ``id`` is opaque (see
    ``app.services.distractors.option_id``) -- nothing about which of the
    four is right can be read off it."""

    id: str
    text: str


class PracticeChoiceOut(BaseModel):
    """A recognise exercise's prompt, either direction -- neither shows a
    sentence. Passive is the bare English word: ``before``/``after`` are
    empty and ``target`` carries the lemma, so the client has something to
    head the four definitions with. Active shows only ``shown_meaning_uz``
    (``before``/``target``/``after`` all empty) -- the brief's active
    `recognise` is "Uzbek meaning + pos + 4 English lemmas", with nothing
    else in it."""

    kind: Literal["choice"] = "choice"
    before: str
    target: str
    after: str
    shown_meaning_uz: str | None = None
    options: list[PracticeChoiceOptionOut]


class PracticeProduceOut(BaseModel):
    """Active `produce`'s prompt: the Uzbek meaning, the part of speech,
    and a first-letter cue -- the reveal is where the teaching happens, not
    the cue, same as `recall`'s."""

    kind: Literal["produce"] = "produce"
    meaning_uz: str
    pos: str
    cue: str


class PracticeItemOut(BaseModel):
    """One card, queued for one sitting. ``prompt`` never carries the
    answer -- a definition and three distractors for `recognise`, nothing
    for `recall`/`produce` -- so nothing sent to the browser before the
    learner submits could be read out of the network tab.

    ``planned_exercise`` is what the ladder actually asked for; it differs
    from ``exercise_type`` exactly on a distractor-pipeline fallback (see
    ``app.services.distractors``), which is what makes a fallback
    measurable on the wire as well as in the log.
    """

    #: Exactly one of ``word_id`` / ``list_entry_id`` is set: a word-list item
    #: has no word until its first answer creates it.
    word_id: uuid.UUID | None
    list_entry_id: uuid.UUID | None = None
    context_id: uuid.UUID | None
    lemma: str
    pos: str
    cefr_level: str
    is_new: bool
    direction: Direction
    exercise_type: Level
    planned_exercise: Level
    prompt: Annotated[
        Union[
            PracticePromptOut,
            PracticeChoiceOut,
            PracticeProduceOut,
            PracticeListenOut,
            PracticeSpeakOut,
        ],
        Field(discriminator="kind"),
    ]


class PracticeSessionOut(BaseModel):
    items: list[PracticeItemOut]


class PracticeAnswerIn(BaseModel):
    """One answer to one item. ``context_id`` and ``planned_exercise`` are
    echoed back from whatever :class:`PracticeItemOut` carried --
    ``context_id`` may be null (the fallback prompt), and a value that
    turns out not to belong to ``word_id`` is treated as null rather than
    rejected (see ``app.services.practice.record_answer``).

    ``given`` is reused across every exercise: the option id for
    `recognise`, the typed word for `recall`/`produce`/`listen`, the matched
    speech alternative for `speak` (the server re-runs the matcher on it), and
    empty for "I don't know". ``claim_known`` is set only by the "I know
    this" flow's single follow-up answer.

    ``gave_up`` is `speak`'s "I don't know": a deliberate answer, rated
    Again, never to be confused with the recogniser failing to hear (that is
    ``speak-check``'s miss, and writes nothing to the schedule). It is
    refused on any other exercise -- nothing else has an "I don't know" that
    is not simply a wrong answer.

    ``requeued`` marks this as the SAME item's second serving within one
    session, after an earlier ``Again`` -- the client re-shows the failed
    card at the end of the session rather than whatever the ladder would
    now serve. Verified server-side against the word's own last logged
    answer for this direction (see ``record_answer``); a claim that does
    not match a recent ``Again`` at this ``exercise_type`` (or, for a
    `listen`/`speak` card, its `recall` fallback) is a 422, not a silent
    no-op.

    ``planned_exercise`` is never believed, ``"speak"`` included: a typed
    answer from a speak card (the unsupported-browser fallback) is graded and
    laddered as the ordinary `recall` answer it is.
    """

    #: Exactly one of the two. ``list_entry_id`` for the first answer to a
    #: word-list item; every later answer (requeue, leech) uses the
    #: ``word.word_id`` that answer returned.
    word_id: uuid.UUID | None = None
    list_entry_id: uuid.UUID | None = None
    context_id: uuid.UUID | None = None
    direction: Direction
    exercise_type: ExerciseType
    planned_exercise: Level | None = None
    #: What the learner actually typed or picked, kept unmodified all the
    #: way to ``VocabularyReviewLog.given`` -- see that model's docstring
    #: for why.
    given: str = Field(default="", max_length=200)
    elapsed_ms: int = Field(ge=0)
    claim_known: bool = False
    requeued: bool = False
    gave_up: bool = False

    @model_validator(mode="after")
    def _one_of(self) -> "PracticeAnswerIn":
        if (self.word_id is None) == (self.list_entry_id is None):
            raise ValueError("send exactly one of word_id and list_entry_id")
        if self.gave_up and self.exercise_type != "speak":
            raise ValueError("gave_up is only for a speak answer")
        return self


class PracticeAnswerWordOut(BaseModel):
    """The word as it stood in the context just practised -- or, with no
    context, the word on its own. Mirrors ``VocabularyEntryOut``'s meaning
    fields rather than reusing that schema outright: this is a narrower
    slice (no offsets, no ``also_at``) and a saved word's own copy rather
    than a live read of ``material_vocabulary``.

    ``sense_id`` (P4) is what the practice reveal's own "this translation is
    wrong" link reports against -- one of the exactly two places the brief
    allows that link, the word page being the other.
    """

    #: The saved word -- for a word-list item, the one this answer just
    #: created. What every later request about it names.
    word_id: uuid.UUID
    sense_id: uuid.UUID
    lemma: str
    pos: str
    cefr_level: str
    meaning_core_en: str
    meaning_core_uz: str
    meaning_en: str
    meaning_uz: str
    sense_differs: bool
    material_id: uuid.UUID | None
    material_title: str
    #: The word's pronunciation, for the reveal's speaker button and the
    #: pronunciation autoplay. ``null`` = not ready yet (queued).
    audio: AudioOut | None = None


class LeechContextOut(BaseModel):
    """The sentence "See it in context" shows, in place of the card, the
    moment ``became_leech`` fires -- the word's own newest context that has
    one. ``before``/``target``/``after`` are the same shape a passive
    `recall` gap would mark it in, built by
    ``app.services.practice.resolve_mark``, so the client only needs one
    rendering rule for "the word, marked, inside a sentence"."""

    before: str
    target: str
    after: str
    material_id: uuid.UUID
    material_title: str


class PracticeAnswerOut(BaseModel):
    verdict: Verdict
    #: 1..4 = Again/Hard/Good/Easy, an ``fsrs.Rating`` value carried as a
    #: plain int so the wire format never has to know the library exists.
    rating: Literal[1, 2, 3, 4]
    #: For `recall`, the text AS IT STOOD in the sentence (or the lemma,
    #: for the fallback). For passive `recognise`, the right English
    #: DEFINITION -- the Uzbek meaning is not repeated here, it is already
    #: on ``word.meaning_core_uz``. For `produce`, the lemma. Never sent
    #: before this response, per the brief.
    answer: str
    #: True exactly when ``rating`` is Again. The client, not the server,
    #: re-queues the word at the end of THIS session -- see the brief's
    #: decision on why no session state is kept here, and
    #: ``PracticeAnswerIn.requeued`` for the answer that comes back in.
    returns_this_session: bool
    next_due_at: datetime
    #: Set only when ``claim_known`` was sent AND the answer was correct --
    #: the word left the queue as ``known``. False for an ordinary answer,
    #: and false for a failed "I know this" check, which stays in rotation.
    known: bool
    #: True the moment this lapse pushed the word over either leech
    #: threshold -- the session then offers the three choices (§5).
    became_leech: bool
    #: The sentence "See it in context" would show, filled in exactly when
    #: ``became_leech`` is true and the word has a context with one --
    #: ``None`` otherwise, including a leech word with no sentence anywhere
    #: on its list. The client holds this to show it later; the leech
    #: endpoint itself does not repeat it.
    leech_context: LeechContextOut | None = None
    status: str
    #: The direction's level AFTER this answer -- what the NEXT encounter
    #: in this direction will be asked, once the ladder has had its say.
    level: Level
    word: PracticeAnswerWordOut


class VocabularySettingsOut(BaseModel):
    daily_minutes: int
    direction: Literal["passive", "both"]
    exercise_types: list[str] | None
    #: Whether a word's audio plays by itself as an answer is revealed (the
    #: speaker button is there either way). Default on.
    pronunciation: bool
    #: How many of the learner's active cards have actually started and
    #: are not already retired -- shown beside the direction toggle so
    #: switching it to ``passive`` is an informed choice: "N words are
    #: being practised actively -- they'll pause, not reset." See
    #: ``practice.active_in_progress_count``.
    active_in_progress: int = 0


class VocabularySettingsIn(BaseModel):
    """The whole settings screen, saved together: a plain replace, not a
    per-field patch, because that is how the screen presents it."""

    daily_minutes: Literal[5, 10, 15, 20]
    #: The brief's toggle has no "active only" -- ``passive`` is silence,
    #: ``both`` is the toggle switched on.
    direction: Literal["passive", "both"]
    #: Null means "Automatic" (the system chooses); otherwise exactly ONE of
    #: the tasks -- the settings screen's exercise type is a single choice
    #: (Automatic / Recognise / Recall / Produce / Listen / Speak), never a
    #: subset, so both an empty list and a list of more than one are refused
    #: here rather than accepted and silently narrowed to the first entry.
    #: `listen` and `speak` are manual picks like the rest: they filter the
    #: queue to words already on that rung (`speak`: at `recall` or
    #: `listen`) and never bypass the ladder.
    exercise_types: list[Level] | None = Field(default=None, min_length=1, max_length=1)
    #: Absent (or null) = unchanged: the screen's own save carries the three
    #: fields above and must not flip this one, and only the Pronunciation
    #: control sends it.
    pronunciation: bool | None = None


# --- "This translation is wrong" (P4) ---------------------------------------


class TranslationReportIn(BaseModel):
    """Filed from exactly two places -- the word page, and the practice
    reveal right after an answer -- never the lookup popover, which "is
    small and busy" (`brief-lexicon.md` §6.3). ``where`` is the wire's own
    name for `app.models.lexicon.TranslationReport.source`; ``practice``
    maps onto the stored ``practice_reveal`` (unchanged since P1, so the
    admin queue's existing reading of that column needs no migration of its
    own for this rename)."""

    sense_id: uuid.UUID
    where: Literal["word_page", "practice"]
    note: str | None = Field(default=None, max_length=500)


class TranslationReportOut(BaseModel):
    """A minimal ack -- "Thanks, we'll check it." needs nothing more. 201
    the first time; 200, same shape, on a repeat report for the same
    ``(user, sense)`` -- see ``app.services.lexicon.report_translation``."""

    id: uuid.UUID
    sense_id: uuid.UUID
    status: str


# --- Word lists --------------------------------------------------------------


class WordListOut(BaseModel):
    key: str
    title: str
    description: str
    word_count: int
    #: Entries whose sense the learner has as a saved word, by any route.
    owned: int
    active: bool
    #: A ``user_word_lists`` row exists (active or stopped).
    started: bool


class WordListSampleOut(BaseModel):
    lemma: str
    pos: str
    #: ``None`` for an unrated sense -- no chip.
    cefr: str | None
    definition_en: str
    meaning_uz: str


class WordListDetailOut(WordListOut):
    cefr: dict[str, int]
    samples: list[WordListSampleOut]
    attribution: str
    source_title: str
    licence_name: str
    licence_url: str
    #: Saved words never practised yet -- they come before this list's words.
    pending_saved: int


class WordListStartOut(BaseModel):
    active: Literal[True] = True
    pending_saved: int


class WordListStopOut(BaseModel):
    active: Literal[False] = False


# --- speak, and On the go (stage 3) ------------------------------------------


class SpeakCheckIn(BaseModel):
    """What the browser's recogniser heard: up to five alternatives for ONE
    attempt (``maxAlternatives = 5``), each capped at 200 characters -- the
    same cap ``given`` has -- so the body cannot be used to carry anything
    else. ``attempt`` is 1 to 3 on the wire and is NOT trusted: the server
    counts the learner's recent misses itself, and the reveal is the miss it
    counts as the third."""

    word_id: uuid.UUID
    alternatives: list[Annotated[str, Field(max_length=200)]] = Field(
        min_length=1, max_length=5
    )
    attempt: Literal[1, 2, 3]


class SpeakCheckOut(BaseModel):
    """``caught`` with the alternative that matched, or a miss. ``answer`` and
    ``audio`` are filled ONLY on attempt 3 with ``caught: false`` -- the
    reveal (the server's own count, not the request's ``attempt``) -- so
    before that a miss tells the client nothing about the word."""

    caught: bool
    matched: str | None = None
    answer: str | None = None
    audio: AudioOut | None = None


class OnTheGoItemOut(BaseModel):
    """One rendered file: definition, a pause, the word, a short tail.
    ``word_offset_ms`` is where the WORD starts inside it -- the moment an
    exposure counts. The word is never on the wire."""

    word_id: uuid.UUID
    url: str
    duration_ms: int
    word_offset_ms: int


class OnTheGoOut(BaseModel):
    items: list[OnTheGoItemOut]
    #: Words in rotation whose file is not rendered yet and still being made
    #: (queued or in progress). A render that has FAILED is not "preparing":
    #: it is not coming, and counting it would leave the client waiting.
    preparing: int


class OnTheGoExposureIn(BaseModel):
    word_id: uuid.UUID

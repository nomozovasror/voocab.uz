import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    SmallInteger,
    String,
    UniqueConstraint,
    true as sa_true,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as SA_UUID
from sqlmodel import Field, SQLModel

#: Where an entry came from, and therefore what a re-generation may do to it.
#:
#: ``extracted`` is the pipeline's; a later run replaces it without asking.
#: ``review_lookup`` is one a LEARNER caused, by tapping a word on the review
#: page that the pipeline never offered -- machine-made like ``extracted``,
#: and overwritable on the same terms, but kept apart because it answers a
#: question nothing else can: which words the frequency filter is wrong
#: about. ``author_edited`` is one the pipeline wrote and a person then
#: corrected; ``author_added`` is one no pipeline ever produced. Neither of
#: the last two is ever overwritten, which is the whole reason the column
#: exists.
#:
#: Nothing edits vocabulary yet -- there is no authoring screen for it. The
#: column is here from the start anyway, because the alternative is that the
#: first person to correct a wrong translation discovers that the next seed
#: run silently threw their correction away, and the fix for that is a
#: migration plus a conversation about what happened to the data.
SOURCES: tuple[str, ...] = (
    "extracted",
    "review_lookup",
    "author_edited",
    "author_added",
)

#: The ones a re-extraction may throw away, which is the whole question the
#: column answers. Named rather than tested as ``!= author_*`` so that the
#: next source added has to decide which side it is on instead of landing on
#: whichever default the test happened to give it.
MACHINE_MADE: frozenset[str] = frozenset({"extracted", "review_lookup"})

#: A saved word's place in its own study cycle. Only ``learning`` and
#: ``review`` are ever WRITTEN by stage 1 -- see ``app.services.practice`` --
#: derived straight from the FSRS state of the direction just practised.
#: ``known``, ``suspended`` and ``leech`` exist from the first migration so
#: later stages need no schema change, but nothing in this stage sets them;
#: they only ever narrow a query (a suspended word is never queued).
STATUSES: tuple[str, ...] = ("learning", "review", "known", "suspended", "leech")

#: Two directions, scored and scheduled apart -- recognising a word (en→uz)
#: and producing it (uz→en) are different skills, per the brief. Stage 1
#: exercises ``passive`` only; ``active`` exists on every row from the start
#: so the columns never need a later migration.
DIRECTIONS: tuple[str, ...] = ("passive", "active")

#: The four drills the rating table (``app.services.practice.RATING_TABLE``)
#: is shaped for. Stage 1 issues only ``recall`` -- a gap in the word's own
#: sentence -- the other three are enum members with nothing behind them yet.
EXERCISE_TYPES: tuple[str, ...] = ("recognise", "recall", "produce", "listen")

#: The ladder for each direction, floor first. A passive card climbs
#: ``recognise`` -> ``recall``; an active card climbs ``recognise`` ->
#: ``produce`` -- two different top rungs because recognising a word from
#: four options and typing it from nothing are different skills, per the
#: brief's addendum (which replaced the original brief's single shared
#: ladder for exactly this reason: a single number ("level 2") would mean
#: "recall" for one direction and "produce" for the other, which is a bug
#: waiting to happen rather than a fact about the word). ``SavedWord.
#: {direction}_level`` always holds one of these two for its direction, in
#: TEXT matching :data:`EXERCISE_TYPES` exactly, never a bare integer.
#: ``app.services.practice`` is the only place that moves a word along
#: either ladder, and does so by INDEX -- one step within the list named
#: here, not a hand-written floor/top special case -- so a ladder gaining a
#: middle rung later is a one-line change to the list, not a rewrite of the
#: function that walks it.
PASSIVE_LADDER: tuple[str, str] = ("recognise", "recall")
ACTIVE_LADDER: tuple[str, str] = ("recognise", "produce")


class MaterialVocabulary(SQLModel, table=True):
    """One word or phrase of one material, glossed in that material's sense.

    ## Why this is per-material and not a dictionary

    The obvious shape is a global ``words`` table with a ``meaning`` column,
    and every material pointing into it. It throws away the only thing here
    that is hard to get.

    ``spring`` is a season in one passage, a coil in another and a source of
    water in a third. ``bank`` is a place money is kept and the side of a
    river. ``figure`` is a number, a diagram, and a person of importance. A
    global row has to pick one, and whichever it picks is wrong for two thirds
    of the passages that use the word -- which is exactly the failure that
    makes a plain dictionary API useless to a band 5 reader: they are shown
    five senses and choose the wrong one.

    So the sense is stored where the sense is true: beside the passage it was
    read in. The duplication is real -- ``analysis`` will be glossed in forty
    materials -- and it is the cheapest part of this. Forty rows of a hundred
    bytes is four kilobytes; a global table that loses the contextual meaning
    costs the feature.

    Deduplication DOES happen, once, in the place it is meaningful: when a
    learner saves a word (see :class:`SavedWord`), where one word with several
    contexts is exactly what somebody studying it wants.

    ## Where an entry sits in the passage

    ``part_id`` + ``paragraph_index`` + ``offset_start``/``offset_end`` --
    the same coordinates the reading highlights use (see
    ``frontend/src/features/reading/highlights.ts``). Not a copy of the
    matched words and not a DOM range: offsets into a paragraph's plain text
    survive a re-render, a font-size change and a mark laid over the top, and
    they point at the RIGHT occurrence of a word that appears four times.

    ``material_id`` is carried as well as ``part_id``, which is a
    denormalisation and deliberate. Every read of this table is "the
    vocabulary of this material" -- the review page, the card's count, the
    lookup during a sitting -- and none of them care which part a word was in
    until they come to draw it.

    ## Going stale

    Nothing here is invalidated by a write; staleness is derived. An entry
    whose ``generated_at`` is older than its material's ``updated_at`` was
    glossed against text that has since been edited, and its offsets may now
    point somewhere else. That is a question the service asks when it reads
    (``app.services.vocabulary.stale``), not a flag a trigger keeps -- a
    stored flag would need every authoring path to remember to set it, and
    the one that forgot would be the one nobody noticed.
    """

    __tablename__ = "material_vocabulary"
    __table_args__ = (
        # One entry per lemma per material, which is also how a lookup finds
        # one: a learner taps a word, it is lemmatised, and exactly one row
        # answers. Two rows for one lemma would make the answer arbitrary.
        UniqueConstraint("material_id", "lemma", name="uq_vocab_material_lemma"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    material_id: uuid.UUID = Field(foreign_key="materials.id", index=True)
    part_id: uuid.UUID = Field(foreign_key="parts.id", index=True)

    #: The dictionary form: ``undertake`` for ``undertaken``. What a lookup
    #: matches on, and what a saved word is filed under.
    lemma: str = Field(max_length=80)
    #: The form that actually stands in the passage: ``undertaken``. Shown
    #: nowhere on its own -- the reader can see it -- and kept because it is
    #: what makes the offsets checkable.
    surface: str = Field(max_length=120)
    #: ``n``, ``v``, ``adj``, ``adv``, ``prep``, ``conj``, ``phr``. Empty
    #: where the model would not commit to one, which is rare and is better
    #: than a guess printed in italics beside the word.
    pos: str = Field(default="", max_length=8)
    #: What the word USUALLY means -- its commonest general sense, wherever
    #: it is met -- and the field a learner is shown first.
    #:
    #: ## Why an entry carries two meanings now
    #:
    #: For a long time it carried one, and that one was contextual, for the
    #: reason written at the top of this class: a global dictionary row has
    #: to pick a sense and picks wrong for two thirds of the passages. All
    #: of that is still true and none of it is being undone.
    #:
    #: What it missed is that a learner does not stop at this passage. A
    #: passage about artificial intelligence gave `learn` the gloss "a
    #: computer process of finding patterns in data" -- which is a correct
    #: reading of `machine learning` and a false statement about the verb
    #: `learn`. Somebody who studies that entry has learnt something that is
    #: wrong in every other sentence they will ever write with the word. A
    #: word list that only ever says *here* teaches the passage and not the
    #: language.
    #:
    #: So both are stored, and the ordinary sense LEADS: it is the one worth
    #: carrying away. The passage's sense follows it, under "Here:", and
    #: only where the two genuinely differ -- see :attr:`sense_differs`.
    #:
    #: Empty on an entry written before the field existed, and on one whose
    #: model would not answer for it. Every reader falls back to
    #: :attr:`meaning_en`, because a missing usual sense is help that is
    #: narrower than intended and a missing contextual sense is no help at
    #: all.
    meaning_core_en: str = Field(default="", max_length=200)
    #: The same usual sense in Uzbek. Filled and emptied together with
    #: :attr:`meaning_core_en` -- an English line with no Uzbek beside it is
    #: a heading promising a meaning the reader cannot read.
    meaning_core_uz: str = Field(default="", max_length=200)
    #: One line, in simpler English than the word itself, for the sense THIS
    #: passage uses.
    meaning_en: str = Field(max_length=200)
    #: The same sense in Uzbek. The reason the whole stage exists: an English
    #: gloss of a C1 word is regularly harder than the word.
    meaning_uz: str = Field(max_length=200)
    #: Whether this passage's sense is NOT the word's usual one.
    #:
    #: The switch that decides whether a reader is shown one meaning or two.
    #: Most words in most passages are used ordinarily and a second line
    #: under them would be the same sentence twice; the minority where it is
    #: false are where the passage is doing something worth pointing at.
    #:
    #: Stored rather than derived from the two strings being different,
    #: because "different wording" and "different meaning" are not the same
    #: question and only something that has read both can answer the second.
    #: It is nonetheless refused where the two strings ARE the same -- see
    #: `seed/read_vocabulary.py`, `judged` -- because a mark on every row is
    #: a mark that means nothing.
    sense_differs: bool = Field(default=False)
    #: The sentence from the passage that contains it, cut from the passage
    #: rather than written by anyone. It is what makes a saved word worth
    #: more than a word from a list: the learner met it here.
    example: str = Field(default="", max_length=600)

    paragraph_index: int = Field(default=0)
    offset_start: int = Field(default=0)
    offset_end: int = Field(default=0)
    #: Everywhere ELSE the same word stands in this material, as
    #: ``[paragraph_index, start, end]`` triples in reading order.
    #:
    #: ## Why the row keeps a list instead of there being more rows
    #:
    #: One entry per lemma per material is the constraint the whole lookup
    #: rests on: a reader taps a word, it is lemmatised, and exactly one row
    #: answers. A row per occurrence would make that answer arbitrary and
    #: would duplicate a gloss, an example and a level fourteen times over
    #: for `revolution`.
    #:
    #: But the passage has to be MARKED at every occurrence, and for a long
    #: time it was not: the entry carried one span, the review drew it, and
    #: 17% of entries -- 8 864 occurrences across the corpus -- stood in the
    #: text with nothing on them. A reader who meets `solutionism` twice and
    #: sees one of them marked does not conclude that the second is a
    #: different word. They conclude the list is incomplete.
    #:
    #: So: one row, one gloss, and the places as data on it. They cost
    #: nothing to produce -- the deterministic scan already had them -- and
    #: they are drawn more quietly than the first (see
    #: ``features/reading/layers.ts``), because the first occurrence is
    #: where the reader meets the word and the rest are where they meet it
    #: again.
    #:
    #: Empty for an entry whose gloss is about one USE rather than about the
    #: word: an unusual sense, or one the passage uses differently from the
    #: word's ordinary meaning. `address` as "deal with" says nothing about
    #: the `address` four paragraphs later, and the scan cannot tell them
    #: apart. See ``repeatable`` in ``seed/read_vocabulary.py``.
    also_at: list[list[int]] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False,
                                               server_default="[]")
    )

    #: ``B1``, ``B2`` or ``C1``, for the word in this sense -- so a common
    #: word used unusually is rated on the unusual use. THIS is the figure a
    #: learner sees, because CEFR is a scale they already have a feel for.
    cefr_level: str = Field(default="", max_length=4, index=True)
    #: ``core``, ``common``, ``wider``, ``academic`` or ``off-list``, from the
    #: frequency lists alone. Never shown to a learner -- "NGSL rank 2400" is
    #: a fact about a corpus -- and used for arithmetic instead: it is the
    #: same measurement on every material, which is what makes two passages
    #: comparable before anybody has sat either.
    #:
    #: Kept apart from ``cefr_level`` rather than averaged into one
    #: "difficulty", because the two disagreeing is itself a signal: a word
    #: that is frequent and rated C1 is being used in an unusual sense, and
    #: unusual senses are where an IELTS passage lays its traps.
    frequency_band: str = Field(default="", max_length=16)
    #: Whether this is a multi-word expression -- ``give rise to`` -- rather
    #: than a word. Its own entry with its own span, so a tap on ``rise``
    #: inside it can offer the phrase first and the word underneath.
    is_phrase: bool = Field(default=False)
    #: A COMMON word used in a sense a reader would not expect: ``bank`` as
    #: the side of a river, ``spring`` as a coil, ``address`` as "deal with".
    #:
    #: The one thing neither measure can report on its own. The frequency
    #: band says easy -- ``bank`` is NGSL rank 627 -- and the CEFR says C1,
    #: and the DISAGREEMENT between them is the finding. It is also the
    #: nastiest kind of hard word, because nothing about it looks difficult
    #: and so nothing tells the reader there is anything to check.
    #:
    #: Its own column rather than derived from ``frequency_band`` being
    #: ``core`` with a high ``cefr_level``. Today that derivation would
    #: work, because the candidate filter drops everything below NGSL rank
    #: 2000 and these are the only common words that reach the table at all
    #: -- which makes it a rule that holds by accident of one constant, and
    #: would silently stop meaning anything the day that constant moved.
    unusual: bool = Field(default=False)

    source: str = Field(default="extracted", max_length=16)
    #: Kept out of the way without being deleted. An author who judges an
    #: entry unhelpful should not have to choose between leaving it and
    #: losing the record that the pipeline produced it.
    #:
    #: Also set AUTOMATICALLY, by kind rather than by row: `lexicon.link_row`
    #: sets this whenever the row's lexeme turns out to be a proper noun
    #: (`Lexeme.is_proper_noun`) or a function word/single letter
    #: (`Lexeme.is_function_word`) -- neither is ever glossed in a material,
    #: however it was found or created, including a row a learner's own live
    #: lookup generated. The lookup itself still answers the learner; this
    #: only keeps the gloss out of the passage's own word list.
    hidden: bool = Field(default=False)
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    #: This passage's word, pointed at the GLOBAL word it is one instance of
    #: -- see `app.models.lexicon.Lexeme` for why that is a different table
    #: rather than a second meaning stuffed into this one. Nullable in the
    #: DDL because a migration cannot populate 24 000+ rows inside the same
    #: transaction that adds the column without holding a lock on this table
    #: for the length of the backfill; `backend/scripts/build_lexicon.py`
    #: fills every row in P1, immediately after, and the verification that
    #: closes that phase is exactly "is any row still null". Every FUTURE
    #: write is find-or-create (`lexicon-spec.md` §8, wired up in P3) and
    #: never leaves it null even for an instant.
    lexeme_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SA_UUID(as_uuid=True),
            ForeignKey("lexemes.id"),
            nullable=True,
            index=True,
        ),
    )
    #: This row's `meaning_core_en`/`meaning_core_uz`, pointed at the ONE
    #: `LexemeSense` they are a wording of. `meaning_core_*` itself is not
    #: removed and not stopped being read by the pages that already read it
    #: (`lexicon-spec.md`, P1 note under D2/§3 of the brief) -- only stopped
    #: being WRITTEN to, from P1 onward, once this column exists: the sense
    #: lives here now, and a row that kept writing its own copy beside it
    #: would let the two drift apart with nothing to notice.
    sense_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SA_UUID(as_uuid=True),
            ForeignKey("lexeme_senses.id"),
            nullable=True,
            index=True,
        ),
    )


class SavedWord(SQLModel, table=True):
    """A word one learner is studying, whatever passage they met it in.

    ## Deduplicated by SENSE, not by lemma (P4)

    It used to be deduplicated by lemma alone, on the theory that what
    somebody is STUDYING is one word however many passages they met it in.
    That was wrong the day a learner saved `bank` the river and `bank` the
    financial institution from two different passages and got one card that
    tried to be both: one FSRS schedule, one "usual meaning" slot, for two
    things that have nothing to do with each other except their spelling.
    `bank` (finance) and `bank` (river) are two words to learn and two FSRS
    cards, exactly as `spring` (season) met twice is still one word --
    the two cases look identical until you ask what a learner is being
    tested ON, and a sense is the honest unit for that question in a way a
    lemma never was.

    So the key is now :attr:`lexeme_sense_id`, one row per
    ``(user_id, lexeme_sense_id)`` -- `uq_saved_user_lexeme_sense` -- and
    ``lemma`` stays as a plain denormalised copy, for display and search
    only (two rows may now legitimately share it). The senses are not thrown
    away: each context arrives as a :class:`SavedWordContext`, so the word
    carries every example sentence it was met in, which is a better
    flashcard than either alone -- but every context hanging off one saved
    word must genuinely be an instance of the SAME sense; see the P4
    migration's backfill for what happens to a saved word whose contexts
    turn out to disagree about that.

    ## No longer thin

    It used to be, on the theory that scheduling was a design nobody had made
    yet and a column added early would be a guess. The vocabulary module's
    stage 1 brief settled that design, so the guess is over: everything
    below is exactly what ``app.services.practice`` reads and writes, and
    nothing else may touch it (see that module's docstring).

    ## Two FSRS cards, one row

    ``passive_*`` and ``active_*`` are two independent spaced-repetition
    cards -- recognising ``spring`` on the page and producing it from
    scratch are different skills, and a learner can hold one without the
    other. Each set mirrors ``fsrs.Card`` field for field (``state``,
    ``step``, ``stability``, ``difficulty``, ``due``, ``last_review``), which
    is what makes ``practice._load_card``/``_store_card`` a straight copy in
    either direction rather than a translation.

    ``{direction}_state`` is null for a direction never practised. This is
    NOT the same as ``fsrs.State.Learning`` (1): a fresh card in the library
    starts Learning the moment it is built, but a saved word that has never
    been drilled is not "in" any FSRS state at all -- there is no stability,
    no difficulty, nothing an interval could be computed from. Null is the
    honest value, and ``practice._load_card`` builds a brand-new
    ``fsrs.Card()`` on the fly for it rather than ever writing state 1 to a
    row nobody has reviewed.

    ``lapses`` and ``reps`` are not split by direction. They count how many
    times this WORD has been wrong and how many times it has been answered
    at all, which is one fact about the word, not two -- and the brief lists
    them once, unlike the FSRS fields above.
    """

    __tablename__ = "saved_words"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "lexeme_sense_id", name="uq_saved_user_lexeme_sense"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    #: Denormalised display/search copy of the sense's own lexeme's lemma,
    #: set once at creation (see ``vocabulary.save``) and never the key any
    #: more (P4) -- two rows may share it, e.g. `bank` (finance) and `bank`
    #: (river). Kept rather than dropped because every reader that shows a
    #: word or searches the list wants a plain string without a join, and
    #: because the migration that stopped it being unique had no reason to
    #: also make every caller join through `LexemeSense`/`Lexeme` for a
    #: field this cheap to keep in step.
    lemma: str = Field(max_length=80, index=True)
    #: THE fact that makes this row one sense rather than one spelling
    #: (P4) -- see the class docstring. Never null: every saved word points
    #: at exactly one `LexemeSense`, found (via the material row that caused
    #: the save) or, failing that, backfilled to the lexeme's rank-1 sense
    #: by the P4 migration. No ``ondelete`` -- a sense a saved word points at
    #: must be REPOINTED before it is ever deleted (`lexicon_enrich._absorb`
    #: now does this for a merge, alongside `MaterialVocabulary.sense_id`
    #: and `TranslationReport.lexeme_sense_id`), never silently nulled or
    #: cascaded away: a learner's card disappearing because two provisional
    #: senses turned out to be the same meaning is a worse failure than the
    #: delete raising loudly on an oversight.
    lexeme_sense_id: uuid.UUID = Field(foreign_key="lexeme_senses.id", index=True)

    #: ``n``, ``v``, ``adj``, ... -- copied from the newest context at save
    #: time (see ``vocabulary.save``) and by the migration's backfill for
    #: every word saved before this column existed. A word's part of speech
    #: does not depend on which passage it came from often enough to be
    #: worth tracking per context.
    pos: str = Field(default="", max_length=8)
    #: DEAD from P4 onward: no writer sets these two any more (see
    #: ``vocabulary.save``) and no reader reads them -- the word's usual
    #: meaning/Uzbek/CEFR are read LIVE from :attr:`lexeme_sense_id`'s
    #: `LexemeSense` instead, so an admin fixing a translation in Studio
    #: propagates to everybody studying the word without touching a row per
    #: learner. The columns stay rather than being dropped: dropping a
    #: column a running server might still have a stale read path for is how
    #: a migration turns into an outage, and there is no cost to a column
    #: nothing reads.
    meaning_core_en: str = Field(default="", max_length=200)
    meaning_core_uz: str = Field(default="", max_length=200)

    status: str = Field(default="learning", max_length=16, index=True)

    #: Passive card (recognising the word, en -> uz). ``_state`` holds an
    #: ``fsrs.State`` value (1 Learning, 2 Review, 3 Relearning) or null for
    #: never practised; ``_step`` is the library's learning/relearning step
    #: index, meaningless outside those two states and so left null there
    #: too.
    passive_state: int | None = Field(
        default=None, sa_column=Column(SmallInteger, nullable=True)
    )
    passive_step: int | None = Field(default=None)
    passive_stability: float | None = Field(
        default=None, sa_column=Column(Float, nullable=True)
    )
    passive_difficulty: float | None = Field(
        default=None, sa_column=Column(Float, nullable=True)
    )
    passive_due: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    passive_last_review: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    #: Active card (producing the word, uz -> en). Same shape, same rules,
    #: unused until a later stage asks for it -- present now so that stage
    #: never needs a migration of its own.
    active_state: int | None = Field(
        default=None, sa_column=Column(SmallInteger, nullable=True)
    )
    active_step: int | None = Field(default=None)
    active_stability: float | None = Field(
        default=None, sa_column=Column(Float, nullable=True)
    )
    active_difficulty: float | None = Field(
        default=None, sa_column=Column(Float, nullable=True)
    )
    active_due: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    active_last_review: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    lapses: int = Field(default=0)
    reps: int = Field(default=0)

    #: The task actually served for each direction -- see ``PASSIVE_LADDER``/
    #: ``ACTIVE_LADDER``. Stored rather than derived from the FSRS state
    #: because the ladder has its own rule (2 consecutive corrects to
    #: promote, 1 after a demotion; an Again at the top step to demote) that
    #: is deliberately NOT a schedule penalty -- FSRS keeps scheduling this
    #: card exactly as it would with no ladder at all.
    #:
    #: ``passive_level`` is never null: every saved word has a passive card
    #: from the moment it exists, floored at ``recognise``. ``active_level``
    #: is null until the active card starts (direction setting ``both`` AND
    #: passive stability >= ``MASTERED_STABILITY_DAYS`` -- see
    #: ``practice.maybe_unlock_active``), which is a different fact from
    #: state 0 the same way ``active_state`` being null is: there is no rung
    #: to be ON before the ladder exists.
    passive_level: str = Field(default="recognise", max_length=16)
    active_level: str | None = Field(default=None, max_length=16)

    #: When this word's lapse count last reset to zero -- null means "never
    #: reset, count from the beginning". Set by every leech resolution
    #: (``practice.resolve_leech``) and by the 30-day auto-return from
    #: ``suspended`` (``practice._reap_suspensions``), both of which are
    #: exactly the moments the brief calls a fresh start: a learner who has
    #: just chosen what to do about a stubborn word should not be judged
    #: leech again by lapses from before that choice.
    leech_reset_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: Set by "set aside for 30 days" (a leech choice, or the bulk ``suspend``
    #: action); null otherwise. ``status`` becomes ``suspended`` at the same
    #: time, and the two are read together: past this timestamp, the word is
    #: due back whether or not anything has touched it since, and every
    #: queue query resolves that lazily rather than a worker sweeping for it.
    suspended_until: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    #: Exposed to the client as ``added_at`` -- the name stays, because it is
    #: also the row's ordinary bookkeeping column, and nothing about renaming
    #: it in the database would be worth the migration.
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    #: When a Browse card for this word was last shown (`POST /vocabulary/
    #: words/{id}/browsed`) -- the ONLY thing Browse ever writes. Browse is
    #: explicitly not practice (§C of the brief): no `VocabularyReviewLog`
    #: row, no FSRS card touched, no `due` moved, nothing counted in daily
    #: minutes. Null for a word never browsed, which is every word before
    #: this column existed and most words after.
    browsed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    #: Which word list presented this word when the learner first answered
    #: it -- analytics only. Nothing reads it to decide anything: a word is
    #: the learner's whatever its origin, and owning it through a material
    #: or another list counts toward every list's progress alike.
    origin_list_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SA_UUID(as_uuid=True),
            ForeignKey("word_lists.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


class SavedWordContext(SQLModel, table=True):
    """One place a saved word was met, with the sense it had there.

    The gloss is COPIED rather than read through ``vocabulary_id``. A
    material can be edited and its vocabulary re-generated, and a learner's
    saved word quietly changing its meaning underneath them -- or losing it
    when a row is replaced -- is worse than a copy that has gone slightly out
    of date. What they saved is what they met.

    ``vocabulary_id`` is kept anyway, nullable, as provenance: it says which
    entry this was taken from for anybody later asking where a translation
    came from, and it is what stops one material being saved twice.

    **ON DELETE SET NULL, and that is the copy rule enforced in the
    database.** A re-extraction deletes and rewrites every machine-made
    entry, and the plain foreign key made that impossible the moment one
    learner had saved a word from the passage: the delete raised, and the
    whole import of that passage failed with it. Found by running a
    vocabulary re-import across the corpus for the first time on a database
    with saved words in it -- `cam11-t1-p1`, one row.

    Blocking the delete would have been the wrong repair even if it had
    worked, because it is the opposite of what the paragraph above decides.
    The gloss is already copied; what is lost when the source row goes is a
    POINTER, and a pointer going null is what "this came from an entry that
    no longer exists" looks like. The learner keeps their word, their
    meaning and their sentence.
    """

    __tablename__ = "saved_word_contexts"
    __table_args__ = (
        # One context per material per word. Pressing save twice on the same
        # review page is one word met once, not two.
        UniqueConstraint("saved_word_id", "material_id",
                         name="uq_saved_context_material"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    saved_word_id: uuid.UUID = Field(foreign_key="saved_words.id", index=True)
    material_id: uuid.UUID = Field(foreign_key="materials.id", index=True)
    vocabulary_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SA_UUID(as_uuid=True),
            ForeignKey("material_vocabulary.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    surface: str = Field(default="", max_length=120)
    pos: str = Field(default="", max_length=8)
    #: The word's usual sense, copied like everything else here.
    #:
    #: This one is ALSO filled in later, and it is the single exception to
    #: the copy rule above. A context saved before the field existed has an
    #: empty one, and the card for it would show only the sense one passage
    #: gave the word -- which is the failure the field was added to stop.
    #: Filling an empty one from a fresh extraction adds a meaning the
    #: learner did not have and changes none they did:
    #: ``enrich_saved_contexts`` never writes over a meaning, an example or
    #: a level. What they saved stays what they met.
    meaning_core_en: str = Field(default="", max_length=200)
    meaning_core_uz: str = Field(default="", max_length=200)
    meaning_en: str = Field(max_length=200)
    meaning_uz: str = Field(max_length=200)
    sense_differs: bool = Field(default=False)
    example: str = Field(default="", max_length=600)
    cefr_level: str = Field(default="", max_length=4)
    is_phrase: bool = Field(default=False)

    #: Where this meeting sits in the source audio, when the material is a
    #: listening one -- null for reading and for every context saved before
    #: this column existed. Stage 1 does not cut audio; the columns are here
    #: so stage 3 (listening's own exercise) needs no migration to reach
    #: back into a word saved today.
    audio_start_ms: int | None = Field(default=None)
    audio_end_ms: int | None = Field(default=None)
    #: When this meeting happened, distinct from ``created_at`` -- the row is
    #: written once, at save time, but a LATER stage means to update this
    #: column every time the same word turns up again in a passage the
    #: learner reads, as the "met again, unprompted" signal the plan calls
    #: for. Null until that stage writes it; nothing in stage 1 sets it.
    seen_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class LookupEvent(SQLModel, table=True):
    """One time a reader asked what a word meant.

    ## Why this is written from the first day

    Everything it will be asked is a question about the PAST, and a table
    added in three months answers none of them — it starts empty and the
    three months that would have been interesting are gone. It costs one row
    per lookup, of which there are at most three a sitting.

    ## What it is for

    Four questions, in the order they will be asked:

    * **What share is served from the extraction?** If it is 95%, pushing a
      five-thousand-word dictionary through the pipeline in advance buys
      nothing. If it is 60%, it buys a great deal. ``source`` is the whole
      answer, and nothing else in the database can reconstruct it after the
      fact -- a live lookup and an extracted one leave identical rows in
      ``material_vocabulary``.
    * **Which words go live?** If they turn out to be `people` and `water`,
      the learners are further from the extraction's assumptions than the
      frequency lists suggest, and the filter's cut is in the wrong place.
    * **How long does a live one take?** ``latency_ms``. A reader waiting two
      seconds mid-paper is a reader who stops using the feature.
    * **Is three the right number?** It was a judgement, not a measurement.
      If most sittings spend all three, three is too few; if most stop at
      one, it is not the budget that is limiting them.

    And later, the thing the extraction cannot know. The pipeline decides
    which words are hard from frequency, which is a statement about English.
    This is a statement about a person: these are the words that stopped
    THIS reader, in this passage, badly enough to spend one of three on.

    ## No unique constraint, on purpose

    The same reader looking the same word up twice is two events. The budget
    treats it as one charge -- see ``features/reading/lookups.ts`` -- and
    that is a rule about fairness, not a claim about what happened. Somebody
    who checked the same word three times has told us something about the
    word, and a unique key would throw it away.
    """

    __tablename__ = "lookup_events"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    material_id: uuid.UUID = Field(foreign_key="materials.id", index=True)
    #: The sitting it belonged to, filled in at SUBMIT rather than here.
    #:
    #: No attempt row exists while a paper is open -- one is created by the
    #: submit that ends it -- so the id cannot be known at the moment of the
    #: lookup. Rather than leave the column meaningless, the submit claims
    #: every unclaimed event this reader made against this material (see
    #: ``app.services.vocabulary.claim_lookups``).
    #:
    #: Null therefore means "the paper was never submitted", which is itself
    #: a fact worth being able to count: somebody who looked up three words
    #: and then abandoned the passage is a different story from somebody who
    #: finished it.
    attempt_id: uuid.UUID | None = Field(
        default=None, foreign_key="attempts.id", index=True
    )

    #: What was asked, as the reader selected it -- lower-cased and trimmed,
    #: but not lemmatised, because half the point is to see what people
    #: actually tap.
    asked: str = Field(max_length=120)
    #: The lemma that answered, where one did. Differs from ``asked``
    #: whenever the reader tapped an inflected form, and is empty where
    #: nothing could be glossed.
    lemma: str = Field(default="", max_length=80, index=True)

    #: ``cache`` -- answered from a row the extraction had already written.
    #: ``live`` -- nothing matched, so a model was asked on the spot.
    #:
    #: The single most important column here, and the one that cannot be
    #: recovered later: by the time anybody looks, the live answer has been
    #: saved and is indistinguishable from an extracted one.
    source: str = Field(default="cache", max_length=8, index=True)
    #: How long the whole answer took, in milliseconds. Near zero for a
    #: cached one; the wait the reader actually sat through for a live one.
    latency_ms: int = Field(default=0)
    #: Whether anything came back at all. False is a name, a number, a word
    #: in another language -- or a minute when the provider was down.
    found: bool = Field(default=False)

    #: ``take`` -- asked while the paper was open, out of a budget of three.
    #: ``review`` -- asked afterwards, on the review page, where there is no
    #: budget because the exam is over and this is studying.
    #:
    #: The distinction is the reason the column exists, and it is not a
    #: detail about which screen was on. A ``take`` lookup says *this word
    #: stopped me badly enough to spend one of three.* A ``review`` lookup
    #: says something the platform could not otherwise learn at all: *I did
    #: not know this word, and I did not know that I did not know it* --
    #: they read past it, answered the questions, and only found out
    #: afterwards. Words that many readers look up in REVIEW and that the
    #: extraction never offered are the candidates for fixing the filter,
    #: because the frequency lists and the learners disagree about them.
    context: str = Field(default="take", max_length=8, index=True)

    #: Where in the passage they tapped, in the coordinates the highlights
    #: use. Null where the client did not send a position.
    paragraph_index: int | None = Field(default=None)
    offset: int | None = Field(default=None)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class VocabularyReviewLog(SQLModel, table=True):
    """One answer, to one card, in one direction.

    Not FSRS's own ``ReviewLog`` -- that class is a transient return value
    from ``Scheduler.review_card``, gone the moment the caller stops holding
    it. This table is the reason stage 1 exists in this shape at all: FSRS's
    default parameters were fit on ~727 million reviews of a population that
    is not this one, and the only way to ever re-fit them on ours is to have
    kept, from the first answer, more than the final rating.

    So every column earns its place by being something that FIT would want
    and a smaller row would not have:

    * ``given`` -- the raw text the learner typed, not the verdict. A
      verdict can always be recomputed from this and the accepted answer; the
      reverse is not true. See the granularity rule in the top-level
      ``CLAUDE.md``: cheap to store now, impossible to reconstruct later.
    * ``scheduled_at`` -- the card's ``due`` BEFORE this answer, i.e. how
      overdue (or early) the review was. A refit needs to know the actual
      elapsed time the retrievability was computed against, not only the
      interval that was scheduled.
    * ``state``/``stability``/``difficulty`` -- the card's own parameters
      AFTER this answer, copied off the ``fsrs.Card`` the scheduler just
      returned. ``saved_words`` only ever holds the CURRENT card; a re-fit
      needs the whole path a card walked to get there, one row per step.

    ``saved_word_id`` is ``ON DELETE SET NULL``, matching
    ``SavedWordContext.vocabulary_id`` for the identical reason: "forget"
    (``vocabulary.forget``) removes a word from someone's list, and a
    training signal is not owed a favour to the row it came from. Deleting
    every log a forgotten word ever produced would throw away real answers
    -- real elapsed times, real ratings -- over an unrelated decision to stop
    studying one lemma. ``lemma`` is copied alongside the (nullable)
    pointer so the row still means something once it goes null.

    ``context_id`` is ``ON DELETE SET NULL`` for the same reason and is
    nullable outright: the fallback prompt (see ``app.services.practice``,
    no example sentence found or none on the word at all) answers about the
    word on its own, with no context to point at.
    """

    __tablename__ = "vocabulary_review_logs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    saved_word_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SA_UUID(as_uuid=True),
            ForeignKey("saved_words.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    lemma: str = Field(max_length=80, index=True)
    context_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SA_UUID(as_uuid=True),
            ForeignKey("saved_word_contexts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    direction: str = Field(max_length=8)
    exercise_type: str = Field(max_length=16)
    #: What the ladder asked for, as opposed to ``exercise_type`` -- what was
    #: actually served. On an ordinary ladder serving they differ exactly on
    #: a distractor-pipeline fallback (too short a definition, or too few
    #: good distractors survive the guard -- see ``app.services
    #: .distractors``), which is also what makes a fallback measurable:
    #: ``planned_exercise IS NOT NULL AND planned_exercise != exercise_type``
    #: IS the definition, not a separate flag that could drift from it (the
    #: ``IS NOT NULL`` matters -- see the next paragraph).
    #:
    #: Null on three kinds of row, all of them for the same reason: the
    #: answer is not the ladder's own evidence about a level, and a value
    #: here would forge some. Every stage-1 row predates this column and
    #: never had a plan distinct from what it served (backfilling it would
    #: have to guess, and a guessed row would be indistinguishable from a
    #: real one the day somebody re-fits FSRS on this table). A known-check
    #: ("I know this") answer is a BYPASS of the ladder, always at
    #: ``recall``, regardless of what level the word's ladder is actually
    #: at -- logging that as the ladder's OWN plan would let
    #: ``app.services.practice._has_reached_level`` believe the word had
    #: genuinely reached ``recall``. A verified same-session requeue is the
    #: SAME task the learner already failed once this session, not fresh
    #: evidence about it -- logging ``exercise_type`` here has the identical
    #: forging problem. ``_promotion_streak``/``_has_reached_level`` both
    #: skip a null-planned row entirely (neither breaking a streak nor
    #: extending one, and never counting as "reached"), and null also keeps
    #: both kinds of row out of the fallback metric above, since neither is
    #: a fallback.
    planned_exercise: str | None = Field(default=None, max_length=16)
    #: 1..4 = Again/Hard/Good/Easy, an ``fsrs.Rating`` value stored as a
    #: plain int so this table never has to import the library either.
    rating: int = Field(sa_column=Column(SmallInteger, nullable=False))
    #: What the learner actually typed, unmodified -- see the class
    #: docstring. Empty string for a skipped/blank answer, never null, so
    #: "typed nothing" and "no row" stay two different facts.
    given: str = Field(default="", max_length=200)
    elapsed_ms: int = Field(default=0)

    scheduled_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    reviewed_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )

    #: The card's own state AFTER this answer -- see the class docstring for
    #: why the log keeps its own copy rather than reading ``saved_words``.
    state: int = Field(sa_column=Column(SmallInteger, nullable=False))
    stability: float | None = Field(
        default=None, sa_column=Column(Float, nullable=True)
    )
    difficulty: float | None = Field(
        default=None, sa_column=Column(Float, nullable=True)
    )


class Deck(SQLModel, table=True):
    """A named set of words -- stage 1's whole reason for existing is that a
    LATER system needs somewhere to point.

    ``all`` and ``material`` decks are not rows in this table at all in
    stage 1: they are resolved virtually (every saved word; every saved word
    with a context in one material), because materialising them would mean
    keeping a deck's membership in step with every save and every forget for
    a grouping that is already implied by data that exists. The table and
    ``DeckWord`` exist so that a ``custom`` deck -- and, later, a teacher's
    assignment pointing at one -- has somewhere to live without a migration
    when that system is built. Nothing in stage 1 creates a ``custom`` deck
    either; the column is ready, not used.
    """

    __tablename__ = "decks"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    kind: str = Field(default="custom", max_length=16)
    material_id: uuid.UUID | None = Field(default=None, foreign_key="materials.id")
    title: str = Field(default="", max_length=200)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class DeckWord(SQLModel, table=True):
    """One word's membership in one (``custom``) deck. Composite key rather
    than a surrogate id: membership is the whole fact this row states, and
    two rows for the same pair would just be the question "is this word in
    this deck" answered twice."""

    __tablename__ = "deck_words"

    deck_id: uuid.UUID = Field(foreign_key="decks.id", primary_key=True)
    saved_word_id: uuid.UUID = Field(
        foreign_key="saved_words.id", primary_key=True
    )


class VocabularySettings(SQLModel, table=True):
    """One learner's practice preferences. ``user_id`` is the primary key
    rather than a surrogate one, because there is exactly one row per
    learner and a lookup is always "this user's settings", never "settings
    number 4".

    Stage 1 read and wrote ``daily_minutes`` only; stage 2's
    ``PUT /vocabulary/settings`` also writes ``direction`` (``passive`` or
    ``both`` -- the brief's toggle has no "active only") and
    ``exercise_types``. ``pronunciation`` sat as a column with no setter and
    no UI control until stage 3 -- kept from stage 1 rather than dropped,
    because a screen that shows three of four settings and grows a fourth
    later must not need the row's shape to change under people who already
    saved a preference. Stage 3 gives it its meaning (autoplay of the word's
    audio on reveal) and the default TRUE.
    """

    __tablename__ = "vocabulary_settings"

    user_id: uuid.UUID = Field(foreign_key="users.id", primary_key=True)
    #: 5, 10, 15 or 20 -- validated at the schema layer
    #: (``app.schemas.vocabulary``), not here; the column accepts any int so
    #: a future plan tier is not a migration.
    daily_minutes: int = Field(default=10)
    direction: str = Field(default="passive", max_length=8)
    #: Null means "the system chooses" -- the brief's explicit default, not
    #: an empty list, which would instead mean "practise nothing".
    exercise_types: list[str] | None = Field(
        default=None, sa_column=Column(ARRAY(String(length=16)), nullable=True)
    )
    #: When on, a word's audio plays by itself as its answer is revealed (the
    #: speaker button is there either way). Default TRUE since stage 3: the
    #: control did not exist before, so no existing row holds a choice -- the
    #: migration sets them all, and the server default does the same for any
    #: row written by code that never heard of the column.
    pronunciation: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=sa_true()),
    )

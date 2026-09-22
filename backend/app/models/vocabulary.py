import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, UniqueConstraint
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
    #: One line, in simpler English than the word itself, for the sense THIS
    #: passage uses.
    meaning_en: str = Field(max_length=200)
    #: The same sense in Uzbek. The reason the whole stage exists: an English
    #: gloss of a C1 word is regularly harder than the word.
    meaning_uz: str = Field(max_length=200)
    #: The sentence from the passage that contains it, cut from the passage
    #: rather than written by anyone. It is what makes a saved word worth
    #: more than a word from a list: the learner met it here.
    example: str = Field(default="", max_length=600)

    paragraph_index: int = Field(default=0)
    offset_start: int = Field(default=0)
    offset_end: int = Field(default=0)

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
    hidden: bool = Field(default=False)
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class SavedWord(SQLModel, table=True):
    """A word one learner is studying, whatever passage they met it in.

    Deduplicated by lemma, which is the opposite decision to
    :class:`MaterialVocabulary` and right for the opposite reason. There, the
    question is "what does this word mean in this passage" and the answer
    differs per passage. Here the question is "what am I learning", and a
    learner who meets ``spring`` in two materials is learning one word.

    The senses are not thrown away: each context arrives as a
    :class:`SavedWordContext`, so the word carries two meanings and two
    example sentences, which is a better flashcard than either alone.

    Thin on purpose. Scheduling -- when to show it again, how well it is
    known -- belongs to the vocabulary module and is not built; putting an
    interval column here now would be guessing at that design from the
    outside.
    """

    __tablename__ = "saved_words"
    __table_args__ = (
        UniqueConstraint("user_id", "lemma", name="uq_saved_user_lemma"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    lemma: str = Field(max_length=80, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
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
    meaning_en: str = Field(max_length=200)
    meaning_uz: str = Field(max_length=200)
    example: str = Field(default="", max_length=600)
    cefr_level: str = Field(default="", max_length=4)
    is_phrase: bool = Field(default=False)
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

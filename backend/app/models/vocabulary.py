import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel

#: Where an entry came from, and therefore what a re-generation may do to it.
#:
#: ``extracted`` is the pipeline's; a later run replaces it without asking.
#: ``author_edited`` is one the pipeline wrote and a person then corrected;
#: ``author_added`` is one no pipeline ever produced. Neither of the last two
#: is ever overwritten, which is the whole reason the column exists.
#:
#: Nothing edits vocabulary yet -- there is no authoring screen for it. The
#: column is here from the start anyway, because the alternative is that the
#: first person to correct a wrong translation discovers that the next seed
#: run silently threw their correction away, and the fix for that is a
#: migration plus a conversation about what happened to the data.
SOURCES: tuple[str, ...] = ("extracted", "author_edited", "author_added")


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
        default=None, foreign_key="material_vocabulary.id"
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

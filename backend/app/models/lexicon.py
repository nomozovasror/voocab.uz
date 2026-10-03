"""The global lexicon: one row per WORD, independent of any material.

See `brief-lexicon.md` for the product reasoning and `lexicon-spec.md`
(scratchpad) for the decisions made answering it. The short version, because
`app/services/CLAUDE.md` already carries the long one for
`MaterialVocabulary`: that table is right for "what does this word mean IN
THIS PASSAGE" and cannot answer "how many words does this platform teach" --
`appropriate` is one word to a learner and seventeen rows to that table, one
per material it was glossed in. `Lexeme`/`LexemeSense` are the other question
answered honestly: a word once, a meaning once, with every material row that
used it pointing back in.

## Why two tables and not one

A word has ONE frequency in English and MAY have several meanings, and the
two do not share a lifecycle. `Lexeme.frequency_band` is fixed the day the
word is looked up in the NGSL family and never revisited; `LexemeSense.cefr`
is graded per SENSE (`spring` the season is not `spring` the coil) and is
exactly what P2's model regrades, sense by sense, as the corpus grows. Voting
both into one row would mean a Lexeme with three senses either repeating its
frequency three times or losing the fact that CEFR is a per-sense question --
see the top-level CEFR discussion in the brief, §2-3.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, TEXT
from sqlalchemy.dialects.postgresql import UUID as SA_UUID
from sqlmodel import Field, SQLModel

#: Which of the five NGSL-family lists actually classifies a Lexeme, in the
#: priority a lemma is checked in when more than one list knows it (a word
#: can be both NGSL-core AND on the business list -- see `domain_tags` for
#: how that second fact is kept rather than thrown away). ``off-list`` is a
#: real value, not a null: a word met only in a material, in none of the
#: five lists, is exactly as classifiable as one that is -- it is classified
#: "not in any of them", which is the reading candidate filter's own
#: `frequency_band == "off-list"` carried up from `MaterialVocabulary`.
FREQUENCY_SOURCES: tuple[str, ...] = ("ngsl", "nawl", "bsl", "tsl", "moel", "off-list")

#: The same coarse scale `seed/vocabulary.py`'s reading pipeline has always
#: used (`core`/`common`/`wider` by NGSL rank tier, `academic` for NAWL,
#: `off-list` for neither) -- unchanged in meaning, because the arithmetic
#: that already reads it (`material_difficulty`, the distractor pipeline's
#: CEFR-band matching) must keep comparing the same measurement it always
#: has. BSL/TSL/MOEL do not get their own band: they are DOMAIN lists, not
#: general-frequency ones, and contribute to `domain_tags` instead -- see
#: that field for why a word can carry both a `frequency_band` from this
#: scale AND a domain tag from a specialist list at the same time.
FREQUENCY_BANDS: tuple[str, ...] = ("core", "common", "wider", "academic", "off-list")

#: A Lexeme's domain memberships, independent of `frequency_source` --
#: independent on purpose. `portfolio` is BSL (business) and may also be
#: NGSL-`common` by plain frequency; `academic` here is NAWL membership
#: restated as a domain rather than a frequency claim, because a word can be
#: both "rare in general English" (its `frequency_band`) and "the domain
#: this project would file it under" (its `domain_tags`) at once, and a
#: single-valued column cannot hold both facts. The brief's own study-set
#: use case (`business`, `academic`, `medical`, `toeic` reading lists) reads
#: this column directly rather than joining against which list a word came
#: from.
DOMAIN_TAGS: tuple[str, ...] = ("business", "academic", "medical", "toeic")

#: Where a `LexemeSense`'s definition and translation came from. Deliberately
#: two values, not three: `brief-lexicon.md` §4 (D2 in `lexicon-spec.md`)
#: chose OEWN over Wiktionary specifically so that nothing here has to carry
#: a share-alike obligation, and rather than leave a `"wiktionary"` value
#: sitting unused as an invitation, it is simply not a member of this tuple.
#: Grep this file's name for `wiktionary` and find nothing: that absence IS
#: the licensing decision, not a note about it.
SENSE_SOURCES: tuple[str, ...] = ("oewn", "model")

#: `oewn` senses carry OEWN's own licence, which is *why* OEWN rather than
#: Wiktionary supplies definitions in the first place (CC BY, no
#: share-alike -- see `seed/wordlists/README.md`). `model` senses are this
#: project's own generated text -- a provisional sense built from a
#: material's own gloss, or (P2) a gap-filling definition written in OEWN's
#: style -- and carries no third-party obligation at all, hence
#: `proprietary` rather than any Creative Commons value: there is no
#: upstream licence to preserve for text this project produced itself.
SENSE_LICENCES: tuple[str, ...] = ("cc-by-4.0", "proprietary")

#: Reasons a `LexemeSense` needs a human's eye, kept SEPARATE from the single
#: `needs_review` boolean so `translation_reports` and the Studio review tab
#: (P5) can count each failure mode on its own rather than one undifferentiated
#: pile -- see `lexicon-spec.md` D5. Only `ngsl_conflict` and `lemma_merge`
#: are ever set in P1, because they are free: the first compares two numbers
#: this project already has (a sense's CEFR against its lexeme's frequency
#: band) and the second is a fact about how the lexeme itself was built. The
#: other three describe P2's own model-judgement failures (a translation
#: judge saying `different`/`unsure`, a fresh CEFR grade disagreeing sharply
#: with the material rows that fed it) and cannot fire before a model has
#: been asked anything -- they are named here now so the column's shape does
#: not change under P2. ``pos_mismatch`` (added in P2) is the matcher saying
#: the material rows behind a sense use the headword as another part of
#: speech (`subject` v glossed "a topic") or define a different word (`ai
#: safety` glossed as plain "safety"). It flags; it never moves a row to
#: another lexeme -- that is a human's call.
REVIEW_REASONS: tuple[str, ...] = (
    "judge_different",
    "judge_unsure",
    "ngsl_conflict",
    "material_level_gap",
    "lemma_merge",
    "pos_mismatch",
)

#: Where a translation-wrong report was filed from -- the brief is explicit
#: that this is offered in exactly two places (word page, and after a
#: practice reveal) and nowhere else, e.g. not the lookup popover, which "is
#: small and busy" (`brief-lexicon.md` §6.3). Kept as a checked value rather
#: than free text so a Studio review queue can group by it without a typo
#: splitting one place into two.
REPORT_SOURCES: tuple[str, ...] = ("word_page", "practice_reveal")

#: A report's own lifecycle -- unused until P5's Studio review tab exists to
#: change it, present now so that tab needs no migration of its own.
REPORT_STATUSES: tuple[str, ...] = ("open", "resolved")


class Lexeme(SQLModel, table=True):
    """One word or phrase, independent of any material.

    Keyed by ``(lemma, pos)``, which is a decision worth stating plainly: two
    entries in different parts of speech are two different things to learn
    (`learning` the noun is not `learn` wearing a label), and a merge across
    parts of speech is never automatic -- see `backend/scripts/
    build_lexicon.py`'s own merge rule, which only ever merges within one
    `pos`, for exactly that reason.

    ``cefr`` is a DENORMALISATION of ``LexemeSense.cefr`` where
    ``sense_rank == 1`` -- see that field's docstring for why grading lives on
    the sense and not here, and this column exists purely so a catalogue
    listing or a frequency filter can sort/filter by level in SQL without a
    join into every lexeme's sense list. It is recomputed, never hand-set,
    and is null until the lexeme has at least one sense -- true of every
    list-only lexeme until P2 gives it one.
    """

    __tablename__ = "lexemes"
    __table_args__ = (
        UniqueConstraint("lemma", "pos", name="uq_lexeme_lemma_pos"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    lemma: str = Field(max_length=80, index=True)
    #: ``n``, ``v``, ``adj``, ``adv``, ``prep``, ``conj``, ``phr`` -- the same
    #: vocabulary `MaterialVocabulary.pos` already uses, so a row copied
    #: across needs no translation table. Empty where no material and no list
    #: committed to one -- see the part-of-speech guess for list-only
    #: lexemes in `build_lexicon.py`.
    pos: str = Field(default="", max_length=8)
    is_phrase: bool = Field(default=False)
    #: A name (`alan`, `google`), not vocabulary. The lexicon does not take
    #: names in (the seed filter, the extraction prompt and the OEWN loader
    #: all drop them); this marks the few kept only because a learner already
    #: met one in a material or saved it. A proper noun has no CEFR (its
    #: senses' ``cefr`` is NULL -- a real state, not "not graded yet") and is
    #: left out of practice: the session queues, the summary counts and the
    #: distractor pool (`app.services.practice`, `app.services.distractors`).
    #: Set by `app.services.lexicon.link_row` for a new lexeme too.
    is_proper_noun: bool = Field(default=False, index=True)
    #: A grammatical function word (article, pronoun, preposition,
    #: conjunction, auxiliary/modal, "not") or a single-letter token (`a`,
    #: `i`) -- not vocabulary, the same judgement `is_proper_noun` makes
    #: about a name, for a different reason. See
    #: `app.services.lexicon.FUNCTION_WORDS`/`is_excluded_word` for the exact
    #: set and why. Kept, not deleted, only where a material row or a saved
    #: word already references it (`scripts/lexicon_cleanup.py
    #: function-words`, the one-off data step that found and marked the
    #: existing ones); excluded from practice and the distractor pool the
    #: same way a proper noun is (`app.services.practice._practisable_clause`,
    #: `app.services.distractors._candidates`). `app.services.lexicon
    #: .link_row`'s two writers refuse to create a NEW row for one at all, so
    #: nothing sets this going forward except that same cleanup script,
    #: re-run against whatever a future frequency-list update adds.
    is_function_word: bool = Field(default=False, index=True)

    #: Denormalised from the rank-1 sense -- see the class docstring.
    #: NULL for a proper noun, and until the lexeme has a sense.
    cefr: str | None = Field(default=None, max_length=4, index=True)
    frequency_band: str | None = Field(default=None, max_length=16, index=True)
    frequency_source: str | None = Field(default=None, max_length=8)
    domain_tags: list[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(TEXT), nullable=False, server_default="{}"),
    )
    #: When P2's enrichment (`app.services.lexicon_enrich`) last finished
    #: this lexeme -- matched its material senses to OEWN, added OEWN's top
    #: senses, graded and translated. Null means "not enriched yet", and is
    #: the whole of P2's resume state: a lexeme is enriched in ONE
    #: transaction that sets this column last, so a crash leaves either the
    #: finished lexeme or the untouched one, never half of it, and the next
    #: run simply picks up every lexeme still null here.
    enriched_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        ),
    )


class LexemeSense(SQLModel, table=True):
    """One meaning of one `Lexeme`.

    ``sense_rank`` orders a lexeme's own senses, commonest first -- 1 is
    always the sense `Lexeme.cefr` is copied from. For a P1 PROVISIONAL sense
    (see ``provisional`` below) rank is assigned by how many
    `MaterialVocabulary` rows actually used that wording: the meaning most of
    the corpus agrees on for this word is, absent anything better, the most
    likely candidate for "the commonest sense" until P2 can check it against
    OEWN's own frequency-ordered inventory.

    ``cefr`` lives HERE rather than on `Lexeme` because level is a fact about
    a MEANING: `bank` the riverbank and `bank` the financial institution are
    not the same difficulty, and averaging them would describe neither. A P1
    provisional sense's `cefr` is the MAJORITY level among the
    `MaterialVocabulary` rows grouped into it -- not a fresh grading, which is
    P2's job (`lexicon-spec.md` D3): P1 makes no model call, so what it
    reports here is simply what the corpus already said about those rows,
    aggregated.

    ``provisional`` marks a sense built by clustering material wordings
    rather than matched to a real OEWN synset. P2's job is to either match a
    provisional sense onto an OEWN synset (filling `oewn_synset_id`,
    `source_id` becomes ``"oewn"``, `provisional` clears) or leave it as a
    standalone `model` sense where OEWN has nothing that fits -- see
    `lexicon-spec.md` P2. The flag exists as a real column (not inferred from
    `oewn_synset_id is null`, which conflates it with a `model`-source gap
    definition that was never provisional in the first place) because the
    two are different facts: a `model` sense from P2's gap-filling is
    DELIBERATELY final, an OEWN-shaped definition for a lemma OEWN does not
    have; a `provisional` sense is unfinished by construction and expected to
    be revisited.
    """

    __tablename__ = "lexeme_senses"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    lexeme_id: uuid.UUID = Field(foreign_key="lexemes.id", index=True)
    sense_rank: int = Field(default=1)

    definition_en: str = Field(default="", max_length=400)
    meaning_uz: str = Field(default="", max_length=400)
    #: The OTHER model's translation, where this sense was translated by two
    #: (P2: OEWN senses and gap definitions -- anything that did not come
    #: with a material's own Uzbek). Kept for the reviewer, not the learner:
    #: when the judge says `different` or `unsure` the Studio review tab has
    #: to show both candidates, or the reviewer is re-translating from
    #: scratch. Empty for a sense whose Uzbek was copied from a material.
    meaning_uz_alt: str = Field(default="", max_length=400)
    #: The material's own Uzbek this sense's meaning was COPIED from,
    #: verbatim; empty for a translated sense. Where it differs from
    #: `meaning_uz`, P2 rewrote a sentence-style gloss ("Bahor fasli.") into
    #: dictionary style ("bahor") -- this column is the audit trail for that
    #: rewrite, and how a re-run recognises a copy it already normalised. Its
    #: own column rather than `meaning_uz_alt`, which means "the other
    #: translator's candidate" and would then mean two things.
    meaning_uz_material: str = Field(default="", max_length=400)
    #: The pair (`meaning_uz`, `meaning_uz_alt`) a re-translation trial
    #: replaced, kept until the trial is decided -- see
    #: `scripts/retranslate_different.py`. Empty: no trial on this sense.
    meaning_uz_prev: str = Field(default="", max_length=400)
    meaning_uz_alt_prev: str = Field(default="", max_length=400)
    #: Null until something has graded this sense -- see the class docstring.
    #: Distinct from `""`: a P1 provisional sense built from rows that ALL
    #: have an empty `cefr_level` (never graded by the extraction pipeline)
    #: gets null here too, and both cases mean the same thing, "nobody has
    #: rated this yet", which `needs_review`'s NGSL-conflict check must be
    #: able to tell apart from an actual rating. Null is also FINAL for a
    #: proper noun's sense (`Lexeme.is_proper_noun`): a name has no level,
    #: and the UI shows no chip at all for a null level.
    cefr: str | None = Field(default=None, max_length=4, index=True)

    oewn_synset_id: str | None = Field(default=None, max_length=32, index=True)
    #: This sense's Princeton WordNet 3.1 SemCor tag-count rank among its
    #: lemma's synsets (1 = commonest) -- what `sense_rank` for an `oewn`
    #: sense is actually ORDERED BY (`lexicon_enrich`'s `oewn_rank` field on
    #: its in-memory `Sense`, persisted here since P2 originally only kept it
    #: for the length of one enrichment run). Null for a `model` sense: there
    #: is no Princeton rank for a definition OEWN never had. This is the data
    #: `app.services.lexicon_licences.sources` reads to decide whether
    #: Princeton WordNet 3.1's SemCor counts belong on the licences page --
    #: see that module for why the page is generated from a fact about the
    #: data rather than a permanent hand-written row.
    oewn_rank: int | None = Field(default=None)
    #: The SemCor tag COUNT behind `oewn_rank` (Princeton WordNet 3.1; 0 =
    #: the synset exists and SemCor never tagged it; NULL = no OEWN data at
    #: all, i.e. a `model` sense or one written before this column -- see
    #: `scripts/backfill_oewn_count.py`). Persisted because the lookup's
    #: `most common` / `common` / `less common` labels compare COUNTS (a
    #: sense is `common` when it has at least a quarter of the word's top
    #: count); a rank cannot say whether rank 2 is 20 against 25 or 1
    #: against 25. Never shown as a number.
    oewn_count: int | None = Field(default=None)
    source_id: str = Field(default="model", max_length=16)
    licence: str = Field(default="proprietary", max_length=16)

    needs_review: bool = Field(default=False, index=True)
    review_reasons: list[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(TEXT), nullable=False, server_default="{}"),
    )
    provisional: bool = Field(default=True, index=True)

    #: Whether the recall prompt's first-letter cue is worth showing --
    #: computed, never hand-set (`app.services.lexicon_hints`). True when
    #: ANOTHER lexeme's sense shares this one's `oewn_synset_id`, or carries
    #: a (near-)identical `definition_en` after normalisation -- the two
    #: cases a bare "starts with s" genuinely narrows down a guess between
    #: (`shortage`/`scarcity`) rather than wasting a hint on a word nothing
    #: else could be confused with. Computed ONCE by a full backfill
    #: (`scripts/backfill_letter_hint.py`) for every sense, and again for a
    #: single lexeme's senses whenever the worker's enrichment loop rewrites
    #: them (`app.worker._lexicon_enrich_once`) -- both call the same
    #: `app.services.lexicon_hints.recompute_*` functions, so a lexeme this
    #: has never run against is simply `false`, never a guess.
    needs_letter_hint: bool = Field(default=False, index=True)

    #: Who last cleared this sense in Studio's admin review tab (P5), and
    #: when -- null means "never approved", which is a different fact from
    #: `needs_review is False`: a P1 provisional sense with no reasons at all
    #: has never been reviewed by anybody, and the review queue's "core"
    #: bucket (`app.services.lexicon_review`) is exactly the top-frequency
    #: senses this is still null for. `ON DELETE SET NULL` -- losing the
    #: reviewer's account is not a reason to lose the fact that a human
    #: looked at this sense, the same tolerance `TranslationReport
    #: .material_vocabulary_id` already uses.
    approved_by: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SA_UUID(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    approved_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        ),
    )


class TranslationReport(SQLModel, table=True):
    """"This translation is wrong" -- filed from exactly two places, per the
    brief (§6.3): the word page, and a practice screen right after the
    answer is revealed, because those are the only two moments a learner is
    actually shown a translation.

    Schema only in P1 -- nothing wrote to this table yet, and nothing read
    it before P4/P5. It was created early, alongside the rest of the
    lexicon's schema, so that wiring up the reporting link (P4,
    ``app.services.lexicon.report_translation``,
    ``POST /vocabulary/translation-reports``) and the review queue reading it
    (P5, ``app.services.lexicon_review`` -- the "Reported" bucket, sorted
    first) are a code change against an existing table rather than a
    migration bundled with unrelated product work. One open report per
    ``(user_id, lexeme_sense_id)`` -- a partial unique index, `status =
    'open'` only, added in the P4 migration -- makes a repeat report from
    the same learner about the same sense a no-op rather than a second row;
    approving or fixing the sense in Studio closes every open report against
    it in the same transaction.

    ``material_vocabulary_id`` is nullable and ``ON DELETE SET NULL``: a
    report from the word page has no material in view at all, and one filed
    from a practice reveal points at the row whose context prompted it,
    which can be re-extracted out from under the report the same way
    `SavedWordContext.vocabulary_id` already tolerates -- the report is about
    the SENSE (`lexeme_sense_id`, never nulled by this table), and losing the
    pointer to which practice encounter triggered it is a detail worth
    keeping if it survives, not a reason to lose the report if it doesn't.
    """

    __tablename__ = "translation_reports"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    lexeme_sense_id: uuid.UUID = Field(foreign_key="lexeme_senses.id", index=True)
    material_vocabulary_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SA_UUID(as_uuid=True),
            ForeignKey("material_vocabulary.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    source: str = Field(default="word_page", max_length=16)
    note: str = Field(default="", max_length=500)
    status: str = Field(default="open", max_length=16, index=True)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    resolved_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

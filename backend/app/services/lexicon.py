"""P3: find-or-create -- the lexicon's other entry point besides
`scripts/build_lexicon.py`'s one-time backfill.

`brief-lexicon.md` §8 (D6 in the lexicon spec) is unconditional: every
`material_vocabulary` row, from the day this module exists, gets its
`lexeme_id` and `sense_id` at the moment it is written -- never later, never
approximately, and never behind a model call in the caller's request. The
two writers are `app.services.vocabulary.replace_extracted` (the seed
import path) and `app.services.vocabulary._generate` (a live lookup
answering a word the seed extraction missed); both call :func:`link_row` on
every row they create, right before it is committed.

## Find

A brand-new lemma is not assumed to be a brand-new WORD. `descending` and
`descent` reached one material as two rows because the reading pipeline's
own model, asked separately, answered `descend` for both -- see
`scripts/build_lexicon.py`'s own docstring, which measured 315 such
collisions across the whole corpus and wrote the narrow, per-part-of-speech
inflectional rule that catches them. That rule -- :func:`merge_candidate`,
:func:`build_merge_map`, :func:`normalise_meaning`, :func:`lexeme_is_phrase`
-- now LIVES here rather than in that script, which imports it from here
instead: P3 needs the identical rule applied one row at a time, and a rule
copied into two files is a rule that quietly drifts the first time either
one is fixed.

:func:`link_row` checks the rule against every OTHER lexeme of the same part
of speech ALREADY IN THE DATABASE, not the batch-wide graph P1's one-off run
builds over the whole corpus at once -- a live request sees one row, not
25,000. What that gives up: two brand-new lemmas arriving in the same
request that are inflected forms of EACH OTHER (neither exists yet, so
neither can be found as the other's match) are not merged until a later
`scripts/build_lexicon.py --wipe-enriched` pass notices -- gracefully
degrading. This codebase's actual write pattern is one `material_vocabulary`
row at a time, so the gap is theoretical; it is written down because the
one-off script's own docstring records the same class of gap for the same
reason.

## Create

A brand-new sense is PROVISIONAL (`LexemeSense.provisional`), built from the
row's own wording -- `meaning_core_en`/`_uz` falling back to the contextual
`meaning_en`/`_uz`, the same fallback P1's clustering and every other reader
of `MaterialVocabulary` already uses -- with `source_id="model"`, `cefr`
copied from the row's own `cefr_level`, and the same free NGSL-conflict
check P1 runs at cluster time. It is never left ungraded forever: creating
one clears the lexeme's `enriched_at`, so `app.worker`'s lexicon loop
(`app.services.lexicon_enrich`) picks it up on its next pass exactly as it
would a P1 provisional sense -- including a sense added to a lexeme P2 had
already finished, which is what makes this safe to call on an old, settled
word as well as a brand-new one.

**Unless one already says the same thing.** Two rows glossing the same
lexeme with the same wording -- the ordinary case for a common word met in
two materials -- must not each buy their own provisional sense: P1's own
clustering would merge them on its next rebuild, and creating two senses now
only to merge them later is work this function can skip for free by
checking first. "The same thing" is :func:`normalise_meaning` applied to the
row's usual English gloss, matched against every EXISTING sense of the
target lexeme under the same normalisation -- exactly P1's own grouping key,
reused rather than reinvented, because two callers deciding "is this the
same wording" two different ways is how they end up disagreeing.

## Where the frequency lists and OEWN extract live now

:data:`WORDLISTS` points inside `backend/`, not `seed/wordlists/`, because
only `backend/` is bind-mounted into the Docker `backend`/`worker`
containers (`docker-compose.yml`) and copied into the built image
(`backend/Dockerfile`'s `COPY . .`) -- a worker enriching a lexeme at 2am
needs the same OEWN extract this module needs to grade one at request time,
and neither can reach outside the image to get it. `seed/wordlists/README.md`
documents both copies and how they are kept in sync.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.core.database import AsyncSession
from app.models.lexicon import Lexeme, LexemeSense, TranslationReport
from app.models.vocabulary import MaterialVocabulary

#: `backend/app/data/wordlists` -- see the module docstring's last section.
WORDLISTS = Path(__file__).resolve().parents[1] / "data" / "wordlists"


def _rows(name: str, encoding: str = "utf-8-sig") -> list[list[str]]:
    """One vendored CSV, comment lines and blank lines dropped."""
    path = WORDLISTS / name
    text = path.read_bytes().decode(encoding, "replace")
    return [
        [cell.strip() for cell in line.split(",")]
        for line in text.splitlines()
        if line.strip() and not line.startswith("##")
    ]


class FrequencyLists:
    """The five NGSL-family lists plus the supplementary one, read once.

    ``frequency_band`` keeps the exact meaning `seed/vocabulary.py`'s
    reading pipeline has always given it -- core/common/wider by NGSL rank
    tier, academic for NAWL, off-list otherwise -- because the arithmetic
    that already reads that scale (`material_difficulty`, the distractor
    pipeline's CEFR-band matching) must keep comparing what it always has.
    BSL/TSL/MOEL do not extend that scale; they are domain lists and only
    ever contribute to ``domain_tags``.
    """

    def __init__(self) -> None:
        self.ngsl_rank: dict[str, int] = {}
        self.nawl: set[str] = set()
        self.supplementary: set[str] = set()
        self.bsl: set[str] = set()
        self.tsl: set[str] = set()
        self.moel: set[str] = set()

        for row in _rows("NGSL_12_stats.csv"):
            if row[0] == "Lemma":
                continue
            self.ngsl_rank[row[0].lower()] = int(row[1])
        for row in _rows("NAWL_12_lemmatized_for_research.csv", "latin-1"):
            self.nawl.add(row[0].lower())
        for row in _rows("SUP_lemmatized.csv"):
            self.supplementary.add(row[0].lower())
        for row in _rows("BSL_120_lemmatized_for_research.csv"):
            self.bsl.add(row[0].lower())
        for row in _rows("TSL_12_lemmatized_for_research.csv", "latin-1"):
            self.tsl.add(row[0].lower())
        for line in (WORDLISTS / "MOEL_terms.csv").read_text(encoding="utf-8").splitlines():
            term = line.strip().lower()
            if term:
                self.moel.add(term)

    def band(self, lemma: str) -> str:
        if lemma in self.supplementary:
            return "core"
        rank = self.ngsl_rank.get(lemma)
        if rank is not None:
            return "core" if rank <= 1000 else "common" if rank <= 2000 else "wider"
        return "academic" if lemma in self.nawl else "off-list"

    def source(self, lemma: str) -> str | None:
        """The single list credited for this lemma's classification, in
        priority order -- see `app.models.lexicon.FREQUENCY_SOURCES`."""
        if lemma in self.ngsl_rank or lemma in self.supplementary:
            return "ngsl"
        if lemma in self.nawl:
            return "nawl"
        if lemma in self.bsl:
            return "bsl"
        if lemma in self.tsl:
            return "tsl"
        if lemma in self.moel:
            return "moel"
        return "off-list"

    def domain_tags(self, lemma: str) -> list[str]:
        tags = []
        if lemma in self.nawl:
            tags.append("academic")
        if lemma in self.bsl:
            tags.append("business")
        if lemma in self.tsl:
            tags.append("toeic")
        if lemma in self.moel:
            tags.append("medical")
        return tags

    def all_lemmas(self) -> set[str]:
        return (self.ngsl_rank.keys() | self.nawl | self.supplementary
                | self.bsl | self.tsl | self.moel)


_frequency_lists_cache: FrequencyLists | None = None


def frequency_lists() -> FrequencyLists:
    """A process-wide cached read of the frequency lists.

    Six small flat files that never change except when somebody re-vendors
    them, so re-reading them on every request -- :func:`link_row` runs in
    the request path for a live lookup -- would be pure waste. The worker
    and `scripts/build_lexicon.py` each get their own copy in their own
    process, which is the only "sharing" that would ever matter here.
    """
    global _frequency_lists_cache
    if _frequency_lists_cache is None:
        _frequency_lists_cache = FrequencyLists()
    return _frequency_lists_cache


# --- The merge rule -----------------------------------------------------------
#
# Moved here from `scripts/build_lexicon.py`, which explains it at length in
# its own module docstring ("The merge rule, and why it is not
# `seed.vocabulary.stripped()`") -- read that for the reasoning; what
# follows is the rule itself, unchanged, so P1's one-off batch run and P3's
# one-row-at-a-time :func:`link_row` apply the identical inflectional test.

#: Purely inflectional endings for verbs -- tense/aspect, never a
#: derivational change of meaning.
_VERB_SUFFIXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ying", ("ie",)),
    ("ies", ("y",)),
    ("ied", ("y",)),
    ("ing", ("", "e")),
    ("ed", ("", "e")),
    ("es", ("", "e")),
    ("s", ("",)),
)
#: Comparative/superlative -- always the same underlying adjective in
#: English, unlike a noun's `-er` (agent noun: `printer` != `print`).
_ADJ_SUFFIXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("iest", ("y",)),
    ("ier", ("y",)),
    ("est", ("", "e")),
    ("er", ("", "e")),
)
_SIBILANT_PLURAL = re.compile(r"^(.{2,}(?:ch|sh|[oxz]))es$")
_DOUBLED_CONSONANT = re.compile(r"^(.*[bcdfghjklmnpqrstvwxz])\1(ed|ing)$")


def merge_candidate(lemma: str, pos: str, known: set[str]) -> str | None:
    """The other lemma, of the SAME `pos`, that ``lemma`` is an inflected
    form of -- or ``None``. See the module comment above for the rule's
    reasoning."""
    if pos == "v":
        for ending, replacements in _VERB_SUFFIXES:
            if lemma.endswith(ending) and len(lemma) - len(ending) >= 2:
                stem = lemma[: -len(ending)]
                for replacement in replacements:
                    candidate = stem + replacement
                    if candidate != lemma and candidate in known:
                        return candidate
        doubled = _DOUBLED_CONSONANT.match(lemma)
        if doubled:
            base = lemma[: len(doubled.group(0)) - len(doubled.group(2)) - 1]
            for candidate in (base, base + "e"):
                if candidate in known:
                    return candidate
    elif pos == "adj":
        for ending, replacements in _ADJ_SUFFIXES:
            if lemma.endswith(ending) and len(lemma) - len(ending) >= 2:
                stem = lemma[: -len(ending)]
                for replacement in replacements:
                    candidate = stem + replacement
                    if candidate != lemma and candidate in known:
                        return candidate
    elif pos == "n":
        sibilant = _SIBILANT_PLURAL.match(lemma)
        if sibilant and sibilant.group(1) in known:
            return sibilant.group(1)
        if lemma.endswith("ies") and len(lemma) > 4:
            candidate = lemma[:-3] + "y"
            if candidate in known:
                return candidate
        if lemma.endswith("s") and not lemma.endswith("ss") and len(lemma) > 3:
            candidate = lemma[:-1]
            if candidate in known:
                return candidate
    return None


def build_merge_map(word_pairs: set[tuple[str, str]]) -> dict[tuple[str, str], tuple[str, str]]:
    """Every (lemma, pos) in ``word_pairs`` mapped to its canonical form --
    P1's own batch use of :func:`merge_candidate`, over the whole corpus at
    once. See `scripts/build_lexicon.py` for the caller.

    A pair not involved in any merge maps to itself, so every raw pair this
    project has ever produced always has an entry -- callers never need a
    ``.get(pair, pair)`` fallback scattered through them.
    """
    by_pos: dict[str, set[str]] = {}
    for lemma, pos in word_pairs:
        by_pos.setdefault(pos, set()).add(lemma)

    one_hop: dict[tuple[str, str], tuple[str, str]] = {}
    for lemma, pos in word_pairs:
        target = merge_candidate(lemma, pos, by_pos[pos])
        if target is not None:
            one_hop[(lemma, pos)] = (target, pos)

    def resolve(pair: tuple[str, str]) -> tuple[str, str]:
        seen = {pair}
        while pair in one_hop:
            pair = one_hop[pair]
            if pair in seen:  # a cycle would mean two lemmas reduce to each
                break         # other; never observed, guarded rather than assumed
            seen.add(pair)
        return pair

    return {pair: resolve(pair) for pair in word_pairs}


# --- Provisional-sense grouping -------------------------------------------
#
# Also moved from `scripts/build_lexicon.py`: the string-normalisation P1
# clusters material rows by, reused here so :func:`link_row`'s "is this
# sense already here" check groups a row the same way a later P1 rebuild
# would.

_PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
_WS_RE = re.compile(r"\s+")


def normalise_meaning(text: str) -> str:
    """A meaning string reduced to bare words, for GROUPING only -- never
    shown to anybody. See `scripts/build_lexicon.py`'s own docstring
    (`_normalise_meaning`, this function's former name and home) for why
    this is pure string matching and not the semantic merge P2 exists to
    do."""
    lowered = text.lower().strip()
    despunct = _PUNCT_RE.sub(" ", lowered)
    return _WS_RE.sub(" ", despunct).strip()


def lexeme_is_phrase(lemma: str, pos: str) -> bool:
    """A lexeme counts as a phrase if its lemma is plainly multi-word, OR
    its part of speech was tagged `phr` -- see `scripts/build_lexicon.py`'s
    own docstring (`_lexeme_is_phrase`) for why an OR of both signals is
    used rather than trusting either alone."""
    return (" " in lemma) or (pos == "phr")


# --- Find-or-create -------------------------------------------------------


async def link_row(session: AsyncSession, row: MaterialVocabulary) -> None:
    """Give ``row`` its ``lexeme_id`` and ``sense_id``, finding or creating
    both -- synchronously, with no model call, so a row this call touches is
    never left unlinked even for an instant (`lexicon-spec.md` D6).

    Sets the two columns on ``row`` directly and leaves adding/flushing/
    committing ``row`` itself to the caller (`app.services.vocabulary`'s two
    writers): this function only flushes what IT creates, because a fresh
    `Lexeme`/`LexemeSense` needs a real id for ``row`` to point at before
    the caller's own insert.
    """
    lemma = (row.lemma or "").strip().lower()
    if not lemma:
        return
    pos = row.pos or ""
    is_phrase = row.is_phrase or lexeme_is_phrase(lemma, pos)

    lexeme = await _find_or_create_lexeme(session, lemma, pos, is_phrase)
    row.lexeme_id = lexeme.id

    sense = await _find_or_create_sense(session, lexeme, row)
    row.sense_id = sense.id


async def _find_or_create_lexeme(
    session: AsyncSession, lemma: str, pos: str, is_phrase: bool
) -> Lexeme:
    found = (
        await session.exec(select(Lexeme).where(Lexeme.lemma == lemma, Lexeme.pos == pos))
    ).first()
    if found is not None:
        return found

    if not is_phrase and pos:
        known = set(
            (await session.exec(select(Lexeme.lemma).where(Lexeme.pos == pos))).all()
        )
        target_lemma = merge_candidate(lemma, pos, known)
        if target_lemma is not None:
            target = (
                await session.exec(
                    select(Lexeme).where(Lexeme.lemma == target_lemma, Lexeme.pos == pos)
                )
            ).first()
            if target is not None:
                return target

    lists = frequency_lists()
    lexeme = Lexeme(
        lemma=lemma, pos=pos, is_phrase=is_phrase,
        frequency_band=lists.band(lemma), frequency_source=lists.source(lemma),
        domain_tags=lists.domain_tags(lemma),
    )
    session.add(lexeme)
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError:
        # Another request created the same (lemma, pos) between the SELECT
        # above and this INSERT -- the identical race
        # `app.services.vocabulary._generate` already guards against for
        # `material_vocabulary` itself. Its row won; find it rather than
        # failing this request over a race a learner never caused. The
        # savepoint (`begin_nested`) means only THIS insert is rolled back,
        # not whatever else the caller's transaction is in the middle of.
        found = (
            await session.exec(select(Lexeme).where(Lexeme.lemma == lemma, Lexeme.pos == pos))
        ).first()
        assert found is not None
        return found
    return lexeme


async def _find_or_create_sense(
    session: AsyncSession, lexeme: Lexeme, row: MaterialVocabulary
) -> LexemeSense:
    usual_en = row.meaning_core_en or row.meaning_en
    usual_uz = row.meaning_core_uz or row.meaning_uz
    normalised = normalise_meaning(usual_en)

    existing = (
        await session.exec(select(LexemeSense).where(LexemeSense.lexeme_id == lexeme.id))
    ).all()
    if normalised:
        for sense in existing:
            if normalise_meaning(sense.definition_en) == normalised:
                return sense

    cefr = row.cefr_level or None
    reasons: list[str] = []
    if cefr in ("C1", "C2") and lexeme.frequency_band == "core":
        reasons.append("ngsl_conflict")
    if cefr in ("A1", "A2") and lexeme.frequency_band == "off-list":
        reasons.append("ngsl_conflict")

    sense = LexemeSense(
        lexeme_id=lexeme.id,
        sense_rank=len(existing) + 1,
        definition_en=usual_en[:400],
        meaning_uz=usual_uz[:400],
        cefr=cefr,
        source_id="model",
        licence="proprietary",
        provisional=True,
        needs_review=bool(reasons),
        review_reasons=reasons,
    )
    session.add(sense)
    await session.flush()

    if not existing:
        lexeme.cefr = cefr
    # A new provisional sense means there is fresh, ungraded material for
    # `app.worker`'s lexicon loop to look at -- including on a lexeme P2 had
    # already finished, whose `enriched_at` would otherwise hide this sense
    # from every future pass.
    lexeme.enriched_at = None
    session.add(lexeme)
    return sense


# --- "This translation is wrong" -------------------------------------------


async def report_translation(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    sense_id: uuid.UUID,
    source: str,
    note: str,
    material_vocabulary_id: uuid.UUID | None = None,
) -> tuple[TranslationReport, bool]:
    """File "this translation is wrong" against one sense. Returns the
    report and whether this call created it.

    One open report per ``(user_id, sense_id)`` -- a repeat is a no-op that
    hands back the report already open, not a second row -- because a
    learner pressing the link twice on the same word has said the same
    thing twice, not filed two complaints. Enforced by a partial unique
    index (`status = 'open'` only, the P4 migration) rather than only here,
    which is what makes it safe against two requests racing: this function
    checks first for the ordinary case, then falls back to a re-read on the
    index's own `IntegrityError` for the race, rather than trusting the
    check alone.
    """
    existing = (
        await session.exec(
            select(TranslationReport).where(
                TranslationReport.user_id == user_id,
                TranslationReport.lexeme_sense_id == sense_id,
                TranslationReport.status == "open",
            )
        )
    ).first()
    if existing is not None:
        return existing, False

    report = TranslationReport(
        user_id=user_id,
        lexeme_sense_id=sense_id,
        material_vocabulary_id=material_vocabulary_id,
        source=source,
        note=note,
    )
    session.add(report)
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError:
        # Another request filed the identical report between the SELECT
        # above and this INSERT -- the same shape of race `_find_or_create_
        # lexeme` already guards against, and answered the same way: find
        # the winner rather than fail this request over a race a learner
        # never caused.
        await session.rollback()
        found = (
            await session.exec(
                select(TranslationReport).where(
                    TranslationReport.user_id == user_id,
                    TranslationReport.lexeme_sense_id == sense_id,
                    TranslationReport.status == "open",
                )
            )
        ).first()
        assert found is not None
        return found, False
    await session.commit()
    await session.refresh(report)
    return report, True

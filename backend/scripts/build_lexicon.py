"""Lexicon P1: build the global word list out of what is already here.

`brief-lexicon.md` + `lexicon-spec.md` (the phase plan agreed on top of it)
split the lexicon build into phases; this script is P1, and P1 makes **no
model call at all**. Everything below is either arithmetic over data this
project already has (`material_vocabulary`'s 24 000+ rows, each carrying a
model-written gloss from the READING pipeline, months old) or a lookup
against a frequency list. The reason that matters enough to say twice: this
script can be re-run for free, as often as the corpus changes, and P2 (which
DOES call a model, per lexeme, to match senses to OEWN and translate) is a
separate, resumable, budgeted job that reads what this one built.

Run from ``backend/``::

    uv run python -m scripts.build_lexicon              # build + report
    uv run python -m scripts.build_lexicon --report-only # just print the numbers

## The five steps, in the order they run

1. **Load the frequency/domain lists** (NGSL, NAWL, SUP, BSL, TSL, MOEL --
   see ``seed/wordlists/README.md``) and the OEWN sense inventory
   (``seed/wordlists/oewn_senses.jsonl.gz``).
2. **Detect lemma collisions** among the lemmas ``material_vocabulary``
   already carries -- see :func:`_merge_candidate` for the rule and why it is
   far narrower than it could be.
3. **Upsert every `Lexeme`**: one per canonical (lemma, pos) found in
   ``material_vocabulary`` (after the merge above), plus one per lemma that
   is on a frequency list and appears in NO material at all ("list-only").
   Every lexeme gets its `frequency_band`/`frequency_source`/`domain_tags`
   here, from the lists alone.
4. **Cluster provisional senses.** For every material-derived lexeme, group
   its rows by a NORMALISED reading of their usual meaning
   (`meaning_core_en`, falling back to the contextual `meaning_en` exactly as
   every other reader of this table already does) and write one
   `LexemeSense` per group -- see :func:`_normalise_meaning` for why this is
   pure string matching and not the semantic merge P2 exists to do.
5. **Link every `material_vocabulary` row** to the lexeme and sense its own
   wording landed in, and **verify + report** (:func:`report`) the numbers
   this phase is accountable for.

## Why this is idempotent rather than tracking a resume cursor

Nothing here is slow enough to need one. Twenty-five thousand rows, six flat
files and a 6 MB gzip all fit in memory, and the whole run measures in
seconds -- see the printed counts after every step, timed by hand while this
was written. "Resumable" therefore means: re-running it from a cold start,
any number of times, on a database already built by a previous run, produces
the same end state and crashes on nothing. Concretely:

* `Lexeme` rows are upserted by their `(lemma, pos)` unique key -- a re-run
  updates the same row's frequency fields rather than colliding with it.
* `LexemeSense` rows for a material-derived lexeme are DELETED and rebuilt
  from scratch every run (`material_vocabulary.sense_id` is nulled first, so
  the delete never hits the foreign key). This is safe in P1 specifically
  because nothing else has a lasting pointer into `lexeme_senses` yet --
  `saved_words` does not move to `lexeme_sense_id` until P4, and
  `translation_reports` is empty. **P2 must not copy this pattern**: the
  moment a sense carries a real OEWN match or a paid translation, deleting
  and rebuilding it on every run would throw both away.

## The merge rule, and why it is not `seed.vocabulary.stripped()`

`lexicon-spec.md` §5 asks for a lemma-collision rule and its motivating
example is real: the reading pipeline's own model, asked separately about
`descending` and `descent` inside one material, answered `descend` for both
(`app.services.vocabulary.replace_extracted`'s own comment records it) --
and because `material_vocabulary` keeps one row per `(material, lemma)`, that
collision is invisible from inside a single material. It only becomes
visible once every material's lemmas are pooled into one global table, which
is exactly what building `Lexeme` does -- so the pooling has to carry its own
check for it.

The obvious tool is already in this repository: `seed/vocabulary.stripped()`,
the suffix-stripper the reading candidate filter uses to reduce a SURFACE
form to a lemma the frequency lists know. Reusing it here was tried first and
measured, against the corpus's actual 9 395 distinct (lemma, pos) pairs, and
it is unsafe for this job specifically: `stripped()` is built to answer "is
there SOME known lemma this could reduce to", and a wrong answer there just
means a word is not offered as a candidate -- a safe failure. Applied to
LEMMA-vs-LEMMA collision detection, a wrong answer MERGES two different
words, which is not safe, and `stripped()`'s `-er`/`-est` rule (built for
comparatives like `bigger` -> `big`) does exactly that: it reduced `digest`
to `dig`, `printer` to `print`, `porter` to `port`, `recorder` to `record` --
agent nouns and unrelated words that happen to end the way a comparative
does.

So :func:`_merge_candidate` below is deliberately narrower: only the
suffixes that are PURELY INFLECTIONAL for a given part of speech survive --
verb tense endings for `v` (`-ing`/`-ed`/`-es`/`-s`, plus doubled-consonant
undoubling: `stopped` -> `stop`), comparative/superlative for `adj`
(`-er`/`-est`/`-ier`/`-iest` -- unlike a noun's `-er`, an adjective's
ALWAYS relates back to its base form in English, there is no agent-noun
reading to confuse it with), and plural-forming endings only for `n`
(`-s`/`-ies`/sibilant `-es`, explicitly NOT `-ing`, which nominalises to a
DIFFERENT word -- `engineering` is not a form of `engineer`, `housing` is not
a form of `house` in the sense that matters here). Measured against the same
corpus this narrower rule still finds 315 real collisions (`accumulating`/
`accumulate`, `broader`/`broad`, `accomplishments`/`accomplishment`, and so
on) with none of the `digest`/`dig` shape of false positive spot-checked
across the full list. `descend`/`descent` itself is not among the 315 --
today's data shows it was fully absorbed at the material level, per the
comment above, wherever it happened -- but the mechanism that would catch a
recurrence of exactly that shape of error is this one, and is exercised on
315 real cases.

Every lexeme a merge collapsed into is marked: its senses get
`review_reasons += ["lemma_merge"]` and `needs_review = True`, because a
mechanical rule, however narrow, is still a machine's guess about two words
being one, and a human should be able to find every guess this phase made.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import func, select, update as sa_update
from sqlmodel import select as sm_select

from app.core.database import async_session_factory
from app.models.lexicon import Lexeme, LexemeSense
from app.models.vocabulary import MaterialVocabulary, SavedWord, SavedWordContext, LookupEvent

REPO_ROOT = Path(__file__).resolve().parents[2]
WORDLISTS = REPO_ROOT / "seed" / "wordlists"

CEFR_ORDER: tuple[str, ...] = ("A1", "A2", "B1", "B2", "C1", "C2")


# --- Step 1: the frequency/domain lists --------------------------------------


def _rows(name: str, encoding: str = "utf-8-sig") -> list[list[str]]:
    """One vendored CSV, comment lines and blank lines dropped.

    The same shape as `seed/vocabulary.py`'s own reader, kept separate
    (rather than imported) because that module lives outside this project's
    installed package -- `seed/` is a standalone pipeline with its own venv,
    and this script runs inside the backend's. Duplicating nine lines is
    cheaper than wiring two independent Python environments together for
    them.
    """
    path = WORDLISTS / name
    text = path.read_bytes().decode(encoding, "replace")
    return [[cell.strip() for cell in line.split(",")]
            for line in text.splitlines()
            if line.strip() and not line.startswith("##")]


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
        priority order -- see `app.models.lexicon.FREQUENCY_SOURCES`. A word
        can be on more than one list (`portfolio` is BSL and NGSL-common);
        `domain_tags` is what keeps the OTHER memberships from being lost
        when only one can be the `frequency_source`.
        """
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
        return (set(self.ngsl_rank) | self.nawl | self.supplementary
                | self.bsl | self.tsl | self.moel)


# --- OEWN sense inventory (attached, not yet matched) ------------------------


class OewnIndex:
    """The compact OEWN extract, indexed for two questions P1 asks of it:
    "does this (lemma, pos) have any synsets" (coverage reporting) and
    "which part of speech is this lemma most often used as" (the only guess
    P1 makes about a list-only lexeme's `pos`, since none of the five
    frequency lists carries one).

    Matching a Lexeme's provisional senses onto specific synsets -- the hard
    part, per the brief -- is explicitly P2's job (`lexicon-spec.md` P2) and
    is NOT done here. See the module docstring's "why this runs offline"
    section in `seed/wordlists/extract_oewn.py` and the "attached in P1,
    matched in P2" note in `seed/wordlists/README.md` for why no new table
    is created to hold this: `(lemma, pos)` is already the join key this
    class needs, and both already live on `Lexeme`.
    """

    def __init__(self) -> None:
        #: (lemma, pos) -> sense count. What "coverage" and the pos guess
        #: both read.
        self.counts: dict[tuple[str, str], int] = {}
        path = WORDLISTS / "oewn_senses.jsonl.gz"
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                record = json.loads(line)
                key = (record["lemma"], record["pos"])
                self.counts[key] = self.counts.get(key, 0) + len(record["senses"])

    def has_any(self, lemma: str, pos: str) -> bool:
        return (lemma, pos) in self.counts

    def has_lemma(self, lemma: str) -> bool:
        return any(lem == lemma for lem, _ in self.counts)

    #: Preference order when two parts of speech are tied on sense count --
    #: the open classes, commonest first, since a list-only lemma with no
    #: material evidence at all is likelier to be a plain noun or verb than
    #: anything else.
    _POS_PRIORITY = ("n", "v", "adj", "adv")

    def guess_pos(self, lemma: str) -> str:
        """The part of speech OEWN itself uses most for this lemma, or ``""``
        if OEWN has never heard of it either -- the same honest empty string
        `MaterialVocabulary.pos` already uses for "would not commit to one".
        """
        candidates = [(pos, count) for (lem, pos), count in self.counts.items()
                      if lem == lemma]
        if not candidates:
            return ""
        def sort_key(item: tuple[str, int]) -> tuple[int, int]:
            pos, count = item
            priority = self._POS_PRIORITY.index(pos) if pos in self._POS_PRIORITY else 99
            return (-count, priority)
        candidates.sort(key=sort_key)
        return candidates[0][0]


# --- Step 2: lemma-collision detection ---------------------------------------

#: Purely inflectional endings for verbs -- tense/aspect, never a
#: derivational change of meaning. ``("", "e")`` etc. are the replacements
#: tried after the ending is stripped, in order.
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


def _merge_candidate(lemma: str, pos: str, known: set[str]) -> str | None:
    """The other lemma, of the SAME `pos`, that ``lemma`` is an inflected
    form of -- or ``None``. See the module docstring for why the suffix
    sets are this narrow and per-`pos`.
    """
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
    """Every (lemma, pos) in ``word_pairs`` mapped to its canonical form.

    A pair not involved in any merge maps to itself, so every raw pair this
    project has ever produced always has an entry -- callers never need a
    ``.get(pair, pair)`` fallback scattered through them.
    """
    by_pos: dict[str, set[str]] = defaultdict(set)
    for lemma, pos in word_pairs:
        by_pos[pos].add(lemma)

    one_hop: dict[tuple[str, str], tuple[str, str]] = {}
    for lemma, pos in word_pairs:
        target = _merge_candidate(lemma, pos, by_pos[pos])
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


# --- Step 4: provisional sense clustering ------------------------------------

_PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
_WS_RE = re.compile(r"\s+")


def _normalise_meaning(text: str) -> str:
    """A meaning string reduced to bare words, for GROUPING only -- never
    shown to anybody. Two material rows glossing the same sense of a word
    rarely use identical wording (that variation, 3 568 groups of it, is
    §1's whole reason for this brief), so exact-string clustering after this
    normalisation is what P1 can afford without a model: it groups
    "an action of moving downward" with "An Action Of Moving Downward!" and
    leaves "an action of moving downward" and "the act of falling" as two
    provisional senses -- correctly, since P1 cannot know they mean the same
    thing. Merging those is P2's job, matched against OEWN.
    """
    lowered = text.lower().strip()
    despunct = _PUNCT_RE.sub(" ", lowered)
    return _WS_RE.sub(" ", despunct).strip()


def _usual_meaning(row: dict) -> tuple[str, str]:
    """A row's (English, Uzbek) USUAL meaning, falling back to its
    contextual one -- the same fallback every other reader of
    `MaterialVocabulary` already uses (see that model's own docstring),
    applied here so a row written before `meaning_core_*` existed still
    contributes a sense rather than being silently skipped.
    """
    en = row["meaning_core_en"] or row["meaning_en"]
    uz = row["meaning_core_uz"] or row["meaning_uz"]
    return en, uz


def _majority_cefr(levels: list[str]) -> str | None:
    """The commonest non-empty CEFR level among a sense's rows, ties broken
    toward the LOWER level -- a deliberate conservative lean, since this
    figure feeds the NGSL-conflict check straight back (a tie nudged upward
    would manufacture its own false positive).
    """
    counts = Counter(level for level in levels if level)
    if not counts:
        return None
    top = max(counts.values())
    tied = [level for level, count in counts.items() if count == top]
    tied.sort(key=lambda level: CEFR_ORDER.index(level) if level in CEFR_ORDER else 99)
    return tied[0]


def _pick_representative(rows: list[dict]) -> tuple[str, str]:
    """The exact (unnormalised) wording shown for a sense: the most common
    literal (en, uz) pairing in the group, so the definition a reader sees
    is a wording somebody actually wrote, never a synthesised one. Ties
    favour the shorter text, then alphabetical order, both purely for
    determinism -- re-running this script must pick the same wording, not
    merely an equally valid one.
    """
    pairs = Counter((r["meaning_core_en"] or r["meaning_en"],
                      r["meaning_core_uz"] or r["meaning_uz"]) for r in rows)
    top = max(pairs.values())
    tied = [pair for pair, count in pairs.items() if count == top]
    tied.sort(key=lambda pair: (len(pair[0]), pair[0]))
    return tied[0]


def cluster_senses(rows: list[dict]) -> list[dict]:
    """One provisional-sense group per distinct normalised usual meaning
    among ``rows`` (all belonging to one lexeme), ranked commonest first.

    Returns a list of ``{"definition_en", "meaning_uz", "cefr", "row_ids"}``.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        en, _ = _usual_meaning(row)
        groups[_normalise_meaning(en)].append(row)

    ranked = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    senses = []
    for _, group_rows in ranked:
        definition_en, meaning_uz = _pick_representative(group_rows)
        senses.append({
            "definition_en": definition_en[:400],
            "meaning_uz": meaning_uz[:400],
            "cefr": _majority_cefr([r["cefr_level"] for r in group_rows]),
            "row_ids": [r["id"] for r in group_rows],
        })
    return senses


# --- Orchestration ------------------------------------------------------------


async def _fetch_material_rows(session) -> list[dict]:
    result = await session.exec(
        sm_select(
            MaterialVocabulary.id,
            MaterialVocabulary.lemma,
            MaterialVocabulary.pos,
            MaterialVocabulary.is_phrase,
            MaterialVocabulary.meaning_core_en,
            MaterialVocabulary.meaning_core_uz,
            MaterialVocabulary.meaning_en,
            MaterialVocabulary.meaning_uz,
            MaterialVocabulary.cefr_level,
        )
    )
    return [
        {
            "id": row.id, "lemma": row.lemma, "pos": row.pos,
            "is_phrase": row.is_phrase,
            "meaning_core_en": row.meaning_core_en, "meaning_core_uz": row.meaning_core_uz,
            "meaning_en": row.meaning_en, "meaning_uz": row.meaning_uz,
            "cefr_level": row.cefr_level,
        }
        for row in result.all()
    ]


def _lexeme_is_phrase(lemma: str, pos: str) -> bool:
    """A lexeme counts as a phrase if its lemma is plainly multi-word, OR
    its part of speech was tagged `phr` -- checked with OR rather than
    trusting either signal alone, because the corpus has both: 58 rows with
    a multi-word lemma (`"they are"`, `"tip-of-the-tongue"`) tagged some
    other `pos` by mistake, and one single-token-looking phrase
    (`"ai safety"`, which IS multi-word -- the point is the flag on the ROW,
    `is_phrase`, is not reliably set either way, so the lexicon build trusts
    neither the row's own flag nor `pos` alone and instead asks the one
    question that is actually reliable: does the string contain a space, or
    was it filed as a phrase.
    """
    return (" " in lemma) or (pos == "phr")


async def build(session, allow_wipe: bool = False) -> dict:
    print("Loading frequency lists and OEWN sense inventory...")
    lists = FrequencyLists()
    oewn = OewnIndex()
    print(f"  NGSL {len(lists.ngsl_rank)}, NAWL {len(lists.nawl)}, "
          f"SUP {len(lists.supplementary)}, BSL {len(lists.bsl)}, "
          f"TSL {len(lists.tsl)}, MOEL {len(lists.moel)}")
    print(f"  OEWN: {len(oewn.counts)} (lemma, pos) entries")

    print("Loading material_vocabulary rows...")
    rows = await _fetch_material_rows(session)
    print(f"  {len(rows)} rows")

    word_rows = [r for r in rows if not _lexeme_is_phrase(r["lemma"], r["pos"])]
    phrase_rows = [r for r in rows if _lexeme_is_phrase(r["lemma"], r["pos"])]
    word_pairs = {(r["lemma"], r["pos"]) for r in word_rows}
    phrase_pairs = {(r["lemma"], r["pos"]) for r in phrase_rows}

    print("Detecting lemma collisions...")
    merge_map = build_merge_map(word_pairs)
    merged_pairs = {pair: target for pair, target in merge_map.items() if pair != target}
    merged_lexeme_keys = set(merged_pairs.values())
    print(f"  {len(merged_pairs)} raw (lemma, pos) pairs merged into "
          f"{len(merged_lexeme_keys)} lexemes")

    def canonical_key(row: dict) -> tuple[str, str]:
        pair = (row["lemma"], row["pos"])
        return merge_map.get(pair, pair) if pair in word_pairs else pair

    material_rows_by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        material_rows_by_key[canonical_key(row)].append(row)

    material_keys = set(material_rows_by_key)
    print(f"  {len(material_keys)} canonical lexemes from material rows "
          f"({len(word_pairs)} raw word pairs, {len(phrase_pairs)} phrase pairs)")

    print("Selecting list-only lemmas (on a frequency list, absent from every material)...")
    material_lemmas = {lemma for lemma, _ in material_keys}
    list_only_lemmas = sorted(lists.all_lemmas() - material_lemmas)
    print(f"  {len(list_only_lemmas)} list-only lemmas")

    # --- Upsert Lexemes -------------------------------------------------
    print("Upserting lexemes...")
    existing = (await session.exec(sm_select(Lexeme))).all()
    lexeme_by_key: dict[tuple[str, str], Lexeme] = {(lx.lemma, lx.pos): lx for lx in existing}

    def upsert_lexeme(lemma: str, pos: str, is_phrase: bool) -> Lexeme:
        key = (lemma, pos)
        band = lists.band(lemma)
        source = lists.source(lemma)
        tags = lists.domain_tags(lemma)
        lexeme = lexeme_by_key.get(key)
        if lexeme is None:
            lexeme = Lexeme(
                lemma=lemma, pos=pos, is_phrase=is_phrase,
                frequency_band=band, frequency_source=source, domain_tags=tags,
            )
            session.add(lexeme)
            lexeme_by_key[key] = lexeme
        else:
            lexeme.is_phrase = is_phrase
            lexeme.frequency_band = band
            lexeme.frequency_source = source
            lexeme.domain_tags = tags
        return lexeme

    for lemma, pos in sorted(material_keys):
        rows_here = material_rows_by_key[(lemma, pos)]
        is_phrase = any(_lexeme_is_phrase(r["lemma"], r["pos"]) for r in rows_here)
        upsert_lexeme(lemma, pos, is_phrase)
    for lemma in list_only_lemmas:
        pos = oewn.guess_pos(lemma)
        upsert_lexeme(lemma, pos, " " in lemma)
    await session.flush()
    print(f"  {len(lexeme_by_key)} lexemes total")

    # --- Rebuild provisional senses for material-derived lexemes ---------
    print("Rebuilding provisional senses...")
    enriched = (await session.exec(
        select(func.count()).select_from(Lexeme).where(Lexeme.enriched_at.is_not(None))
    )).scalar_one()
    if enriched and not allow_wipe:
        raise SystemExit(
            f"{enriched} lexemes are already enriched by P2 (scripts.enrich_lexicon): "
            "rebuilding would delete their OEWN matches and paid translations. "
            "Re-run with --wipe-enriched only if that is intended."
        )
    material_lexeme_ids = [lexeme_by_key[key].id for key in material_keys]
    # Null the pointer before deleting, so the delete never hits the FK.
    await session.exec(
        sa_update(MaterialVocabulary)
        .where(MaterialVocabulary.lexeme_id.in_(material_lexeme_ids))
        .values(sense_id=None)
    )
    old_senses = (await session.exec(
        sm_select(LexemeSense).where(LexemeSense.lexeme_id.in_(material_lexeme_ids))
    )).all()
    for sense in old_senses:
        await session.delete(sense)
    await session.execute(
        sa_update(Lexeme).where(Lexeme.id.in_(material_lexeme_ids)).values(enriched_at=None)
    )
    await session.flush()

    sense_count = 0
    review_counts: Counter[str] = Counter()
    row_sense_id: dict[object, object] = {}
    for key, rows_here in material_rows_by_key.items():
        lexeme = lexeme_by_key[key]
        clusters = cluster_senses(rows_here)
        merged = key in merged_lexeme_keys
        for rank, cluster in enumerate(clusters, start=1):
            reasons = []
            cefr = cluster["cefr"]
            if merged:
                reasons.append("lemma_merge")
            if cefr in ("C1", "C2") and lexeme.frequency_band == "core":
                reasons.append("ngsl_conflict")
            if cefr in ("A1", "A2") and lexeme.frequency_band == "off-list":
                reasons.append("ngsl_conflict")
            sense = LexemeSense(
                lexeme_id=lexeme.id,
                sense_rank=rank,
                definition_en=cluster["definition_en"],
                meaning_uz=cluster["meaning_uz"],
                cefr=cefr,
                source_id="model",
                licence="proprietary",
                provisional=True,
                needs_review=bool(reasons),
                review_reasons=reasons,
            )
            session.add(sense)
            await session.flush()
            sense_count += 1
            review_counts.update(reasons)
            for row_id in cluster["row_ids"]:
                row_sense_id[row_id] = sense.id
        lexeme.cefr = clusters[0]["cefr"] if clusters else None
    await session.flush()
    print(f"  {sense_count} provisional senses "
          f"({sum(review_counts.values())} review flags: {dict(review_counts)})")

    # --- Link every material_vocabulary row -------------------------------
    print("Linking material_vocabulary rows to lexeme_id + sense_id...")
    mappings = [
        {
            "id": row["id"],
            "lexeme_id": lexeme_by_key[canonical_key(row)].id,
            "sense_id": row_sense_id.get(row["id"]),
        }
        for row in rows
    ]
    for chunk_start in range(0, len(mappings), 2000):
        chunk = mappings[chunk_start:chunk_start + 2000]
        await session.execute(sa_update(MaterialVocabulary), chunk)
    await session.flush()
    print(f"  {len(mappings)} rows linked")

    return {
        "lists": lists, "oewn": oewn,
        "material_keys": material_keys, "list_only_lemmas": list_only_lemmas,
        "merged_pairs": merged_pairs, "merged_lexeme_keys": merged_lexeme_keys,
        "review_counts": review_counts,
    }


# --- Verification + report ----------------------------------------------------


async def report(session, build_state: dict | None) -> None:
    print("\n=== Lexicon P1 report ===\n")

    lexemes = (await session.exec(sm_select(Lexeme))).all()
    words = [lx for lx in lexemes if not lx.is_phrase]
    phrases = [lx for lx in lexemes if lx.is_phrase]
    material_lexeme_ids = set((await session.exec(
        select(MaterialVocabulary.lexeme_id).distinct()
        .where(MaterialVocabulary.lexeme_id.is_not(None))
    )).scalars().all())
    list_only = [lx for lx in lexemes if lx.id not in material_lexeme_ids]
    print(f"Lexemes: {len(lexemes)} total -- {len(words)} words, {len(phrases)} phrases "
          f"({len(lexemes) - len(list_only)} material-derived, {len(list_only)} list-only)")

    senses = (await session.exec(sm_select(LexemeSense))).all()
    provisional = [s for s in senses if s.provisional]
    print(f"Senses: {len(senses)} total, {len(provisional)} provisional")
    needing_review = [s for s in senses if s.needs_review]
    reason_counts: Counter[str] = Counter()
    for s in needing_review:
        reason_counts.update(s.review_reasons)
    print(f"needs_review: {len(needing_review)} senses -- by reason: {dict(reason_counts)}")

    total_rows = (await session.exec(
        select(func.count()).select_from(MaterialVocabulary)
    )).scalar_one()
    linked_rows = (await session.exec(
        select(func.count()).select_from(MaterialVocabulary)
        .where(MaterialVocabulary.lexeme_id.is_not(None))
    )).scalar_one()
    print(f"material_vocabulary rows linked to a lexeme: {linked_rows} of {total_rows}")
    linked_sense_rows = (await session.exec(
        select(func.count()).select_from(MaterialVocabulary)
        .where(MaterialVocabulary.sense_id.is_not(None))
    )).scalar_one()
    print(f"material_vocabulary rows linked to a sense: {linked_sense_rows} of {total_rows}")

    band_counts = Counter(lx.frequency_source for lx in lexemes)
    print(f"Lexemes by frequency_source: {dict(band_counts)}")
    domain_counts: Counter[str] = Counter()
    for lx in lexemes:
        domain_counts.update(lx.domain_tags)
    print(f"Domain tag counts: {dict(domain_counts)}")

    oewn = build_state["oewn"] if build_state else OewnIndex()
    words_with_oewn = sum(1 for lx in words if oewn.has_any(lx.lemma, lx.pos))
    phrases_with_oewn = sum(1 for lx in phrases if oewn.has_any(lx.lemma, lx.pos))
    words_with_oewn_lemma = sum(1 for lx in words if oewn.has_lemma(lx.lemma))
    phrases_with_oewn_lemma = sum(1 for lx in phrases if oewn.has_lemma(lx.lemma))
    print(f"OEWN coverage (exact lemma+pos match): {words_with_oewn} of {len(words)} words, "
          f"{phrases_with_oewn} of {len(phrases)} phrases")
    print(f"OEWN coverage (lemma known, any pos): {words_with_oewn_lemma} of {len(words)} words, "
          f"{phrases_with_oewn_lemma} of {len(phrases)} phrases")

    if build_state:
        print(f"Lemma merges: {len(build_state['merged_pairs'])} raw pairs -> "
              f"{len(build_state['merged_lexeme_keys'])} lexemes")

    for table, label in ((SavedWord, "saved_words"),
                          (SavedWordContext, "saved_word_contexts"),
                          (LookupEvent, "lookup_events")):
        count = (await session.exec(select(func.count()).select_from(table))).scalar_one()
        print(f"{label}: {count} (untouched by this script)")

    print("\ngrep for Oxford in the pipeline (git-tracked files only -- "
          "rejection comments are fine, listed below):")
    try:
        grep = subprocess.run(
            ["git", "grep", "-niI", "oxford", "--",
             "backend/app", "backend/scripts", "seed/*.py",
             "seed/README.md", "seed/wordlists"],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        output = grep.stdout.strip()
        print(output if output else "  (no matches)")
    except FileNotFoundError:
        print("  (git not available)")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-only", action="store_true",
                         help="skip the build, only print the verification report")
    parser.add_argument("--wipe-enriched", action="store_true",
                         help="allow the rebuild to delete senses P2 already enriched")
    args = parser.parse_args()

    async with async_session_factory() as session:
        state = None
        if not args.report_only:
            state = await build(session, allow_wipe=args.wipe_enriched)
            await session.commit()
        await report(session, state)


if __name__ == "__main__":
    asyncio.run(main())

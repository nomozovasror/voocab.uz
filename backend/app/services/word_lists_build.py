"""Populate ``word_list_entries``: which lemmas each list has, in what order,
and which SENSE each list means by each of them.

Run by ``scripts/build_word_lists.py`` (see its docstring for the command).
The decisions this module implements were agreed with the user and are not
this module's to revise:

## Membership

One entry per lemma of the published list, read from the vendored files
(:data:`LIST_FILES`, all in ``app.services.lexicon.WORDLISTS``):
NGSL 1.2 / BSL 1.20 / NAWL 1.2 / TSL 1.2 from their ranked ``*_stats.csv``
(the stats file IS the list -- NAWL's lemmatised file carries two forms the
957-word list does not), MOEL from ``MOEL_terms.csv``. Never a card: a
single letter, one of `lexicon.FUNCTION_WORDS`, or a proper noun (every
lexeme of the lemma marked, the chosen sense's lexeme marked, or the model
answering "skip" because the headword is a name or a fragment).

## Order (``rank``, ``rank_source``)

Most frequent first, renumbered 1..n after exclusions. A list's own rank
wins (``list``). A list with none (MOEL) is ordered by the NGSL project's
31K-lemma frequency table (``sfi31k``: `NGSL_SFI_31K.csv`, extracted from
`NGSLwithSFI-31K.xlsx`), highest SFI first -- SFI being the measure the
family's own ranks are made of. Only a term that table lacks (an exact,
lower-cased match; it holds single lemmas, so every phrase) falls down the
chain, one source per entry, the groups after ``sfi31k`` in the chain's
order: SemCor tag count of the lemma, summed over every OEWN sense in every
part of speech, highest first (``semcor``); else NGSL rank (``ngsl``); else
the chosen sense's CEFR, easy to hard, unrated last (``cefr``). Ties inside
a group fall to the next signals (NGSL rank, CEFR, material rows, single
words before phrases, shorter first) and only then to the lemma -- so the
lemma decides exact ties only, never the order (:func:`order_entries`).

## Sense

* **Core**: the lemma's most SemCor-tagged OEWN synset ACROSS parts of
  speech (`lexicon_enrich.top_sense_any_pos`, the rule list-only lexemes
  already follow) -- not the rank-1 sense of whichever lexeme the lexicon
  happens to hold, which made `good` "goods" and `school` a children's
  game. Where the counts do not decide between parts of speech, the model
  picks among each pos's top sense (as for list-only lexemes); where it
  declines all of them (`till` the conjunction is none), it is asked once
  more over the domain lists' full menu -- every OEWN sense plus ours, a
  definition of its own allowed -- and only then the tie order; where OEWN
  does not know the lemma (`whereas`, `criteria`), or the chosen pos is a
  proper-noun/function-word lexeme, the old rule stands: the rank-1 sense of
  the PRIMARY lexeme (:func:`primary_lexeme`). A synset the lexicon lacks
  is created exactly as for a domain list (below), and every Core decision
  is logged like a domain one (:func:`core_decision`).
* **Domain lists** (business, academic, medical, toeic): one decision per
  (list, lemma), asked in batches (:data:`DOMAIN_PROMPT`): which of ALL the
  lemma's OEWN synsets, across parts of speech, plus every sense our lexicon
  already has, this list means. A synset not yet a `LexemeSense` is created
  (source ``oewn``, ``cc-by-4.0``); "none fits" gets the model's own
  WordNet-style definition (source ``model``). A new sense goes through the
  SAME enrichment pieces a lexeme's senses do -- `lexicon_enrich.step_cefr`,
  `step_translate` (two translators, the judge twice), `review_reasons` --
  and `lexicon_hints.recompute_for_lexemes` for `needs_letter_hint`. Nothing
  else about the lexeme is touched: no existing sense is re-ranked or
  rewritten, and `Lexeme.enriched_at` is left as it was (set on a lexeme
  this module creates, because its one sense IS enriched).

## Resumable, idempotent, replayable

The database is the resume state: an entry with a ``sense_id`` is done and
is never asked about again (``reselect`` overrides). Every model answer --
the choice, and a new sense's grade/translation -- is also appended to a
JSONL decisions log the moment it arrives, so a crash costs nothing already
paid for, and the SAME log replayed against another copy of the database
(the real run after the dry run) writes the same senses with no model call
at all. A logged answer naming a sense id the target database does not have
is ignored and asked again.
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import time
import uuid
from collections import ChainMap, Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete as sa_delete
from sqlalchemy import func
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select

from app.models.lexicon import Lexeme, LexemeSense
from app.models.vocabulary import MaterialVocabulary
from app.models.word_list import WordList, WordListEntry
from app.services import lexicon_enrich as le
from app.services import lexicon_hints
from app.services.lexicon import (
    WORDLISTS,
    frequency_lists,
    is_excluded_word,
    lexeme_is_phrase,
    normalise_meaning,
)
from app.services.word_lists_seed import seed_word_lists

logger = logging.getLogger("app.services.word_lists_build")

CORE = "core"
DOMAIN_LISTS: tuple[str, ...] = ("business", "academic", "medical", "toeic")
ALL_LISTS: tuple[str, ...] = (CORE, *DOMAIN_LISTS)

#: key -> (file, encoding, has its own rank). Encodings are the files' own
#: (TSL is Latin-1: `résumé`, `café`, `entrée`).
LIST_FILES: dict[str, tuple[str, str, bool]] = {
    "core": ("NGSL_12_stats.csv", "utf-8-sig", True),
    "business": ("BSL_120_stats.csv", "utf-8-sig", True),
    "academic": ("NAWL_12_stats.csv", "utf-8-sig", True),
    "toeic": ("TSL_12_stats.csv", "latin-1", True),
    "medical": ("MOEL_terms.csv", "utf-8", False),
}

#: The NGSL project's 31K-lemma frequency table (`seed/wordlists/
#: extract_sfi31k.py`): orders a list that has no rank of its own.
SFI31K_FILE = "NGSL_SFI_31K.csv"

#: What the domain chooser is told each list is about. ``core`` is asked
#: only when SemCor cannot choose between parts of speech.
LIST_DOMAINS: dict[str, str] = {
    "core": (
        "Core English (the New General Service List) -- the most frequent "
        "words of general English, the ones that cover most of what a "
        "learner reads and hears every day; each is taught in the meaning "
        "met most often in everyday and general reading"
    ),
    "business": (
        "Business English (the Business Service List) -- words typical of "
        "business texts: finance, accounting, investment, management, "
        "marketing, trade, companies and the workplace"
    ),
    "academic": (
        "Academic English (the New Academic Word List) -- words typical of "
        "academic writing and lectures across subjects (journal articles, "
        "textbooks), beyond the most common general words"
    ),
    "medical": (
        "Medical English (the Medical Oral English List) -- words and phrases "
        "patients, doctors and nurses use when they talk about the body, "
        "symptoms, illness, tests and treatment"
    ),
    "toeic": (
        "TOEIC (the TOEIC Service List) -- words typical of the TOEIC test: "
        "everyday workplace and business situations such as offices, "
        "meetings, email, hiring, travel, hotels, shopping and dining"
    ),
}

#: The domain chooser. Cheap and decisive; overridable per run.
DEFAULT_CHOICE_MODEL = le.MODEL_MAIN
CHOICE_BATCH = 25
#: OEWN senses shown per part of speech (`lexicon_enrich.OEWN_SHOWN`).
CANDIDATES_PER_POS = le.OEWN_SHOWN
#: The lexicon's own parts of speech (`Lexeme.pos`).
CHOICE_POS = ("n", "v", "adj", "adv", "prep", "conj", "phr")

CEFR_ORDER = le.CEFR_ORDER


# --- Reading the lists --------------------------------------------------------


@dataclass(frozen=True)
class SourceEntry:
    lemma: str
    #: The list's own rank; None for a list that has none (MOEL).
    list_rank: int | None


def read_list(key: str, directory: Path = WORDLISTS) -> list[SourceEntry]:
    """One list's lemmas in file order, lower-cased, de-duplicated."""
    name, encoding, ranked = LIST_FILES[key]
    text = (directory / name).read_bytes().decode(encoding, "replace")
    out: list[SourceEntry] = []
    seen: set[str] = set()
    if ranked:
        for row in csv.reader(text.splitlines()):
            if not row or not row[0].strip() or row[0].startswith("##"):
                continue
            lemma = " ".join(row[0].split()).lower()
            # The header is the one row without a numeric rank -- never
            # skipped by name: "word" is itself an NGSL lemma.
            if len(row) < 2 or not row[1].strip().isdigit():
                continue
            if lemma not in seen:
                seen.add(lemma)
                out.append(SourceEntry(lemma, int(row[1])))
    else:
        for line in text.splitlines():
            lemma = " ".join(line.split()).lower()
            if lemma and lemma not in seen:
                seen.add(lemma)
                out.append(SourceEntry(lemma, None))
    return out


def read_sfi31k(directory: Path = WORDLISTS) -> dict[str, float]:
    """lemma -> SFI from the 31K table; a lemma listed twice keeps the
    higher figure."""
    out: dict[str, float] = {}
    text = (directory / SFI31K_FILE).read_text(encoding="utf-8")
    for row in csv.DictReader(text.splitlines()):
        lemma = " ".join(row["lemma"].split()).lower()
        try:
            sfi = float(row["sfi"])
        except (TypeError, ValueError):
            continue
        if lemma and sfi > out.get(lemma, float("-inf")):
            out[lemma] = sfi
    return out


# --- The lexicon, as this build needs it --------------------------------------


@dataclass
class LexemeInfo:
    id: uuid.UUID
    lemma: str
    pos: str
    is_phrase: bool
    is_proper_noun: bool
    is_function_word: bool
    frequency_band: str | None
    material_rows: int = 0

    @property
    def flagged(self) -> bool:
        return self.is_proper_noun or self.is_function_word


@dataclass
class SenseInfo:
    id: uuid.UUID
    lexeme_id: uuid.UUID
    sense_rank: int
    definition_en: str
    oewn_synset_id: str | None
    cefr: str | None
    source_id: str


@dataclass
class LexiconView:
    lexemes: dict[uuid.UUID, LexemeInfo] = field(default_factory=dict)
    by_lemma: dict[str, list[LexemeInfo]] = field(default_factory=lambda: defaultdict(list))
    senses: dict[uuid.UUID, SenseInfo] = field(default_factory=dict)
    senses_of: dict[uuid.UUID, list[SenseInfo]] = field(default_factory=lambda: defaultdict(list))

    def add_lexeme(self, lexeme: LexemeInfo) -> None:
        self.lexemes[lexeme.id] = lexeme
        self.by_lemma[lexeme.lemma].append(lexeme)

    def add_sense(self, sense: SenseInfo) -> None:
        self.senses[sense.id] = sense
        self.senses_of[sense.lexeme_id].append(sense)
        self.senses_of[sense.lexeme_id].sort(key=lambda s: s.sense_rank)

    def rank1(self, lexeme_id: uuid.UUID) -> SenseInfo | None:
        senses = self.senses_of.get(lexeme_id) or []
        return senses[0] if senses else None


class _Merged:
    """``base.get(key)`` followed by ``extra.get(key)``: read-only."""

    def __init__(self, base: dict, extra: dict) -> None:
        self.base, self.extra = base, extra

    def get(self, key, default=None):
        merged = list(self.base.get(key, [])) + list(self.extra.get(key, []))
        return merged if merged else default


class UnitView(LexiconView):
    """What one unit has written but not yet committed, laid over the shared
    view. Lookups see both; writes land only here. :meth:`merge_into` makes
    them visible to every other unit, and is called only once the unit's
    commit has succeeded -- a failed commit just drops this object, so no
    later unit can refer to a sense that was rolled back."""

    def __init__(self, base: LexiconView) -> None:
        super().__init__()
        self.base = base
        self.own = LexiconView()
        self.lexemes = ChainMap(self.own.lexemes, base.lexemes)
        self.senses = ChainMap(self.own.senses, base.senses)
        self.by_lemma = _Merged(base.by_lemma, self.own.by_lemma)
        self.senses_of = _Merged(base.senses_of, self.own.senses_of)

    def add_lexeme(self, lexeme: LexemeInfo) -> None:
        self.own.add_lexeme(lexeme)

    def add_sense(self, sense: SenseInfo) -> None:
        self.own.add_sense(sense)

    def merge_into(self) -> None:
        for lexeme in self.own.lexemes.values():
            self.base.add_lexeme(lexeme)
        for sense in self.own.senses.values():
            self.base.add_sense(sense)


async def load_view(session, lemmas: set[str] | None = None) -> LexiconView:
    """Every lexeme and sense (or only those of ``lemmas``), plus each
    lexeme's count of non-hidden material rows."""
    query = select(Lexeme)
    if lemmas is not None:
        query = query.where(Lexeme.lemma.in_(sorted(lemmas)))
    lexemes = (await session.exec(query)).all()
    ids = [lx.id for lx in lexemes]
    view = LexiconView()
    if not ids:
        return view
    rows = dict((await session.exec(
        select(MaterialVocabulary.lexeme_id, func.count())
        .where(MaterialVocabulary.lexeme_id.in_(ids), MaterialVocabulary.hidden.is_(False))
        .group_by(MaterialVocabulary.lexeme_id)
    )).all())
    for lx in lexemes:
        view.add_lexeme(LexemeInfo(
            id=lx.id, lemma=lx.lemma, pos=lx.pos, is_phrase=lx.is_phrase,
            is_proper_noun=lx.is_proper_noun, is_function_word=lx.is_function_word,
            frequency_band=lx.frequency_band, material_rows=int(rows.get(lx.id, 0)),
        ))
    senses = (await session.exec(
        select(LexemeSense).where(LexemeSense.lexeme_id.in_(ids))
    )).all()
    for s in senses:
        view.add_sense(SenseInfo(
            id=s.id, lexeme_id=s.lexeme_id, sense_rank=s.sense_rank,
            definition_en=s.definition_en, oewn_synset_id=s.oewn_synset_id,
            cefr=s.cefr, source_id=s.source_id,
        ))
    return view


# --- OEWN-derived numbers -----------------------------------------------------


def semcor_by_pos(oewn: dict[tuple[str, str], list[dict]]) -> dict[str, dict[str, int]]:
    """lemma -> pos -> SemCor tag count summed over that pos's OEWN senses."""
    out: dict[str, dict[str, int]] = defaultdict(dict)
    for (lemma, pos), senses in oewn.items():
        out[lemma][pos] = sum(int(s.get("count") or 0) for s in senses)
    return out


def semcor_total(by_pos: dict[str, dict[str, int]], lemma: str) -> int:
    return sum((by_pos.get(lemma) or {}).values())


# --- Exclusions ---------------------------------------------------------------


def exclusion_reason(lemma: str, lexemes: list[LexemeInfo]) -> str | None:
    """Why ``lemma`` is never a card, before any sense is chosen -- or None.

    A proper noun is excluded only when EVERY lexeme of the lemma is one:
    `bath` the city sitting beside `bath` the word must not cost the word."""
    lemma = lemma.strip().lower()
    if len(lemma) <= 1:
        return "single_letter"
    if is_excluded_word(lemma):
        return "function_word"
    if lexemes and all(lx.flagged for lx in lexemes):
        return "proper_noun" if any(lx.is_proper_noun for lx in lexemes) else "function_word"
    return None


# --- Core: the primary lexeme -------------------------------------------------


def primary_lexeme(lexemes: list[LexemeInfo], counts_by_pos: dict[str, int],
                   has_sense) -> LexemeInfo | None:
    """The lexeme whose part of speech SemCor tags most (summed over that
    pos's OEWN senses); a tie -- most often 0 against 0 -- goes to the one
    with the most material rows, then to `lexicon_enrich.POS_PRIORITY`.
    Only unflagged lexemes that have a sense compete."""
    candidates = [lx for lx in lexemes if not lx.flagged and has_sense(lx.id)]
    if not candidates:
        return None

    def key(lx: LexemeInfo):
        pos_order = le.POS_PRIORITY.index(lx.pos) if lx.pos in le.POS_PRIORITY else 99
        return (-counts_by_pos.get(lx.pos, 0), -lx.material_rows, pos_order, lx.pos)

    return min(candidates, key=key)


def global_rank1(view: LexiconView, by_pos: dict[str, dict[str, int]],
                 lemma: str) -> SenseInfo | None:
    """Core's rule: the rank-1 sense of the lemma's primary lexeme."""
    lexeme = primary_lexeme(view.by_lemma.get(lemma, []), by_pos.get(lemma) or {},
                            lambda lid: bool(view.senses_of.get(lid)))
    return view.rank1(lexeme.id) if lexeme else None


# --- Order --------------------------------------------------------------------


@dataclass
class RankInput:
    lemma: str
    list_rank: int | None = None
    #: The lemma's SFI in the 31K table, None when the table lacks it.
    sfi31k: float | None = None
    semcor: int = 0
    ngsl_rank: int | None = None
    cefr: str | None = None
    material_rows: int = 0


_BIG = 10 ** 9


def _cefr_index(cefr: str | None) -> int:
    return CEFR_ORDER.index(cefr) if cefr in CEFR_ORDER else len(CEFR_ORDER)


def rank_source_of(item: RankInput) -> str:
    if item.list_rank is not None:
        return "list"
    if item.sfi31k is not None:
        return "sfi31k"
    if item.semcor > 0:
        return "semcor"
    if item.ngsl_rank is not None:
        return "ngsl"
    return "cefr"


def order_entries(items: list[RankInput]) -> list[tuple[str, int, str]]:
    """``(lemma, rank, rank_source)`` with rank 1..n, most frequent first.

    The list's own rank first; then the 31K table's SFI, high to low; then
    the chain groups in order (SemCor count high to low, NGSL rank low to
    high, CEFR easy to hard with unrated last). Within a group the later
    signals break ties, then single words before phrases and shorter before
    longer; the lemma itself only ever separates exact ties, so the order
    is deterministic without ever being alphabetical."""
    group_of = {"list": 0, "sfi31k": 1, "semcor": 2, "ngsl": 3, "cefr": 4}

    def key(item: RankInput):
        source = rank_source_of(item)
        return (
            group_of[source],
            item.list_rank if item.list_rank is not None else _BIG,
            -(item.sfi31k if item.sfi31k is not None else float("-inf")),
            -item.semcor,
            item.ngsl_rank if item.ngsl_rank is not None else _BIG,
            _cefr_index(item.cefr),
            -item.material_rows,
            len(item.lemma.split()),
            len(item.lemma),
            item.lemma,
        )

    ordered = sorted(items, key=key)
    return [(item.lemma, rank, rank_source_of(item)) for rank, item in enumerate(ordered, 1)]


# --- Domain choice: candidates, prompt, answers --------------------------------


@dataclass
class Candidate:
    cid: str
    pos: str
    definition: str
    #: OEWN synset, when the candidate is one (whether or not we hold it).
    synset: str | None = None
    oewn_rank: int | None = None
    #: The `LexemeSense` we already hold for it, if any.
    sense_id: uuid.UUID | None = None


def build_candidates(lemma: str, oewn: dict[tuple[str, str], list[dict]],
                     oewn_pos: list[str], view: LexiconView) -> list[Candidate]:
    """Every OEWN synset of ``lemma`` in every pos (at most
    :data:`CANDIDATES_PER_POS` each, OEWN order), each joined to the sense we
    already hold for it; then every sense of ours that is not one of those
    (a material/model sense, or a synset deeper than the cut-off)."""
    lexemes = [lx for lx in view.by_lemma.get(lemma, []) if not lx.flagged]
    held_by_synset: dict[tuple[str, str], SenseInfo] = {}
    for lx in lexemes:
        for s in view.senses_of.get(lx.id, []):
            if s.oewn_synset_id:
                held_by_synset.setdefault((lx.pos, s.oewn_synset_id), s)

    out: list[Candidate] = []
    used: set[uuid.UUID] = set()
    pos_order = sorted(set(oewn_pos) | {lx.pos for lx in lexemes},
                       key=lambda p: (le.POS_PRIORITY.index(p) if p in le.POS_PRIORITY else 9, p))
    for pos in pos_order:
        for entry in (oewn.get((lemma, pos)) or [])[:CANDIDATES_PER_POS]:
            held = held_by_synset.get((pos, entry["synset"]))
            out.append(Candidate(
                cid="", pos=pos, definition=entry["definition"], synset=entry["synset"],
                oewn_rank=entry["rank"], sense_id=held.id if held else None,
            ))
            if held:
                used.add(held.id)
        for lx in lexemes:
            if lx.pos != pos:
                continue
            for s in view.senses_of.get(lx.id, []):
                if s.id in used or not s.definition_en.strip():
                    continue
                used.add(s.id)
                out.append(Candidate(cid="", pos=pos or "?", definition=s.definition_en,
                                     synset=s.oewn_synset_id, sense_id=s.id))
    for index, cand in enumerate(out, 1):
        cand.cid = f"c{index}"
    return out


DOMAIN_PROMPT = """You are helping build English vocabulary courses for
Uzbek learners. Each course is one published word list, built by counting
words in texts of one domain and keeping the words typical of it:

{domain}

A learner who studies a word from this list should learn it in the meaning
that puts it on this list. For each headword below you get every meaning we
have for it, across parts of speech -- WordNet's senses, and meanings our
own dictionary carries -- each with an id (c1, c2, ...); "*" marks a meaning
already in our dictionary. Choose the ONE meaning this list means: the sense
in which the word is typical of this domain, in the part of speech the
domain uses it in most. That is often the everyday sense (a medical list's
"pain" is ordinary pain) and sometimes a specialist one (a business list's
"statement" is a financial statement; a medical list's "tender" means
painful when touched; a TOEIC list's "reservation" is a booking). Where two
candidates say the same thing, choose the one marked "*".

If none of them is the meaning this list means, answer "none" with that
meaning: "pos" (n, v, adj, adv, prep, conj, or phr for a multi-word
expression) and "def", one definition in WordNet's own style -- short, lower case, without
the headword, no final full stop.
If the headword is not something to teach on its own -- a person's or a
place's name, or a fragment that is never used as a word -- answer "skip"
with "why".

{items}

Reply with JSON only:
{{"choices": {{"w1": "c3", "w2": {{"choice": "none", "pos": "n", "def": "..."}},
  "w3": {{"choice": "skip", "why": "name"}}}}}}
Answer every headword."""


def render_item(word_id: str, lemma: str, candidates: list[Candidate]) -> str:
    lines = [f"{word_id}  {lemma}"]
    if not candidates:
        lines.append("  (no meanings on file -- answer none or skip)")
    for cand in candidates:
        mark = " *" if cand.sense_id else ""
        lines.append(f"  {cand.cid} ({cand.pos}) {cand.definition}{mark}")
    return "\n".join(lines)


@dataclass
class Decision:
    """What the chooser answered for one (list, lemma), in a form that means
    the same thing in any copy of the database."""

    type: str  # "oewn" | "sense" | "model" | "skip"
    pos: str = ""
    synset: str | None = None
    oewn_rank: int | None = None
    definition: str = ""
    sense_id: uuid.UUID | None = None
    why: str = ""

    def to_json(self) -> dict:
        out = {"type": self.type, "pos": self.pos, "definition": self.definition}
        if self.synset:
            out["synset"] = self.synset
            out["oewn_rank"] = self.oewn_rank
        if self.sense_id:
            out["sense_id"] = str(self.sense_id)
        if self.why:
            out["why"] = self.why
        return out

    @classmethod
    def from_json(cls, data: dict) -> Decision:
        return cls(
            type=data["type"], pos=data.get("pos", ""), synset=data.get("synset"),
            oewn_rank=data.get("oewn_rank"), definition=data.get("definition", ""),
            sense_id=uuid.UUID(data["sense_id"]) if data.get("sense_id") else None,
            why=data.get("why", ""),
        )


def parse_choice(value: object, candidates: list[Candidate]) -> Decision | None:
    """One headword's answer, or None when it is not a usable one. A chosen
    OEWN synset is recorded AS the synset (even when we hold it) so the
    decision survives a database where the sense id differs."""
    if isinstance(value, str):
        value = {"choice": value}
    if not isinstance(value, dict):
        return None
    choice = str(value.get("choice") or "").strip().lower()
    by_id = {c.cid: c for c in candidates}
    if choice in by_id:
        cand = by_id[choice]
        if cand.synset and cand.oewn_rank is not None:
            return Decision(type="oewn", pos=cand.pos, synset=cand.synset,
                            oewn_rank=cand.oewn_rank, definition=cand.definition,
                            sense_id=cand.sense_id)
        if cand.sense_id:
            return Decision(type="sense", pos=cand.pos, definition=cand.definition,
                            sense_id=cand.sense_id, synset=cand.synset)
        return None
    if choice == "none":
        pos = str(value.get("pos") or "").strip().lower()
        definition = " ".join(str(value.get("def") or "").split()).rstrip(".")
        if pos not in CHOICE_POS or not definition:
            return None
        return Decision(type="model", pos=pos, definition=definition[: le.DEF_MAX])
    if choice == "skip":
        return Decision(type="skip", why=str(value.get("why") or "")[:60])
    return None


async def ask_choices(gemini: le.Gemini, model: str, list_key: str,
                      items: list[tuple[str, list[Candidate]]]) -> dict[str, Decision]:
    """lemma -> Decision for every item the model answered usably. Items
    the reply skipped or garbled are asked once more on their own request;
    still nothing is no decision (the entry stays unresolved), never a
    guess."""
    out: dict[str, Decision] = {}

    async def ask(batch: list[tuple[str, list[Candidate]]]) -> None:
        keyed = {f"w{i}": item for i, item in enumerate(batch, 1)}
        text = "\n\n".join(render_item(w, lemma, cands) for w, (lemma, cands) in keyed.items())
        reply = await gemini.ask(
            model, DOMAIN_PROMPT.format(domain=LIST_DOMAINS[list_key], items=text),
            step=f"choose-{list_key}", max_tokens=3000 + 100 * len(batch),
        )
        choices = reply.get("choices") if reply and isinstance(reply.get("choices"), dict) else {}
        for word_id, (lemma, cands) in keyed.items():
            decision = parse_choice(choices.get(word_id), cands)
            if decision is not None:
                out[lemma] = decision

    for batch in le._chunks(items, CHOICE_BATCH):
        await ask(batch)
        missing = [item for item in batch if item[0] not in out]
        if missing:
            await ask(missing)
    return out


# --- Core: the decision -------------------------------------------------------

#: How a Core decision was reached -- written as the ``model`` of its log
#: line (a real model name when the model picked the pos).
CORE_SEMCOR = "semcor-top"
CORE_TIE = "tie-order"
CORE_FALLBACK = "rank1-fallback"


def _flagged_in_pos(view: LexiconView, lemma: str, pos: str) -> bool:
    """The lemma's lexeme in ``pos`` is a proper noun or function word --
    `(lemma, pos)` is unique, so a word sense cannot be filed beside it."""
    return any(lx.pos == pos and lx.flagged for lx in view.by_lemma.get(lemma, []))


def _blocked(view: LexiconView, lemma: str, pos: str) -> bool:
    """A new sense in ``pos`` would have to go on a flagged lexeme (no
    unflagged one :func:`_find_lexeme` could use instead)."""
    return _find_lexeme(view, lemma, pos) is None and _flagged_in_pos(view, lemma, pos)


def oewn_decision(lemma: str, pos: str, entry: dict, view: LexiconView) -> Decision:
    lexeme = _find_lexeme(view, lemma, pos)
    held = None
    if lexeme is not None:
        held = next((s.id for s in view.senses_of.get(lexeme.id, [])
                     if s.oewn_synset_id == entry["synset"]), None)
    return Decision(type="oewn", pos=pos, synset=entry["synset"], oewn_rank=entry["rank"],
                    definition=entry["definition"], sense_id=held)


def rank1_decision(view: LexiconView, by_pos: dict[str, dict[str, int]],
                   lemma: str) -> Decision | None:
    sense = global_rank1(view, by_pos, lemma)
    if sense is None:
        return None
    return Decision(type="sense", pos=view.lexemes[sense.lexeme_id].pos,
                    definition=sense.definition_en, synset=sense.oewn_synset_id,
                    sense_id=sense.id)


def core_decision(lemma: str, oewn: dict[tuple[str, str], list[dict]],
                  index: dict[str, list[str]], view: LexiconView,
                  by_pos: dict[str, dict[str, int]],
                  ) -> tuple[Decision | None, str, list[Candidate]]:
    """Core's sense for ``lemma``: ``(decision, how, [])`` when it is
    settled without a model, ``(None, "", candidates)`` when SemCor cannot
    choose between parts of speech and the model must pick among
    ``candidates`` (each pos's top sense), ``(None, how, [])`` when nothing
    can be chosen at all."""
    top = le.top_sense_any_pos(oewn, index, lemma)
    if top is None:
        return rank1_decision(view, by_pos, lemma), CORE_FALLBACK, []
    pos, sense, decided = top
    if decided:
        if _blocked(view, lemma, pos):
            return rank1_decision(view, by_pos, lemma), CORE_FALLBACK, []
        return oewn_decision(lemma, pos, sense, view), CORE_SEMCOR, []
    options = [(p, oewn[(lemma, p)][0]) for p in sorted(
        index.get(lemma, []),
        key=lambda p: le.POS_PRIORITY.index(p) if p in le.POS_PRIORITY else 99)
        if not _blocked(view, lemma, p)]
    if not options:
        return rank1_decision(view, by_pos, lemma), CORE_FALLBACK, []
    if len(options) == 1:
        return oewn_decision(lemma, *options[0], view), CORE_SEMCOR, []
    candidates = []
    for i, (p, entry) in enumerate(options, 1):
        held = oewn_decision(lemma, p, entry, view).sense_id
        candidates.append(Candidate(cid=f"c{i}", pos=p, definition=entry["definition"],
                                    synset=entry["synset"], oewn_rank=entry["rank"],
                                    sense_id=held))
    return None, "", candidates


def core_pick(candidates: list[Candidate], answer: Decision | None,
              lemma: str, view: LexiconView) -> tuple[Decision, bool]:
    """The model's pick among each pos's top sense when it named one of
    them; otherwise the first in `lexicon_enrich.POS_PRIORITY` order (the
    tie order `top_sense_any_pos` itself falls back to). Returns the
    decision and whether the model's answer was used."""
    if answer is not None and answer.type == "oewn" and any(
            c.synset == answer.synset for c in candidates):
        return answer, True
    first = candidates[0]
    return oewn_decision(lemma, first.pos, {"synset": first.synset, "rank": first.oewn_rank,
                                            "definition": first.definition}, view), False


#: Suffix on the model name in the log when Core's answer came from the
#: second, full menu (every OEWN sense plus ours, or a model definition).
CORE_ALL_SENSES = ":all-senses"


def core_full_answer_usable(answer: Decision | None, lemma: str, view: LexiconView) -> bool:
    """Whether Core can take the model's answer from the FULL menu (asked
    when it declined each pos's top sense): a sense we hold on an unflagged
    lexeme, or an OEWN synset / model definition in a part of speech that is
    not a name's or a function word's. A skip is not usable -- every Core
    lemma is a word to teach."""
    if answer is None or answer.type == "skip":
        return False
    if answer.type == "sense":
        sense = view.senses.get(answer.sense_id) if answer.sense_id else None
        return sense is not None and not view.lexemes[sense.lexeme_id].flagged
    return not _blocked(view, lemma, answer.pos)


# --- The decisions log --------------------------------------------------------


def new_sense_key(lemma: str, decision: Decision) -> str:
    if decision.type == "oewn":
        return f"{lemma}|{decision.pos}|oewn:{decision.synset}"
    return f"{lemma}|{decision.pos}|model:{normalise_meaning(decision.definition)}"


class DecisionLog:
    """Append-only JSONL of every model answer this build paid for."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.choices: dict[tuple[str, str], Decision] = {}
        #: (list, lemma) -> who decided: a model name, or a Core rule
        #: (`CORE_SEMCOR`, `CORE_TIE`, `CORE_FALLBACK`).
        self.deciders: dict[tuple[str, str], str] = {}
        self.senses: dict[str, dict] = {}
        if path is not None and path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("kind") == "choice":
                    self.choices[(record["list"], record["lemma"])] = Decision.from_json(
                        record["decision"])
                    self.deciders[(record["list"], record["lemma"])] = record.get("model", "")
                elif record.get("kind") == "sense":
                    self.senses[record["key"]] = record

    def _append(self, record: dict) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def put_choice(self, list_key: str, lemma: str, decision: Decision, model: str) -> None:
        self.choices[(list_key, lemma)] = decision
        self.deciders[(list_key, lemma)] = model
        self._append({"kind": "choice", "list": list_key, "lemma": lemma, "model": model,
                      "decision": decision.to_json(),
                      "at": datetime.now(timezone.utc).isoformat()})

    def put_sense(self, key: str, payload: dict) -> None:
        record = {"kind": "sense", "key": key, **payload,
                  "at": datetime.now(timezone.utc).isoformat()}
        self.senses[key] = record
        self._append(record)


# --- Writing ------------------------------------------------------------------


@dataclass
class BuildReport:
    started: float = field(default_factory=time.monotonic)
    source_size: dict[str, int] = field(default_factory=dict)
    excluded: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    excluded_lemmas: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    unresolved: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    new_senses: Counter = field(default_factory=Counter)
    new_lexemes: int = 0
    replayed_choices: int = 0
    replayed_senses: int = 0
    asked_choices: int = 0
    failures: list[str] = field(default_factory=list)
    #: lemma -> its global rank-1 sense (the old Core rule: rank 1 of the
    #: primary lexeme) BEFORE this build wrote anything -- what "a sense
    #: other than rank 1" and "a Core sense that changed" are measured against.
    global_before: dict[str, uuid.UUID | None] = field(default_factory=dict)
    #: How each Core entry was decided this run (replayed ones included).
    core_how: Counter = field(default_factory=Counter)
    #: New senses by the list whose entry wrote them first.
    new_by_list: Counter = field(default_factory=Counter)

    def exclude(self, list_key: str, lemma: str, reason: str) -> None:
        self.excluded[list_key][reason] += 1
        self.excluded_lemmas[list_key].append(f"{lemma} ({reason})")


async def sync_entries(session, word_list: WordList, keep: dict[str, SourceEntry]) -> None:
    """Make the list's entries exactly ``keep``'s lemmas: insert the missing
    ones unresolved (rank fixed later by :func:`rerank`), delete the ones no
    longer included. A resolved entry is never touched here."""
    if keep:
        rows = [{"id": uuid.uuid4(), "list_id": word_list.id, "lemma": lemma,
                 "rank": index, "rank_source": "list" if src.list_rank is not None else "cefr"}
                for index, (lemma, src) in enumerate(keep.items(), 1)]
        for start in range(0, len(rows), 1000):
            await session.execute(
                pg_insert(WordListEntry).values(rows[start:start + 1000])
                .on_conflict_do_nothing(index_elements=["list_id", "lemma"])
            )
    stale = sa_delete(WordListEntry).where(WordListEntry.list_id == word_list.id)
    if keep:
        stale = stale.where(WordListEntry.lemma.not_in(list(keep)))
    await session.execute(stale)


async def _set_entry(session, list_id: uuid.UUID, lemma: str,
                     lexeme_id: uuid.UUID | None, sense_id: uuid.UUID | None) -> None:
    await session.execute(
        sa_update(WordListEntry)
        .where(WordListEntry.list_id == list_id, WordListEntry.lemma == lemma)
        .values(lexeme_id=lexeme_id, sense_id=sense_id)
    )


async def rerank(session, word_list: WordList, sources: dict[str, SourceEntry],
                 view: LexiconView, by_pos: dict[str, dict[str, int]],
                 sfi31k: dict[str, float] | None = None) -> Counter:
    """Rank every entry of the list (:func:`order_entries`) and write it.
    Returns rank_source counts."""
    entries = (await session.exec(
        select(WordListEntry).where(WordListEntry.list_id == word_list.id)
    )).all()
    ngsl = frequency_lists().ngsl_rank
    sfi31k = sfi31k or {}
    items = []
    for entry in entries:
        sense = view.senses.get(entry.sense_id) if entry.sense_id else None
        lexeme = view.lexemes.get(entry.lexeme_id) if entry.lexeme_id else None
        src = sources.get(entry.lemma)
        items.append(RankInput(
            lemma=entry.lemma, list_rank=src.list_rank if src else None,
            sfi31k=sfi31k.get(entry.lemma),
            semcor=semcor_total(by_pos, entry.lemma), ngsl_rank=ngsl.get(entry.lemma),
            cefr=sense.cefr if sense else None,
            material_rows=lexeme.material_rows if lexeme else 0,
        ))
    ordered = order_entries(items)
    ids = {e.lemma: e.id for e in entries}
    updates = [{"id": ids[lemma], "rank": rank, "rank_source": source}
               for lemma, rank, source in ordered]
    if updates:
        await session.execute(sa_update(WordListEntry), updates)
    return Counter(source for _, _, source in ordered)


@dataclass
class NewSense:
    """A sense the domain chooser asked for that the lexicon does not hold
    yet -- enriched before it is written."""

    key: str
    lemma: str
    pos: str
    decision: Decision
    lexeme_id: uuid.UUID | None
    frequency_band: str | None
    sense: le.Sense


def _find_lexeme(view: LexiconView, lemma: str, pos: str) -> LexemeInfo | None:
    lexemes = [lx for lx in view.by_lemma.get(lemma, []) if not lx.flagged]
    exact = next((lx for lx in lexemes if lx.pos == pos), None)
    if exact is not None:
        return exact
    if lexeme_is_phrase(lemma, pos) and len(lexemes) == 1 and lexemes[0].is_phrase:
        # A phrase is filed under its head's pos as often as under `phr`
        # (`lexicon_enrich.pos_mismatch`): one phrase lexeme is THE lexeme.
        return lexemes[0]
    return None


def _held_sense(view: LexiconView, lemma: str, decision: Decision) -> SenseInfo | None:
    """The sense the lexicon already has for ``decision``, if any."""
    if decision.type == "sense":
        return view.senses.get(decision.sense_id) if decision.sense_id else None
    lexeme = _find_lexeme(view, lemma, decision.pos)
    if lexeme is None:
        return None
    for sense in view.senses_of.get(lexeme.id, []):
        if decision.type == "oewn" and sense.oewn_synset_id == decision.synset:
            return sense
        if decision.type == "model" and normalise_meaning(sense.definition_en) \
                == normalise_meaning(decision.definition):
            return sense
    return None


async def enrich_new_senses(gemini: le.Gemini | None, pending: list[NewSense],
                            log: DecisionLog, report: BuildReport) -> None:
    """CEFR, two translators and the double judge for new senses -- the
    `lexicon_enrich` steps themselves, run over one-sense `LexemeWork`s -- or
    the same answers replayed from the log."""
    todo: list[NewSense] = []
    for item in pending:
        cached = log.senses.get(item.key)
        if cached is not None:
            item.sense.cefr = cached.get("cefr")
            item.sense.meaning_uz = cached.get("meaning_uz", "")
            item.sense.meaning_uz_alt = cached.get("meaning_uz_alt", "")
            item.sense.judge = cached.get("judge")
            report.replayed_senses += 1
        else:
            todo.append(item)
    if not todo:
        return
    if gemini is None:  # the caller drops these before asking
        raise RuntimeError("new senses need enrichment and no model is configured")
    works = [le.LexemeWork(
        id=item.lexeme_id or uuid.uuid4(), lemma=item.lemma, pos=item.pos,
        is_phrase=lexeme_is_phrase(item.lemma, item.pos),
        frequency_band=item.frequency_band, oewn=[], senses=[], rows=[], plan=[item.sense],
    ) for item in todo]
    await le.step_cefr(gemini, works)
    await le.step_translate(gemini, works)
    for item, work in zip(todo, works):
        if work.note.strip():
            report.failures.append(f"{item.key}: {work.note.strip()}")
        log.put_sense(item.key, {
            "definition_en": item.sense.definition_en, "cefr": item.sense.cefr,
            "meaning_uz": item.sense.meaning_uz, "meaning_uz_alt": item.sense.meaning_uz_alt,
            "judge": item.sense.judge,
        })


async def write_new_sense(session, view: LexiconView, item: NewSense,
                          report: BuildReport) -> SenseInfo:
    """Insert ``item`` (and its lexeme, when the lemma has none in that
    pos), or return the sense another unit wrote meanwhile."""
    held = _held_sense(view, item.lemma, item.decision)
    if held is not None:
        return held
    lists = frequency_lists()
    lexeme_info = _find_lexeme(view, item.lemma, item.pos)
    created_lexeme = lexeme_info is None
    if created_lexeme:
        lexeme = Lexeme(
            lemma=item.lemma, pos=item.pos, is_phrase=lexeme_is_phrase(item.lemma, item.pos),
            frequency_band=lists.band(item.lemma), frequency_source=lists.source(item.lemma),
            domain_tags=lists.domain_tags(item.lemma),
            is_function_word=is_excluded_word(item.lemma),
            # Its one sense is enriched below; left null, the worker would
            # "finish" it by deleting that sense (not OEWN's top one).
            enriched_at=datetime.now(timezone.utc),
        )
        session.add(lexeme)
        await session.flush()
        lexeme_info = LexemeInfo(
            id=lexeme.id, lemma=lexeme.lemma, pos=lexeme.pos, is_phrase=lexeme.is_phrase,
            is_proper_noun=False, is_function_word=lexeme.is_function_word,
            frequency_band=lexeme.frequency_band,
        )
        view.add_lexeme(lexeme_info)
        report.new_lexemes += 1
    existing = view.senses_of.get(lexeme_info.id, [])
    rank = max((s.sense_rank for s in existing), default=0) + 1
    planned = item.sense
    reasons = le.review_reasons(
        cefr=planned.cefr, frequency_band=lexeme_info.frequency_band, material_levels=[],
        carried=[], judge=planned.judge, rank=rank,
    )
    sense = LexemeSense(
        lexeme_id=lexeme_info.id, sense_rank=rank,
        definition_en=planned.definition_en[: le.DEF_MAX],
        meaning_uz=planned.meaning_uz[: le.UZ_MAX],
        meaning_uz_alt=planned.meaning_uz_alt[: le.UZ_MAX],
        cefr=planned.cefr, oewn_synset_id=planned.oewn_synset_id,
        oewn_rank=planned.oewn_rank, source_id=planned.source_id, licence=planned.licence,
        provisional=False, needs_review=bool(reasons), review_reasons=reasons,
    )
    session.add(sense)
    await session.flush()
    if created_lexeme or rank == 1:
        await session.execute(
            sa_update(Lexeme).where(Lexeme.id == lexeme_info.id).values(cefr=planned.cefr))
    info = SenseInfo(id=sense.id, lexeme_id=lexeme_info.id, sense_rank=rank,
                     definition_en=sense.definition_en, oewn_synset_id=sense.oewn_synset_id,
                     cefr=sense.cefr, source_id=sense.source_id)
    view.add_sense(info)
    report.new_senses[sense.source_id] += 1
    return info


def _new_sense_for(lemma: str, decision: Decision, view: LexiconView) -> NewSense:
    lexeme = _find_lexeme(view, lemma, decision.pos)
    band = lexeme.frequency_band if lexeme else frequency_lists().band(lemma)
    if decision.type == "oewn":
        sense = le.Sense(id=None, definition_en=decision.definition[: le.DEF_MAX],
                         oewn_synset_id=decision.synset, oewn_rank=decision.oewn_rank,
                         source_id="oewn", licence=le.OEWN_LICENCE, translate=True)
    else:
        sense = le.Sense(id=None, definition_en=decision.definition[: le.DEF_MAX],
                         source_id="model", licence=le.MODEL_LICENCE, translate=True)
    return NewSense(key=new_sense_key(lemma, decision), lemma=lemma, pos=decision.pos,
                    decision=decision, lexeme_id=lexeme.id if lexeme else None,
                    frequency_band=band, sense=sense)


# --- The build ----------------------------------------------------------------


@dataclass
class BuildOptions:
    lists: tuple[str, ...] = ALL_LISTS
    model: str = DEFAULT_CHOICE_MODEL
    #: (list, lemma) pairs per unit: asked, enriched and committed together.
    unit: int = 100
    concurrency: int = 6
    #: Lists whose resolved entries are chosen again from scratch.
    reselect: tuple[str, ...] = ()
    #: At most this many unresolved domain entries per list (a pilot).
    limit: int | None = None
    #: Never call a model; only what the log can replay is resolved.
    no_model: bool = False


async def build(session_factory, gemini: le.Gemini | None, options: BuildOptions,
                log: DecisionLog, oewn: dict[tuple[str, str], list[dict]] | None = None,
                *, sources: dict[str, list[SourceEntry]] | None = None,
                word_lists: dict[str, WordList] | None = None,
                sfi31k: dict[str, float] | None = None,
                ) -> tuple[BuildReport, dict[str, Counter]]:
    """Populate every list in ``options.lists``. Returns the report and the
    rank_source counts per list. ``sources``/``word_lists``/``sfi31k``
    replace the vendored files and the five seeded rows -- for tests, which
    must never rewrite a real list's entries."""
    report = BuildReport()
    oewn = oewn if oewn is not None else le.load_oewn()
    index = le.pos_index(oewn)
    by_pos = semcor_by_pos(oewn)
    sfi31k = sfi31k if sfi31k is not None else read_sfi31k()
    sources = {key: {e.lemma: e for e in (sources[key] if sources else read_list(key))}
               for key in options.lists}
    for key, entries in sources.items():
        report.source_size[key] = len(entries)

    async with session_factory() as session:
        lists = word_lists if word_lists is not None else await seed_word_lists(session)
        view = await load_view(session)
        for key in options.lists:
            for lemma in sources[key]:
                if lemma not in report.global_before:
                    before = global_rank1(view, by_pos, lemma)
                    report.global_before[lemma] = before.id if before else None
        for key in options.lists:
            keep: dict[str, SourceEntry] = {}
            for lemma, src in sources[key].items():
                reason = exclusion_reason(lemma, view.by_lemma.get(lemma, []))
                cached = log.choices.get((key, lemma))
                if reason is None and cached is not None and cached.type == "skip" \
                        and key not in options.reselect:
                    # The chooser already said this is a name or a fragment.
                    reason = f"skip:{cached.why or 'model'}"
                if reason:
                    report.exclude(key, lemma, reason)
                else:
                    keep[lemma] = src
            await sync_entries(session, lists[key], keep)
            sources[key] = keep
            if key in options.reselect:
                await session.execute(
                    sa_update(WordListEntry).where(WordListEntry.list_id == lists[key].id)
                    .values(lexeme_id=None, sense_id=None))
        await session.commit()

        unresolved: dict[str, list[str]] = {}
        for key in options.lists:
            rows = (await session.exec(
                select(WordListEntry.lemma).where(
                    WordListEntry.list_id == lists[key].id, WordListEntry.sense_id.is_(None))
            )).all()
            unresolved[key] = sorted(rows, key=lambda lemma: (
                sources[key][lemma].list_rank or 0, lemma))

    # One decision per (list, lemma), in units -- Core's mostly without a
    # model (`core_decision`), the domain lists' by one.
    pairs: list[tuple[str, str]] = []
    for key in options.lists:
        todo = unresolved[key][: options.limit] if options.limit else unresolved[key]
        pairs += [(key, lemma) for lemma in todo]
    # Same lemma across lists lands in one unit, so a sense two lists both
    # want is enriched once.
    pairs.sort(key=lambda p: (p[1], p[0]))
    units = [pairs[i:i + options.unit] for i in range(0, len(pairs), options.unit)]
    model_off = options.no_model or gemini is None
    write_lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(options.concurrency)
    done = 0

    async def decide(unit: list[tuple[str, str]]) -> dict[tuple[str, str], Decision]:
        """The unit's decisions: replayed from the log where it has one
        (unless the list is being reselected), asked otherwise."""
        decisions: dict[tuple[str, str], Decision] = {}
        to_ask: dict[str, list[tuple[str, list[Candidate]]]] = defaultdict(list)
        for key, lemma in unit:
            cached = None if key in options.reselect else log.choices.get((key, lemma))
            if cached is not None and (cached.type != "sense" or cached.sense_id in view.senses):
                decisions[(key, lemma)] = cached
                report.replayed_choices += 1
                if key == CORE:
                    report.core_how[log.deciders.get((key, lemma), "")] += 1
            elif key == CORE:
                decision, how, candidates = core_decision(lemma, oewn, index, view, by_pos)
                if decision is not None:
                    decisions[(key, lemma)] = decision
                    log.put_choice(key, lemma, decision, how)
                    report.core_how[how] += 1
                elif candidates:
                    to_ask[key].append((lemma, candidates))
                else:
                    report.unresolved[key].append(lemma)
            else:
                to_ask[key].append(
                    (lemma, build_candidates(lemma, oewn, index.get(lemma, []), view)))
        for key, items in to_ask.items():
            if model_off:
                report.unresolved[key] += [lemma for lemma, _ in items]
                continue
            answers = await ask_choices(gemini, options.model, key, items)
            report.asked_choices += len(items)

            def record(key: str, lemma: str, decision: Decision, how: str) -> None:
                decisions[(key, lemma)] = decision
                log.put_choice(key, lemma, decision, how)
                report.core_how[how] += 1

            if key == CORE:
                # The model declined each pos's top sense (`till` the
                # conjunction is none of them): ask once more over every
                # OEWN sense plus ours, a definition of its own allowed --
                # the domain lists' menu. Never unresolved: the tie order is
                # the last resort, and says so in the log.
                retry: list[tuple[str, Decision]] = []
                for lemma, candidates in items:
                    decision, used = core_pick(candidates, answers.get(lemma), lemma, view)
                    if used:
                        record(key, lemma, decision, options.model)
                    else:
                        retry.append((lemma, decision))
                if retry:
                    full = [(lemma, build_candidates(lemma, oewn, index.get(lemma, []), view))
                            for lemma, _ in retry]
                    second = await ask_choices(gemini, options.model, key, full)
                    report.asked_choices += len(full)
                    for lemma, tie in retry:
                        answer = second.get(lemma)
                        if core_full_answer_usable(answer, lemma, view):
                            record(key, lemma, answer, options.model + CORE_ALL_SENSES)
                        else:
                            record(key, lemma, tie, CORE_TIE)
                continue
            for lemma, candidates in items:
                if lemma in answers:
                    decisions[(key, lemma)] = answers[lemma]
                    log.put_choice(key, lemma, answers[lemma], options.model)
                else:
                    report.unresolved[key].append(lemma)
                    report.failures.append(f"choose {key}/{lemma}: no usable answer")
        return decisions

    async def run_unit(unit: list[tuple[str, str]]) -> None:
        nonlocal done
        async with semaphore:
            decisions = await decide(unit)
            pending: dict[str, NewSense] = {}
            for (key, lemma), decision in list(decisions.items()):
                if decision.type not in ("oewn", "model") or _held_sense(view, lemma, decision) \
                        or _blocked(view, lemma, decision.pos):
                    continue
                item = _new_sense_for(lemma, decision, view)
                if model_off and item.key not in log.senses:
                    # Nothing to replay its grade/translation from.
                    report.unresolved[key].append(lemma)
                    del decisions[(key, lemma)]
                    continue
                pending.setdefault(item.key, item)
            await enrich_new_senses(gemini, list(pending.values()), log, report)

            async with write_lock:
                touched: set[uuid.UUID] = set()
                unit_view = UnitView(view)
                async with session_factory() as session:
                    for (key, lemma), decision in sorted(decisions.items()):
                        drop = None
                        if decision.type == "skip":
                            drop = f"skip:{decision.why or 'model'}"
                        else:
                            held = _held_sense(unit_view, lemma, decision)
                            if held is None and decision.type != "sense" \
                                    and _blocked(unit_view, lemma, decision.pos):
                                # `(lemma, pos)` is a name or function word;
                                # a second lexeme there would break the
                                # unique key, and the word is not taught.
                                flagged = next(lx for lx in unit_view.by_lemma.get(lemma, [])
                                               if lx.pos == decision.pos)
                                drop = ("proper_noun" if flagged.is_proper_noun
                                        else "function_word")
                            elif held is None:
                                item = pending.get(new_sense_key(lemma, decision))
                                if item is None:
                                    report.unresolved[key].append(lemma)
                                    continue
                                created = sum(report.new_senses.values())
                                held = await write_new_sense(session, unit_view, item, report)
                                if sum(report.new_senses.values()) > created:
                                    report.new_by_list[key] += 1
                                touched.add(held.lexeme_id)
                            if held is not None:
                                lexeme = unit_view.lexemes[held.lexeme_id]
                                if lexeme.flagged:
                                    drop = ("proper_noun" if lexeme.is_proper_noun
                                            else "function_word")
                        if drop:
                            report.exclude(key, lemma, drop)
                            await session.execute(sa_delete(WordListEntry).where(
                                WordListEntry.list_id == lists[key].id,
                                WordListEntry.lemma == lemma))
                            continue
                        await _set_entry(session, lists[key].id, lemma, held.lexeme_id, held.id)
                    await session.commit()
                    unit_view.merge_into()
                    if touched:
                        await lexicon_hints.recompute_for_lexemes(session, sorted(touched))
            done += len(unit)
            logger.info("word lists: %d/%d entries", done, len(pairs))

    results = await asyncio.gather(*(run_unit(u) for u in units), return_exceptions=True)
    for unit, result in zip(units, results):
        if isinstance(result, BaseException):
            logger.error("unit failed", exc_info=result)
            report.failures.append(f"unit of {len(unit)} from {unit[0]}: {result!r}")
            for key, lemma in unit:
                report.unresolved[key].append(lemma)

    rank_sources: dict[str, Counter] = {}
    async with session_factory() as session:
        view = await load_view(session)
        for key in options.lists:
            keep = {lemma: src for lemma, src in sources[key].items()}
            rank_sources[key] = await rerank(session, lists[key], keep, view, by_pos, sfi31k)
        await session.commit()
    for key in report.unresolved:
        report.unresolved[key] = sorted(set(report.unresolved[key]))
    return report, rank_sources


# --- What the build produced --------------------------------------------------


async def summarise(session_factory, oewn: dict[tuple[str, str], list[dict]] | None = None,
                    lists: tuple[str, ...] = ALL_LISTS, examples: int = 15,
                    named: tuple[str, ...] = ("security", "bond", "share", "interest", "culture",
                                              "discharge", "theatre"),
                    global_before: dict[str, uuid.UUID | None] | None = None,
                    core_named: tuple[str, ...] = ("good", "school", "interest", "mean")) -> dict:
    """Numbers for the report: entries per list (resolved/unresolved),
    rank_source counts, and how many domain entries mean something other
    than the lemma's global rank-1 sense -- with examples. ``global_before``
    (`BuildReport.global_before`) is that rank-1 as it was before the build;
    without it the CURRENT lexicon's is used, where a sense the build put
    on a brand-new lexeme reads as that lemma's rank 1."""
    oewn = oewn if oewn is not None else le.load_oewn()
    by_pos = semcor_by_pos(oewn)
    async with session_factory() as session:
        word_lists = {wl.key: wl for wl in (await session.exec(select(WordList))).all()}
        view = await load_view(session)
        out: dict = {"lists": {}, "non_rank1_examples": [], "core_changed_examples": []}
        candidates = []
        core_changed = []

        def describe(sense_id: uuid.UUID | None) -> str:
            sense = view.senses.get(sense_id) if sense_id else None
            if sense is None:
                return "-"
            return f"({view.lexemes[sense.lexeme_id].pos}) {sense.definition_en}"
        for key in lists:
            wl = word_lists.get(key)
            if wl is None:
                continue
            entries = (await session.exec(
                select(WordListEntry).where(WordListEntry.list_id == wl.id)
                .order_by(WordListEntry.rank))).all()
            resolved = [e for e in entries if e.sense_id]
            stat = {
                "entries": len(entries), "resolved": len(resolved),
                "rank_source": dict(Counter(e.rank_source for e in entries)),
                "cefr": dict(Counter((view.senses[e.sense_id].cefr or "unrated")
                                     for e in resolved)),
                "first": [e.lemma for e in entries[:8]],
                "first20": [{"rank": e.rank, "lemma": e.lemma, "rank_source": e.rank_source,
                             "sense": describe(e.sense_id)} for e in entries[:20]],
            }
            if key == CORE and global_before is not None:
                changed = [e for e in resolved if e.lemma in global_before
                           and global_before[e.lemma] != e.sense_id]
                stat["changed_vs_old_rule"] = len(changed)
                core_changed = [{"rank": e.rank, "lemma": e.lemma,
                                 "now": describe(e.sense_id),
                                 "old_rule": describe(global_before[e.lemma])}
                                for e in changed]
            if key != CORE:
                differs = []
                for e in resolved:
                    if global_before is not None and e.lemma in global_before:
                        before = global_before[e.lemma]
                        g = view.senses.get(before) if before else None
                    else:
                        g = global_rank1(view, by_pos, e.lemma)
                    if g is None or g.id != e.sense_id:
                        differs.append((e, g))
                stat["non_rank1"] = len(differs)
                stat["non_rank1_new_lexeme"] = sum(1 for _, g in differs if g is None)
                for e, g in differs:
                    s = view.senses[e.sense_id]
                    candidates.append({
                        "list": key, "lemma": e.lemma, "rank": e.rank,
                        "chosen": f"({view.lexemes[s.lexeme_id].pos}) {s.definition_en}"
                                  f" [{s.source_id}, {s.cefr or 'unrated'}]",
                        "global_rank1": (f"({view.lexemes[g.lexeme_id].pos}) {g.definition_en}"
                                         if g else "-"),
                    })
            out["lists"][key] = stat
    picked = [c for c in candidates if c["lemma"] in named]
    rest = [c for c in candidates if c["lemma"] not in named]
    step = max(1, len(rest) // max(1, examples - len(picked))) if rest else 1
    picked += rest[::step][: max(0, examples - len(picked))]
    out["non_rank1_examples"] = picked
    first = [c for c in core_changed if c["lemma"] in core_named]
    rest = [c for c in core_changed if c["lemma"] not in core_named]
    step = max(1, len(rest) // max(1, examples - len(first))) if rest else 1
    out["core_changed_examples"] = first + rest[::step][: max(0, examples - len(first))]
    return out

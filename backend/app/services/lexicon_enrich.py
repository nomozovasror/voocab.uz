"""Lexicon P2: turn P1's provisional senses into a real dictionary entry.

P1 (`scripts/build_lexicon.py`) clustered every material row of a word by the
literal wording of its "usual meaning" and made one provisional
`LexemeSense` per wording. That gives `subject` fourteen senses that are
mostly one sense in fourteen phrasings, and it trusts `meaning_core_en`,
which the reading pipeline often got wrong: every `figure` row, whether the
passage meant a statistic, a statue or "a major figure in American art",
carries the usual meaning "A number or a digit." This module is the model
work that fixes that, one lexeme at a time.

## What happens to one lexeme

1. **Match.** Every distinct USE of the word in a material (the example
   sentence, the contextual gloss, the usual gloss, both Uzbek versions) is
   shown to a model beside OEWN's senses for that (lemma, pos). The model
   labels each use with the OEWN sense it is (``S<rank>``) or a fresh
   ``X<k>`` where OEWN has nothing that fits (uses sharing one meaning share
   the ``X``). The SENTENCE is the evidence; the glosses are hints and are
   said to be unreliable. Matching is per use, not per provisional sense,
   because a P1 cluster can hold rows of two different meanings (every
   `figure` row sits in "A number or a digit").
2. **Merge.** Rows with the same label become one sense (:func:`plan_senses`):
   an existing sense is reused where it holds most of those rows, every
   `material_vocabulary.sense_id` is re-pointed, and a provisional sense left
   with no rows is deleted after its pointers are redirected to the sense
   that absorbed its rows. Nothing is deleted that holds OEWN data or has no
   rows to hand over -- see the build script's warning about delete-and-
   rebuild.
3. **Uzbek from the material.** For each label the model also picks, from
   the material's own Uzbek strings on those uses, the one that translates
   THAT sense alone -- or none. That is a choice among texts a material
   already wrote (brief §6: material meanings are copied, not retranslated),
   and it is how "Metall prujina yoki buloq" (coil OR spring of water) is
   kept off a sense that is only one of the two. The matcher also names the
   part of speech the headword has in each label's uses, and whether those
   uses define a different word altogether -- the source of ``pos_mismatch``.
4. **OEWN top sense.** OEWN's single most frequent sense is added if not
   already present -- to a lexeme with material rows (beside its material
   senses) and to a list-only lexeme (as its only sense). Deeper OEWN senses
   appear only where a material uses them; an unused one left by an earlier
   run is deleted.
5. **Gaps.** A lexeme with no sense at all and no OEWN entry gets one
   model-written definition in OEWN's own style (source ``model``).
6. **CEFR.** Every sense of the lexeme is graded afresh from word + pos +
   definition (D3) -- no material levels are consulted.
7. **Uzbek style.** A copied Uzbek string that reads like a sentence or an
   explanation ("Bahor fasli.") is rewritten into dictionary style
   ("bahor") by a cheap model, told not to change the meaning; a second
   model checks the rewrite means the same, and a rewrite it does not pass
   is dropped. Mechanical tidying that cannot change a meaning (final full
   stop, capital first letter) is applied to every copy without a model.
   The verbatim copy is kept in ``meaning_uz_material`` either way.
8. **Uzbek by two models + judge**, for every sense that did not get a
   material's Uzbek in step 3. ``meaning_uz`` takes the translation the judge
   prefers (the stronger model's on a tie), ``meaning_uz_alt`` the other.
9. **Rank, review reasons, `Lexeme.cefr`** (:func:`rank_senses`,
   :func:`review_reasons`), written in one transaction with
   ``Lexeme.enriched_at`` set last.

## Ranking rule (``sense_rank``)

Senses our materials use come first, most material rows first (ties: OEWN
rank, then definition) -- the corpus is what the learner meets, so its
commonest sense is "the usual meaning" and what `Lexeme.cefr` copies. Then
the remaining OEWN senses in OEWN's own (frequency) order, then any unused
model sense.

## Review reasons (D3/D5)

* ``ngsl_conflict`` -- rank-1 sense only: C1/C2 while the lexeme is
  NGSL-core (top 1 000), or A1/A2 while off-list. A deeper sense of a core
  word legitimately grades C1, so checking every sense was mostly noise.
* ``material_level_gap`` -- the sense's grade is >= 2 bands from the
  majority level of the material rows linked to it, and the grade is B1 or
  above: the seed only ever assigned B1-C1, so an A1/A2 sense ("spring" the
  season) is two bands from B2 by construction, not by error.
* ``pos_mismatch`` -- set by the matcher (step 1), never recomputed here; a
  re-run's matcher answer replaces it.
* ``judge_different`` / ``judge_unsure`` -- the two translations were judged
  not to mean the same thing.
* ``lemma_merge`` -- carried over from P1, never set here.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import random
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from sqlalchemy import update as sa_update
from sqlmodel import select

from app.core.config import settings
from app.models.lexicon import Lexeme, LexemeSense, TranslationReport
from app.models.vocabulary import MaterialVocabulary, SavedWord, SavedWordContext
from app.services.dictionary import GEMINI_CHAT_URL
from app.services.lexicon import WORDLISTS

logger = logging.getLogger("app.services.lexicon_enrich")

CEFR_ORDER: tuple[str, ...] = ("A1", "A2", "B1", "B2", "C1", "C2")

#: Structure work (match, gap definitions, CEFR) and the "stronger"
#: translator. Pinned rather than `gemini-flash-latest`: the alias reports
#: no version, so neither the price nor the behaviour of a run could be
#: stated afterwards.
MODEL_MAIN = "gemini-3.8-flash"
#: The second, independent translator.
MODEL_ALT = "gemini-3.1-flash-lite"
#: The judge: a third model, so neither translator grades its own work.
MODEL_JUDGE = "gemini-3.5-flash-lite"

#: USD per 1M tokens (input, output incl. thinking), Gemini API paid tier,
#: read from ai.google.dev/gemini-api/docs/pricing on 2026-09-27. 3.8 Flash
#: doubles on 2027-01-01 (1.50 / 7.50).
PRICES: dict[str, tuple[float, float]] = {
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.5-flash-lite": (0.30, 2.50),
}

#: `reasoning_effort` each model accepts on the OpenAI-compatible endpoint
#: (measured: 3.8 Flash refuses "minimal", 3.5 Flash-Lite refuses "none").
EFFORT: dict[str, str] = {
    "gemini-3.8-flash": "low",
    "gemini-3.1-flash-lite": "none",
    "gemini-3.5-flash-lite": "minimal",
}

OEWN_LICENCE = "cc-by-4.0"
MODEL_LICENCE = "proprietary"
#: How many of OEWN's senses (in its frequency order) every lexeme gets
#: whether or not a material uses them.
OEWN_TOP = 1
#: At most this many OEWN senses are shown to the matcher -- enough for any
#: sense a passage uses; `take` has 40+ and the tail is archaic.
OEWN_SHOWN = 30
#: Rewrites a sentence-style copied Uzbek into dictionary style, and the
#: (different) model that checks the rewrite kept the meaning.
MODEL_STYLE = "gemini-3.5-flash-lite"
MODEL_STYLE_CHECK = "gemini-3.8-flash"
#: Reasons this module recomputes every run; anything else is carried.
COMPUTED_REASONS = {"ngsl_conflict", "material_level_gap", "judge_different", "judge_unsure"}
JUDGE_REASONS = {"judge_different", "judge_unsure"}
#: Set by the matcher; replaced when it answers, carried when it does not.
MATCH_REASONS = {"pos_mismatch"}
POS_WORDS = {"n", "v", "adj", "adv", "prep", "conj"}
UZ_MAX = 400
DEF_MAX = 400


# --- OEWN sense inventory ------------------------------------------------------

OEWN_PATH = WORDLISTS / "oewn_senses.jsonl.gz"


def load_oewn() -> dict[tuple[str, str], list[dict]]:
    """(lemma, pos) -> senses in OEWN order, for :func:`load_works` and
    :func:`enrich` below. Two entries for one key (`adj` folds WordNet's `a`
    and `s`) are concatenated and re-ranked.

    Moved here from `scripts/enrich_lexicon.py` (which now calls
    ``le.load_oewn()``) so `app.worker`'s lexicon loop -- which needs exactly
    the same dict, on the same cadence P2's CLI run always loaded it fresh --
    can read it without importing the `scripts` package into the running
    app. ``OEWN_PATH`` sits inside `backend/` (`app.services.lexicon.
    WORDLISTS`) rather than `seed/wordlists/`, for the reason that module's
    own docstring gives: only `backend/` reaches into the Docker worker.
    """
    index: dict[tuple[str, str], list[dict]] = defaultdict(list)
    with gzip.open(OEWN_PATH, "rt", encoding="utf-8") as fh:
        for line in fh:
            record = json.loads(line)
            index[(record["lemma"], record["pos"])].extend(record["senses"])
    out = {}
    for key, senses in index.items():
        seen, ranked = set(), []
        for sense in senses:
            if sense["synset"] in seen:
                continue
            seen.add(sense["synset"])
            ranked.append({"synset": sense["synset"], "rank": len(ranked) + 1,
                           "definition": sense["definition"]})
        out[key] = ranked
    return out


# --- Usage / cost -------------------------------------------------------------


@dataclass
class Usage:
    requests: int = 0
    failures: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def cost(self, model: str) -> float:
        price_in, price_out = PRICES.get(model, (0.0, 0.0))
        return (self.input_tokens * price_in + self.output_tokens * price_out) / 1e6


class UsageLog:
    def __init__(self) -> None:
        self.by_model: dict[str, Usage] = defaultdict(Usage)
        self.by_step: dict[str, Usage] = defaultdict(Usage)

    def add(self, model: str, step: str, prompt: int, output: int) -> None:
        for bucket in (self.by_model[model], self.by_step[f"{step}:{model}"]):
            bucket.requests += 1
            bucket.input_tokens += prompt
            bucket.output_tokens += output

    def fail(self, model: str) -> None:
        self.by_model[model].failures += 1

    def total_cost(self) -> float:
        return sum(u.cost(m) for m, u in self.by_model.items())


# --- Gemini client ------------------------------------------------------------

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)
_RETRY_STATUS = {408, 429, 500, 502, 503, 504}


class Gemini:
    """Google's OpenAI-compatible chat endpoint, JSON replies only.

    Model output is untrusted: a reply that is not a JSON object is retried
    once like a transport error and then given up on (``None``); every
    caller treats ``None`` and every missing key as "no answer" and falls
    back to leaving that item as it was.
    """

    def __init__(self, usage: UsageLog, api_key: str | None = None,
                 attempts: int = 5, timeout: float = 180.0) -> None:
        self.usage = usage
        self._key = api_key if api_key is not None else settings.gemini_api_key
        self._attempts = attempts
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def ask(self, model: str, prompt: str, *, step: str,
                  max_tokens: int = 8192, repair_flat: bool = False) -> dict | None:
        if not self._key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
            "reasoning_effort": EFFORT.get(model, "low"),
        }
        parse_failures = 0
        for attempt in range(1, self._attempts + 1):
            try:
                response = await self._client.post(
                    GEMINI_CHAT_URL, json=body,
                    headers={"Authorization": f"Bearer {self._key}"},
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                logger.warning("%s %s transport error: %s", step, model, exc)
                await self._backoff(attempt)
                continue
            if response.status_code in _RETRY_STATUS:
                logger.warning("%s %s HTTP %s", step, model, response.status_code)
                await self._backoff(attempt)
                continue
            if response.status_code >= 400:
                logger.error("%s %s HTTP %s: %s", step, model,
                             response.status_code, response.text[:300])
                self.usage.fail(model)
                return None
            data = response.json()
            usage = data.get("usage") or {}
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            total = int(usage.get("total_tokens") or 0)
            # Thinking tokens are billed as output but not reported in
            # completion_tokens; total - prompt counts both.
            output_tokens = max(total - prompt_tokens, int(usage.get("completion_tokens") or 0))
            self.usage.add(model, step, prompt_tokens, output_tokens)
            content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            parsed = parse_json_object(content)
            if parsed is None and repair_flat:
                parsed = repair_flat_map(content)
            if parsed is not None:
                return parsed
            logger.warning("%s %s unparseable reply: %r", step, model, content[:200])
            parse_failures += 1
            if parse_failures >= 2:
                break
        self.usage.fail(model)
        return None

    @staticmethod
    async def _backoff(attempt: int) -> None:
        await asyncio.sleep(min(60.0, 2.0 ** attempt) + random.random())


def parse_json_object(text: str) -> dict | None:
    text = _FENCE.sub("", text.strip())
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    if isinstance(value, list) and len(value) == 1:
        # Measured: 3.5 Flash-Lite in JSON mode sometimes wraps the object
        # it was asked for in a one-element array.
        value = value[0]
    return value if isinstance(value, dict) else None


_FLAT_TOP = re.compile(r'^\s*\{\s*"(\w+)"\s*:\s*\{')
_FLAT_PAIR = re.compile(r'^\s*"(k\d+)"\s*:\s*"?(.*?)"?\s*,?\s*$')


def repair_flat_map(text: str) -> dict | None:
    """``{"uz": {"k1": "...", ...}}`` recovered line by line from a reply
    that is almost that. Measured: 3.1 Flash-Lite in JSON mode sometimes
    drops the opening quote of a value (``"k2": majbur qilmoq",``), which
    no JSON parser accepts and which costs a whole batch otherwise. Only
    for this one flat shape -- nested replies are never "repaired"."""
    text = _FENCE.sub("", text.strip())
    top = _FLAT_TOP.match(text)
    if not top:
        return None
    pairs = {}
    for line in text.splitlines():
        match = _FLAT_PAIR.match(line)
        if match and match.group(2).strip():
            pairs[match.group(1)] = match.group(2).strip()
    return {top.group(1): pairs} if pairs else None


# --- Working state ------------------------------------------------------------


@dataclass
class Row:
    id: uuid.UUID
    sense_id: uuid.UUID | None
    meaning_en: str
    meaning_uz: str
    core_en: str
    core_uz: str
    example: str
    cefr_level: str
    surface: str = ""


EXAMPLE_WINDOW = 320


def example_window(example: str, surface: str, lemma: str) -> str:
    """At most EXAMPLE_WINDOW characters of the sentence, centred on the
    word -- a long sentence cut from the start can lose the very word the
    matcher is asked about."""
    if len(example) <= EXAMPLE_WINDOW:
        return example
    lowered = example.lower()
    at = -1
    for needle in (surface, lemma):
        if needle:
            at = lowered.find(needle.lower())
            if at >= 0:
                break
    if at < 0:
        return example[:EXAMPLE_WINDOW] + "…"
    start = max(0, min(at - EXAMPLE_WINDOW // 2, len(example) - EXAMPLE_WINDOW))
    piece = example[start:start + EXAMPLE_WINDOW]
    return ("…" if start > 0 else "") + piece + ("…" if start + EXAMPLE_WINDOW < len(example) else "")


@dataclass
class Sense:
    """A sense as it is and, after planning, as it will be written."""

    id: uuid.UUID | None
    definition_en: str = ""
    meaning_uz: str = ""
    meaning_uz_alt: str = ""
    meaning_uz_material: str = ""
    cefr: str | None = None
    oewn_synset_id: str | None = None
    oewn_rank: int | None = None
    source_id: str = "model"
    licence: str = MODEL_LICENCE
    provisional: bool = False
    review_reasons: list[str] = field(default_factory=list)
    sense_rank: int = 0
    row_ids: list[uuid.UUID] = field(default_factory=list)
    #: planning only
    absorbed: list[uuid.UUID] = field(default_factory=list)
    translate: bool = False
    normalise: bool = False
    judge: str | None = None


@dataclass
class LexemeWork:
    id: uuid.UUID
    lemma: str
    pos: str
    is_phrase: bool
    frequency_band: str | None
    oewn: list[dict]
    senses: list[Sense]
    rows: list[Row]
    #: outputs
    plan: list[Sense] = field(default_factory=list)
    deleted: dict[uuid.UUID, uuid.UUID | None] = field(default_factory=dict)
    new_pos: str | None = None
    needs_gap: bool = False
    note: str = ""


@dataclass
class Use:
    """One distinct way a word was used across the materials: rows with the
    same contextual AND usual gloss are one use, shown to the model once."""

    id: str
    row_ids: list[uuid.UUID]
    sense_ids: set
    example: str
    here_en: str
    here_uz: str
    usual_en: str
    usual_uz: str


_NORM = re.compile(r"[^a-z0-9 ]+")


def _norm(text: str) -> str:
    return " ".join(_NORM.sub(" ", text.lower()).split())


def build_uses(rows: list[Row], prefix: str = "u", lemma: str = "") -> list[Use]:
    groups: dict[tuple[str, str], list[Row]] = {}
    for row in rows:
        key = (_norm(row.meaning_en), _norm(row.core_en or row.meaning_en))
        groups.setdefault(key, []).append(row)
    uses = []
    for index, group in enumerate(groups.values(), start=1):
        first = group[0]
        uses.append(Use(
            id=f"{prefix}{index}",
            row_ids=[r.id for r in group],
            sense_ids={r.sense_id for r in group},
            example=example_window(first.example, first.surface, lemma),
            here_en=first.meaning_en, here_uz=first.meaning_uz,
            usual_en=first.core_en or first.meaning_en,
            usual_uz=first.core_uz or first.meaning_uz,
        ))
    return uses


def candidate_text(uses: list[Use], cand: object, kinds: str,
                   label: str | None = None, usual_labels: dict | None = None) -> str | None:
    """``u3a``/``u3b``/``u3c``/``u3d`` -> here-en, here-uz, usual-en, usual-uz.

    ``kinds`` is which of those the caller will accept ("bd" for Uzbek, "ac"
    for English): a model that answers an Uzbek slot with an English id
    would otherwise put English into ``meaning_uz``.
    """
    if not isinstance(cand, str) or len(cand) < 3:
        return None
    cand = cand.strip()
    use_id, part = cand[:-1], cand[-1]
    if part not in kinds:
        return None
    for use in uses:
        if use.id == use_id:
            if part == "d" and label is not None and usual_labels is not None \
                    and usual_labels.get(use.id) != label:
                # The usual gloss describes some OTHER sense (or two at once):
                # its Uzbek is not this sense's meaning.
                return None
            if part == "b" and _has_own_usual(use):
                # The contextual Uzbek of a use whose sense differs from the
                # usual one is a paraphrase of ONE sentence ("the tier of a
                # ship's oars"), not a dictionary meaning; the prompt says so
                # and the model still picks it, so it is refused here.
                return None
            text = {"a": use.here_en, "b": use.here_uz,
                    "c": use.usual_en, "d": use.usual_uz}.get(part)
            return text or None
    return None


def _has_own_usual(use: Use) -> bool:
    return (_norm(use.usual_en) != _norm(use.here_en)
            or _norm(use.usual_uz) != _norm(use.here_uz))


_X_LABEL = re.compile(r"^X\d{1,3}$")


def _valid_label(label: object, ranks: set[int]) -> str | None:
    if not isinstance(label, str):
        return None
    label = label.strip().upper()
    if label.startswith("S") and label[1:].isdigit() and int(label[1:]) in ranks:
        return label
    if _X_LABEL.match(label):
        return label
    return None


# --- Planning (pure) ----------------------------------------------------------


def plan_senses(work: LexemeWork, uses: list[Use], answer: dict | None) -> None:
    """Fill ``work.plan`` and ``work.deleted`` from the matcher's answer.

    ``answer`` = ``{"uses": {use_id: "S2"|"X1"}, "senses": {label: {"uz":
    cand, "def": cand}}}``; anything missing or invalid means "no answer",
    and an unanswered row stays in the sense it is already in (label
    ``P:<sense id>``) -- never merged on a guess.
    """
    answer = answer if isinstance(answer, dict) else {}
    use_labels = answer.get("uses") if isinstance(answer.get("uses"), dict) else {}
    label_info = answer.get("senses") if isinstance(answer.get("senses"), dict) else {}
    usual_raw = answer.get("usual") if isinstance(answer.get("usual"), dict) else {}
    oewn_by_rank = {s["rank"]: s for s in work.oewn[:OEWN_SHOWN]}
    ranks = set(oewn_by_rank)
    usual_labels = {k: _valid_label(v, ranks) for k, v in usual_raw.items()}

    row_label: dict[uuid.UUID, str] = {}
    for use in uses:
        label = _valid_label(use_labels.get(use.id), ranks)
        for row_id in use.row_ids:
            row_label[row_id] = label or ""
    rows_by_id = {r.id: r for r in work.rows}
    for row in work.rows:
        if not row_label.get(row.id):
            row_label[row.id] = f"P:{row.sense_id}"

    groups: dict[str, list[uuid.UUID]] = defaultdict(list)
    for row in work.rows:
        groups[row_label[row.id]].append(row.id)

    existing = {s.id: s for s in work.senses}
    rows_of_sense: dict[uuid.UUID | None, set] = defaultdict(set)
    for row in work.rows:
        rows_of_sense[row.sense_id].add(row.id)
    by_synset = {s.oewn_synset_id: s for s in work.senses if s.oewn_synset_id}
    claimed: set[uuid.UUID] = set()
    plan: dict[str, Sense] = {}

    def fresh() -> Sense:
        return Sense(id=None)

    def clone(old: Sense) -> Sense:
        return Sense(
            id=old.id, definition_en=old.definition_en, meaning_uz=old.meaning_uz,
            meaning_uz_alt=old.meaning_uz_alt, meaning_uz_material=old.meaning_uz_material,
            cefr=old.cefr, oewn_synset_id=old.oewn_synset_id, oewn_rank=old.oewn_rank,
            source_id=old.source_id, licence=old.licence,
            review_reasons=list(old.review_reasons), provisional=old.provisional,
        )

    # 1. OEWN groups reuse the sense already carrying that synset.
    for label in groups:
        if label.startswith("S"):
            synset = oewn_by_rank[int(label[1:])]["synset"]
            if synset in by_synset and by_synset[synset].id not in claimed:
                plan[label] = clone(by_synset[synset])
                claimed.add(by_synset[synset].id)

    # 2. X groups reuse the unclaimed non-OEWN sense holding most of their
    #    rows (largest groups choose first), or are new senses.
    answered = [lab for lab in groups if not lab.startswith("P:") and lab not in plan]
    for label in sorted(answered, key=lambda lab: (-len(groups[lab]), lab)):
        members = set(groups[label])
        best, best_overlap = None, 0
        for sense in work.senses:
            if sense.id in claimed or sense.oewn_synset_id:
                continue
            overlap = len(rows_of_sense.get(sense.id, set()) & members)
            if overlap > best_overlap:
                best, best_overlap = sense, overlap
        if best is not None:
            plan[label] = clone(best)
            claimed.add(best.id)
        else:
            plan[label] = fresh()

    # 2b. Unanswered rows stay in the sense they are in: with whichever group
    #     now holds that sense, or keeping it as it is.
    holder = {s.id: lab for lab, s in plan.items() if s.id is not None}
    for label in [lab for lab in groups if lab.startswith("P:")]:
        sense_id = next((rows_by_id[r].sense_id for r in groups[label]), None)
        if sense_id in holder:
            groups[holder[sense_id]].extend(groups.pop(label))
        elif sense_id in existing:
            plan[label] = clone(existing[sense_id])
            claimed.add(sense_id)
            holder[sense_id] = label
        else:
            plan[label] = fresh()
            first = rows_by_id[groups[label][0]]
            plan[label].definition_en = (first.core_en or first.meaning_en)[:DEF_MAX]
            plan[label].meaning_uz = (first.core_uz or first.meaning_uz)[:UZ_MAX]

    # 3. Fill each group's content.
    for label, sense in plan.items():
        sense.row_ids = sorted(groups[label], key=str)
        info = label_info.get(label) if isinstance(label_info.get(label), dict) else {}
        before_uz = sense.meaning_uz
        was_provisional = sense.provisional
        if label.startswith("S"):
            entry = oewn_by_rank[int(label[1:])]
            sense.oewn_synset_id = entry["synset"]
            sense.oewn_rank = entry["rank"]
            sense.definition_en = entry["definition"][:DEF_MAX]
            sense.source_id, sense.licence = "oewn", OEWN_LICENCE
            chosen = candidate_text(uses, info.get("uz"), "bd", label, usual_labels)
            if chosen:
                set_copied_uz(sense, chosen)
            elif not (sense.meaning_uz and existing.get(sense.id)
                      and existing[sense.id].oewn_synset_id == sense.oewn_synset_id):
                sense.meaning_uz = sense.meaning_uz_material = ""
        elif label.startswith("X"):
            sense.oewn_synset_id, sense.oewn_rank = None, None
            sense.source_id, sense.licence = "model", MODEL_LICENCE
            definition = candidate_text(uses, info.get("def"), "ac")
            if definition:
                sense.definition_en = definition[:DEF_MAX]
            elif not sense.definition_en:
                first = rows_by_id[sense.row_ids[0]]
                sense.definition_en = (first.core_en or first.meaning_en)[:DEF_MAX]
            chosen = candidate_text(uses, info.get("uz"), "bd", label, usual_labels)
            if chosen:
                set_copied_uz(sense, chosen)
            elif not (sense.meaning_uz and existing.get(sense.id)
                      and not existing[sense.id].provisional
                      and existing[sense.id].definition_en == sense.definition_en):
                # A provisional sense's Uzbek is P1's copy of a possibly
                # two-meaning gloss; the model declined it. A finished sense's
                # (a re-run) was already chosen or translated -- kept, unless
                # this run chose a different definition: the Uzbek was for
                # the old one.
                sense.meaning_uz = sense.meaning_uz_material = ""
        else:
            # "P:" groups: nobody answered -- content kept as it was. A P1
            # provisional sense's Uzbek is a material copy all the same.
            if (sense.id is None or was_provisional) and sense.meaning_uz \
                    and not sense.meaning_uz_material:
                set_copied_uz(sense, sense.meaning_uz)
        if label[0] in "SX" and label in label_info:
            # The matcher answered for this label: its pos verdict replaces
            # whatever an earlier run said.
            sense.review_reasons = [r for r in sense.review_reasons if r not in MATCH_REASONS]
            if pos_mismatch(work.pos, info):
                sense.review_reasons.append("pos_mismatch")
        if sense.meaning_uz != before_uz or sense.id is None:
            sense.meaning_uz_alt = ""
            sense.review_reasons = [r for r in sense.review_reasons if r not in JUDGE_REASONS]
        sense.translate = not sense.meaning_uz
        if sense.translate:
            sense.normalise = False
        sense.provisional = False

    # 4. Existing senses no group claimed. Kept: an OEWN top-`OEWN_TOP`
    #    sense, which belongs to the lexeme whether or not a material uses
    #    it, and a non-OEWN sense that never had rows (a gap definition).
    #    Deleted: a deeper OEWN sense no material uses (an earlier run's
    #    "top 2", or rows a re-run moved away) -- anything pointing at it is
    #    redirected to the lexeme's rank-1 sense in `apply_work`. Anything
    #    else lost its rows to another sense and is absorbed into whichever
    #    planned sense took most of them.
    kept_untouched: list[Sense] = []
    row_to_label = {rid: lab for lab, ids in groups.items() for rid in ids}
    top_synsets = {e["synset"] for e in work.oewn[:OEWN_TOP]}
    for sense in work.senses:
        if sense.id in claimed:
            continue
        old_rows = rows_of_sense.get(sense.id, set())
        if not old_rows and sense.oewn_synset_id and sense.oewn_synset_id not in top_synsets:
            work.deleted[sense.id] = None
            continue
        if sense.oewn_synset_id in top_synsets or not old_rows:
            kept = clone(sense)
            kept.oewn_rank = sense.oewn_rank
            kept.row_ids = []
            if kept.provisional and kept.meaning_uz and not kept.meaning_uz_material:
                set_copied_uz(kept, kept.meaning_uz)
            kept.provisional = False
            kept.translate = not kept.meaning_uz
            kept_untouched.append(kept)
            continue
        target_label = Counter(row_to_label[r] for r in old_rows).most_common(1)[0][0]
        target = plan[target_label]
        target.absorbed.append(sense.id)
        for reason in sense.review_reasons:
            if reason not in COMPUTED_REASONS and reason not in MATCH_REASONS \
                    and reason not in target.review_reasons:
                target.review_reasons.append(reason)
        work.deleted[sense.id] = target.id  # None until inserted; fixed in apply

    senses = list(plan.values()) + kept_untouched

    # 5. OEWN's top sense(s).
    present = {s.oewn_synset_id for s in senses if s.oewn_synset_id}
    for entry in work.oewn[:OEWN_TOP]:
        if entry["synset"] not in present:
            senses.append(Sense(
                id=None, definition_en=entry["definition"][:DEF_MAX],
                oewn_synset_id=entry["synset"], oewn_rank=entry["rank"],
                source_id="oewn", licence=OEWN_LICENCE, translate=True,
            ))

    work.needs_gap = not senses and not work.oewn
    work.plan = senses


#: A copied Uzbek string reads as a dictionary gloss when it is short, has
#: no sentence punctuation or brackets and does not open with a capital.
GLOSS_MAX_WORDS = 6
_SENTENCE_END = (".", "!", "?", ";", ":")


def looks_like_gloss(text: str) -> bool:
    text = text.strip()
    if not text:
        return True
    return (not text.endswith(_SENTENCE_END) and "(" not in text
            and len(text.split()) <= GLOSS_MAX_WORDS and not text[0].isupper())


def tidy_copy(text: str) -> str:
    """The mechanical half of dictionary style, which cannot change a
    meaning: no final full stop, no capital on the first word (unless that
    word is all capitals: an abbreviation such as "AQSH")."""
    text = " ".join(text.split()).rstrip(".").rstrip()
    first = text.split(" ", 1)[0] if text else ""
    if first and not (len(first) > 1 and first.isupper()):
        text = text[0].lower() + text[1:]
    return text


def set_copied_uz(sense: Sense, text: str) -> None:
    """``meaning_uz`` copied from a material (tidied; the verbatim string is
    kept in ``meaning_uz_material``). A re-run choosing the same material
    string keeps what the last run made of it instead of asking again."""
    text = text[:UZ_MAX]
    if text == sense.meaning_uz_material and sense.meaning_uz:
        return
    sense.meaning_uz_material = text
    sense.meaning_uz = tidy_copy(text) or text
    # A copy written as a sentence goes to the model even once tidied:
    # "Bahor fasli." tidies to "bahor fasli", and the entry is "bahor".
    sense.normalise = (not looks_like_gloss(sense.meaning_uz)
                       or text.rstrip().endswith(_SENTENCE_END))


def pos_mismatch(lexeme_pos: str, info: dict) -> bool:
    """The matcher's verdict on one label: the uses define another word
    (``wrong_word``), or show the headword as a part of speech the lexeme
    is not. ``phr`` and an unknown pos never conflict -- a phrase lexeme is
    filed under its head's pos as often as under ``phr``."""
    if info.get("wrong_word") is True:
        return True
    used = str(info.get("pos") or "").strip().lower()
    return lexeme_pos in POS_WORDS and used in POS_WORDS and used != lexeme_pos


def rank_senses(senses: list[Sense]) -> list[Sense]:
    """Order and number a lexeme's senses -- see the module docstring."""
    used = sorted((s for s in senses if s.row_ids),
                  key=lambda s: (-len(s.row_ids), s.oewn_rank or 10**6, s.definition_en))
    oewn = sorted((s for s in senses if not s.row_ids and s.oewn_rank is not None),
                  key=lambda s: s.oewn_rank)
    model = sorted((s for s in senses if not s.row_ids and s.oewn_rank is None),
                   key=lambda s: s.definition_en)
    ordered = used + oewn + model
    for rank, sense in enumerate(ordered, start=1):
        sense.sense_rank = rank
    return ordered


def majority_level(levels: list[str]) -> str | None:
    """Commonest non-empty level, ties toward the lower -- the same rule P1
    used for a provisional sense's level."""
    counts = Counter(level for level in levels if level in CEFR_ORDER)
    if not counts:
        return None
    top = max(counts.values())
    return min((lvl for lvl, n in counts.items() if n == top), key=CEFR_ORDER.index)


def review_reasons(*, cefr: str | None, frequency_band: str | None,
                   material_levels: list[str], carried: list[str],
                   judge: str | None, rank: int = 1) -> list[str]:
    reasons = [r for r in carried if r not in COMPUTED_REASONS]
    if judge is None:  # not translated this run: keep the earlier verdict
        reasons += [r for r in carried if r in JUDGE_REASONS]
    elif judge == "different":
        reasons.append("judge_different")
    elif judge != "same":
        reasons.append("judge_unsure")
    if rank == 1:
        if cefr in ("C1", "C2") and frequency_band == "core":
            reasons.append("ngsl_conflict")
        if cefr in ("A1", "A2") and frequency_band == "off-list":
            reasons.append("ngsl_conflict")
    majority = majority_level(material_levels)
    if cefr in CEFR_ORDER and majority is not None \
            and CEFR_ORDER.index(cefr) >= CEFR_ORDER.index("B1"):
        if abs(CEFR_ORDER.index(cefr) - CEFR_ORDER.index(majority)) >= 2:
            reasons.append("material_level_gap")
    return list(dict.fromkeys(reasons))


# --- Prompts ------------------------------------------------------------------

MATCH_PROMPT = """You are building an English learner's dictionary for Uzbek
speakers. Below are headwords, each with:
- its senses from WordNet, S1, S2, ... (WordNet's own order, commonest first);
- its USES: sentences from reading passages containing the word, each with a
  gloss another model wrote for the word IN THAT SENTENCE ("here") and for the
  word in general ("usual"), each in English and Uzbek, with an id in [].
The glosses were written quickly and are often wrong or join two meanings
("a number or a shape"). The SENTENCE is the evidence; trust it over any gloss.

For every use, say which sense the headword has IN THAT SENTENCE:
- "S<n>" when a listed WordNet sense fits. WordNet splits senses finely: pick
  the one a learner would recognise as the same meaning.
- "X<k>" when none fits (a sense WordNet lacks, or the word is used as another
  part of speech, or inside a fixed phrase whose meaning is not a sense of the
  word). Uses sharing one such meaning share the same X label.

For every use that has a separate "usual" line, also say which sense that
USUAL gloss describes: an S or X label, or "mixed" when it names two meanings
or none of them.

Then for EVERY label you used, choose:
- "uz": the id of the Uzbek text, among the uses you gave that label, that best
  translates the headword in THAT sense alone -- natural Uzbek naming one
  meaning, not two joined by "yoki", not a narrow paraphrase of one sentence.
  Where a use has a separate "usual" line, only its usual Uzbek ([..d]) may be
  chosen, and only if that usual gloss describes THIS label. null if none fits.
- for X labels only, "def": the id of the English text ([..a] or [..c]), among
  those uses, that best defines that meaning in general -- usually the "here"
  gloss. null if none does.
- "pos": the part of speech the headword has in those uses: n, v, adj, adv,
  prep, conj, or phr for a multi-word expression.
- "wrong_word": true when those uses (or the gloss you chose for them) give
  the meaning of a DIFFERENT word or phrase than the headword -- e.g. the
  headword "ai safety" glossed as plain "safety", "learn" glossed as
  "machine learning", or "tax" (adj) used as "taxing"; otherwise false.
"uz" must be an Uzbek id ([..b] or [..d]); never an English one.

{words}

Reply with JSON only:
{{"words": [{{"id": "w1", "uses": {{"u1": "S2", "u2": "X1"}},
  "usual": {{"u2": "X1"}},
  "senses": {{"S2": {{"uz": "u1b", "pos": "n", "wrong_word": false}},
             "X1": {{"uz": "u2d", "def": "u2a", "pos": "v", "wrong_word": false}}}}}}]}}
Answer every use of every headword."""


def render_match_word(word_id: str, work: LexemeWork, uses: list[Use]) -> str:
    lines = [f"{word_id}  {work.lemma} ({work.pos or '?'})"]
    if work.oewn:
        lines.append("  WordNet senses:")
        for entry in work.oewn[:OEWN_SHOWN]:
            lines.append(f"    S{entry['rank']}: {entry['definition']}")
    else:
        lines.append("  WordNet senses: none -- use X labels only")
    lines.append("  Uses:")
    for use in uses:
        lines.append(f"    {use.id}: \"{use.example}\"")
        lines.append(f"        here: \"{use.here_en}\" [{use.id}a] / \"{use.here_uz}\" [{use.id}b]")
        if _has_own_usual(use):
            lines.append(f"        usual: \"{use.usual_en}\" [{use.id}c] / \"{use.usual_uz}\" [{use.id}d]")
    return "\n".join(lines)


GAP_PROMPT = """WordNet does not list the English headwords below. Write one
definition for each in WordNet's own style: a short lower-case gloss, no
headword in it, no final full stop, no example -- like "a financial
institution that accepts deposits and channels the money into lending
activities" or "tip laterally". Define the commonest meaning. Where a part of
speech is given, define it as that; where it is "?", choose one of n, v, adj,
adv, phr (phr for any multi-word expression).

If a headword is not an English word or expression at all (a name, a
fragment, a typo), give "def": "".

{words}

Reply with JSON only: {{"defs": {{"w1": {{"pos": "n", "def": "..."}}}}}}"""

CEFR_PROMPT = """Grade each English word sense below on the CEFR scale (A1,
A2, B1, B2, C1, C2): the level at which a learner typically knows the word IN
THIS SENSE. Grade the meaning, not the spelling: a common word in a rare,
technical or figurative sense is harder than the same word in its everyday
sense, and the everyday sense of a common word is easy even when the word
also has hard senses.

A1-A2: basic everyday words (house, eat, happy). B1: common general
vocabulary. B2: wider general and early academic vocabulary (appropriate,
significant). C1: less frequent, abstract or academic words and senses. C2:
rare, literary or highly specialised.

{items}

Reply with JSON only: {{"levels": {{"k1": "B2", ...}}}}"""

TRANSLATE_PROMPT = """Translate English word senses into Uzbek for a
bilingual learner's dictionary. The readers are Uzbek speakers learning
English (IELTS band 5-6).

Each item gives a word, its part of speech and ONE sense (a definition).
Give the Uzbek word or short phrase a good English-Uzbek dictionary would
give for the word IN THAT SENSE -- not a translation of the definition
sentence. Natural modern Uzbek, Latin script, with ' in o' and g'. Verbs in
the -moq form. Do not transliterate the English word unless Uzbek really uses
that loanword. Where one Uzbek word is ambiguous, add a second synonym after
a comma; at most about eight words.

{items}

Reply with JSON only: {{"uz": {{"k1": "...", ...}}}}"""

JUDGE_PROMPT = """Two translators rendered English word senses into Uzbek.
For each item decide whether translation A and translation B give the SAME
meaning of the English word as defined:
- "same": they name the same meaning (synonyms, different suffixes or word
  order still count as same);
- "different": they name different meanings, or at least one is wrong for
  this definition or is not Uzbek;
- "unsure": you cannot tell.
Also say which fits the definition better: "a", "b", or "both".

{items}

Reply with JSON only:
{{"verdicts": {{"k1": {{"verdict": "same", "better": "both"}}, ...}}}}"""


STYLE_PROMPT = """Below are Uzbek meanings of English words, copied from
reading materials. Some are written as a sentence or an explanation instead
of the way a bilingual dictionary prints a meaning. Rewrite each in
dictionary style: the Uzbek word or short phrase, lower case (except proper
names), no final full stop, no brackets, at most about six words; where the
text itself gives synonyms, keep up to three, comma-separated. Verbs in the
-moq form.

Do NOT change the meaning. Do not add a meaning, drop one, narrow or widen
it, or replace the text with your own translation of the English word: use
the Uzbek words already in the text wherever you can. If the text is
already in dictionary style, or cannot be shortened without changing its
meaning, return it unchanged. Latin script, ' in o' and g'.

Examples: "spring (n): Bahor fasli." -> "bahor"; "subject (n): Muhokama
qilinayotgan mavzu." -> "mavzu"; "bank (n): Pul saqlanadigan moliya
muassasasi (bank)" -> "bank, moliya muassasasi".

{items}

Reply with JSON only: {{"uz": {{"k1": "...", ...}}}}"""

STYLE_CHECK_PROMPT = """Each item gives an English word, the sense it is
used in, and two Uzbek renderings of that sense: LONG (from a textbook) and
SHORT (a dictionary-style rewrite of LONG). Decide whether SHORT names the
same meaning as LONG -- not narrower, not wider, not a different sense:
"same" or "different".

{items}

Reply with JSON only: {{"verdicts": {{"k1": "same", ...}}}}"""


# --- Model steps --------------------------------------------------------------


def _chunks(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


async def step_match(gemini: Gemini, works: list[LexemeWork], max_uses: int = 60) -> None:
    """Match and plan every lexeme in ``works``. Lexemes needing no model
    (no rows; or one use and no OEWN entry) are planned directly."""
    pending: list[tuple[LexemeWork, list[Use]]] = []
    for work in works:
        uses = build_uses(work.rows, lemma=work.lemma)
        if not uses:
            plan_senses(work, uses, None)
            continue
        # A single use with no OEWN entry has nothing to merge but is still
        # asked: the copy rule for its Uzbek and the pos check need the
        # model as much as a word with forty uses does.
        pending.append((work, uses))

    batches: list[list[tuple[LexemeWork, list[Use]]]] = []
    current: list = []
    count = 0
    for work, uses in pending:
        if current and (count + len(uses) > max_uses or len(current) >= 12):
            batches.append(current)
            current, count = [], 0
        current.append((work, uses))
        count += len(uses)
    if current:
        batches.append(current)

    async def one(batch):
        # Re-id uses so ids are unique across the batch.
        rendered, keyed = [], {}
        counter = 0
        for index, (work, uses) in enumerate(batch, start=1):
            for use in uses:
                counter += 1
                use.id = f"u{counter}"
            rendered.append(render_match_word(f"w{index}", work, uses))
            keyed[f"w{index}"] = (work, uses)
        reply = await gemini.ask(MODEL_MAIN, MATCH_PROMPT.format(words="\n\n".join(rendered)),
                                 step="match", max_tokens=4000 + 60 * counter)
        answers = {}
        if reply and isinstance(reply.get("words"), list):
            for item in reply["words"]:
                if isinstance(item, dict) and item.get("id") in keyed:
                    answers[item["id"]] = item
        for word_id, (work, uses) in keyed.items():
            if word_id not in answers:
                work.note += "match:no-answer "
            plan_senses(work, uses, answers.get(word_id))

    await asyncio.gather(*(one(batch) for batch in batches))


async def step_gaps(gemini: Gemini, works: list[LexemeWork]) -> None:
    gaps = [w for w in works if w.needs_gap]
    for batch in _chunks(gaps, 40):
        words = "\n".join(f"w{i}: {w.lemma} ({w.pos or '?'})" for i, w in enumerate(batch, 1))
        reply = await gemini.ask(MODEL_MAIN, GAP_PROMPT.format(words=words), step="gap",
                                 max_tokens=4000)
        defs = reply.get("defs") if reply and isinstance(reply.get("defs"), dict) else {}
        for i, work in enumerate(batch, 1):
            item = defs.get(f"w{i}")
            if not isinstance(item, dict):
                work.note += "gap:no-answer "
                continue
            definition = str(item.get("def") or "").strip()
            if not definition:
                work.note += "gap:not-a-word "
                continue
            pos = str(item.get("pos") or "").strip().lower()
            if not work.pos and pos in ("n", "v", "adj", "adv", "prep", "conj", "phr"):
                work.new_pos = pos
            work.plan.append(Sense(id=None, definition_en=definition[:DEF_MAX],
                                   source_id="model", licence=MODEL_LICENCE, translate=True))


def _label(work: LexemeWork) -> str:
    return f"{work.lemma} ({work.new_pos or work.pos or '?'})"


async def step_cefr(gemini: Gemini, works: list[LexemeWork]) -> None:
    items = [(w, s) for w in works for s in w.plan]
    for batch in _chunks(items, 60):
        text = "\n".join(f"k{i}: {_label(w)} -- {s.definition_en}"
                         for i, (w, s) in enumerate(batch, 1))
        reply = await gemini.ask(MODEL_MAIN, CEFR_PROMPT.format(items=text), step="cefr",
                                 max_tokens=3000)
        levels = reply.get("levels") if reply and isinstance(reply.get("levels"), dict) else {}
        for i, (work, sense) in enumerate(batch, 1):
            level = str(levels.get(f"k{i}") or "").strip().upper()
            if level in CEFR_ORDER:
                sense.cefr = level
            else:
                work.note += "cefr:no-answer "


async def step_normalise(gemini: Gemini, works: list[LexemeWork]) -> None:
    """Rewrite sentence-style copied Uzbek into dictionary style, keeping a
    rewrite only if a second model agrees it means the same."""
    items = [(w, s) for w in works for s in w.plan if s.normalise and s.meaning_uz]
    for batch in _chunks(items, 50):
        text = "\n".join(f"k{i}: {_label(w)}: {s.meaning_uz}"
                         for i, (w, s) in enumerate(batch, 1))
        reply = await gemini.ask(MODEL_STYLE, STYLE_PROMPT.format(items=text), step="style",
                                 max_tokens=3000, repair_flat=True)
        got = reply.get("uz") if reply and isinstance(reply.get("uz"), dict) else {}
        candidates = []
        for i, (work, sense) in enumerate(batch, 1):
            short = _clean_uz(got.get(f"k{i}")).rstrip(".").strip()
            original = sense.meaning_uz
            if not short:
                work.note += "style:no-answer "
            elif short == original or len(short) > len(original):
                work.note += "style:unchanged "
            else:
                candidates.append((work, sense, short))
        if not candidates:
            continue
        text = "\n".join(
            f"k{i}: {_label(w)} -- {s.definition_en}\n    LONG: {s.meaning_uz}"
            f"\n    SHORT: {short}"
            for i, (w, s, short) in enumerate(candidates, 1))
        reply = await gemini.ask(MODEL_STYLE_CHECK, STYLE_CHECK_PROMPT.format(items=text),
                                 step="style-check", max_tokens=2000, repair_flat=True)
        verdicts = reply.get("verdicts") if reply and isinstance(reply.get("verdicts"), dict) else {}
        for i, (work, sense, short) in enumerate(candidates, 1):
            if str(verdicts.get(f"k{i}") or "").strip().lower() == "same":
                sense.meaning_uz = short
                work.note += "style:normalised "
            else:
                work.note += "style:rejected "  # the tidied copy stays


def _clean_uz(value: object) -> str:
    text = " ".join(str(value or "").split())
    # One apostrophe convention, the one the material Uzbek already uses.
    for mark in ("ʻ", "ʼ", "‘", "’", "`"):
        text = text.replace(mark, "'")
    return text[:UZ_MAX]


async def step_translate(gemini: Gemini, works: list[LexemeWork]) -> None:
    items = [(w, s) for w in works for s in w.plan if s.translate]
    for batch in _chunks(items, 50):
        text = "\n".join(f"k{i}: {_label(w)} -- {s.definition_en}"
                         for i, (w, s) in enumerate(batch, 1))
        prompt = TRANSLATE_PROMPT.format(items=text)
        main, alt = await asyncio.gather(
            gemini.ask(MODEL_MAIN, prompt, step="translate", max_tokens=4000, repair_flat=True),
            gemini.ask(MODEL_ALT, prompt, step="translate", max_tokens=4000, repair_flat=True),
        )
        uz_main = main.get("uz") if main and isinstance(main.get("uz"), dict) else {}
        uz_alt = alt.get("uz") if alt and isinstance(alt.get("uz"), dict) else {}
        # A translator that failed or skipped items is asked once more for just
        # those -- otherwise one bad request turns into a row of `judge_unsure`
        # flags that are about the API, not the translation.
        for model, got in ((MODEL_MAIN, uz_main), (MODEL_ALT, uz_alt)):
            missing = [i for i in range(1, len(batch) + 1) if not _clean_uz(got.get(f"k{i}"))]
            if not missing:
                continue
            text = "\n".join(f"k{i}: {_label(batch[i - 1][0])} -- {batch[i - 1][1].definition_en}"
                             for i in missing)
            retry = await gemini.ask(model, TRANSLATE_PROMPT.format(items=text),
                                     step="translate", max_tokens=4000, repair_flat=True)
            if retry and isinstance(retry.get("uz"), dict):
                for i in missing:
                    if retry["uz"].get(f"k{i}"):
                        got[f"k{i}"] = retry["uz"][f"k{i}"]
            # Still missing: one item per request, so a single item the model
            # refuses (a blocked medical term, say) cannot sink its neighbours.
            still = [i for i in missing if not _clean_uz(got.get(f"k{i}"))]
            if len(still) > 1:
                singles = await asyncio.gather(*(
                    gemini.ask(model, TRANSLATE_PROMPT.format(
                        items=f"k1: {_label(batch[i - 1][0])} -- {batch[i - 1][1].definition_en}"),
                        step="translate", max_tokens=1000, repair_flat=True)
                    for i in still
                ))
                for i, single in zip(still, singles):
                    if single and isinstance(single.get("uz"), dict) and single["uz"].get("k1"):
                        got[f"k{i}"] = single["uz"]["k1"]
        judged = []
        for i, (work, sense) in enumerate(batch, 1):
            a, b = _clean_uz(uz_alt.get(f"k{i}")), _clean_uz(uz_main.get(f"k{i}"))
            sense.meaning_uz, sense.meaning_uz_alt = b or a, a if b else ""
            sense.meaning_uz_material = ""
            if a and b:
                judged.append((work, sense, a, b))
            elif a or b:
                sense.judge = "unsure"  # only one translator answered
            else:
                work.note += "translate:no-answer "
        if not judged:
            continue
        text = "\n".join(
            f"k{i}: {_label(w)} -- {s.definition_en}\n    A: {a}\n    B: {b}"
            for i, (w, s, a, b) in enumerate(judged, 1)
        )
        reply = await gemini.ask(MODEL_JUDGE, JUDGE_PROMPT.format(items=text), step="judge",
                                 max_tokens=3000)
        verdicts = reply.get("verdicts") if reply and isinstance(reply.get("verdicts"), dict) else {}
        for i, (work, sense, a, b) in enumerate(judged, 1):
            v = verdicts.get(f"k{i}")
            v = v if isinstance(v, dict) else {}
            verdict = str(v.get("verdict") or "").lower()
            sense.judge = verdict if verdict in ("same", "different", "unsure") else "unsure"
            if str(v.get("better") or "").lower() == "a":
                sense.meaning_uz, sense.meaning_uz_alt = a, b


def finalise(work: LexemeWork) -> None:
    """Rank and review reasons, once every model step has run."""
    levels_by_row = {r.id: r.cefr_level for r in work.rows}
    rank_senses(work.plan)
    # `lemma_merge` is a fact about the LEXEME (P1 marks every sense of a
    # merged one): a sense split off or added here inherits it.
    merged = any("lemma_merge" in s.review_reasons for s in work.senses)
    for sense in work.plan:
        if merged and "lemma_merge" not in sense.review_reasons:
            sense.review_reasons.append("lemma_merge")
        sense.review_reasons = review_reasons(
            cefr=sense.cefr, frequency_band=work.frequency_band,
            material_levels=[levels_by_row[r] for r in sense.row_ids],
            carried=sense.review_reasons, judge=sense.judge, rank=sense.sense_rank,
        )


# --- DB -----------------------------------------------------------------------


async def load_works(session, lexeme_ids: list[uuid.UUID],
                     oewn: dict[tuple[str, str], list[dict]]) -> list[LexemeWork]:
    lexemes = (await session.exec(select(Lexeme).where(Lexeme.id.in_(lexeme_ids)))).all()
    senses = (await session.exec(
        select(LexemeSense).where(LexemeSense.lexeme_id.in_(lexeme_ids))
    )).all()
    rows = (await session.exec(
        select(MaterialVocabulary).where(MaterialVocabulary.lexeme_id.in_(lexeme_ids))
    )).all()
    senses_by: dict = defaultdict(list)
    for s in senses:
        senses_by[s.lexeme_id].append(s)
    rows_by: dict = defaultdict(list)
    for r in rows:
        rows_by[r.lexeme_id].append(r)
    works = []
    for lx in lexemes:
        entries = oewn.get((lx.lemma, lx.pos), [])
        rank_of = {e["synset"]: e["rank"] for e in entries}
        works.append(LexemeWork(
            id=lx.id, lemma=lx.lemma, pos=lx.pos, is_phrase=lx.is_phrase,
            frequency_band=lx.frequency_band, oewn=entries,
            senses=[Sense(
                id=s.id, definition_en=s.definition_en, meaning_uz=s.meaning_uz,
                meaning_uz_alt=s.meaning_uz_alt, meaning_uz_material=s.meaning_uz_material,
                cefr=s.cefr,
                oewn_synset_id=s.oewn_synset_id, oewn_rank=rank_of.get(s.oewn_synset_id),
                source_id=s.source_id, licence=s.licence, provisional=s.provisional,
                review_reasons=list(s.review_reasons), sense_rank=s.sense_rank,
            ) for s in sorted(senses_by[lx.id], key=lambda s: s.sense_rank)],
            rows=[Row(
                id=r.id, sense_id=r.sense_id, meaning_en=r.meaning_en, meaning_uz=r.meaning_uz,
                core_en=r.meaning_core_en, core_uz=r.meaning_core_uz, example=r.example,
                cefr_level=r.cefr_level, surface=r.surface,
            ) for r in sorted(rows_by[lx.id], key=lambda r: str(r.id))],
        ))
    return works


async def _repoint_saved_words(
    session, old_sense_id: uuid.UUID, new_sense_id: uuid.UUID | None
) -> None:
    """A sense absorbed into another (P4: `saved_words.lexeme_sense_id` is
    NOT NULL) must not leave a saved word pointing at a row about to be
    deleted -- repointed one word at a time, because whether it collides
    with a word the SAME learner already has for the survivor is a per-row
    question `sa_update`'s bulk form cannot ask.

    No collision: a plain repoint, exactly like `MaterialVocabulary.sense_id`
    and `TranslationReport.lexeme_sense_id` above. A collision -- the
    learner already has a saved word for `new_sense_id`, which happens when
    two provisional senses they had separately saved words for turn out to
    be the same meaning -- MERGES the two: every context the absorbed word
    carried moves onto the survivor (a context for a material the survivor
    already has is dropped rather than violating `uq_saved_context_material`
    -- the survivor's own meeting of the word stands), and the absorbed word
    is deleted. Its FSRS history is lost in that case; there is no honest
    way to combine two schedules into one, and losing a duplicate card's
    history is a smaller failure than an `IntegrityError` crashing the
    worker's enrichment loop.
    """
    if new_sense_id is None:
        # No survivor at all -- nothing sane to repoint to. Left alone; the
        # caller's delete will raise loudly if a saved word is ever really
        # left stranded this way, which has not been observed and is
        # preferable to guessing.
        return
    words = (await session.exec(
        select(SavedWord).where(SavedWord.lexeme_sense_id == old_sense_id)
    )).all()
    for word in words:
        survivor = (await session.exec(
            select(SavedWord).where(
                SavedWord.user_id == word.user_id,
                SavedWord.lexeme_sense_id == new_sense_id,
            )
        )).first()
        if survivor is None:
            word.lexeme_sense_id = new_sense_id
            session.add(word)
            continue
        contexts = (await session.exec(
            select(SavedWordContext).where(SavedWordContext.saved_word_id == word.id)
        )).all()
        existing_materials = set((await session.exec(
            select(SavedWordContext.material_id).where(
                SavedWordContext.saved_word_id == survivor.id
            )
        )).all())
        for context in contexts:
            if context.material_id in existing_materials:
                await session.delete(context)
            else:
                context.saved_word_id = survivor.id
                session.add(context)
        await session.flush()
        await session.delete(word)
    await session.flush()


async def _repoint_translation_reports(
    session, old_sense_id: uuid.UUID, new_sense_id: uuid.UUID | None
) -> None:
    """A sense absorbed into another must not leave a translation report
    pointing at a row about to be deleted -- repointed one row at a time,
    exactly like :func:`_repoint_saved_words` above and for the same reason:
    whether it collides with a report the SAME learner already has OPEN
    against the survivor is a per-row question the bulk ``sa_update`` two
    lines below this function's call site cannot ask, and the collision is
    real -- one open report per ``(user_id, lexeme_sense_id)`` is a partial
    unique index, and a learner who reported the same wrong translation once
    under each of two senses that turn out to be the same meaning has one
    open row against both today.

    No collision, or the report is already resolved: a plain repoint --
    ``lexeme_sense_id`` moves to the survivor either way, because
    ``old_sense_id`` is about to be deleted and the column is NOT NULL with
    no ``ON DELETE`` of its own (unlike `SavedWordContext.vocabulary_id`).
    A collision ALSO keeps the survivor's OWN open report (it is the one
    that will keep being shown in the review queue), appends the absorbed
    report's note onto it so neither complaint is lost, and resolves the
    absorbed report -- the same terminal state `_close_open_reports`
    (`lexicon_review.py`) already puts a report into once it has been acted
    on, since a merge is exactly that: an answer, not a second open row a
    reviewer would otherwise have to notice is a duplicate. Resolved rows
    are exempt from the partial unique index, so two resolved reports (or a
    resolved one and an open one) sharing `(user_id, new_sense_id)` is not a
    collision at all -- only two OPEN ones are.
    """
    if new_sense_id is None:
        return
    reports = (await session.exec(
        select(TranslationReport).where(
            TranslationReport.lexeme_sense_id == old_sense_id
        )
    )).all()
    for report in reports:
        if report.status == "open":
            survivor = (await session.exec(
                select(TranslationReport).where(
                    TranslationReport.user_id == report.user_id,
                    TranslationReport.lexeme_sense_id == new_sense_id,
                    TranslationReport.status == "open",
                )
            )).first()
            if survivor is not None:
                if report.note and report.note not in survivor.note:
                    merged_note = (
                        f"{survivor.note}\n{report.note}" if survivor.note else report.note
                    )
                    survivor.note = merged_note[:500]
                    session.add(survivor)
                report.status = "resolved"
                report.resolved_at = datetime.now(timezone.utc)
        report.lexeme_sense_id = new_sense_id
        session.add(report)
    await session.flush()


async def apply_work(session, work: LexemeWork) -> None:
    """Write one planned lexeme. The caller commits; ``enriched_at`` is set
    in the same transaction, so a crash leaves the lexeme untouched."""
    lexeme = await session.get(Lexeme, work.id)
    existing = {s.id: s for s in (await session.exec(
        select(LexemeSense).where(LexemeSense.lexeme_id == work.id)
    )).all()}

    for planned in work.plan:
        row = existing.get(planned.id) if planned.id else None
        if row is None:
            row = LexemeSense(lexeme_id=work.id)
            session.add(row)
        row.sense_rank = planned.sense_rank
        row.definition_en = planned.definition_en[:DEF_MAX]
        row.meaning_uz = planned.meaning_uz[:UZ_MAX]
        row.meaning_uz_alt = planned.meaning_uz_alt[:UZ_MAX]
        row.meaning_uz_material = planned.meaning_uz_material[:UZ_MAX]
        row.cefr = planned.cefr
        row.oewn_synset_id = planned.oewn_synset_id
        row.source_id = planned.source_id
        row.licence = planned.licence
        row.provisional = False
        row.review_reasons = list(planned.review_reasons)
        row.needs_review = bool(planned.review_reasons)
        await session.flush()
        planned.id = row.id

    # Re-point material rows, then redirect and delete absorbed senses.
    moves = [{"id": rid, "sense_id": planned.id}
             for planned in work.plan for rid in planned.row_ids]
    if moves:
        await session.execute(sa_update(MaterialVocabulary), moves)
    for planned in work.plan:
        for old_id in planned.absorbed:
            work.deleted[old_id] = planned.id
    first = next((s for s in work.plan if s.sense_rank == 1), None)
    for old_id, new_id in work.deleted.items():
        # An unused deep OEWN sense has no absorber: anything that still
        # points at it (a translation report) moves to the rank-1 sense.
        new_id = new_id or (first.id if first else None)
        await session.execute(
            sa_update(MaterialVocabulary).where(MaterialVocabulary.sense_id == old_id)
            .values(sense_id=new_id)
        )
        # Not a bulk `sa_update` like the one above -- an OPEN report is
        # guarded by a partial unique index on `(user_id, lexeme_sense_id)`,
        # which a blind bulk repoint can violate the moment one learner has
        # an open report on both the absorbed sense and the survivor. See
        # `_repoint_translation_reports`'s own docstring.
        await _repoint_translation_reports(session, old_id, new_id)
        # `saved_words.lexeme_sense_id` is NOT NULL (P4): a sense about to be
        # deleted must not leave a saved word pointing at it, the same
        # obligation the update above already meets for material rows and
        # the repoint just above meets for reports.
        await _repoint_saved_words(session, old_id, new_id)
        if old_id in existing:
            await session.delete(existing[old_id])
    await session.flush()

    if work.new_pos and not lexeme.pos:
        clash = (await session.exec(select(Lexeme.id).where(
            Lexeme.lemma == lexeme.lemma, Lexeme.pos == work.new_pos))).first()
        if clash is None:
            lexeme.pos = work.new_pos
    lexeme.cefr = first.cefr if first else None
    lexeme.enriched_at = datetime.now(timezone.utc)
    session.add(lexeme)
    await session.flush()


async def enrich(session_factory, gemini: Gemini, lexeme_ids: list[uuid.UUID],
                 oewn: dict[tuple[str, str], list[dict]]) -> list[LexemeWork]:
    """One unit: plan every lexeme with the model, then write them all and
    commit. Nothing is written until every model step has answered."""
    async with session_factory() as session:
        works = await load_works(session, lexeme_ids, oewn)
    await step_match(gemini, works)
    await step_gaps(gemini, works)
    await asyncio.gather(step_cefr(gemini, works), step_normalise(gemini, works))
    await step_translate(gemini, works)
    for work in works:
        finalise(work)
    async with session_factory() as session:
        for work in works:
            await apply_work(session, work)
        await session.commit()
    return works

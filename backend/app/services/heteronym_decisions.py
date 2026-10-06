"""Which pronunciation does each sense of a heteronym take? Decide once, keep
the answer in the repo, replay it anywhere.

`record` is /ˈrekɔːd/ as a noun and /rɪˈkɔːd/ as a verb, and misaki's
part-of-speech table settles that much. It cannot settle `lead` (the metal
against to lead), `close` (near against to shut, when the part of speech is
the same, or wrongly tagged), `wound`, `tear`, `bass`, `bow`, `row` ... where
the pronunciation follows the MEANING. So for every sense of every heteronym
lemma in the lexicon one model request chooses ONE of the lemma's candidate
pronunciations (:mod:`app.services.pronunciation`), given the sense's
definition and part of speech.

## One log per accent

Each accent has its OWN log and its own column, because a phoneme string
belongs to its alphabet (decision 25): British in
``heteronym_decisions.jsonl`` -> ``LexemeSense.pronunciation``, American in
``heteronym_decisions_us.jsonl`` -> ``LexemeSense.pronunciation_us``. The two
are decided separately (the candidates, and sometimes which senses are even
heteronyms, differ) and keyed identically; every function here takes the
``accent``.

## The decisions log

``app/data/tts/heteronym_decisions.jsonl``, append-only, one JSON object per
decision, committed to the repo like ``app/data/word_lists/decisions.jsonl``
and for the same reason: the answers cost money, are not reproducible, and a
wrong one teaches a learner a wrong pronunciation, so the log -- readable,
reviewable, diffable -- is the record of why each sense sounds as it does. A
later line for the same sense wins on replay.

**The key is not a database id.** The log must replay onto a database that
never saw ours (production, a fresh dev copy), where every ``LexemeSense.id``
is different. A sense is keyed by what is the same everywhere:

* ``lemma`` + ``pos`` -- the lexeme;
* ``synset`` -- the Open English WordNet synset id, when the sense has one
  (a meaning-preserving correction of its definition text then changes
  nothing);
* otherwise the ``definition`` text itself (a model-written sense has no
  synset; if its definition is edited, its decision no longer matches and it
  is decided again -- which is the right behaviour, the meaning may have
  changed).

## Applying

:func:`apply` writes the accent's column for every heteronym sense
the log answers, and ONLY those. A heteronym sense with no decision is left
NULL, and at serving time falls back to misaki's own entry for its part of
speech (``DEFAULT`` if none) and is logged -- see
:func:`app.services.pronunciation.sense_pronunciation`. Nothing is ever
guessed into the column.
"""

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, update

from app.core.database import AsyncSession
from app.models.lexicon import Lexeme, LexemeSense
from app.services import lexicon_enrich as le
from app.services import pronunciation
from app.services.accents import DEFAULT_ACCENT, Accent

logger = logging.getLogger(__name__)

DEFAULT_LOG = pronunciation.DATA_DIR / "heteronym_decisions.jsonl"
LOG_PATHS: dict[Accent, Path] = {
    "british": DEFAULT_LOG,
    "american": pronunciation.DATA_DIR / "heteronym_decisions_us.jsonl",
}
DEFAULT_MODEL = le.MODEL_MAIN

SenseKey = tuple[str, str, str, str]


def sense_key(lemma: str, pos: str, synset: str | None, definition: str) -> SenseKey:
    """The stable identity of a sense (module docstring). The definition is
    part of the key only for a sense with no synset."""
    return (
        lemma.lower().strip(),
        pos,
        synset or "",
        "" if synset else " ".join((definition or "").split()).lower(),
    )


class DecisionLog:
    """Append-only JSONL of heteronym pronunciation decisions."""

    def __init__(self, path: Path | None = DEFAULT_LOG) -> None:
        self.path = path
        self.decisions: dict[SenseKey, str] = {}
        if path is not None and path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                key = sense_key(
                    record["lemma"], record["pos"], record.get("synset"),
                    record.get("definition", ""),
                )
                self.decisions[key] = record["ps"]

    @classmethod
    def for_accent(cls, accent: Accent) -> "DecisionLog":
        return cls(LOG_PATHS[accent])

    def put(
        self, lemma: str, pos: str, synset: str | None, definition: str,
        ps: str, model: str,
    ) -> None:
        self.decisions[sense_key(lemma, pos, synset, definition)] = ps
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "lemma": lemma.lower().strip(),
            "pos": pos,
            "synset": synset,
            "definition": definition,
            "ps": ps,
            "ipa": pronunciation.to_ipa(ps),
            "model": model,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def get(self, lemma: str, pos: str, synset: str | None, definition: str) -> str | None:
        return self.decisions.get(sense_key(lemma, pos, synset, definition))


@dataclass(frozen=True)
class SenseRow:
    """The few facts about a sense that decisions need. Plain columns, not the
    ORM entity, on purpose: ``decide`` only READS the lexicon and must work on
    a database that has not been migrated to the ``pronunciation`` column yet
    (the dev database is migrated after a backup, later)."""

    sense_id: uuid.UUID
    lemma: str
    pos: str
    synset: str | None
    definition: str


async def heteronym_senses(
    session: AsyncSession, accent: Accent = DEFAULT_ACCENT
) -> list[SenseRow]:
    """Every sense (with a definition) of every lemma that is a heteronym in
    ``accent`` in the lexicon. Proper nouns are not vocabulary and are left
    out."""
    lemmas = pronunciation.heteronym_lemmas(accent)
    rows = (
        await session.execute(
            select(
                LexemeSense.id, Lexeme.lemma, Lexeme.pos,
                LexemeSense.oewn_synset_id, LexemeSense.definition_en,
            )
            .join(LexemeSense, LexemeSense.lexeme_id == Lexeme.id)
            .where(Lexeme.is_proper_noun.is_(False), LexemeSense.definition_en != "")
            .order_by(Lexeme.lemma, Lexeme.pos, LexemeSense.sense_rank)
        )
    ).all()
    return [
        SenseRow(sense_id, lemma, pos, synset, definition)
        for sense_id, lemma, pos, synset, definition in rows
        if lemma.lower().strip() in lemmas
    ]


PROMPT = """You decide how an English word is PRONOUNCED in a given meaning, for \
a {accent} English text-to-speech voice used in an English-learning app.

Below is one word with its possible pronunciations, numbered, in approximate IPA \
({accent}), each with a note on what it is used for where we have one. Then come \
numbered senses of the word, each with its part of speech and definition. For \
EVERY sense choose the number of the pronunciation a {accent} speaker uses for the \
word in THAT meaning. Decide by the meaning and the definition, not by which \
pronunciation is more common. If no listed pronunciation fits a sense, answer 0.

Reply with ONLY a JSON object mapping each sense key to the number, for example \
{{"s1": 2, "s2": 1}}.

WORD: {lemma}

PRONUNCIATIONS:
{candidates}

SENSES:
{senses}
"""


def render_prompt(
    lemma: str,
    candidates: tuple[pronunciation.Candidate, ...],
    senses: list[tuple[str, str, str]],
    accent: Accent = DEFAULT_ACCENT,
) -> str:
    """The request for one lemma. ``senses`` are ``(key, pos, definition)``."""
    lines = []
    for number, candidate in enumerate(candidates, 1):
        note = f" -- {candidate.note}" if candidate.note else ""
        tags = f" [misaki tags: {', '.join(candidate.tags)}]" if candidate.tags and not note else ""
        lines.append(f"{number}. /{pronunciation.to_ipa(candidate.ps)}/{note}{tags}")
    sense_lines = [
        f'{key}: ({pos or "no part of speech"}) {definition}'
        for key, pos, definition in senses
    ]
    return PROMPT.format(
        accent=accent.capitalize(), lemma=lemma,
        candidates="\n".join(lines), senses="\n".join(sense_lines),
    )


def parse_choices(reply: dict[str, Any] | None, keys: list[str], size: int) -> dict[str, int]:
    """``{sense key: candidate number}`` for every key the reply answered with
    a valid number 1..size. Model output is untrusted: anything else (0, a
    word, an out-of-range number, a missing key) is simply no decision."""
    out: dict[str, int] = {}
    if not isinstance(reply, dict):
        return out
    for key in keys:
        value = reply.get(key)
        try:
            number = int(str(value).strip().rstrip("."))
        except (TypeError, ValueError):
            continue
        if 1 <= number <= size:
            out[key] = number
    return out


@dataclass
class DecideReport:
    lemmas: int = 0
    senses: int = 0
    replayed: int = 0
    decided: int = 0
    undecided: list[str] = field(default_factory=list)


async def decide(
    gemini: le.Gemini,
    log: DecisionLog,
    items: list[SenseRow],
    *,
    model: str = DEFAULT_MODEL,
    concurrency: int = 6,
    limit: int | None = None,
    accent: Accent = DEFAULT_ACCENT,
) -> DecideReport:
    """Ask the model for every sense the log cannot already answer: one
    request per lemma, covering all its undecided senses. Appends each answer
    to the log as it arrives (a crash costs nothing already paid for)."""
    report = DecideReport()
    by_lemma: dict[str, list[SenseRow]] = defaultdict(list)
    for row in items:
        report.senses += 1
        if log.get(row.lemma, row.pos, row.synset, row.definition):
            report.replayed += 1
            continue
        by_lemma[row.lemma.lower().strip()].append(row)
    lemmas = sorted(by_lemma)[: limit if limit is not None else None]
    report.lemmas = len(lemmas)
    semaphore = asyncio.Semaphore(concurrency)

    async def one(lemma: str) -> None:
        candidates = pronunciation.candidates(lemma, accent)
        pairs = by_lemma[lemma]
        keys = [f"s{i}" for i in range(1, len(pairs) + 1)]
        prompt = render_prompt(
            lemma, candidates,
            [(k, row.pos, row.definition) for k, row in zip(keys, pairs)],
            accent,
        )
        async with semaphore:
            reply = await gemini.ask(model, prompt, step="heteronym", max_tokens=2048)
        choices = parse_choices(reply, keys, len(candidates))
        for key, row in zip(keys, pairs):
            number = choices.get(key)
            if number is None:
                report.undecided.append(f"{lemma} ({row.pos}): {row.definition[:60]}")
                continue
            log.put(
                row.lemma, row.pos, row.synset, row.definition,
                candidates[number - 1].ps, model,
            )
            report.decided += 1

    await asyncio.gather(*(one(lemma) for lemma in lemmas))
    return report


@dataclass
class ApplyReport:
    heteronym_senses: int = 0
    written: int = 0
    unchanged: int = 0
    undecided: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    #: stale answers whose previously written column was set back to NULL.
    cleared: int = 0


async def apply(
    session: AsyncSession, log: DecisionLog, accent: Accent = DEFAULT_ACCENT
) -> ApplyReport:
    """Write the accent's column (``pronunciation`` / ``pronunciation_us``)
    from the log for every heteronym sense it answers (module docstring). A logged answer that is not one of
    the lemma's CURRENT candidates (the extras table changed under it) is
    reported, not written, and any value an earlier apply left in the column is
    set to NULL (serving then uses misaki's POS entry). Commits."""
    report = ApplyReport()
    column = "pronunciation_us" if accent == "american" else "pronunciation"
    current = dict(
        (
            await session.execute(select(LexemeSense.id, getattr(LexemeSense, column)))
        ).all()
    )
    for row in await heteronym_senses(session, accent):
        report.heteronym_senses += 1
        ps = log.get(row.lemma, row.pos, row.synset, row.definition)
        label = f"{row.lemma} ({row.pos})"
        if ps is None:
            report.undecided.append(label)
            continue
        if ps not in {c.ps for c in pronunciation.candidates(row.lemma, accent)}:
            report.stale.append(f"{label}: {ps}")
            # Clear what an earlier apply wrote: a phoneme string that is no
            # longer a candidate would be served as is, so serving falls back
            # to misaki's own entry instead.
            if current.get(row.sense_id) is not None:
                await session.execute(
                    update(LexemeSense)
                    .where(LexemeSense.id == row.sense_id)
                    .values({column: None})
                )
                report.cleared += 1
                logger.warning(
                    "heteronym %s: logged %r is no longer a candidate in %s; "
                    "cleared, serving falls back to misaki's own",
                    label, ps, accent,
                )
            continue
        if current.get(row.sense_id) == ps:
            report.unchanged += 1
            continue
        await session.execute(
            update(LexemeSense).where(LexemeSense.id == row.sense_id).values({column: ps})
        )
        report.written += 1
    await session.commit()
    return report

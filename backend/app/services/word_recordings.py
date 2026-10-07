"""Human recordings of words: which one a sense takes, and how it is stored.

A word is spoken by a person where the dictionary has a recording for the
learner's accent (``vocabulary_settings.word_voice = 'recorded'``, the
default) and by Kokoro otherwise (:mod:`app.services.word_audio` decides at
request time; this module decides, once, what the ``word_recordings`` table
holds). Definitions are always Kokoro.

## Nothing from the source is committed

The repository is PUBLIC and the recordings, the transcriptions and the
headword list belong to the Cambridge Advanced Learner's Dictionary. The
files are copied into storage (``rec/``, local ``media/`` in dev, R2 in
production -- the same places the TTS renders go, never the repository); the
transcription stays in the private index (``app/data/private/cald/``);
the reports of an import go there too. Tests generate their own tones.

## Which recording a sense takes (agreed 2026-10-07)

A heteronym is the case that decides everything: `record` the noun and the
verb are two different recordings in the source, so "the recording of the
word" is not a thing -- it is the recording of a BLOCK (one part of speech
and guideword of an entry).

* A sense with a ``cald_ref`` (``entry#block#sense``) takes the recording of
  THE BLOCK its ref points into. Right by construction, heteronyms included.
* A sense with none, whose lexeme the matcher found a headword for
  (``exact``/``variant``, or a headword it lists without defining): when the lemma is NOT a heteronym in either accent
  (:func:`app.services.pronunciation.is_heteronym`) every block of that
  part of speech is said the same way, so the first such block with a
  recording is taken (``basis = 'pos'``). When it IS a heteronym we cannot
  tell which block is ours, so it is Kokoro with the phonemes we decided.
* No headword: Kokoro.

Two more guards, because a block is only ever a recording of its OWN headword
(:func:`speaks`): a sense whose ref points into another word's block (a plural
mapped to its singular's page, `went` to `go`, a phrase sense inside the
page of one of its words) would say the wrong word, so it falls back too.
The accent only picks the file: British the ``uk`` recording, American the
``us`` one; a block with none for that accent falls back for THAT accent.

## One format

Recordings are decoded, trimmed (:func:`app.services.tts.trim_edges`), levelled
(:func:`app.services.audio_pcm.normalise_rms`) and encoded exactly as a TTS
render is (24 kHz mono AAC in MP4): the source is a mix of 16 kHz and 44.1 kHz
files at unrelated levels, and On the go plays a recording and a synthetic
definition one after the other. Stored under ``rec/<sha256>.m4a`` -- the hash
of the normalised bytes, so two senses on one block share one file, and the
import is idempotent at the storage layer too.

## The import

:func:`plan` is pure and decides everything; :func:`run_import` does the
work and is resumable (a ``(sense, accent)`` row already holding the planned
source file is skipped) and idempotent. CPU work -- decoding and encoding --
runs in a process pool, a bounded window of files at a time.
:func:`attach_for_lexemes` is the worker's hook for senses created after the
full run.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import settings
from app.services import audio_pcm, pronunciation
from app.services.accents import ACCENT_NAMES, Accent
from app.services.storage import get_storage, recording_storage_key, sha256_hex

logger = logging.getLogger("app.services.word_recordings")

AUDIO_MIME = "audio/mp4"

#: Our accent -> the source's key for it.
SOURCE_ACCENT: dict[Accent, str] = {"british": "uk", "american": "us"}

#: How a pick was made: from the sense's own ref, or from the lemma's part
#: of speech.
BASIS_REF = "ref"
BASIS_POS = "pos"

#: Why a (sense, accent) is Kokoro, the keys of the report's fallback tally.
NO_HEADWORD = "no-headword"  # the matcher found nothing (suffixed with its kind)
HETERONYM = "heteronym-no-ref"
REF_UNKNOWN = "ref-not-in-index"
OTHER_WORD = "block-is-another-word"
NO_ACCENT = "no-recording-for-accent"
FILE_MISSING = "file-missing"
UNDECODABLE = "undecodable"

_said: set[str] = set()


def _say_once(key: str, level: int, message: str, *args: object) -> None:
    if key not in _said:
        _said.add(key)
        logger.log(level, message, *args)


# --- Normalising one file ------------------------------------------------------------


class EmptyRecording(ValueError):
    """The file decoded to nothing, or to digital silence."""


@dataclass(frozen=True)
class Normalised:
    data: bytes
    duration_ms: int
    #: Levels before and after, dBFS RMS -- for the import's report.
    rms_in_dbfs: float
    rms_out_dbfs: float
    peak_out: float


def normalise(raw: bytes) -> Normalised:
    """``raw`` (any file PyAV reads) as one stored recording: decoded to 24 kHz
    mono, edges trimmed like a TTS render's, RMS-levelled, encoded to m4a.
    Synchronous and pure -- the importer runs it in a worker process."""
    pcm = audio_pcm.decode(raw)
    if len(pcm) == 0:
        raise EmptyRecording("the file has no audio")
    # Imported here: `tts` pulls in the database layer, and this runs in every
    # pool worker -- they should pay for it once, not at module import.
    from app.services import tts

    trimmed = tts.trim_edges(pcm)
    levelled = audio_pcm.normalise_rms(trimmed)
    if float(np.max(np.abs(levelled))) < 1e-4:
        raise EmptyRecording("the file is silent")
    return Normalised(
        data=audio_pcm.encode_m4a(levelled),
        duration_ms=audio_pcm.duration_ms(levelled),
        rms_in_dbfs=float(audio_pcm.rms_dbfs(trimmed)),
        rms_out_dbfs=float(audio_pcm.rms_dbfs(levelled)),
        peak_out=float(np.max(np.abs(levelled))),
    )


def process_file(path: str) -> Normalised | str:
    """The pool's unit of work: the file at ``path`` normalised, or the reason
    it could not be (a string -- an exception from a worker process would take
    the pool's pickling with it)."""
    try:
        with open(path, "rb") as handle:
            return normalise(handle.read())
    except EmptyRecording as exc:
        return f"{UNDECODABLE}: {exc}"
    except Exception as exc:  # noqa: BLE001 - a corrupt file is a result, not a crash
        return f"{UNDECODABLE}: {type(exc).__name__}: {exc}"


# --- Which recording --------------------------------------------------------------------


@dataclass(frozen=True)
class Pick:
    #: Path relative to the source directory (``media/audio/<file>.mp3``).
    path: str
    basis: str

    @property
    def file_name(self) -> str:
        return self.path.rsplit("/", 1)[-1]


@dataclass(frozen=True)
class SenseRow:
    id: uuid.UUID
    lexeme_id: uuid.UUID
    lemma: str
    pos: str
    cald_ref: str | None


def lemma_forms(lemma: str, index: Any) -> set[str]:
    """Every spelling a block's own headword may have and still be THIS word:
    the lemma, its phrase normalisations, hyphen/space/closed variants, the
    British/American spellings, and the dictionary's own alias for it."""
    from app.services.lexicon_cald import (
        alias_is_same,
        clean_text,
        hyphen_variants,
        phrase_forms,
        spelling_variants,
    )

    base = clean_text(lemma).lower()
    forms = {base} | phrase_forms(base) | hyphen_variants(base) | spelling_variants(base, 2)
    canonical = index.aliases.get(base)
    if canonical and alias_is_same(base, canonical):
        forms.add(str(canonical).lower())
    return forms


def speaks(forms: set[str], block: dict) -> bool:
    """Whether the block's recording is of the word ``forms`` describes: its own
    headword (or, for a redirect or a phrasal-verb page, the page's key), or a
    variant spelling it lists. A derived sub-entry's key is NOT its word
    (`busker` sits under `busk`)."""
    from app.services.lexicon_cald import phrase_forms

    own = {str(block["hw"]).lower()} | phrase_forms(block["hw"])
    if block.get("redirect") or block.get("base"):
        own.add(str(block["key"]).lower())
    own |= {str(v["word"]).lower() for v in block.get("variants") or []}
    return bool(own & forms)


def _block_audio(block: dict, accent: Accent) -> str | None:
    part = (block.get("pron") or {}).get(SOURCE_ACCENT[accent]) or {}
    return part.get("audio") or None


def is_heteronym_either(lemma: str) -> bool:
    return any(pronunciation.is_heteronym(lemma, accent) for accent in ACCENT_NAMES)


@dataclass
class Plan:
    """What an import would do. ``picks`` is every planned (sense, accent);
    ``todo`` those not already in the table with the same source file, grouped
    by source file so a file shared by many senses is processed once."""

    senses: int = 0
    picks: dict[tuple[uuid.UUID, Accent], Pick] = field(default_factory=dict)
    #: fallback reason -> accent -> count
    fallbacks: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    #: reason -> a few lemmas, for the private report
    examples: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    todo: dict[str, list[tuple[uuid.UUID, Accent, str]]] = field(default_factory=dict)
    already: int = 0

    def covered(self, accent: Accent) -> int:
        return sum(1 for (_, a) in self.picks if a == accent)

    def fall_back(self, reason: str, accent: Accent, lemma: str) -> None:
        self.fallbacks[reason][accent] += 1
        if len(self.examples[reason]) < 25 and lemma not in self.examples[reason]:
            self.examples[reason].append(lemma)


def _undefined_headword(index: Any, row: SenseRow) -> dict[Accent, Pick | str]:
    """A headword the dictionary lists without defining (`abandonment` under
    `abandon`, examples only) still has its own recording. Its entries are the
    DISTINCT pronunciations it has, each with the classes of the blocks that
    use it; the first entry for a part of speech compatible with the lexeme's,
    that has a recording for the accent, is taken (a lemma that is a heteronym
    never gets here)."""
    from app.services.lexicon_cald import _is_multiword, clean_text, compatible

    lemma = clean_text(row.lemma).lower()
    multi = _is_multiword(lemma)
    entries = [
        entry for entry in index.undefined_pron.get(lemma, [])
        if any(compatible(row.pos, cls, multi) for cls in entry["classes"])
    ]
    out: dict[Accent, Pick | str] = {}
    for accent in ACCENT_NAMES:
        part = next((e["pron"].get(SOURCE_ACCENT[accent]) for e in entries
                     if (e["pron"].get(SOURCE_ACCENT[accent]) or {}).get("audio")), None)
        out[accent] = Pick(part["audio"], BASIS_POS) if part else NO_ACCENT
    return out


def plan_sense(
    index: Any,
    row: SenseRow,
    *,
    match: Any,
    forms: set[str],
    heteronym: bool,
) -> dict[Accent, Pick | str]:
    """``{accent: Pick | reason}`` for one sense: see the module docstring.
    ``match`` is ``index.match(lemma, pos)``, ``forms`` is :func:`lemma_forms`."""
    if row.cald_ref:
        found = index.senses.get(row.cald_ref)
        if found is None:
            return {accent: REF_UNKNOWN for accent in ACCENT_NAMES}
        blocks, basis = [found[0]], BASIS_REF
    else:
        if match.kind not in ("exact", "variant", "no-definition"):
            return {accent: f"{NO_HEADWORD}:{match.kind}" for accent in ACCENT_NAMES}
        if heteronym:
            return {accent: HETERONYM for accent in ACCENT_NAMES}
        if match.kind == "no-definition":
            return _undefined_headword(index, row)
        seen: set[str] = set()
        blocks, basis = [], BASIS_POS
        for ref in match.refs:
            block = index.senses[ref][0]
            if block["id"] not in seen:
                seen.add(block["id"])
                blocks.append(block)
    blocks = [block for block in blocks if speaks(forms, block)]
    out: dict[Accent, Pick | str] = {}
    for accent in ACCENT_NAMES:
        if not blocks:
            out[accent] = OTHER_WORD
            continue
        path = next((p for p in (_block_audio(b, accent) for b in blocks) if p), None)
        out[accent] = Pick(path, basis) if path else NO_ACCENT
    return out


def plan(
    index: Any,
    senses: Iterable[SenseRow],
    existing: dict[tuple[uuid.UUID, str], str],
    *,
    source_dir: Path | None = None,
) -> Plan:
    """The whole decision. ``existing`` is ``{(sense id, accent): source file
    name}`` already in ``word_recordings``; ``source_dir`` (when given) lets a
    pick whose file is not there fall back as ``file-missing`` instead of
    failing the import later."""
    result = Plan()
    matches: dict[tuple[str, str], Any] = {}
    forms_of: dict[str, set[str]] = {}
    hetero: dict[str, bool] = {}
    on_disk: dict[str, bool] = {}
    for row in senses:
        result.senses += 1
        key = (row.lemma, row.pos)
        if key not in matches:
            matches[key] = index.match(row.lemma, row.pos)
        if row.lemma not in forms_of:
            forms_of[row.lemma] = lemma_forms(row.lemma, index)
            hetero[row.lemma] = is_heteronym_either(row.lemma)
        decided = plan_sense(
            index, row, match=matches[key], forms=forms_of[row.lemma],
            heteronym=hetero[row.lemma],
        )
        for accent, pick in decided.items():
            if isinstance(pick, str):
                result.fall_back(pick, accent, row.lemma)
                continue
            if source_dir is not None:
                if pick.path not in on_disk:
                    on_disk[pick.path] = (source_dir / pick.path).is_file()
                if not on_disk[pick.path]:
                    result.fall_back(FILE_MISSING, accent, row.lemma)
                    continue
            result.picks[(row.id, accent)] = pick
            if existing.get((row.id, accent)) == pick.file_name:
                result.already += 1
            else:
                result.todo.setdefault(pick.path, []).append((row.id, accent, pick.basis))
    return result


def restrict(decided: Plan, senses: Iterable[SenseRow], limit: int) -> Plan:
    """``decided`` cut to the first ``limit`` lexemes (in ``senses`` order)
    that still have something to import -- a smoke test, and a way to do a
    little at a time. The coverage figures (``picks``, ``fallbacks``) stay
    those of the whole plan."""
    owner = {row.id: row.lexeme_id for row in senses}
    pending = {sense_id for rows in decided.todo.values() for sense_id, _, _ in rows}
    chosen: list[uuid.UUID] = []
    for row in senses:
        if row.id in pending and row.lexeme_id not in chosen:
            chosen.append(row.lexeme_id)
            if len(chosen) >= limit:
                break
    keep = set(chosen)
    cut = Plan(senses=decided.senses, picks=decided.picks, fallbacks=decided.fallbacks,
               examples=decided.examples, already=decided.already)
    for path, rows in decided.todo.items():
        kept = [r for r in rows if owner.get(r[0]) in keep]
        if kept:
            cut.todo[path] = kept
    return cut


# --- Reading the database --------------------------------------------------------------


async def has_table(conn: Any) -> bool:
    """Whether the migration has run here (the dry run reads a database it may
    not have reached)."""
    from sqlalchemy import text

    return bool((await conn.execute(text(
        "select count(*) from information_schema.tables where table_schema = current_schema() "
        "and table_name = 'word_recordings'"))).scalar_one())


async def load_senses(
    conn: Any, *, lexeme_ids: list[uuid.UUID] | None = None, lemmas: list[str] | None = None,
) -> list[SenseRow]:
    """Every sense of every vocabulary lexeme (no proper nouns, no function
    words -- neither is practised), in a stable order. ``conn`` is anything
    with ``execute`` (a read-only connection, or the import's session)."""
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import ARRAY, UUID
    from sqlalchemy import String

    sql = (
        "select s.id, s.lexeme_id, l.lemma, l.pos, s.cald_ref from lexeme_senses s "
        "join lexemes l on l.id = s.lexeme_id "
        "where not l.is_proper_noun and not l.is_function_word")
    params: dict[str, Any] = {}
    binds = []
    if lexeme_ids is not None:
        sql += " and l.id = any(:ids)"
        params["ids"] = list(lexeme_ids)
        binds.append(bindparam("ids", type_=ARRAY(UUID(as_uuid=True))))
    if lemmas is not None:
        sql += " and l.lemma = any(:lemmas)"
        params["lemmas"] = list(lemmas)
        binds.append(bindparam("lemmas", type_=ARRAY(String())))
    stmt = text(sql + " order by l.lemma, l.pos, l.id, s.sense_rank, s.id").bindparams(*binds)
    rows = (await conn.execute(stmt, params)).all()
    return [SenseRow(r[0], r[1], r[2], r[3] or "", r[4]) for r in rows]


async def load_existing(conn: Any, sense_ids: list[uuid.UUID] | None = None) -> dict[tuple[uuid.UUID, str], str]:
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import ARRAY, UUID

    if not await has_table(conn):
        return {}
    if sense_ids is None:
        rows = (await conn.execute(text(
            "select lexeme_sense_id, accent, source_file from word_recordings"))).all()
    else:
        stmt = text(
            "select lexeme_sense_id, accent, source_file from word_recordings "
            "where lexeme_sense_id = any(:ids)"
        ).bindparams(bindparam("ids", type_=ARRAY(UUID(as_uuid=True))))
        rows = (await conn.execute(stmt, {"ids": sense_ids})).all()
    return {(r[0], r[1]): r[2] for r in rows}


# --- Doing it --------------------------------------------------------------------------


@dataclass
class ImportStats:
    files: int = 0
    rows: int = 0
    bytes: int = 0
    failed: dict[str, str] = field(default_factory=dict)
    #: per source file: (duration ms, rms in, rms out, bytes) -- the report's levels
    measured: dict[str, tuple[int, float, float, int]] = field(default_factory=dict)


async def _process(pool: ProcessPoolExecutor | None, path: str) -> Normalised | str:
    if pool is None:
        return await asyncio.to_thread(process_file, path)
    return await asyncio.get_running_loop().run_in_executor(pool, process_file, path)


async def _upsert(session: Any, rows: list[dict[str, Any]]) -> None:
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.models.word_recording import WordRecording

    for start in range(0, len(rows), 500):
        stmt = pg_insert(WordRecording).values(rows[start:start + 500])
        stmt = stmt.on_conflict_do_update(
            constraint="uq_word_recordings_sense_accent",
            set_={
                "storage_key": stmt.excluded.storage_key,
                "duration_ms": stmt.excluded.duration_ms,
                "source_file": stmt.excluded.source_file,
                "basis": stmt.excluded.basis,
                "created_at": stmt.excluded.created_at,
            },
        )
        # The connection, not `session.execute`: sqlmodel's session warns on it.
        await (await session.connection()).execute(stmt)


async def run_import(
    session_factory: Callable[[], Any],
    todo: dict[str, list[tuple[uuid.UUID, Accent, str]]],
    source_dir: Path,
    *,
    workers: int = 1,
    window: int = 64,
    progress: Callable[[int, int], None] | None = None,
) -> ImportStats:
    """Process ``todo`` (:attr:`Plan.todo`) a window of ``window`` source files
    at a time: normalise in the pool, ``storage.put``, upsert and COMMIT the
    window's rows. A killed run loses at most one window, and the next
    :func:`plan` sees the committed rows. ``workers`` <= 1 runs in a thread."""
    stats = ImportStats()
    storage = get_storage()
    paths = sorted(todo)
    pool = ProcessPoolExecutor(max_workers=workers) if workers > 1 else None
    try:
        for start in range(0, len(paths), window):
            chunk = paths[start:start + window]
            results = await asyncio.gather(*(_process(pool, str(source_dir / p)) for p in chunk))
            rows: list[dict[str, Any]] = []
            for path, result in zip(chunk, results):
                name = path.rsplit("/", 1)[-1]
                if isinstance(result, str):
                    stats.failed[name] = result
                    continue
                key = recording_storage_key(sha256_hex(result.data))
                await storage.put(key, result.data, AUDIO_MIME)
                stats.files += 1
                stats.bytes += len(result.data)
                stats.measured[name] = (
                    result.duration_ms, result.rms_in_dbfs, result.rms_out_dbfs, len(result.data)
                )
                now = datetime.now(timezone.utc)
                rows += [
                    {"id": uuid.uuid4(), "lexeme_sense_id": sense_id, "accent": accent,
                     "storage_key": key, "duration_ms": result.duration_ms,
                     "source_file": name, "basis": basis, "created_at": now}
                    for sense_id, accent, basis in todo[path]
                ]
            if rows:
                async with session_factory() as session:
                    await _upsert(session, rows)
                    await session.commit()
                stats.rows += len(rows)
            if progress:
                progress(min(start + window, len(paths)), len(paths))
    finally:
        if pool is not None:
            pool.shutdown()
    return stats


async def estimate(todo: dict[str, list[Any]], source_dir: Path, *, sample: int = 60) -> dict[str, Any]:
    """Size of the whole import, extrapolated from really normalising a
    ``sample`` of its files (spread evenly through the sorted list)."""
    paths = sorted(todo)
    if not paths or sample <= 0:
        return {"files": len(paths), "sampled": 0, "mean_bytes": 0, "estimated_mb": 0.0}
    step = max(1, len(paths) // sample)
    chosen = paths[::step][:sample]
    results = [await asyncio.to_thread(process_file, str(source_dir / p)) for p in chosen]
    good = [r for r in results if not isinstance(r, str)]
    mean = sum(len(r.data) for r in good) / max(1, len(good))
    mean_ms = sum(r.duration_ms for r in good) / max(1, len(good))
    return {"files": len(paths), "sampled": len(chosen), "failed_in_sample": len(chosen) - len(good),
            "mean_bytes": round(mean), "mean_ms": round(mean_ms),
            "estimated_mb": round(mean * len(paths) / 1_000_000, 1)}


# --- The worker's hook ---------------------------------------------------------------------


async def attach_for_lexemes(
    index: Any, lexeme_ids: Iterable[uuid.UUID], *, session_factory: Callable[[], Any] | None = None,
) -> Counter:
    """Recordings for the senses of ``lexeme_ids``, where the source directory
    (``settings.cald_source_dir``) is on this machine -- else ONE log line and
    nothing. For the lexemes the CALD hook just finished: their senses may
    have a ``cald_ref`` now. Never raises into the hook."""
    counts: Counter = Counter()
    source = settings.cald_source_dir.strip()
    if not source:
        _say_once("no-source", logging.INFO,
                  "CALD source directory not configured (cald_source_dir); new senses are spoken "
                  "by the synthetic voice")
        return counts
    source_dir = Path(source).expanduser()
    if not (source_dir / "media" / "audio").is_dir():
        _say_once(f"missing:{source_dir}", logging.WARNING,
                  "CALD source directory %s has no media/audio; no recordings attached", source_dir)
        return counts
    from app.core.database import async_session_factory

    factory = session_factory or async_session_factory
    ids = list(dict.fromkeys(lexeme_ids))
    try:
        async with factory() as session:
            conn = await session.connection()
            senses = await load_senses(conn, lexeme_ids=ids)
            existing = await load_existing(conn, [s.id for s in senses])
        decided = await asyncio.to_thread(plan, index, senses, existing, source_dir=source_dir)
        if decided.todo:
            stats = await run_import(factory, decided.todo, source_dir, workers=1)
            counts["recordings"] = stats.rows
            counts["recording files"] = stats.files
            counts["recordings failed"] = len(stats.failed)
    except Exception:  # noqa: BLE001 - audio is an enhancement of the definition pass
        logger.exception("attaching recordings failed; the synthetic voice speaks these words")
        counts["recordings error"] = 1
    return counts

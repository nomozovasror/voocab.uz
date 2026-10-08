"""Structural clean-up of the vocabulary lexicon from a reviewed decisions
file: merge senses, delete junk lexemes, merge or rename headwords, mark
function words, create phrases, add CALD senses, relink material rows.
`scripts/lexicon_restructure.py` is the command line.

Where `lexicon_ai_review` changes a sense's level or Uzbek, this changes the
SHAPE of the lexicon: which senses exist, which lexeme owns them, which
material row points where. That is destructive in a way a CEFR fix is not --
a deleted sense takes saved words, recordings and reports with it -- so every
rule below exists to make a run small, checkable and exactly reversible.

## The decisions file

JSONL, one operation per line, ``op`` and ``note`` on every line that changes
something (the ops are in :data:`OPS`; their keys in :data:`OP_KEYS`). Three
no-op lines are accepted and counted so a reviewer's whole answer can live in
one file: ``keep``, ``skip`` and ``human`` (leave a sense for a person:
`needs_review` plus `review_note`, the AI review's own path, so it shows in
Studio's queue). Unknown keys are rejected, like the AI review: a typo must not
be a silent no-op (a key starting with ``_`` is a comment and ignored).

## A dry run IS the run, rolled back

Ops are validated against the state the EARLIER ops of the same file leave
(an op that moves a lexeme's rows, then the delete of that now row-less
lexeme; a relink, then a merge). The only way to be exact about that is not
to model it: a dry run executes every op for real in one transaction, each in
a savepoint, and rolls the whole transaction back at the end. The same code
path writes and previews, so a dry run cannot say "applies" for something the
real run refuses. (The AI review's dry run is READ ONLY; this one cannot be.)
A rejected op is rolled back to its savepoint and reported with its reason;
later ops go on.

## One transaction per op, a snapshot before each commit

Each op is its own transaction (a failure writes nothing of that op, and a
long file keeps what it finished). Before the commit the op's journal record
-- the full before-image of every row it updated or deleted, the after-image
of everything it touched, and the ids of rows it created -- is appended to the
run's report file and fsynced. The journal is built by :class:`Journal`:
the op CAPTURES the rows it may touch (by pk, before changing anything) and a
``before_flush`` hook refuses any write to a row that was not captured, so an
op can never change a row the snapshot does not hold. Rows are touched through
the ORM only (the DB's own ON DELETE cascades and SET NULLs are done by hand
first, so the journal sees them).

## Undo is exact, and refuses to trample

``undo --run <id>`` walks the run's ops newest first. An op is reversed only
if every row it wrote is still exactly as it left it (after-image) and every
row it deleted is still absent; otherwise that op is reported and skipped (a
person's later edit wins). Reversal: delete what the op created, put back what
it deleted (parents first), restore what it updated -- plus the rules-file
entries the op added.

## Saved words: the one place this differs from enrichment

`lexicon_enrich._repoint_saved_words` keeps the SURVIVOR's word when a learner
has a saved word on both senses and drops the other's FSRS history. A merge
chosen by a reviewer should not cost somebody their progress, so
:func:`_merge_saved_words` keeps the word with MORE progress (more `reps`,
then the later last review; a tie keeps the survivor's) and points it at the
surviving sense. The loser's contexts move over, its review logs are kept but
detached from any saved word, its exposures, speak misses and deck memberships
fold in; its status/due/lapses are dropped (see `_fold_word`). Deleting saved
words (`delete_lexeme`) needs `"allow_saved_words": true`.

## Deleted lemmas and merged headwords must stay that way

Recorded in `app/data/lexicon_rules.json` (committed; keyed by lemma, run id
and op number only -- no reviewer notes): a REFUSED lemma is refused by the
writers (`lexicon.is_refused_lemma`; never by the learner's lookup), and an
ALIAS is consulted by `lexicon._find_or_create_lexeme` only when no lexeme has
the exact `(lemma, pos)`. Written after the op's commit, undone from the
report. Details in `app/services/CLAUDE.md`.

## What it never does

* Touch a sense a PERSON approved: not dropped, not overwritten.
* Re-enrich: `Lexeme.enriched_at` is never cleared (a new lexeme gets it set),
  and every sense it writes is locked (approved by the review account; a
  `cald` or `human` definition), so `lexicon_enrich` and the CALD apply leave
  them alone.
* Create a sense with an empty Uzbek meaning (`translate` runs first).

Everything private (reports, decision files) lives in
`app/data/private/restructure/` (gitignored; the repository is public).
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import uuid
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete as core_delete
from sqlalchemy import event, tuple_
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import insert as core_insert
from sqlalchemy import select as core_select
from sqlalchemy import update as core_update
from sqlmodel import SQLModel, select

from app.core.database import AsyncSession
from app.models.lexicon import (
    LOCKED_DEFINITION_SOURCES,
    Lexeme,
    LexemeSense,
    LexiconAiReview,
    TranslationReport,
)
from app.models.user import REVIEW_BOT_EMAIL, REVIEW_BOT_NAME, User
from app.models.vocabulary import (
    DeckWord,
    MaterialVocabulary,
    SavedWord,
    SavedWordContext,
    VocabularyReviewLog,
)
from app.models.word_audio_log import OnTheGoExposure, SpeakMiss
from app.models.word_list import WordListEntry
from app.models.word_recording import WordRecording
from app.services import lexicon as lexicon_service
from app.services import lexicon_ai_review as air
from app.services import lexicon_cald as lc
from app.services import lexicon_review
from app.services.lexicon_enrich import (
    DEF_MAX,
    UZ_MAX,
    _repoint_translation_reports,
    _repoint_word_list_entries,
)

RUN_ID = re.compile(r"^[0-9a-f]{12}$")
RESTRUCTURE_DIR = Path(__file__).resolve().parents[1] / "data" / "private" / "restructure"

OPS: tuple[str, ...] = (
    "merge_senses", "delete_lexeme", "merge_lexeme", "rename_lexeme",
    "mark_function_word", "create_phrase", "add_sense", "relink_rows", "delete_sense",
    "delete_rows", "keep", "skip", "human",
)
#: Accepted spellings of an op, normalised by `parse_op`.
OP_ALIASES = {"create_entry": "create_phrase"}
POS_VALUES = frozenset({"n", "v", "adj", "adv", "prep", "conj", "phr"})
NOOPS = frozenset({"keep", "skip", "human"})
OP_KEYS: dict[str, frozenset[str]] = {
    "merge_senses": frozenset({"lexeme_id", "keep", "drop", "cefr", "meaning_uz", "meaning_uz_alt"}),
    "delete_lexeme": frozenset({"lexeme_id", "lemma", "allow_saved_words", "refuse"}),
    "merge_lexeme": frozenset({"from", "into", "senses"}),
    "rename_lexeme": frozenset({"lexeme_id", "lemma"}),
    "mark_function_word": frozenset({"lexeme_id"}),
    "delete_sense": frozenset({"sense_id", "into"}),
    "delete_rows": frozenset({"rows"}),
    "create_phrase": frozenset({"lemma", "pos", "definition_en", "cefr", "meaning_uz", "meaning_uz_alt",
                                "cald_ref", "rows", "drop_sense", "cald_cefr", "judge",
                                "needs_review", "review_reasons"}),
    "add_sense": frozenset({"lexeme_id", "cald_ref", "definition_en", "cefr", "meaning_uz",
                            "meaning_uz_alt", "rows", "cald_cefr", "judge", "needs_review",
                            "review_reasons"}),
    "relink_rows": frozenset({"rows", "sense_id"}),
}
NOOP_KEYS: dict[str, frozenset[str]] = {
    "keep": frozenset({"lexeme_id", "headword", "lemma", "pos"}),
    "skip": frozenset({"lexeme_id", "cald_ref", "covered_by", "headword", "lemma", "pos"}),
    "human": frozenset({"lexeme_id", "sense_id"}),
}
JUDGE_REASONS = ("judge_unsure", "judge_different")
NOTE_MAX = 500
REVIEW_TAG = "Claude review (restructure)"


class Reject(Exception):
    """An op that cannot be applied; the message is the reason reported."""


class UncapturedWrite(RuntimeError):
    """An op wrote a row its journal did not capture first: a bug in the op,
    never in the data. Refused at flush, so nothing is written unrecorded."""


# --- Rules file edits -------------------------------------------------------
#
# Written only AFTER the op's database commit, from a fresh read of the file
# under a lock (a hand edit or a second tool run between two ops is never
# lost), and each write is recorded in the run report as its own `rules`
# record so undo can reverse exactly what was written.


def _alias_key(entry: dict) -> tuple[str, str]:
    return entry["from"]["lemma"], entry["from"]["pos"]


def alias_change(data: dict, sources: set[tuple[str, str]], target: tuple[str, str],
                 run_id: str, n: int) -> dict:
    """Edit ``data`` (the rules file's JSON) so every source ``(lemma, pos)``
    resolves to ``target``; returns the change, which :func:`revert_rules`
    can undo. Aliases that pointed at a source are re-pointed at ``target``
    (a chain collapses), and an alias keyed by the target itself is removed
    (the target is a real lexeme; an alias there would send it elsewhere).
    The caller has already dropped the sources that have a lexeme of their
    own: a real lexeme always beats an alias."""
    change: dict = {"set": [], "removed": []}
    aliases: list[dict] = data["aliases"]
    for entry in list(aliases):
        if _alias_key(entry) == target:
            aliases.remove(entry)
            change["removed"].append(entry)
    for entry in aliases:
        if (entry["to"]["lemma"], entry["to"]["pos"]) in sources:
            change["set"].append({"from": entry["from"], "previous_to": dict(entry["to"])})
            entry["to"] = {"lemma": target[0], "pos": target[1]}
    for src in sorted(sources):
        if src == target:
            continue
        existing = next((e for e in aliases if _alias_key(e) == src), None)
        if existing is not None:
            change["set"].append({"from": existing["from"], "previous_to": dict(existing["to"])})
            existing["to"] = {"lemma": target[0], "pos": target[1]}
        else:
            change["set"].append({"from": {"lemma": src[0], "pos": src[1]}, "previous_to": None})
            aliases.append({"from": {"lemma": src[0], "pos": src[1]},
                            "to": {"lemma": target[0], "pos": target[1]}, "run": run_id, "op": n})
    return change


def refuse_change(data: dict, lemma: str, run_id: str, n: int) -> dict:
    lemma = lemma.strip().lower()
    if any(e["lemma"].strip().lower() == lemma for e in data["refused"]):
        return {"refused_added": []}
    data["refused"].append({"lemma": lemma, "run": run_id, "op": n})
    return {"refused_added": [lemma]}


def revert_rules(data: dict, change: dict) -> None:
    """Undo one op's rules edits (newest op first, so each `previous_to` is
    what the op found)."""
    lemmas = set(change.get("refused_added", []))
    if lemmas:
        data["refused"] = [e for e in data["refused"] if e["lemma"].strip().lower() not in lemmas]
    alias_part = change.get("aliases") or {}
    for item in reversed(alias_part.get("set", [])):
        key = (item["from"]["lemma"], item["from"]["pos"])
        entry = next((e for e in data["aliases"] if _alias_key(e) == key), None)
        if item["previous_to"] is None:
            if entry is not None:
                data["aliases"].remove(entry)
        elif entry is not None:
            entry["to"] = item["previous_to"]
    data["aliases"].extend(alias_part.get("removed", []))


@contextmanager
def rules_lock():
    """An exclusive lock for a read-modify-write of the rules file."""
    path = lexicon_service.RULES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(path.suffix + ".lock"), "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def write_rules(plan: dict, run_id: str, n: int) -> dict:
    """Apply an op's rules plan (``refuse`` lemma, ``alias`` sources and
    target) to a FRESH read of the file; returns the change record."""
    with rules_lock():
        data = lexicon_service.read_rules_file()
        change: dict = {}
        if plan.get("refuse"):
            change.update(refuse_change(data, plan["refuse"], run_id, n))
        if plan.get("alias"):
            sources = {tuple(x) for x in plan["alias"]["sources"]}
            change["aliases"] = alias_change(data, sources, tuple(plan["alias"]["target"]),
                                             run_id, n)
        lexicon_service.write_rules_file(data)
    return change


def undo_rules(change: dict) -> None:
    with rules_lock():
        data = lexicon_service.read_rules_file()
        revert_rules(data, change)
        lexicon_service.write_rules_file(data)


# --- Journal ---------------------------------------------------------------

TABLES = SQLModel.metadata.tables

#: Parents first. Undo inserts in this order and deletes in reverse.
TABLE_ORDER: tuple[str, ...] = (
    "lexemes", "lexeme_senses", "material_vocabulary", "saved_words", "saved_word_contexts",
    "decks", "deck_words", "word_list_entries", "translation_reports", "word_recordings",
    "lexicon_ai_reviews", "vocabulary_review_logs", "on_the_go_exposures", "speak_misses",
)


def _ser(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_ser(v) for v in value]
    return value


def _de(column: Any, value: Any) -> Any:
    if value is None:
        return None
    try:
        python_type = column.type.python_type
    except NotImplementedError:
        return value
    if python_type is uuid.UUID:
        return uuid.UUID(value) if isinstance(value, str) else value
    if python_type is datetime:
        return datetime.fromisoformat(value) if isinstance(value, str) else value
    if python_type is date:
        return date.fromisoformat(value) if isinstance(value, str) else value
    return value


def _image(row: Any) -> dict:
    return {key: _ser(value) for key, value in dict(row).items()}


def _pk_names(table: Any) -> list[str]:
    return [c.name for c in table.primary_key.columns]


def _pk_of(table: Any, image: dict) -> dict:
    return {name: image[name] for name in _pk_names(table)}


def _row_key(table_name: str, pk: dict) -> tuple:
    return (table_name, *(str(pk[name]) for name in sorted(pk)))


class Journal:
    """What one op may touch, before and after. See the module docstring."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.images: dict[tuple, tuple[str, dict]] = {}
        self.created: dict[tuple, str] = {}
        self._listener = None

    def attach(self) -> None:
        self._listener = self._before_flush
        event.listen(self.session.sync_session, "before_flush", self._listener)

    def detach(self) -> None:
        if self._listener is not None:
            event.remove(self.session.sync_session, "before_flush", self._listener)
            self._listener = None

    def _key_of(self, obj: Any) -> tuple[str, tuple]:
        mapper = sa_inspect(obj).mapper
        table = mapper.local_table
        values = mapper.primary_key_from_instance(obj)
        pk = dict(zip(_pk_names(table), values))
        return table.name, _row_key(table.name, pk)

    def _before_flush(self, session: Any, flush_context: Any, instances: Any) -> None:
        for obj in session.new:
            name, key = self._key_of(obj)
            self.created[key] = name
        for obj in list(session.dirty):
            if not session.is_modified(obj):
                continue
            name, key = self._key_of(obj)
            if key not in self.images and key not in self.created:
                raise UncapturedWrite(f"update of {name} {key[1:]} was not captured")
        for obj in session.deleted:
            name, key = self._key_of(obj)
            if key not in self.images and key not in self.created:
                raise UncapturedWrite(f"delete of {name} {key[1:]} was not captured")

    async def capture(self, table_name: str, *, ids: list | set | None = None,
                      where: Any = None) -> list:
        """Remember the current image of the matching rows (once). Returns
        their first pk value, for chaining into the next capture."""
        if table_name not in TABLE_ORDER:
            raise UncapturedWrite(f"{table_name} is not in TABLE_ORDER (undo could not order it)")
        table = TABLES[table_name]
        stmt = core_select(table).with_for_update()
        if ids is not None:
            ids = list(ids)
            if not ids:
                return []
            stmt = stmt.where(table.c[_pk_names(table)[0]].in_(ids))
        if where is not None:
            stmt = stmt.where(where)
        out = []
        for row in (await self.session.execute(stmt)).mappings().all():
            image = _image(row)
            pk = _pk_of(table, image)
            key = _row_key(table_name, pk)
            if key not in self.created:  # made by this op: no before-image exists
                self.images.setdefault(key, (table_name, image))
            out.append(row[_pk_names(table)[0]])
        return out

    async def _current(self, table_name: str, pks: list[dict]) -> dict[tuple, dict]:
        """The rows now, by key, for ``pks`` (serialised pk dicts)."""
        table = TABLES[table_name]
        names = _pk_names(table)
        if not pks:
            return {}
        values = [tuple(_de(table.c[n], pk[n]) for n in names) for pk in pks]
        if len(names) == 1:
            clause = table.c[names[0]].in_([v[0] for v in values])
        else:
            clause = tuple_(*(table.c[n] for n in names)).in_(values)
        rows = (await self.session.execute(core_select(table).where(clause))).mappings().all()
        out = {}
        for row in rows:
            image = _image(row)
            out[_row_key(table_name, _pk_of(table, image))] = image
        return out

    async def finish(self) -> dict:
        """Classify everything captured or created, after the op's last
        flush: ``created`` / ``updated`` / ``deleted`` with their images."""
        by_table: dict[str, list[dict]] = {}
        for key, (name, image) in self.images.items():
            by_table.setdefault(name, []).append(_pk_of(TABLES[name], image))
        created_by_table: dict[str, list[dict]] = {}
        for key, name in self.created.items():
            if key in self.images:
                continue
            table = TABLES[name]
            created_by_table.setdefault(name, []).append(
                {n: v for n, v in zip(_pk_names(table), key[1:])})
        out: dict = {"created": [], "updated": [], "deleted": []}
        for name, pks in by_table.items():
            current = await self._current(name, pks)
            for pk in pks:
                key = _row_key(name, pk)
                before = self.images[key][1]
                after = current.get(key)
                if after is None:
                    out["deleted"].append({"table": name, "pk": pk, "before": before})
                elif after != before:
                    out["updated"].append({"table": name, "pk": pk, "before": before,
                                           "after": after})
        for name, pks in created_by_table.items():
            current = await self._current(name, pks)
            for pk in pks:
                after = current.get(_row_key(name, pk))
                if after is not None:  # created and deleted again: nothing to record
                    out["created"].append({"table": name, "pk": pk, "after": after})
        order = {name: i for i, name in enumerate(TABLE_ORDER)}
        for kind in out:
            out[kind].sort(key=lambda e: order.get(e["table"], 99))
        return out


async def reverse_changes(session: AsyncSession, record: dict, *, write: bool) -> list[str]:
    """Reverse one op's journal record. Returns the conflicts (empty = done,
    or, without ``write``, doable). Nothing is written when there are any."""
    conflicts: list[str] = []
    for kind in ("created", "updated", "deleted"):
        for entry in record.get(kind, []):
            if entry.get("table") not in TABLE_ORDER:
                raise ValueError(f"report names a table that is not restructurable: {entry.get('table')!r}")
    journal = Journal(session)

    async def current(entry: dict) -> dict | None:
        found = await journal._current(entry["table"], [entry["pk"]])
        return found.get(_row_key(entry["table"], entry["pk"]))

    for kind in ("created", "updated"):
        for entry in record.get(kind, []):
            now = await current(entry)
            if now is None:
                conflicts.append(f"{entry['table']} {entry['pk']} is gone")
            elif now != entry["after"]:
                changed = sorted(k for k in entry["after"] if now.get(k) != entry["after"][k])
                conflicts.append(f"{entry['table']} {entry['pk']} changed since: {changed}")
    for entry in record.get("deleted", []):
        if await current(entry) is not None:
            conflicts.append(f"{entry['table']} {entry['pk']} exists again")
    if conflicts or not write:
        return conflicts

    def values(entry: dict, image: dict) -> dict:
        table = TABLES[entry["table"]]
        return {name: _de(table.c[name], value) for name, value in image.items()}

    # Per table, parents first: restore the table's updated rows, THEN
    # re-insert its deleted ones -- a saved word an op moved onto another
    # sense must be moved back before the word it displaced comes back
    # (unique per learner and sense).
    for name in TABLE_ORDER:
        for entry in record.get("updated", []):
            if entry["table"] != name:
                continue
            table = TABLES[name]
            names = _pk_names(table)
            data = {k: v for k, v in values(entry, entry["before"]).items() if k not in names}
            stmt = core_update(table).values(**data)
            for pk_name in names:
                stmt = stmt.where(table.c[pk_name] == _de(table.c[pk_name], entry["pk"][pk_name]))
            await session.execute(stmt)
        for entry in record.get("deleted", []):
            if entry["table"] == name:
                await session.execute(
                    core_insert(TABLES[name]).values(**values(entry, entry["before"])))
    for entry in reversed(record.get("created", [])):  # children first
        table = TABLES[entry["table"]]
        stmt = core_delete(table)
        for name in _pk_names(table):
            stmt = stmt.where(table.c[name] == _de(table.c[name], entry["pk"][name]))
        await session.execute(stmt)
    await session.flush()
    return []


# --- Parsing ----------------------------------------------------------------


def _uuid(value: Any, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise Reject(f"{what} is not a uuid") from None


def _uuid_list(value: Any, what: str, *, minimum: int = 1) -> list[uuid.UUID]:
    if not isinstance(value, list) or len(value) < minimum:
        raise Reject(f"{what} must be a list of at least {minimum} uuid(s)")
    out = [_uuid(v, what) for v in value]
    if len(set(out)) != len(out):
        raise Reject(f"{what} lists the same id twice")
    return out


def _cefr(value: Any, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise Reject("cefr is required")
        return None
    if value not in lexicon_review.CEFR_LEVELS:
        raise Reject(f"cefr must be one of {list(lexicon_review.CEFR_LEVELS)}")
    return value


def _uz(value: Any, what: str, *, allow_empty: bool) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip() and not allow_empty:
        raise Reject(f"{what} is empty (run `translate` before apply)")
    text, error = air.clean_uzbek(value, allow_empty=allow_empty)
    if error:
        raise Reject(f"{what}: {error}")
    return text


def normalise_definition(text: Any) -> str:
    """A CALD definition as the existing CALD senses hold it: the source's
    cross-reference markup made readable (`clean_definition`), the label-less
    leading list dropped (`strip_label_lost_prefix`, what `plan_items` applies),
    whitespace collapsed, cut to the column."""
    if not isinstance(text, str):
        raise Reject("definition_en must be a string")
    cleaned = lc.clean_definition(text)[0]
    cleaned = lc.strip_label_lost_prefix(cleaned)
    cleaned = " ".join(cleaned.split())[:DEF_MAX]
    if not cleaned:
        raise Reject("definition_en is empty")
    return cleaned


def parse_op(raw: Any) -> dict:
    """Shape and value checks that need no database; returns the op as a dict
    with uuids parsed. Raises :class:`Reject`."""
    if not isinstance(raw, dict):
        raise Reject("an operation must be a JSON object")
    op = raw.get("op")
    if not isinstance(op, str):
        raise Reject("op must be a string")
    op = OP_ALIASES.get(op, op)
    if op not in OPS:
        raise Reject(f"op must be one of {list(OPS)}")
    note = raw.get("note", "")
    if not isinstance(note, str):
        raise Reject("note must be a string")
    note = " ".join(note.split())
    if len(note) > NOTE_MAX:
        raise Reject(f"note is longer than {NOTE_MAX} characters")
    if op in NOOPS:
        unknown = sorted(k for k in raw if k not in NOOP_KEYS[op] | {"op", "note"}
                         and not k.startswith("_"))
        if unknown:
            raise Reject(f"unknown key(s) {unknown}; allowed: {sorted(NOOP_KEYS[op])}")
        out: dict = {"op": op, "note": note}
        if op == "human" and len(note) < 3:
            raise Reject("a `human` line needs a note saying what a person must look at")
        out["lexeme_id"] = _uuid(raw.get("lexeme_id"), "lexeme_id")
        if op == "human":
            out["sense_id"] = _uuid(raw["sense_id"], "sense_id") if raw.get("sense_id") else None
        if op == "skip":
            out["cald_ref"] = raw.get("cald_ref")
            out["covered_by"] = _uuid(raw["covered_by"], "covered_by") if raw.get("covered_by") else None
        return out
    if len(note) < 3:
        raise Reject("every operation needs a note (why)")
    unknown = sorted(k for k in raw if k not in OP_KEYS[op] | {"op", "note"} and not k.startswith("_"))
    if unknown:
        raise Reject(f"unknown key(s) {unknown}; allowed: {sorted(OP_KEYS[op])}")
    out = {"op": op, "note": note}

    if op == "merge_senses":
        out["lexeme_id"] = _uuid(raw.get("lexeme_id"), "lexeme_id")
        out["keep"] = _uuid(raw.get("keep"), "keep")
        out["drop"] = _uuid_list(raw.get("drop"), "drop")
        if out["keep"] in out["drop"]:
            raise Reject("keep is also listed in drop")
        out["cefr"] = _cefr(raw.get("cefr"))
        out["meaning_uz"] = _uz(raw.get("meaning_uz"), "meaning_uz", allow_empty=False)
        out["meaning_uz_alt"] = _uz(raw.get("meaning_uz_alt"), "meaning_uz_alt", allow_empty=True)
    elif op == "delete_lexeme":
        out["lexeme_id"] = _uuid(raw.get("lexeme_id"), "lexeme_id")
        lemma = raw.get("lemma")
        if not isinstance(lemma, str) or not lemma.strip():
            raise Reject("lemma is required (the guard against a stale id)")
        out["lemma"] = lemma.strip()
        for flag in ("allow_saved_words", "refuse"):
            value = raw.get(flag, False if flag == "allow_saved_words" else True)
            if not isinstance(value, bool):
                raise Reject(f"{flag} must be true or false")
            out[flag] = value
    elif op == "merge_lexeme":
        out["from"] = _uuid(raw.get("from"), "from")
        out["into"] = _uuid(raw.get("into"), "into")
        if out["from"] == out["into"]:
            raise Reject("from and into are the same lexeme")
        senses = raw.get("senses")
        if not isinstance(senses, dict) or not senses:
            raise Reject('senses must map every from-sense id to an into-sense id or "move"')
        out["senses"] = {
            _uuid(k, "senses key"): ("move" if v == "move" else _uuid(v, "senses value"))
            for k, v in senses.items()}
    elif op == "rename_lexeme":
        out["lexeme_id"] = _uuid(raw.get("lexeme_id"), "lexeme_id")
        out["lemma"] = _lemma(raw.get("lemma"))
    elif op == "mark_function_word":
        out["lexeme_id"] = _uuid(raw.get("lexeme_id"), "lexeme_id")
    elif op in ("create_phrase", "add_sense"):
        if op == "create_phrase":
            out["lemma"] = _lemma(raw.get("lemma"))
            out["pos"] = raw.get("pos") or "phr"
            if out["pos"] not in POS_VALUES:
                raise Reject(f"pos must be one of {sorted(POS_VALUES)}")
            out["drop_sense"] = _uuid(raw["drop_sense"], "drop_sense") if raw.get("drop_sense") else None
            out["rows"] = _uuid_list(raw.get("rows"), "rows")
            ref = raw.get("cald_ref")
        else:
            out["lexeme_id"] = _uuid(raw.get("lexeme_id"), "lexeme_id")
            out["rows"] = _uuid_list(raw["rows"], "rows") if raw.get("rows") else []
            ref = raw.get("cald_ref")
            if not isinstance(ref, str) or not ref.strip():
                raise Reject("cald_ref is required")
        if ref is not None and (not isinstance(ref, str) or not ref.strip() or len(ref) > 200):
            raise Reject("cald_ref must be a non-empty string of at most 200 characters")
        out["cald_ref"] = ref.strip() if ref else None
        out["definition_en"] = normalise_definition(raw.get("definition_en"))
        out["cefr"] = _cefr(raw.get("cefr"), required=True)
        cald_cefr = raw.get("cald_cefr")
        if cald_cefr is not None and cald_cefr not in lexicon_review.CEFR_LEVELS:
            raise Reject("cald_cefr must be a CEFR level")
        out["cald_cefr"] = cald_cefr
        out["meaning_uz"] = _uz(raw.get("meaning_uz"), "meaning_uz", allow_empty=False)
        if out["meaning_uz"] is None:
            raise Reject("meaning_uz is required (run `translate` before apply)")
        out["meaning_uz_alt"] = _uz(raw.get("meaning_uz_alt"), "meaning_uz_alt",
                                    allow_empty=True) or ""
        if out["meaning_uz_alt"] and out["meaning_uz_alt"].casefold() == out["meaning_uz"].casefold():
            raise Reject("meaning_uz_alt equals meaning_uz")
        needs = raw.get("needs_review", False)
        if not isinstance(needs, bool):
            raise Reject("needs_review must be true or false")
        reasons = raw.get("review_reasons") or ([] if not needs else ["judge_unsure"])
        if not isinstance(reasons, list) or any(r not in JUDGE_REASONS for r in reasons):
            raise Reject(f"review_reasons may only hold {list(JUDGE_REASONS)}")
        out["needs_review"] = needs
        out["review_reasons"] = list(dict.fromkeys(reasons)) if needs else []
    elif op == "delete_rows":
        out["rows"] = _uuid_list(raw.get("rows"), "rows")
    elif op == "delete_sense":
        out["sense_id"] = _uuid(raw.get("sense_id"), "sense_id")
        out["into"] = _uuid(raw["into"], "into") if raw.get("into") else None
    elif op == "relink_rows":
        out["rows"] = _uuid_list(raw.get("rows"), "rows")
        out["sense_id"] = _uuid(raw.get("sense_id"), "sense_id")
    return out


def _lemma(value: Any) -> str:
    if not isinstance(value, str):
        raise Reject("lemma must be a string")
    lemma = " ".join(value.split()).lower()
    if not lemma or len(lemma) > 80:
        raise Reject("lemma must be 1-80 characters")
    return lemma


# --- Context and shared helpers ---------------------------------------------


@dataclass
class Done:
    detail: str
    outcome: str = "applied"
    #: What to write to the rules file AFTER the commit: ``{"refuse": lemma}``
    #: and/or ``{"alias": {"sources": [[lemma, pos]...], "target": [lemma, pos]}}``.
    rules: dict | None = None


@dataclass
class Ctx:
    session: AsyncSession
    journal: Journal
    bot_id: uuid.UUID
    now: datetime
    run_id: str
    gone: dict[tuple[str, str], int]
    position: int = 0

    def missing(self, table: str, ident: uuid.UUID, what: str) -> str:
        n = self.gone.get((table, str(ident)))
        if n is not None:
            return f"{what} {ident} was removed by op #{n} earlier in this file"
        return f"{what} {ident} does not exist"


def _person(sense: LexemeSense, bot_id: uuid.UUID) -> bool:
    """Approved by somebody other than the review account: a person's
    decision, never dropped or overwritten here."""
    return sense.approved_at is not None and sense.approved_by != bot_id


def _cap(name: str) -> Any:
    return TABLES[name].c


async def _lexeme(ctx: Ctx, lexeme_id: uuid.UUID, what: str = "lexeme") -> Lexeme:
    lexeme = await ctx.session.get(Lexeme, lexeme_id)
    if lexeme is None:
        raise Reject(ctx.missing("lexemes", lexeme_id, what))
    return lexeme


async def _senses_of(ctx: Ctx, lexeme_id: uuid.UUID) -> list[LexemeSense]:
    return list((await ctx.session.exec(
        select(LexemeSense).where(LexemeSense.lexeme_id == lexeme_id)
        .order_by(LexemeSense.sense_rank, LexemeSense.created_at, LexemeSense.id))).all())


async def _capture_lexeme(ctx: Ctx, *lexeme_ids: uuid.UUID) -> None:
    await ctx.journal.capture("lexemes", ids=list(lexeme_ids))
    await ctx.journal.capture("lexeme_senses", where=_cap("lexeme_senses").lexeme_id.in_(list(lexeme_ids)))


async def _capture_words(ctx: Ctx, where: Any) -> list[uuid.UUID]:
    """Saved words matching ``where`` and everything that hangs off them."""
    j = ctx.journal
    words = await j.capture("saved_words", where=where)
    if not words:
        return []
    contexts = await j.capture("saved_word_contexts",
                               where=_cap("saved_word_contexts").saved_word_id.in_(words))
    logs = _cap("vocabulary_review_logs")
    clause = logs.saved_word_id.in_(words)
    if contexts:
        clause = clause | logs.context_id.in_(contexts)
    await j.capture("vocabulary_review_logs", where=clause)
    await j.capture("on_the_go_exposures", where=_cap("on_the_go_exposures").saved_word_id.in_(words))
    await j.capture("speak_misses", where=_cap("speak_misses").saved_word_id.in_(words))
    await j.capture("deck_words", where=_cap("deck_words").saved_word_id.in_(words))
    return words


async def _capture_sense_scope(ctx: Ctx, sense_ids: list[uuid.UUID]) -> None:
    """Every row whose pointer an op over these senses may move or delete."""
    j = ctx.journal
    await j.capture("lexeme_senses", ids=sense_ids)
    await j.capture("material_vocabulary", where=_cap("material_vocabulary").sense_id.in_(sense_ids))
    await j.capture("translation_reports", where=_cap("translation_reports").lexeme_sense_id.in_(sense_ids))
    await j.capture("word_list_entries", where=_cap("word_list_entries").sense_id.in_(sense_ids))
    await j.capture("word_recordings", where=_cap("word_recordings").lexeme_sense_id.in_(sense_ids))
    await j.capture("lexicon_ai_reviews", where=_cap("lexicon_ai_reviews").sense_id.in_(sense_ids))
    await _capture_words(ctx, _cap("saved_words").lexeme_sense_id.in_(sense_ids))


def _adopt_level(row: MaterialVocabulary, sense: LexemeSense, lexeme: Lexeme) -> None:
    air._adopt_level(row, sense, lexeme)


def _progress(word: SavedWord) -> tuple[int, datetime]:
    """More ``reps`` first, then the later last review (either card)."""
    floor = datetime.min.replace(tzinfo=timezone.utc)
    reviews = [t for t in (word.passive_last_review, word.active_last_review) if t is not None]
    return word.reps, max(reviews, default=floor)


async def _fold_word(ctx: Ctx, loser: SavedWord, winner: SavedWord) -> None:
    """Fold ``loser`` into ``winner``; ``loser`` is deleted.

    * Contexts move to the winner (one per material: a duplicate is dropped).
    * The loser's review LOGS are kept as history but detached
      (`saved_word_id` NULL, `context_id` NULL where their context was
      dropped): the winner's own schedule and lapse chain are built from its
      logs and must not be extended by another card's answers.
    * Exposures, speak misses and deck memberships fold into the winner
      (recent-behaviour counters and set membership; nothing is derived from
      them that two cards could corrupt).
    * Dropped with the loser row: its `status`, FSRS state/due/stability,
      `lapses`, ladder levels and leech/suspension marks. The winner's stand."""
    s = ctx.session
    have = {c.material_id: c for c in (await s.exec(
        select(SavedWordContext).where(SavedWordContext.saved_word_id == winner.id))).all()}
    for context in (await s.exec(
            select(SavedWordContext).where(SavedWordContext.saved_word_id == loser.id))).all():
        if have.get(context.material_id) is None:
            context.saved_word_id = winner.id
            s.add(context)
            continue
        for log in (await s.exec(select(VocabularyReviewLog).where(
                VocabularyReviewLog.context_id == context.id))).all():
            log.context_id = None
            s.add(log)
        await s.flush()
        await s.delete(context)
    await s.flush()
    for log in (await s.exec(select(VocabularyReviewLog).where(
            VocabularyReviewLog.saved_word_id == loser.id))).all():
        log.saved_word_id = None
        s.add(log)
    for model in (OnTheGoExposure, SpeakMiss):
        for row in (await s.exec(select(model).where(model.saved_word_id == loser.id))).all():
            row.saved_word_id = winner.id
            s.add(row)
    decks = {dw.deck_id for dw in (await s.exec(
        select(DeckWord).where(DeckWord.saved_word_id == winner.id))).all()}
    for dw in (await s.exec(select(DeckWord).where(DeckWord.saved_word_id == loser.id))).all():
        await s.delete(dw)
        if dw.deck_id not in decks:
            s.add(DeckWord(deck_id=dw.deck_id, saved_word_id=winner.id))
    await s.flush()
    await s.delete(loser)
    await s.flush()


async def _merge_saved_words(ctx: Ctx, old_id: uuid.UUID, new_id: uuid.UUID) -> Counter:
    """Saved words on ``old_id`` move to ``new_id``. Where one learner has
    both, the word with more progress survives (see the module docstring)."""
    s = ctx.session
    stats: Counter = Counter()
    for word in (await s.exec(select(SavedWord).where(SavedWord.lexeme_sense_id == old_id))).all():
        twin = (await s.exec(select(SavedWord).where(
            SavedWord.user_id == word.user_id, SavedWord.lexeme_sense_id == new_id))).first()
        if twin is None:
            word.lexeme_sense_id = new_id
            s.add(word)
            stats["saved words repointed"] += 1
            continue
        if _progress(word) > _progress(twin):
            await _fold_word(ctx, twin, word)
            word.lexeme_sense_id = new_id
            s.add(word)
            stats["saved words merged (the dropped sense's word won)"] += 1
        else:
            await _fold_word(ctx, word, twin)
            stats["saved words merged"] += 1
    await s.flush()
    return stats


async def _absorb(ctx: Ctx, keep: LexemeSense, keep_lexeme: Lexeme,
                  drops: list[LexemeSense]) -> Counter:
    """Move everything of ``drops`` onto ``keep``, then delete them. The
    caller captured the scope. Recordings: moved where ``keep`` has none for
    that accent, else deleted (explicitly -- the cascade would be invisible to
    the journal)."""
    s = ctx.session
    stats: Counter = Counter()
    drop_ids = [d.id for d in drops]
    have = {r.accent for r in (await s.exec(
        select(WordRecording).where(WordRecording.lexeme_sense_id == keep.id))).all()}
    for rec in (await s.exec(select(WordRecording).where(
            WordRecording.lexeme_sense_id.in_(drop_ids)).order_by(WordRecording.accent))).all():
        if rec.accent in have:
            await s.delete(rec)
            stats["recordings dropped"] += 1
        else:
            rec.lexeme_sense_id = keep.id
            s.add(rec)
            have.add(rec.accent)
            stats["recordings moved"] += 1
    await s.flush()
    for row in (await s.exec(select(MaterialVocabulary).where(
            MaterialVocabulary.sense_id.in_(drop_ids)))).all():
        row.sense_id = keep.id
        row.lexeme_id = keep.lexeme_id
        _adopt_level(row, keep, keep_lexeme)
        s.add(row)
        stats["material rows moved"] += 1
    await s.flush()
    for drop in drops:
        await _repoint_translation_reports(s, drop.id, keep.id)
        stats.update(await _merge_saved_words(ctx, drop.id, keep.id))
        await _repoint_word_list_entries(s, drop.id, keep.id)
    for log in (await s.exec(select(LexiconAiReview).where(
            LexiconAiReview.sense_id.in_(drop_ids)))).all():
        await s.delete(log)
    await s.flush()
    for drop in drops:
        await s.delete(drop)
        stats["senses removed"] += 1
    await s.flush()
    return stats


async def _renumber(ctx: Ctx, lexeme: Lexeme) -> None:
    """Contiguous `sense_rank` in the existing order; `Lexeme.cefr` from the
    rank-1 sense, the way `lexicon_enrich.apply_work` does."""
    senses = await _senses_of(ctx, lexeme.id)
    for rank, sense in enumerate(senses, start=1):
        if sense.sense_rank != rank:
            sense.sense_rank = rank
            ctx.session.add(sense)
    first = senses[0] if senses else None
    cefr = first.cefr if first else None
    if lexeme.cefr != cefr:
        lexeme.cefr = cefr
        ctx.session.add(lexeme)
    await ctx.session.flush()


def _stats_text(stats: Counter) -> str:
    return ", ".join(f"{n} {what}" for what, n in stats.items() if n) or "nothing to move"


async def _has_open_report(ctx: Ctx, sense_id: uuid.UUID) -> bool:
    return (await ctx.session.exec(select(TranslationReport.id).where(
        TranslationReport.lexeme_sense_id == sense_id,
        TranslationReport.status == "open"))).first() is not None


def _approve(sense: LexemeSense, ctx: Ctx) -> None:
    sense.approved_by = ctx.bot_id
    sense.approved_at = ctx.now


def _own_rows_check(rows: list[MaterialVocabulary], ids: list[uuid.UUID], ctx: Ctx) -> None:
    found = {r.id for r in rows}
    for rid in ids:
        if rid not in found:
            raise Reject(ctx.missing("material_vocabulary", rid, "material row"))


async def _load_rows(ctx: Ctx, ids: list[uuid.UUID]) -> list[MaterialVocabulary]:
    await ctx.journal.capture("material_vocabulary", ids=ids)
    rows = list((await ctx.session.exec(
        select(MaterialVocabulary).where(MaterialVocabulary.id.in_(ids)))).all())
    _own_rows_check(rows, ids, ctx)
    return rows


# --- The ops ----------------------------------------------------------------


async def op_merge_senses(ctx: Ctx, o: dict) -> Done:
    s = ctx.session
    lexeme = await _lexeme(ctx, o["lexeme_id"])
    await _capture_lexeme(ctx, lexeme.id)
    senses = {x.id: x for x in await _senses_of(ctx, lexeme.id)}
    for sid in [o["keep"], *o["drop"]]:
        if sid not in senses:
            raise Reject(ctx.missing("lexeme_senses", sid, "sense") + f" (or is not a sense of {lexeme.lemma!r})")
    keep, drops = senses[o["keep"]], [senses[d] for d in o["drop"]]
    for drop in drops:
        if _person(drop, ctx.bot_id):
            raise Reject(f"sense {drop.id} was approved by a person; not dropped")
    change: dict[str, Any] = {}
    if o["cefr"] is not None and o["cefr"] != keep.cefr:
        if lexeme.is_proper_noun:
            raise Reject("a name has no CEFR level")
        change["cefr"] = o["cefr"]
    if o["meaning_uz"] is not None and o["meaning_uz"] != keep.meaning_uz:
        change["meaning_uz"] = o["meaning_uz"]
    if o["meaning_uz_alt"] is not None and o["meaning_uz_alt"] != keep.meaning_uz_alt:
        change["meaning_uz_alt"] = o["meaning_uz_alt"]
    if change and _person(keep, ctx.bot_id):
        raise Reject(f"sense {keep.id} was approved by a person; not overwritten")
    new_uz = change.get("meaning_uz", keep.meaning_uz)
    new_alt = change.get("meaning_uz_alt", keep.meaning_uz_alt)
    if new_alt and new_alt.casefold() == new_uz.casefold():
        raise Reject("meaning_uz_alt equals meaning_uz")

    await _capture_sense_scope(ctx, [keep.id, *[d.id for d in drops]])
    chose = any(d.approved_at is not None for d in drops) or keep.approved_at is not None
    stats = await _absorb(ctx, keep, lexeme, drops)
    if "cefr" in change:
        keep.cefr_source = "cald" if change["cefr"] == keep.cald_cefr else "ours"
    for name, value in change.items():
        setattr(keep, name, value)
    if not _person(keep, ctx.bot_id):
        _approve(keep, ctx)
        if not await _has_open_report(ctx, keep.id):
            keep.needs_review = False
    if change or chose:
        keep.review_note = f"{REVIEW_TAG}: {o['note']}"[:NOTE_MAX]
    s.add(keep)
    await s.flush()
    await _renumber(ctx, lexeme)
    return Done(f"{len(drops)} sense(s) merged into {keep.id}: {_stats_text(stats)}"
                + (f"; set {sorted(change)}" if change else ""))


async def op_delete_lexeme(ctx: Ctx, o: dict) -> Done:
    s = ctx.session
    lexeme = await _lexeme(ctx, o["lexeme_id"])
    if lexeme.lemma != o["lemma"]:
        raise Reject(f"lemma mismatch: the lexeme is {lexeme.lemma!r}, the file says {o['lemma']!r}")
    j = ctx.journal
    await _capture_lexeme(ctx, lexeme.id)
    senses = await _senses_of(ctx, lexeme.id)
    for sense in senses:
        if _person(sense, ctx.bot_id):
            raise Reject(f"sense {sense.id} was approved by a person; not deleted")
    sense_ids = [x.id for x in senses]
    mv = _cap("material_vocabulary")
    rows_clause = mv.lexeme_id == lexeme.id
    if sense_ids:
        rows_clause = rows_clause | mv.sense_id.in_(sense_ids)
    row_ids = await j.capture("material_vocabulary", where=rows_clause)
    await _capture_sense_scope(ctx, sense_ids)
    if row_ids:
        await j.capture("saved_word_contexts",
                        where=_cap("saved_word_contexts").vocabulary_id.in_(row_ids))
        await j.capture("translation_reports",
                        where=_cap("translation_reports").material_vocabulary_id.in_(row_ids))
    await j.capture("word_list_entries", where=_cap("word_list_entries").lexeme_id == lexeme.id)

    stats: Counter = Counter()
    words = list((await s.exec(select(SavedWord).where(
        SavedWord.lexeme_sense_id.in_(sense_ids)))).all()) if sense_ids else []
    word_ids = [w.id for w in words]
    users = len({w.user_id for w in words})
    if words:
        summary = f"{len(words)} saved word(s) of {users} learner(s)"
        if not o["allow_saved_words"]:
            raise Reject(f"would delete {summary}; add \"allow_saved_words\": true to confirm")
        stats["learners affected"] = users
    if word_ids:
        # What the database would SET NULL on delete, done by hand so it is
        # journaled; the review history itself stays (it carries the lemma).
        for model in (VocabularyReviewLog, OnTheGoExposure, SpeakMiss):
            for row in (await s.exec(select(model).where(model.saved_word_id.in_(word_ids)))).all():
                row.saved_word_id = None
                s.add(row)
        contexts = list((await s.exec(select(SavedWordContext).where(
            SavedWordContext.saved_word_id.in_(word_ids)))).all())
        context_ids = [c.id for c in contexts]
        if context_ids:
            for log in (await s.exec(select(VocabularyReviewLog).where(
                    VocabularyReviewLog.context_id.in_(context_ids)))).all():
                log.context_id = None
                s.add(log)
        for dw in (await s.exec(select(DeckWord).where(DeckWord.saved_word_id.in_(word_ids)))).all():
            await s.delete(dw)
        await s.flush()
        for context in contexts:
            await s.delete(context)
            stats["saved-word contexts"] += 1
        await s.flush()
        for word in words:
            await s.delete(word)
            stats["saved words"] += 1
        await s.flush()
    if row_ids:
        for context in (await s.exec(select(SavedWordContext).where(
                SavedWordContext.vocabulary_id.in_(row_ids)))).all():
            context.vocabulary_id = None
            s.add(context)
        for report in (await s.exec(select(TranslationReport).where(
                TranslationReport.material_vocabulary_id.in_(row_ids)))).all():
            if report.lexeme_sense_id not in sense_ids:
                report.material_vocabulary_id = None
                s.add(report)
    if sense_ids:
        for model, column in ((TranslationReport, TranslationReport.lexeme_sense_id),
                              (WordRecording, WordRecording.lexeme_sense_id),
                              (LexiconAiReview, LexiconAiReview.sense_id)):
            for row in (await s.exec(select(model).where(column.in_(sense_ids)))).all():
                await s.delete(row)
                stats[model.__tablename__] += 1
    for entry in (await s.exec(select(WordListEntry).where(
            (WordListEntry.lexeme_id == lexeme.id)
            | (WordListEntry.sense_id.in_(sense_ids) if sense_ids else False)))).all():
        await s.delete(entry)
        stats["word-list entries"] += 1
    await s.flush()
    for row in (await s.exec(select(MaterialVocabulary).where(
            MaterialVocabulary.id.in_(row_ids)))).all() if row_ids else []:
        await s.delete(row)
        stats["material rows"] += 1
    await s.flush()
    for sense in senses:
        await s.delete(sense)
        stats["senses"] += 1
    await s.flush()
    await s.delete(lexeme)
    await s.flush()
    # Refuse the bare lemma only where that cannot block a real word: no other
    # lexeme (any pos) shares it, it does not reduce (inflection rule) to an
    # existing lexeme, and CALD does not list it as a headword. If CALD's index
    # cannot be loaded the op is rejected (or `"refuse": false` deletes only).
    reason = None
    if o["refuse"]:
        sibling = (await s.exec(select(Lexeme.pos).where(
            Lexeme.lemma == lexeme.lemma, Lexeme.id != lexeme.id))).first()
        if sibling is not None:
            reason = f"another lexeme has this lemma (pos {sibling or '-'})"
        else:
            known = set((await s.exec(select(Lexeme.lemma).where(
                Lexeme.pos == lexeme.pos, Lexeme.id != lexeme.id))).all())
            base = lexicon_service.merge_candidate(lexeme.lemma, lexeme.pos, known) \
                if lexeme.pos else None
            if base is not None:
                reason = f"it is an inflected form of the existing lexeme {base!r}"
            elif cald_has_headword(lexeme.lemma):  # raises Reject when the index is missing
                reason = "CALD lists it as a headword"
    else:
        reason = "refuse: false in the file"
    detail = (f"deleted {lexeme.lemma!r} ({lexeme.pos or '-'}): {_stats_text(stats)}; "
              f"saved words: {len(words)} of {users} learner(s)")
    if reason:
        return Done(f"{detail}; not refused: {reason}")
    return Done(f"{detail}; lemma refused in future", rules={"refuse": lexeme.lemma})


async def _without_own_lexeme(ctx: Ctx, sources: set[tuple[str, str]]) -> set[tuple[str, str]]:
    """Alias sources that have a lexeme of their own (right now, after the
    op's changes) are dropped: a real lexeme always beats an alias."""
    if not sources:
        return sources
    have = set((await ctx.session.exec(select(Lexeme.lemma, Lexeme.pos).where(
        Lexeme.lemma.in_({lemma for lemma, _ in sources})))).all())
    return {src for src in sources if src not in have}


async def op_merge_lexeme(ctx: Ctx, o: dict) -> Done:
    s = ctx.session
    src = await _lexeme(ctx, o["from"], "from lexeme")
    dst = await _lexeme(ctx, o["into"], "into lexeme")
    _check_target_lexeme(dst)
    await _capture_lexeme(ctx, src.id, dst.id)
    src_senses = {x.id: x for x in await _senses_of(ctx, src.id)}
    dst_senses = {x.id: x for x in await _senses_of(ctx, dst.id)}
    mapping: dict[uuid.UUID, Any] = o["senses"]
    unmapped = sorted(str(i) for i in src_senses if i not in mapping)
    if unmapped:
        raise Reject(f"every sense of {src.lemma!r} must be mapped; missing {unmapped}")
    for sid, target in mapping.items():
        if sid not in src_senses:
            raise Reject(ctx.missing("lexeme_senses", sid, "sense") + f" (not a sense of {src.lemma!r})")
        if target != "move":
            if target not in dst_senses:
                raise Reject(ctx.missing("lexeme_senses", target, "target sense")
                             + f" (not a sense of {dst.lemma!r})")
            if _person(src_senses[sid], ctx.bot_id):
                raise Reject(f"sense {sid} was approved by a person; not absorbed")
    await _capture_sense_scope(ctx, list(src_senses))
    await _capture_sense_scope(ctx, list({t for t in mapping.values() if t != "move"}))
    mv = _cap("material_vocabulary")
    await ctx.journal.capture("material_vocabulary", where=mv.lexeme_id == src.id)
    await ctx.journal.capture("word_list_entries", where=_cap("word_list_entries").lexeme_id == src.id)

    rows_all = list((await s.exec(select(MaterialVocabulary).where(
        MaterialVocabulary.lexeme_id == src.id))).all())
    sources = {(src.lemma, src.pos)} | {(r.lemma, r.pos or "") for r in rows_all}
    stats: Counter = Counter()
    groups: dict[uuid.UUID, list[LexemeSense]] = {}
    for sid, target in mapping.items():
        if target != "move":
            groups.setdefault(target, []).append(src_senses[sid])
    for target, drops in groups.items():
        stats.update(await _absorb(ctx, dst_senses[target], dst, drops))
    last = max((x.sense_rank for x in dst_senses.values()), default=0)
    moved = sorted((src_senses[sid] for sid, t in mapping.items() if t == "move"),
                   key=lambda x: (x.sense_rank, x.created_at, x.id))
    for i, sense in enumerate(moved, start=1):
        sense.lexeme_id = dst.id
        sense.sense_rank = last + i
        s.add(sense)
        stats["senses moved"] += 1
    await s.flush()
    for row in (await s.exec(select(MaterialVocabulary).where(
            MaterialVocabulary.lexeme_id == src.id))).all():
        row.lexeme_id = dst.id
        if dst.is_phrase:
            row.is_phrase = True
        s.add(row)
    for row in rows_all:
        if dst.pos and row.pos != dst.pos:
            row.pos = dst.pos
            s.add(row)
    stats["material rows re-homed"] = len(rows_all)
    for entry in (await s.exec(select(WordListEntry).where(WordListEntry.lexeme_id == src.id))).all():
        entry.lexeme_id = dst.id
        s.add(entry)
    await s.flush()
    await s.delete(src)
    await s.flush()
    await _renumber(ctx, dst)
    sources = await _without_own_lexeme(ctx, sources - {(dst.lemma, dst.pos)})
    plan = {"alias": {"sources": sorted(sources), "target": [dst.lemma, dst.pos]}} if sources else None
    return Done(f"{src.lemma!r} ({src.pos or '-'}) merged into {dst.lemma!r} ({dst.pos or '-'}): "
                f"{_stats_text(stats)}; aliases for {sorted(sources)}", rules=plan)


async def op_rename_lexeme(ctx: Ctx, o: dict) -> Done:
    s = ctx.session
    lexeme = await _lexeme(ctx, o["lexeme_id"])
    if lexeme.lemma == o["lemma"]:
        return Done("already has that lemma", outcome="unchanged")
    clash = (await s.exec(select(Lexeme).where(
        Lexeme.lemma == o["lemma"], Lexeme.pos == lexeme.pos))).first()
    if clash is not None:
        raise Reject(f"{o['lemma']!r} ({lexeme.pos or '-'}) already exists ({clash.id}); that is a merge_lexeme")
    await ctx.journal.capture("lexemes", ids=[lexeme.id])
    rows = list((await s.exec(select(MaterialVocabulary).where(
        MaterialVocabulary.lexeme_id == lexeme.id))).all())
    old = lexeme.lemma
    sources = {(old, lexeme.pos)} | {(r.lemma, r.pos or "") for r in rows}
    sources.discard((o["lemma"], lexeme.pos))
    lexeme.lemma = o["lemma"]
    s.add(lexeme)
    await s.flush()
    sources = await _without_own_lexeme(ctx, sources)
    plan = {"alias": {"sources": sorted(sources), "target": [o["lemma"], lexeme.pos]}} if sources else None
    return Done(f"{old!r} renamed {o['lemma']!r} ({lexeme.pos or '-'}); {len(rows)} material rows keep "
                f"their own lemma; aliases for {sorted(sources)}", rules=plan)


async def op_mark_function_word(ctx: Ctx, o: dict) -> Done:
    s = ctx.session
    lexeme = await _lexeme(ctx, o["lexeme_id"])
    await ctx.journal.capture("lexemes", ids=[lexeme.id])
    await ctx.journal.capture("material_vocabulary",
                              where=_cap("material_vocabulary").lexeme_id == lexeme.id)
    rows = list((await s.exec(select(MaterialVocabulary).where(
        MaterialVocabulary.lexeme_id == lexeme.id))).all())
    hide = [r for r in rows if not r.hidden]
    if lexeme.is_function_word and not hide:
        return Done("already marked, rows already hidden", outcome="unchanged")
    lexeme.is_function_word = True
    s.add(lexeme)
    for row in hide:
        row.hidden = True
        s.add(row)
    await s.flush()
    return Done(f"{lexeme.lemma!r} marked a function word; {len(hide)} of {len(rows)} material rows hidden")


async def _capture_old_homes(ctx: Ctx, rows: list[MaterialVocabulary]) -> None:
    """Rows are about to leave their lexemes: capture those lexemes' senses
    too (an emptied sense keeps its rank; nothing renumbers, but the journal
    must hold what it could touch)."""
    ids = {r.lexeme_id for r in rows if r.lexeme_id}
    if ids:
        await _capture_lexeme(ctx, *ids)


def _check_target_lexeme(lexeme: Lexeme) -> None:
    if lexeme.is_proper_noun or lexeme.is_function_word:
        raise Reject(f"{lexeme.lemma!r} is a name or function word; rows cannot move there")


def _move_row(row: MaterialVocabulary, sense: LexemeSense, lexeme: Lexeme, *,
              phrase: bool = False) -> bool:
    changed = row.sense_id != sense.id or row.lexeme_id != lexeme.id
    row.sense_id, row.lexeme_id = sense.id, lexeme.id
    if lexeme.pos and row.pos != lexeme.pos:
        row.pos = lexeme.pos
        changed = True
    if phrase and not row.is_phrase:
        row.is_phrase = True
        changed = True
    _adopt_level(row, sense, lexeme)
    return changed


async def op_relink_rows(ctx: Ctx, o: dict) -> Done:
    s = ctx.session
    sense = await s.get(LexemeSense, o["sense_id"])
    if sense is None:
        raise Reject(ctx.missing("lexeme_senses", o["sense_id"], "sense"))
    lexeme = await _lexeme(ctx, sense.lexeme_id)
    _check_target_lexeme(lexeme)
    rows = await _load_rows(ctx, o["rows"])
    await ctx.journal.capture("lexeme_senses", ids=[sense.id])
    moved = sum(_move_row(row, sense, lexeme) for row in rows)
    for row in rows:
        s.add(row)
    await s.flush()
    if not moved:
        return Done("every row is already there", outcome="unchanged")
    return Done(f"{moved} of {len(rows)} row(s) moved to sense {sense.id} of {lexeme.lemma!r}")


def _cald_level(ref: str | None) -> str | None:
    """CALD's level for ``ref`` from the private index, if there is one on
    this machine (loaded once per process). None otherwise."""
    if not ref:
        return None
    global _INDEX
    try:
        if _INDEX is None:
            _INDEX = lc.CaldIndex(lc.load_index_data())
        found = _INDEX.senses.get(ref)
        return (found[1].get("level") or None) if found else None
    except Exception:  # no index here: the level stays unknown
        return None


_INDEX: Any = None


def cald_has_headword(lemma: str) -> bool:
    """Whether CALD lists ``lemma`` as a headword (private index). Raises
    :class:`Reject` when the index cannot be loaded: a refusal that was not
    checked against the dictionary must not be written."""
    global _INDEX
    try:
        if _INDEX is None:
            _INDEX = lc.CaldIndex(lc.load_index_data())
    except Exception as exc:
        raise Reject(f"the CALD index could not be loaded ({type(exc).__name__}); cannot tell "
                     f"whether {lemma!r} is a headword -- fix that, or set \"refuse\": false") from exc
    return bool(_INDEX.by_form.get(lemma.lower()))


def _new_sense(lexeme: Lexeme, o: dict, ctx: Ctx, rank: int) -> LexemeSense:
    cald = o["cald_ref"] is not None
    cald_cefr = o["cald_cefr"] if o["cald_cefr"] else (_cald_level(o["cald_ref"]) if cald else None)
    sense = LexemeSense(
        lexeme_id=lexeme.id, sense_rank=rank, definition_en=o["definition_en"],
        meaning_uz=o["meaning_uz"][:UZ_MAX], meaning_uz_alt=o["meaning_uz_alt"][:UZ_MAX],
        cefr=None if lexeme.is_proper_noun else o["cefr"], source_id="model",
        licence=lc.CALD_LICENCE if cald else "proprietary",
        definition_source="cald" if cald else "human",
        cald_ref=o["cald_ref"], cald_cefr=cald_cefr,
        cefr_source="cald" if cald and cald_cefr and cald_cefr == o["cefr"] else "ours",
        provisional=False, needs_review=o["needs_review"],
        review_reasons=list(o["review_reasons"]), review_note=f"{REVIEW_TAG}: {o['note']}"[:NOTE_MAX],
    )
    _approve(sense, ctx)
    return sense


async def op_add_sense(ctx: Ctx, o: dict) -> Done:
    s = ctx.session
    lexeme = await _lexeme(ctx, o["lexeme_id"])
    await _capture_lexeme(ctx, lexeme.id)
    existing = await _senses_of(ctx, lexeme.id)
    norm = lexicon_service.normalise_meaning(o["definition_en"])
    for sense in existing:
        if sense.cald_ref == o["cald_ref"]:
            raise Reject(f"{lexeme.lemma!r} already has sense {sense.id} with cald_ref {o['cald_ref']}")
        if norm and norm == lexicon_service.normalise_meaning(sense.definition_en):
            raise Reject(f"{lexeme.lemma!r} already has sense {sense.id} with this definition")
    rows = await _load_rows(ctx, o["rows"]) if o["rows"] else []
    for row in rows:
        if row.lexeme_id != lexeme.id:
            raise Reject(f"material row {row.id} belongs to another lexeme; use relink_rows")
    sense = _new_sense(lexeme, o, ctx, max((x.sense_rank for x in existing), default=0) + 1)
    s.add(sense)
    await s.flush()
    # `enriched_at` is deliberately left alone: clearing it would send the
    # lexeme back through enrichment, which re-translates its unlocked senses.
    moved = sum(_move_row(row, sense, lexeme) for row in rows)
    for row in rows:
        s.add(row)
    await _renumber(ctx, lexeme)
    return Done(f"sense {sense.id} added at rank {sense.sense_rank} (cald_cefr "
                f"{sense.cald_cefr or 'unknown'}); {moved} row(s) moved to it")


async def op_create_phrase(ctx: Ctx, o: dict) -> Done:
    s = ctx.session
    j = ctx.journal
    rows = await _load_rows(ctx, o["rows"])
    await _capture_old_homes(ctx, rows)
    pos = o["pos"]
    is_phrase = pos == "phr" or " " in o["lemma"]
    lexeme = (await s.exec(select(Lexeme).where(
        Lexeme.lemma == o["lemma"], Lexeme.pos == pos))).first()
    created_lexeme = lexeme is None
    if lexeme is None:
        lists = lexicon_service.frequency_lists()
        lexeme = Lexeme(
            lemma=o["lemma"], pos=pos, is_phrase=is_phrase, frequency_band=lists.band(o["lemma"]),
            frequency_source=lists.source(o["lemma"]), domain_tags=lists.domain_tags(o["lemma"]),
            # Finished: enrichment would match OEWN senses onto a phrase it
            # knows nothing about and could add noise next to the CALD sense.
            enriched_at=ctx.now)
        s.add(lexeme)
        await s.flush()
        existing: list[LexemeSense] = []
    else:
        await _capture_lexeme(ctx, lexeme.id)
        existing = await _senses_of(ctx, lexeme.id)
    norm = lexicon_service.normalise_meaning(o["definition_en"])
    sense = next((x for x in existing if (o["cald_ref"] and x.cald_ref == o["cald_ref"])
                  or (norm and norm == lexicon_service.normalise_meaning(x.definition_en))), None)
    reused = sense is not None
    if sense is None:
        sense = _new_sense(lexeme, o, ctx, max((x.sense_rank for x in existing), default=0) + 1)
        s.add(sense)
        await s.flush()
    moved = sum(_move_row(row, sense, lexeme, phrase=lexeme.is_phrase) for row in rows)
    for row in rows:
        s.add(row)
    await s.flush()
    notes = [f"{'phrase' if lexeme.is_phrase else 'entry'} {'created' if created_lexeme else 'found'}: "
             f"{lexeme.lemma!r} ({pos})",
             f"sense {sense.id} {'reused' if reused else 'created'}", f"{moved} row(s) moved"]
    if o["drop_sense"]:
        drop = await s.get(LexemeSense, o["drop_sense"])
        if drop is None:
            raise Reject(ctx.missing("lexeme_senses", o["drop_sense"], "drop_sense"))
        if drop.id == sense.id:
            raise Reject("drop_sense is the phrase's own sense")
        if _person(drop, ctx.bot_id):
            raise Reject(f"sense {drop.id} was approved by a person; not dropped")
        old_lexeme = await _lexeme(ctx, drop.lexeme_id)
        await _capture_lexeme(ctx, old_lexeme.id)
        await _capture_sense_scope(ctx, [drop.id, sense.id])
        left = (await s.exec(select(MaterialVocabulary.id).where(
            MaterialVocabulary.sense_id == drop.id))).all()
        if left:
            raise Reject(f"drop_sense {drop.id} still has {len(left)} material row(s) "
                         f"(name them in this op or move them in an earlier one)")
        stats = await _absorb(ctx, sense, lexeme, [drop])
        await _renumber(ctx, old_lexeme)
        notes.append(f"sense {drop.id} of {old_lexeme.lemma!r} dropped ({_stats_text(stats)}; "
                     f"learners' saved words follow to the phrase sense)")
    if not created_lexeme:
        await _renumber(ctx, lexeme)
    elif lexeme.cefr != sense.cefr:
        lexeme.cefr = sense.cefr
        s.add(lexeme)
    await s.flush()
    notes.append("rows keep their own lemma and span (row.pos"
                 + (" and is_phrase" if lexeme.is_phrase else "") + " follow the lexeme)")
    return Done("; ".join(notes))


async def op_delete_sense(ctx: Ctx, o: dict) -> Done:
    s = ctx.session
    sense = await s.get(LexemeSense, o["sense_id"])
    if sense is None:
        raise Reject(ctx.missing("lexeme_senses", o["sense_id"], "sense"))
    lexeme = await _lexeme(ctx, sense.lexeme_id)
    await _capture_lexeme(ctx, lexeme.id)
    senses = {x.id: x for x in await _senses_of(ctx, lexeme.id)}
    if len(senses) == 1:
        raise Reject(f"the only sense of {lexeme.lemma!r}; that is delete_lexeme")
    if _person(sense, ctx.bot_id):
        raise Reject("approved by a person; not deleted")
    into = None
    if o["into"] is not None:
        into = senses.get(o["into"])
        if into is None or into.id == sense.id:
            raise Reject(ctx.missing("lexeme_senses", o["into"], "into sense")
                         + f" (or not another sense of {lexeme.lemma!r})")
    ids = [sense.id] + ([into.id] if into else [])
    await _capture_sense_scope(ctx, ids)
    sid = sense.id
    dependants = {
        "material rows": (await s.exec(select(MaterialVocabulary.id).where(
            MaterialVocabulary.sense_id == sid))).all(),
        "saved words": (await s.exec(select(SavedWord.id).where(
            SavedWord.lexeme_sense_id == sid))).all(),
        "word-list entries": (await s.exec(select(WordListEntry.id).where(
            WordListEntry.sense_id == sid))).all(),
        "translation reports": (await s.exec(select(TranslationReport.id).where(
            TranslationReport.lexeme_sense_id == sid))).all(),
    }
    used = {k: len(v) for k, v in dependants.items() if v}
    if into is None:
        if used:
            raise Reject(f"still referenced ({used}); name an `into` sense")
        for model, column in ((WordRecording, WordRecording.lexeme_sense_id),
                              (LexiconAiReview, LexiconAiReview.sense_id)):
            for row in (await s.exec(select(model).where(column == sid))).all():
                await s.delete(row)
        await s.flush()
        await s.delete(sense)
        await s.flush()
        stats = Counter({"senses removed": 1})
    else:
        stats = await _absorb(ctx, into, lexeme, [sense])
    await _renumber(ctx, lexeme)
    return Done(f"sense {sid} of {lexeme.lemma!r} deleted"
                + (f" into {into.id}" if into else "") + f": {_stats_text(stats)}")


async def op_delete_rows(ctx: Ctx, o: dict) -> Done:
    """A false match: the rows go, and so does every pointer to them that the
    database would have nulled (a saved-word context's `vocabulary_id`, a
    report's `material_vocabulary_id`) -- nulled by hand so the journal holds
    it. A saved word left without contexts stays: it is still a saved sense."""
    s = ctx.session
    rows = await _load_rows(ctx, o["rows"])
    ids = [r.id for r in rows]
    await ctx.journal.capture("saved_word_contexts",
                              where=_cap("saved_word_contexts").vocabulary_id.in_(ids))
    await ctx.journal.capture("translation_reports",
                              where=_cap("translation_reports").material_vocabulary_id.in_(ids))
    stats: Counter = Counter()
    for context in (await s.exec(select(SavedWordContext).where(
            SavedWordContext.vocabulary_id.in_(ids)))).all():
        context.vocabulary_id = None
        s.add(context)
        stats["saved-word contexts unlinked"] += 1
    for report in (await s.exec(select(TranslationReport).where(
            TranslationReport.material_vocabulary_id.in_(ids)))).all():
        report.material_vocabulary_id = None
        s.add(report)
        stats["reports unlinked"] += 1
    await s.flush()
    for row in rows:
        await s.delete(row)
    await s.flush()
    stats["material rows deleted"] = len(rows)
    return Done(_stats_text(stats))


async def op_noop(ctx: Ctx, o: dict) -> Done:
    s = ctx.session
    lexeme = await _lexeme(ctx, o["lexeme_id"])
    if o["op"] == "keep":
        return Done(f"{lexeme.lemma!r} kept", outcome="noop")
    if o["op"] == "skip":
        if o["covered_by"] is not None and await s.get(LexemeSense, o["covered_by"]) is None:
            raise Reject(ctx.missing("lexeme_senses", o["covered_by"], "covered_by sense"))
        return Done(f"{lexeme.lemma!r}: CALD sense {o['cald_ref']} not added", outcome="noop")
    # human
    await _capture_lexeme(ctx, lexeme.id)
    senses = await _senses_of(ctx, lexeme.id)
    sense = next((x for x in senses if x.id == o["sense_id"]), None) if o["sense_id"] else (
        senses[0] if senses else None)
    if sense is None:
        raise Reject(ctx.missing("lexeme_senses", o["sense_id"], "sense") if o["sense_id"]
                     else f"{lexeme.lemma!r} has no sense to flag")
    if _person(sense, ctx.bot_id):
        raise Reject("already approved by a person; not re-opened")
    note = f"{REVIEW_TAG}: {o['note']}"[:NOTE_MAX]
    if sense.review_note == note and sense.needs_review:
        return Done("same note already stored", outcome="unchanged")
    sense.review_note, sense.needs_review = note, True
    s.add(sense)
    await s.flush()
    return Done(f"sense {sense.id} of {lexeme.lemma!r} left for a person")


HANDLERS = {
    "merge_senses": op_merge_senses, "delete_lexeme": op_delete_lexeme,
    "merge_lexeme": op_merge_lexeme, "rename_lexeme": op_rename_lexeme,
    "mark_function_word": op_mark_function_word, "create_phrase": op_create_phrase,
    "add_sense": op_add_sense, "relink_rows": op_relink_rows, "delete_sense": op_delete_sense, "delete_rows": op_delete_rows,
    "keep": op_noop, "skip": op_noop, "human": op_noop,
}


# --- Results, report file ---------------------------------------------------


@dataclass
class Result:
    n: int
    op: str
    #: applied | would apply | unchanged | noop | rejected | error | undone |
    #: would undo | skipped | already undone
    outcome: str
    detail: str = ""


def read_decisions(path: Path) -> list[tuple[int, Any]]:
    """``(line number, raw)``; a line that is not JSON comes back as
    ``(n, ValueError)`` so it is reported, not dropped."""
    return air.read_decisions(path)


class Report:
    """The run's append-only JSONL file; every record is fsynced before the
    commit it describes."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: dict) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())


def report_path(out_dir: Path, run_id: str) -> Path:
    return out_dir / f"run_{run_id}.jsonl"


def read_report(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# --- Apply ------------------------------------------------------------------


async def process(
    session: AsyncSession, raw_ops: list[tuple[int, Any]], *, write: bool,
    run_id: str | None = None, out_dir: Path = RESTRUCTURE_DIR, database: str = "",
    decisions: str = "",
) -> list[Result]:
    """Run every op in file order. With ``write`` each op commits on its own
    (journal record first, see the module docstring); without it the same code
    runs and the CALLER rolls the transaction back. One :class:`Result` per
    input line, in order."""
    run_id = run_id or uuid.uuid4().hex[:12]
    results: list[Result] = []
    bot = await air.ensure_account(session)
    bot_id = bot.id
    if write:
        await session.commit()
    report = Report(report_path(out_dir, run_id)) if write else None
    if report:
        report.write({"type": "run", "run_id": run_id, "database": database,
                      "decisions": decisions, "started_at": datetime.now(timezone.utc).isoformat(),
                      "rules_path": str(lexicon_service.RULES_PATH)})
    gone: dict[tuple[str, str], int] = {}
    for position, raw in raw_ops:
        label = raw.get("op", "?") if isinstance(raw, dict) else "?"
        if isinstance(raw, Exception):
            results.append(Result(position, label, "rejected", str(raw)))
            continue
        try:
            op = parse_op(raw)
        except Reject as exc:
            results.append(Result(position, str(label), "rejected", str(exc)))
            continue
        journal = Journal(session)
        ctx = Ctx(session=session, journal=journal, bot_id=bot_id, now=datetime.now(timezone.utc),
                  run_id=run_id, gone=gone, position=position)
        nested = await session.begin_nested()
        journal.attach()
        try:
            done = await HANDLERS[op["op"]](ctx, op)
            await session.flush()
            changes = await journal.finish()
        except Reject as exc:
            journal.detach()
            await nested.rollback()
            results.append(Result(position, op["op"], "rejected", str(exc)))
            continue
        except Exception as exc:  # a bug or a constraint: this op writes nothing
            journal.detach()
            await nested.rollback()
            results.append(Result(position, op["op"], "error", f"{type(exc).__name__}: {exc}"))
            continue
        journal.detach()
        await nested.commit()
        for entry in changes["deleted"]:
            if "id" in entry["pk"]:
                gone[(entry["table"], str(entry["pk"]["id"]))] = position
        outcome = done.outcome
        if outcome == "applied" and not write:
            outcome = "would apply"
        if write and report is not None:
            record = {"type": "op", "run_id": run_id, "n": position, "op": op["op"],
                      "note": op["note"], "outcome": done.outcome, "detail": done.detail,
                      "rules_plan": done.rules or {}, **changes}
            report.write(record)
            await session.commit()
            report.write({"type": "commit", "n": position})
            if done.rules:
                # AFTER the commit, from a fresh read under a lock: a rule
                # never exists for a change that did not happen, and a hand
                # edit between ops is not overwritten. Its own record, so undo
                # reverses exactly what was written.
                try:
                    change = write_rules(done.rules, run_id, position)
                except Exception as exc:
                    results.append(Result(position, op["op"], "error",
                                          f"committed, but the rules file was NOT updated "
                                          f"({type(exc).__name__}: {exc}); {done.detail}"))
                    continue
                report.write({"type": "rules", "n": position, "change": change})
        results.append(Result(position, op["op"], outcome, done.detail))
    return results


# --- Undo -------------------------------------------------------------------


async def undo(
    session_factory: Any, run_id: str, *, write: bool, out_dir: Path = RESTRUCTURE_DIR,
    only: set[int] | None = None,
) -> list[Result]:
    """Reverse a run's ops, newest first, each in its own transaction; see the
    module docstring for what makes an op refuse."""
    if not RUN_ID.match(run_id or ""):
        raise ValueError(f"a run id is 12 hex characters, not {run_id!r}")
    path = report_path(out_dir, run_id)
    if not path.exists():
        raise FileNotFoundError(f"no report for run {run_id!r} in {out_dir}")
    records = read_report(path)
    ops = {r["n"]: r for r in records if r["type"] == "op"}
    committed = {r["n"] for r in records if r["type"] == "commit"}
    undone = {r["n"] for r in records if r["type"] == "undone"}
    rules_changes = {r["n"]: r["change"] for r in records if r["type"] == "rules"}
    report = Report(path)
    results: list[Result] = []
    for n in sorted(ops, reverse=True):
        if only is not None and n not in only:
            continue
        rec = ops[n]
        label = rec["op"]
        if n in undone:
            results.append(Result(n, label, "already undone"))
            continue
        has_changes = any(rec.get(k) for k in ("created", "updated", "deleted")) or n in rules_changes
        if not has_changes:
            if write:
                report.write({"type": "undone", "n": n, "at": datetime.now(timezone.utc).isoformat()})
            results.append(Result(n, label, "undone" if write else "would undo", "nothing was written"))
            continue
        async with session_factory() as session:
            try:
                conflicts = await reverse_changes(session, rec, write=write)
                if conflicts:
                    await session.rollback()
                    if n not in committed and n in rules_changes:
                        # Never committed (no marker) but its rules were written:
                        # take those back, there is nothing else to reverse.
                        if write:
                            undo_rules(rules_changes[n])
                            report.write({"type": "undone", "n": n,
                                          "at": datetime.now(timezone.utc).isoformat()})
                        results.append(Result(n, label, "undone" if write else "would undo",
                                              "rules only: the op never committed"))
                        continue
                    hint = "" if n in committed else " (no commit marker: probably never committed)"
                    results.append(Result(n, label, "skipped",
                                          "; ".join(conflicts[:6]) + hint))
                    continue
                if write:
                    await session.commit()
                    if n in rules_changes:
                        undo_rules(rules_changes[n])
                    report.write({"type": "undone", "n": n,
                                  "at": datetime.now(timezone.utc).isoformat()})
                else:
                    await session.rollback()
            except BaseException:
                await session.rollback()
                raise
        results.append(Result(n, label, "undone" if write else "would undo", rec.get("detail", "")))
    return results


# --- Status -----------------------------------------------------------------


def list_runs(out_dir: Path = RESTRUCTURE_DIR) -> list[dict]:
    """One summary per report file: run id, database, ops by type and
    outcome, how many are committed and how many undone."""
    runs = []
    for path in sorted(out_dir.glob("run_*.jsonl")):
        records = read_report(path)
        header = next((r for r in records if r["type"] == "run"), {})
        ops = [r for r in records if r["type"] == "op"]
        by_op = Counter(f"{r['op']}:{r['outcome']}" for r in ops)
        rows = Counter()
        for r in ops:
            for kind in ("created", "updated", "deleted"):
                rows[kind] += len(r.get(kind, []))
        runs.append({
            "run_id": header.get("run_id", path.stem[4:]), "database": header.get("database", ""),
            "started_at": header.get("started_at", ""), "decisions": header.get("decisions", ""),
            "ops": len(ops), "committed": sum(1 for r in records if r["type"] == "commit"),
            "undone": sum(1 for r in records if r["type"] == "undone"),
            "by_op": dict(sorted(by_op.items())), "rows": dict(rows), "file": str(path),
        })
    return runs


def summarise(results: list[Result]) -> dict[str, Counter]:
    table: dict[str, Counter] = {}
    for r in results:
        table.setdefault(r.op, Counter())[r.outcome] += 1
    return table


# --- Translate --------------------------------------------------------------

TRANSLATE_OPS = ("add_sense", "create_phrase", "create_entry")


def translated_path(path: Path) -> Path:
    return path.with_name(path.name + ".translated.jsonl")


async def translate_file(
    path: Path, gemini: Any, session_factory: Any, *, max_usd: float, chunk: int = 20,
    out: Path | None = None, log: Any = print,
) -> dict:
    """Fill ``meaning_uz`` / ``meaning_uz_alt`` of the `add_sense` /
    `create_phrase` lines that have none, with PRODUCTION's translation path
    for a new sense (`lexicon_enrich.step_translate`: two translators, then
    the judge twice -- no old pair exists to keep). Writes ``<file>.translated
    .jsonl`` (every other line verbatim) with a ``judge`` block per filled
    line; a verdict that is not ``same`` also sets ``needs_review`` and the
    ``judge_unsure`` / ``judge_different`` reason, which `apply` carries onto
    the sense. Stops cleanly -- remaining lines stay empty -- on the spend cap,
    on an account-level HTTP failure (402/401/403, a 429 that outlasted the
    retries) or on two chunks in a row that answered nothing."""
    from app.services import lexicon_enrich as le

    lines = path.read_text(encoding="utf-8").splitlines()
    parsed: list[Any] = []
    for line in lines:
        try:
            parsed.append(json.loads(line) if line.strip() else None)
        except ValueError:
            parsed.append(None)
    todo = [i for i, d in enumerate(parsed)
            if isinstance(d, dict) and d.get("op") in TRANSLATE_OPS
            and not str(d.get("meaning_uz") or "").strip() and d.get("definition_en")]
    lexeme_ids = {_uuid_or_none(parsed[i].get("lexeme_id")) for i in todo
                  if parsed[i]["op"] == "add_sense"} - {None}
    labels: dict[uuid.UUID, tuple[str, str]] = {}
    if lexeme_ids:
        async with session_factory() as session:
            for lexeme in (await session.exec(select(Lexeme).where(Lexeme.id.in_(lexeme_ids)))).all():
                labels[lexeme.id] = (lexeme.lemma, lexeme.pos)
            await session.rollback()
    items: list[tuple[int, str, str, str]] = []
    skipped = 0
    for i in todo:
        d = parsed[i]
        try:
            definition = normalise_definition(d["definition_en"])
        except Reject:
            skipped += 1
            continue
        if d["op"] == "add_sense":
            label = labels.get(_uuid_or_none(d.get("lexeme_id")))
            if label is None:
                skipped += 1
                continue
        else:
            label = (str(d.get("lemma") or "").strip().lower(), d.get("pos") or "phr")
            if not label[0]:
                skipped += 1
                continue
        items.append((i, label[0], label[1], definition))
    stats = {"lines": len(lines), "to_translate": len(items), "translated": 0, "invalid": 0,
             "unfilled": 0, "skipped": skipped, "stopped": None, "verdicts": Counter()}
    empty_chunks = 0
    position = 0
    while position < len(items):
        if gemini.usage.total_cost() >= max_usd:
            stats["stopped"] = f"spend cap ${max_usd:.2f} reached"
            break
        batch = items[position:position + chunk]
        works = []
        for _, lemma, pos, definition in batch:
            sense = le.Sense(id=None, definition_en=definition, translate=True)
            works.append(le.LexemeWork(
                id=uuid.uuid4(), lemma=lemma, pos=pos, is_phrase=pos == "phr", frequency_band=None,
                oewn=[], senses=[], rows=[], plan=[sense]))
        await le.step_translate(gemini, works)
        filled = 0
        for (i, *_), work in zip(batch, works):
            sense = work.plan[0]
            main, error = air.clean_uzbek(sense.meaning_uz, allow_empty=True) if sense.meaning_uz else ("", None)
            if error:
                stats["invalid"] += 1
                log(f"  line {i + 1}: translation refused by the Uzbek rules ({error}); left empty")
                continue
            if not main:
                continue
            alt, error = air.clean_uzbek(sense.meaning_uz_alt, allow_empty=True) \
                if sense.meaning_uz_alt else ("", None)
            if error or (alt and alt.casefold() == main.casefold()):
                alt = ""
            d = parsed[i]
            d["meaning_uz"], d["meaning_uz_alt"] = main, alt or ""
            verdict = sense.judge
            d["judge"] = {"verdict": verdict, "translators": [le.MODEL_MAIN, le.MODEL_ALT],
                          "judge": le.MODEL_JUDGE}
            if verdict in ("unsure", "different"):
                d["needs_review"] = True
                d["review_reasons"] = [f"judge_{verdict}"]
            stats["verdicts"][verdict or "none"] += 1
            filled += 1
        stats["translated"] += filled
        position += len(batch)
        empty_chunks = 0 if filled else empty_chunks + 1
        if gemini.hard_status is not None:
            stats["stopped"] = f"Gemini answered HTTP {gemini.hard_status}"
            break
        if empty_chunks >= 2:
            stats["stopped"] = "two chunks in a row got no usable answer"
            break
    stats["unfilled"] = len(items) - stats["translated"] - stats["invalid"] \
        if stats["stopped"] else stats["invalid"]
    target = out or translated_path(path)
    rendered = [json.dumps(d, ensure_ascii=False) if isinstance(d, dict) else lines[i]
                for i, d in enumerate(parsed)]
    target.write_text("\n".join(rendered) + "\n", encoding="utf-8")
    stats["out"] = str(target)
    stats["remaining"] = sum(1 for i, *_ in items if not str(parsed[i].get("meaning_uz") or "").strip())
    return stats


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None

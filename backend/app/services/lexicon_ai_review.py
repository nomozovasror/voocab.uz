"""AI-assisted review of the lexicon's flagged senses: export what a reviewer
needs, validate its decisions, apply them safely, take them back exactly.

2,619 senses carry `needs_review` and no person can read them all. The owner
agreed (2026-10-07) that Claude reviews them in batches, under rules that make
every decision small, checkable and reversible. This module is the engine;
`scripts/lexicon_ai_review.py` is its command line, and `REVIEW_RUBRIC`
(below) is the instruction sheet the reviewing agents read.

## What a decision may change -- and what it never may

* The sense's **CEFR**, its **Uzbek pair** (`meaning_uz`, `meaning_uz_alt`),
  and -- only behind `--allow-material-fixes` -- the **pos / sense link of a
  material row**. Never a definition: `definition_en` is not a key a decision
  can carry, and `fix_and_approve` is never called with one.
* When unsure it changes nothing and says so (`human`): the sense stays
  flagged and Studio shows the reviewer's note beside it
  (`LexemeSense.review_note`).

The writes go through the services Studio's own buttons use
(`lexicon_review.approve`, `.fix_and_approve`), so a decision has the same
effect a person's has: `needs_review` cleared with the reasons kept as
history, open learner reports closed, the lexeme's denormalised CEFR kept in
step, `cefr_source` turned to `ours` where a dictionary level was changed --
and `approved_at` set, which LOCKS the sense against `scripts/cald.py apply`
and `restore` exactly as a human approval does.

## Who approves: a system account that cannot log in

Approvals are made as the user `claude-review@voocab.local` ("Claude review").
It exists so `approved_by` names who decided and a person can find and undo
those decisions. It is inert by construction, three ways: no password and no
`auth_identities` row (nothing to log in with -- the only login routes are
Telegram and the dev account), `is_admin` false, and
`models.user.is_system_account` makes `get_current_user` and
`POST /auth/refresh` refuse it even for a token somebody minted. It is created
by `apply` (never by a dry run), idempotently.

## A decision refuses what it cannot be sure of

`plan` rejects, with the reason in the report, rather than guessing: an
unknown sense, one no longer `needs_review` (a re-run is idempotent: the
second time is "already decided"), one a person has approved, an unknown key
or value, a `low` confidence outside `human`, and **any sense with an open
learner report** -- approving closes that report, and a learner who took the
trouble to file one is owed a person's answer, so those can only be `human`.
Invalid decisions are skipped and listed; the valid ones still apply.

## Undo is exact, and refuses to trample

Every applied decision stores a `lexicon_ai_reviews` row: BEFORE values (what
undo restores), AFTER values (what undo requires to still be true) and the
material-row link changes with theirs. `undo` reverts only decisions whose
sense is still exactly as the review left it -- a person who fixed or
re-approved the sense since is respected and reported -- in one transaction.
The log row is kept (`undone_at`), so the history survives the undo. A run
is ONE transaction: a failure writes nothing.

## Material fixes (off unless asked for)

Studio's review has no action that touches a material row, and the only
mechanisms in the code are plain pointer writes (`lexicon_enrich.apply_work`
re-pointing rows to the sense that absorbed them; `lexicon.link_row` and
`vocabulary._generate` setting `lexeme_id`/`sense_id`). Two kinds are
supported, both only that: `relink_sense` (a row of this sense moves to
ANOTHER sense of the SAME lexeme) and `relink_lexeme` (a row moves to a sense
of an EXISTING lexeme with the same lemma -- the other part of speech -- and
takes its pos). Neither creates a lexeme or a sense, neither deletes
anything, both record the row's old pointers. A row's level follows the new
sense only by `link_row`'s rule (a dictionary-levelled sense's level, with the
old one kept in `cefr_level_pre_cald`).

## Where the files live

Exports hold definitions, so they -- and the decision reports -- live ONLY in
the gitignored `app/data/private/review/`. The repository is public.
"""

from __future__ import annotations

import json
import random
import re
import unicodedata
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, literal, text
from sqlalchemy import select as core_select
from sqlmodel import select

from app.core.database import AsyncSession
from app.models.lexicon import (
    REVIEW_REASONS,
    Lexeme,
    LexemeSense,
    LexiconAiReview,
    TranslationReport,
)
from app.models.user import REVIEW_BOT_EMAIL, REVIEW_BOT_NAME, User
from app.models.vocabulary import MaterialVocabulary
from app.services import lexicon_review
from app.services import lexicon as lexicon_service
from app.services.lexicon import frequency_lists

REVIEW_DIR = Path(__file__).resolve().parents[1] / "data" / "private" / "review"

ACTIONS: tuple[str, ...] = ("approve", "fix", "human")
CONFIDENCES: tuple[str, ...] = ("high", "medium", "low")
MATERIAL_FIX_KINDS: tuple[str, ...] = ("relink_sense", "relink_lexeme")
CEFR_LEVELS = lexicon_review.CEFR_LEVELS

#: Which reason a sense belongs to when it carries several, for stratified
#: sampling and for ordering batches: rarest first, so a small reason is
#: never swallowed by the 1,383-strong `cald_cefr_far`. A sense is counted
#: once, under the first of these it carries.
REASON_PRIORITY: tuple[str, ...] = (
    "judge_different",
    "ngsl_conflict",
    "pos_mismatch",
    "lemma_merge",
    "material_level_gap",
    "judge_unsure",
    "cald_cefr_far",
)

DECISION_KEYS = frozenset({
    "sense_id", "action", "cefr", "meaning_uz", "meaning_uz_alt",
    "material_fixes", "confidence", "note",
})
MATERIAL_FIX_KEYS = frozenset({"kind", "row_id", "to_sense_id"})

UZ_MAX_ITEMS = 4
UZ_MAX_ITEM_CHARS = 40
NOTE_MAX = 500
MAX_MATERIAL_FIXES = 5
#: Per sense in an export: how many of the lexeme's other senses and of the
#: material usages ride along (a reviewer needs context, not the corpus).
OTHER_SENSES_MAX = 8
USAGES_MAX = 3
DEFINITION_CLIP = 160
SENTENCE_CLIP = 300

_APOSTROPHES = str.maketrans({"ʻ": "'", "ʼ": "'", "’": "'", "‘": "'", "`": "'", "´": "'"})
_UZ_PUNCT = set("'- ().…")


def clip(text: str | None, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


# --- Uzbek validation -----------------------------------------------------


def clean_uzbek(text: Any, *, allow_empty: bool) -> tuple[str | None, str | None]:
    """``(normalised, error)``. Real, standard Latin-script Uzbek: letters of
    the Latin script, digits, spaces and ``' - ( ) .``; 1-4 comma-separated
    equivalents, each short. Typographic apostrophes become the plain ``'``
    the data already uses (``o'zbek``, ``g'isht``); a Cyrillic letter or
    anything outside the script is refused -- that is a transliteration
    problem for a person, not something to store."""
    if not isinstance(text, str):
        return None, "must be a string"
    text = " ".join(text.translate(_APOSTROPHES).split())
    if not text:
        return ("", None) if allow_empty else (None, "must not be empty")
    for ch in text:
        if ch in _UZ_PUNCT or ch == ",":
            continue
        if ch.isdigit():
            continue
        if ch.isalpha() and "LATIN" in unicodedata.name(ch, ""):
            continue
        return None, f"character {ch!r} is not Latin-script Uzbek"
    items = _split_items(text)
    if not 1 <= len(items) <= UZ_MAX_ITEMS:
        return None, f"{len(items)} equivalents (1-{UZ_MAX_ITEMS} allowed)"
    for item in items:
        if not item:
            return None, "empty equivalent between commas"
        if len(item) > UZ_MAX_ITEM_CHARS:
            return None, f"equivalent {item!r} is longer than {UZ_MAX_ITEM_CHARS} characters"
        if not any(ch.isalpha() for ch in item):
            return None, f"equivalent {item!r} has no letters"
    text = ", ".join(items)
    if len(text) > 400:
        return None, "longer than 400 characters"
    return text, None


def _split_items(text: str) -> list[str]:
    """Comma-separated, but not inside parentheses (``kuchli (jismonan)``)."""
    items, depth, current = [], 0, []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
        if ch == "," and depth == 0:
            items.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    items.append("".join(current).strip())
    return items


# --- Decisions: shape -----------------------------------------------------


@dataclass
class Decision:
    sense_id: uuid.UUID
    action: str
    confidence: str
    note: str
    cefr: str | None = None
    meaning_uz: str | None = None
    meaning_uz_alt: str | None = None
    material_fixes: list[dict] = field(default_factory=list)


def _parse_uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def parse_decision(raw: Any) -> tuple[Decision | None, str | None]:
    """Shape and value checks that need no database. ``(decision, None)`` or
    ``(None, reason)``."""
    if not isinstance(raw, dict):
        return None, "a decision must be a JSON object"
    unknown = sorted(set(raw) - DECISION_KEYS)
    if unknown:
        return None, f"unknown key(s) {unknown}; allowed: {sorted(DECISION_KEYS)}"
    sense_id = _parse_uuid(raw.get("sense_id"))
    if sense_id is None:
        return None, "sense_id is not a uuid"
    action = raw.get("action")
    if action not in ACTIONS:
        return None, f"action must be one of {list(ACTIONS)}"
    confidence = raw.get("confidence")
    if confidence not in CONFIDENCES:
        return None, f"confidence must be one of {list(CONFIDENCES)}"
    note = raw.get("note", "")
    if not isinstance(note, str):
        return None, "note must be a string"
    note = " ".join(note.split())
    if len(note) > NOTE_MAX:
        return None, f"note is longer than {NOTE_MAX} characters"
    if action == "human" and len(note) < 3:
        return None, "a `human` decision needs a note saying what a person must look at"
    if confidence == "low" and action != "human":
        return None, "low confidence can only be `human` (anything uncertain is left to a person)"

    changes = {key: raw[key] for key in ("cefr", "meaning_uz", "meaning_uz_alt", "material_fixes")
               if key in raw and raw[key] is not None}
    if action != "fix" and changes:
        return None, f"`{action}` carries no changes (got {sorted(changes)}); use `fix`"
    decision = Decision(sense_id=sense_id, action=action, confidence=confidence, note=note)
    if action != "fix":
        return decision, None

    if "cefr" in changes:
        if changes["cefr"] not in CEFR_LEVELS:
            return None, f"cefr must be one of {list(CEFR_LEVELS)}"
        decision.cefr = changes["cefr"]
    if "meaning_uz" in changes:
        value, error = clean_uzbek(changes["meaning_uz"], allow_empty=False)
        if error:
            return None, f"meaning_uz: {error}"
        decision.meaning_uz = value
    if "meaning_uz_alt" in changes:
        value, error = clean_uzbek(changes["meaning_uz_alt"], allow_empty=True)
        if error:
            return None, f"meaning_uz_alt: {error}"
        decision.meaning_uz_alt = value
    if "material_fixes" in changes:
        fixes = changes["material_fixes"]
        if not isinstance(fixes, list) or not 1 <= len(fixes) <= MAX_MATERIAL_FIXES:
            return None, f"material_fixes must be a list of 1-{MAX_MATERIAL_FIXES} objects"
        for fix in fixes:
            if not isinstance(fix, dict) or set(fix) != MATERIAL_FIX_KEYS:
                return None, f"each material fix has exactly the keys {sorted(MATERIAL_FIX_KEYS)}"
            if fix["kind"] not in MATERIAL_FIX_KINDS:
                return None, f"material fix kind must be one of {list(MATERIAL_FIX_KINDS)}"
            row_id, to_id = _parse_uuid(fix["row_id"]), _parse_uuid(fix["to_sense_id"])
            if row_id is None or to_id is None:
                return None, "material fix row_id / to_sense_id must be uuids"
            decision.material_fixes.append(
                {"kind": fix["kind"], "row_id": row_id, "to_sense_id": to_id})
        if len({f["row_id"] for f in decision.material_fixes}) != len(decision.material_fixes):
            return None, "the same material row appears twice"
    if not any((decision.cefr, decision.meaning_uz, decision.meaning_uz_alt is not None,
                decision.material_fixes)):
        return None, "`fix` with no change; use `approve`"
    return decision, None


def read_decisions(path: Path) -> list[tuple[int, Any]]:
    """``(position, raw)`` from a JSONL file or a JSON array. A line that is
    not JSON comes back as ``(position, ValueError)`` so it is reported, not
    dropped."""
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("["):
        return list(enumerate(json.loads(text), start=1))
    out: list[tuple[int, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append((number, json.loads(line)))
        except ValueError as exc:
            out.append((number, ValueError(f"not JSON: {exc}")))
    return out


# --- Snapshots ------------------------------------------------------------

_SNAPSHOT_FIELDS = ("cefr", "cefr_source", "meaning_uz", "meaning_uz_alt",
                    "needs_review", "approved_by", "approved_at", "review_note")


def snapshot(sense: LexemeSense, lexeme: Lexeme) -> dict:
    """Everything a decision can change on the sense and its lexeme, as JSON.
    BEFORE is what undo restores; AFTER is what undo requires to still hold."""
    out = {name: getattr(sense, name) for name in _SNAPSHOT_FIELDS}
    out["approved_by"] = str(out["approved_by"]) if out["approved_by"] else None
    out["approved_at"] = _iso(out["approved_at"])
    out["lexeme_cefr"] = lexeme.cefr
    return out


def _row_state(row: MaterialVocabulary) -> dict:
    return {"pos": row.pos, "lexeme_id": str(row.lexeme_id) if row.lexeme_id else None,
            "sense_id": str(row.sense_id) if row.sense_id else None,
            "cefr_level": row.cefr_level, "cefr_level_pre_cald": row.cefr_level_pre_cald}


# --- Results --------------------------------------------------------------


@dataclass
class Result:
    sense_id: str
    lemma: str
    outcome: str  # applied | would apply | unchanged | already decided | rejected | undone | skipped
    action: str = ""
    detail: str = ""


# --- The system account ---------------------------------------------------


async def get_account(session: AsyncSession) -> User | None:
    return (await session.exec(select(User).where(User.email == REVIEW_BOT_EMAIL))).first()


async def ensure_account(session: AsyncSession) -> User:
    """The "Claude review" user, created if absent -- inert: see the module
    docstring. Flushes; the caller commits."""
    user = await get_account(session)
    if user is None:
        user = User(email=REVIEW_BOT_EMAIL, display_name=REVIEW_BOT_NAME, is_admin=False)
        session.add(user)
        await session.flush()
    return user


# --- Apply ----------------------------------------------------------------


async def _open_report_sense_ids(session: AsyncSession, sense_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    rows = (await session.exec(
        select(TranslationReport.lexeme_sense_id)
        .where(TranslationReport.lexeme_sense_id.in_(sense_ids),
               TranslationReport.status == "open")
    )).all()
    return set(rows)


def _adopt_level(row: MaterialVocabulary, sense: LexemeSense, lexeme: Lexeme) -> None:
    """`lexicon.link_row`'s rule, for a row moved to ``sense``: a sense whose
    level is the dictionary's gives its level to the row, the row's own kept
    once in `cefr_level_pre_cald`."""
    if (sense.cefr_source == "cald" and sense.cefr and not lexeme.is_proper_noun
            and row.cefr_level_pre_cald is None and row.cefr_level != sense.cefr):
        row.cefr_level_pre_cald = row.cefr_level
        row.cefr_level = sense.cefr


async def _check_material_fixes(
    session: AsyncSession, sense: LexemeSense, lexeme: Lexeme, fixes: list[dict]
) -> tuple[list[tuple[dict, MaterialVocabulary, LexemeSense, Lexeme]] | None, str | None]:
    rows = {r.id: r for r in (await session.exec(
        select(MaterialVocabulary).where(
            MaterialVocabulary.id.in_([f["row_id"] for f in fixes])))).all()}
    targets = {s.id: s for s in (await session.exec(
        select(LexemeSense).where(LexemeSense.id.in_([f["to_sense_id"] for f in fixes])))).all()}
    checked = []
    for fix in fixes:
        row, target = rows.get(fix["row_id"]), targets.get(fix["to_sense_id"])
        if row is None:
            return None, f"material row {fix['row_id']} does not exist"
        if target is None:
            return None, f"target sense {fix['to_sense_id']} does not exist"
        if row.sense_id != sense.id:
            return None, f"material row {row.id} is not linked to this sense"
        if target.id == sense.id:
            return None, "the target is the sense itself"
        target_lexeme = await session.get(Lexeme, target.lexeme_id)
        assert target_lexeme is not None
        if fix["kind"] == "relink_sense":
            if target.lexeme_id != sense.lexeme_id:
                return None, "relink_sense stays inside the lexeme; use relink_lexeme"
        else:
            if target.lexeme_id == sense.lexeme_id:
                return None, "relink_lexeme moves to ANOTHER lexeme; use relink_sense"
            if target_lexeme.lemma not in {lexeme.lemma, row.lemma}:
                return None, (f"relink_lexeme only reaches a lexeme of the same lemma "
                              f"({lexeme.lemma!r}), not {target_lexeme.lemma!r}")
            if target_lexeme.is_proper_noun or target_lexeme.is_function_word:
                return None, "the target lexeme is a name or function word"
        checked.append((fix, row, target, target_lexeme))
    return checked, None


async def _move_rows(session: AsyncSession, checked: list) -> list[dict]:
    out = []
    for fix, row, target, target_lexeme in checked:
        entry = {"kind": fix["kind"], "row_id": str(row.id), "before": _row_state(row)}
        row.sense_id = target.id
        if fix["kind"] == "relink_lexeme":
            row.lexeme_id = target_lexeme.id
            if target_lexeme.pos:
                row.pos = target_lexeme.pos
        _adopt_level(row, target, target_lexeme)
        session.add(row)
        entry["after"] = _row_state(row)
        out.append(entry)
    await session.flush()
    return out


async def process(
    session: AsyncSession,
    raw_decisions: list[tuple[int, Any]],
    *,
    write: bool,
    allow_material_fixes: bool = False,
    run_id: str | None = None,
) -> list[Result]:
    """Validate every decision and, with ``write``, apply the valid ones in
    the session's one transaction (the caller commits). Without ``write``
    nothing is written and nothing is locked -- the dry run may be on a
    read-only transaction. Returns one :class:`Result` per input, in order."""
    run_id = run_id or uuid.uuid4().hex[:12]
    results: dict[int, Result] = {}
    decisions: list[tuple[int, Decision]] = []
    seen: set[uuid.UUID] = set()
    for position, raw in raw_decisions:
        label = f"#{position}"
        if isinstance(raw, Exception):
            results[position] = Result(label, "", "rejected", detail=str(raw))
            continue
        decision, error = parse_decision(raw)
        if decision is None:
            sid = str(raw.get("sense_id", label)) if isinstance(raw, dict) else label
            results[position] = Result(sid, "", "rejected", detail=error or "")
            continue
        if decision.sense_id in seen:
            results[position] = Result(str(decision.sense_id), "", "rejected",
                                       action=decision.action,
                                       detail="duplicate sense_id in the file (the first one counts)")
            continue
        if decision.material_fixes and not allow_material_fixes:
            results[position] = Result(
                str(decision.sense_id), "", "rejected", action=decision.action,
                detail="material_fixes are off; pass --allow-material-fixes to enable them")
            continue
        seen.add(decision.sense_id)
        decisions.append((position, decision))

    ids = [d.sense_id for _, d in decisions]
    loaded: dict[uuid.UUID, tuple[LexemeSense, Lexeme]] = {}
    reported: set[uuid.UUID] = set()
    if ids:
        stmt = (select(LexemeSense, Lexeme).join(Lexeme, LexemeSense.lexeme_id == Lexeme.id)
                .where(LexemeSense.id.in_(ids)))
        if write:
            stmt = stmt.with_for_update(of=LexemeSense)
        loaded = {s.id: (s, lx) for s, lx in (await session.exec(stmt)).all()}
        reported = await _open_report_sense_ids(session, ids)
    bot: User | None = None

    for position, d in decisions:
        sid = str(d.sense_id)
        pair = loaded.get(d.sense_id)
        if pair is None:
            results[position] = Result(sid, "", "rejected", d.action, "no such sense")
            continue
        sense, lexeme = pair
        lemma = lexeme.lemma
        if not sense.needs_review:
            results[position] = Result(sid, lemma, "already decided", d.action,
                                       "no longer needs_review")
            continue
        if sense.approved_at is not None:
            results[position] = Result(sid, lemma, "rejected", d.action,
                                       "already approved by a person; not overwritten")
            continue
        if d.action == "human" and sense.review_note == _human_note(d):
            results[position] = Result(sid, lemma, "unchanged", d.action,
                                       "same note already stored")
            continue
        if d.action != "human" and d.sense_id in reported:
            results[position] = Result(
                sid, lemma, "rejected", d.action,
                "has an open learner report; approving would close it, so only `human` is allowed")
            continue
        if d.action == "fix":
            problem = _fix_problem(d, sense, lexeme)
            if problem:
                results[position] = Result(sid, lemma, "rejected", d.action, problem)
                continue
        checked = None
        if d.material_fixes:
            checked, problem = await _check_material_fixes(session, sense, lexeme, d.material_fixes)
            if problem:
                results[position] = Result(sid, lemma, "rejected", d.action, problem)
                continue
        if not write:
            results[position] = Result(sid, lemma, "would apply", d.action, d.confidence)
            continue

        if bot is None:
            bot = await ensure_account(session)
        before = snapshot(sense, lexeme)
        moved: list[dict] = []
        if d.action == "approve":
            await lexicon_review.approve(session, sense, admin_id=bot.id, commit=False)
        elif d.action == "fix":
            if checked:
                moved = await _move_rows(session, checked)
            await lexicon_review.fix_and_approve(
                session, sense, admin_id=bot.id, commit=False, definition_en=None,
                cefr=d.cefr if d.cefr != sense.cefr else None,
                meaning_uz=d.meaning_uz if d.meaning_uz != sense.meaning_uz else None,
                meaning_uz_alt=(d.meaning_uz_alt
                                if d.meaning_uz_alt is not None
                                and d.meaning_uz_alt != sense.meaning_uz_alt else None),
            )
        else:
            sense.review_note = _human_note(d)
            session.add(sense)
            await session.flush()
        session.add(LexiconAiReview(
            sense_id=sense.id, run_id=run_id, action=d.action, confidence=d.confidence,
            note=d.note, before=before, after=snapshot(sense, lexeme), material_fixes=moved,
        ))
        results[position] = Result(sid, lemma, "applied", d.action, d.confidence)
    await session.flush()
    return [results[position] for position, _ in raw_decisions]


def _human_note(d: Decision) -> str:
    return f"Claude review ({d.confidence}): {d.note}"[:NOTE_MAX]


def _fix_problem(d: Decision, sense: LexemeSense, lexeme: Lexeme) -> str | None:
    """Database-aware checks for a `fix`."""
    if d.cefr and lexeme.is_proper_noun:
        return "a name has no CEFR level"
    new_uz = d.meaning_uz if d.meaning_uz is not None else sense.meaning_uz
    new_alt = d.meaning_uz_alt if d.meaning_uz_alt is not None else sense.meaning_uz_alt
    if new_alt and new_alt.casefold() == new_uz.casefold():
        return "meaning_uz_alt equals meaning_uz"
    changes = (
        (d.cefr is not None and d.cefr != sense.cefr)
        or (d.meaning_uz is not None and d.meaning_uz != sense.meaning_uz)
        or (d.meaning_uz_alt is not None and d.meaning_uz_alt != sense.meaning_uz_alt)
        or bool(d.material_fixes)
    )
    if not changes:
        return "the fix changes nothing (values equal the current ones); use `approve`"
    return None


# --- Undo -----------------------------------------------------------------


async def undo(
    session: AsyncSession, *, sense_ids: list[uuid.UUID] | None, write: bool
) -> list[Result]:
    """Revert the active decisions (all, or for ``sense_ids``), newest first.
    A decision is reverted only when the sense (and each moved material row)
    is still exactly as the review left it and, for an approval, still
    approved by the review's own account."""
    bot = await get_account(session)
    stmt = (select(LexiconAiReview).where(LexiconAiReview.undone_at.is_(None))
            .order_by(LexiconAiReview.created_at.desc()))
    if sense_ids is not None:
        stmt = stmt.where(LexiconAiReview.sense_id.in_(sense_ids))
    logs = (await session.exec(stmt)).all()
    results: list[Result] = []
    reranked: list[uuid.UUID] = []
    for log in logs:
        sense = await session.get(LexemeSense, log.sense_id, with_for_update=write)
        lexeme = await session.get(Lexeme, sense.lexeme_id) if sense else None
        sid = str(log.sense_id)
        if sense is None or lexeme is None:
            results.append(Result(sid, "", "skipped", log.action, "sense is gone"))
            continue
        lemma = lexeme.lemma
        current = snapshot(sense, lexeme)
        if log.action in ("approve", "fix") and (bot is None or sense.approved_by != bot.id):
            results.append(Result(sid, lemma, "skipped", log.action,
                                  "not approved by the review account any more"))
            continue
        if current != log.after:
            changed = sorted(k for k in log.after if current.get(k) != log.after[k])
            results.append(Result(sid, lemma, "skipped", log.action,
                                  f"changed since the review: {changed}"))
            continue
        rows = {}
        if log.material_fixes:
            rows = {r.id: r for r in (await session.exec(
                select(MaterialVocabulary).where(MaterialVocabulary.id.in_(
                    [uuid.UUID(f["row_id"]) for f in log.material_fixes])))).all()}
        stale = [f["row_id"] for f in log.material_fixes
                 if uuid.UUID(f["row_id"]) not in rows
                 or _row_state(rows[uuid.UUID(f["row_id"])]) != f["after"]]
        if stale:
            results.append(Result(sid, lemma, "skipped", log.action,
                                  f"material rows changed since the review: {stale}"))
            continue
        if not write:
            results.append(Result(sid, lemma, "would undo", log.action))
            continue
        before = log.before
        for name in ("cefr", "cefr_source", "meaning_uz", "meaning_uz_alt",
                     "needs_review", "review_note"):
            setattr(sense, name, before[name])
        sense.approved_by = uuid.UUID(before["approved_by"]) if before["approved_by"] else None
        sense.approved_at = (datetime.fromisoformat(before["approved_at"])
                             if before["approved_at"] else None)
        session.add(sense)
        if sense.sense_rank == 1:
            lexeme.cefr = before["lexeme_cefr"]
            session.add(lexeme)
        reranked.append(sense.lexeme_id)
        for fix in log.material_fixes:
            row = rows[uuid.UUID(fix["row_id"])]
            old = fix["before"]
            row.pos, row.cefr_level = old["pos"], old["cefr_level"]
            row.cefr_level_pre_cald = old["cefr_level_pre_cald"]
            row.lexeme_id = uuid.UUID(old["lexeme_id"]) if old["lexeme_id"] else None
            row.sense_id = uuid.UUID(old["sense_id"]) if old["sense_id"] else None
            session.add(row)
        log.undone_at = datetime.now(timezone.utc)
        session.add(log)
        results.append(Result(sid, lemma, "undone", log.action))
    await session.flush()
    if reranked:  # a level went back: the order and the rank-1 flag follow
        await lexicon_service.rerank_lexemes(session, reranked)
    return results


# --- Status ---------------------------------------------------------------

OUTCOMES: tuple[str, ...] = ("pending", "left for a human", "approved", "fixed",
                             "approved by a person", "cleared otherwise")


async def classify(session: AsyncSession) -> list[tuple[uuid.UUID, str, list[str], str, str]]:
    """``(sense_id, lemma, reasons, outcome, review_note)`` for every sense
    that carries a review reason (they stay as history after an approval)."""
    bot = await get_account(session)
    senses = (await session.exec(core_select(
        LexemeSense.id, Lexeme.lemma, LexemeSense.review_reasons, LexemeSense.needs_review,
        LexemeSense.approved_by, LexemeSense.approved_at, LexemeSense.review_note,
    ).join(Lexeme, LexemeSense.lexeme_id == Lexeme.id)
        .where(func.cardinality(LexemeSense.review_reasons) > 0))).all()
    active: dict[uuid.UUID, str] = {}
    for sense_id, action in (await session.exec(core_select(
            LexiconAiReview.sense_id, LexiconAiReview.action)
            .where(LexiconAiReview.undone_at.is_(None))
            .order_by(LexiconAiReview.created_at))).all():
        active[sense_id] = action
    out = []
    for sense_id, lemma, reasons, needs_review, approved_by, approved_at, note in senses:
        action = active.get(sense_id)
        if approved_at is not None and bot is not None and approved_by == bot.id \
                and action in ("approve", "fix"):
            outcome = "approved" if action == "approve" else "fixed"
        elif approved_at is not None:
            outcome = "approved by a person"
        elif needs_review:
            outcome = "left for a human" if action == "human" else "pending"
        else:
            outcome = "cleared otherwise"
        out.append((sense_id, lemma, list(reasons), outcome, note))
    return out


async def status(session: AsyncSession) -> dict[str, Counter]:
    """``{reason: Counter(outcome)}`` over every sense that carries a review
    reason, plus ``"(any reason)"`` counting each sense once. Outcomes:
    `OUTCOMES`."""
    table: dict[str, Counter] = defaultdict(Counter)
    for _, _, reasons, outcome, _ in await classify(session):
        for reason in reasons:
            table[reason][outcome] += 1
        table["(any reason)"][outcome] += 1
    return table


async def list_outcome(session: AsyncSession, outcome: str) -> list[str]:
    """One line per sense with ``outcome`` -- how a person finds what the
    review decided (or left for them, with its note)."""
    rows = sorted((r for r in await classify(session) if r[3] == outcome),
                  key=lambda r: (r[1], str(r[0])))
    return [f"  {sid}  {lemma:<20} {','.join(reasons):<40} {note}"
            for sid, lemma, reasons, _, note in rows]


def format_status(table: dict[str, Counter]) -> str:
    cols = OUTCOMES
    lines = [f"{'reason':<22}" + "".join(f"{c:>22}" for c in cols) + f"{'total':>8}"]
    for reason in (*REVIEW_REASONS, "(any reason)"):
        counts = table.get(reason, Counter())
        lines.append(f"{reason:<22}" + "".join(f"{counts[c]:>22}" for c in cols)
                     + f"{sum(counts.values()):>8}")
    return "\n".join(lines)


# --- Export ---------------------------------------------------------------


def primary_reason(reasons: list[str]) -> str:
    for reason in REASON_PRIORITY:
        if reason in reasons:
            return reason
    return reasons[0] if reasons else ""


def allocate(pools: dict[str, int], n: int) -> dict[str, int]:
    """How many of ``n`` each stratum gives: equal shares, a stratum smaller
    than its share gives all it has and the rest is shared among the others
    (so the pilot sees every reason, not 53 `cald_cefr_far` and one
    `judge_different`)."""
    alloc = {r: 0 for r in pools}
    remaining = min(n, sum(pools.values()))
    while remaining > 0:
        open_ = [r for r in pools if alloc[r] < pools[r]]
        share = max(remaining // len(open_), 1)
        for reason in open_:
            take = min(share, pools[reason] - alloc[reason], remaining)
            alloc[reason] += take
            remaining -= take
            if remaining == 0:
                break
    return alloc


def stratified_sample(rows: list[dict], n: int, seed: int) -> list[dict]:
    """``n`` rows (dicts with ``id`` and ``review_reasons``) stratified over
    each sense's primary reason, reproducibly for a seed."""
    pools: dict[str, list[dict]] = {r: [] for r in REASON_PRIORITY}
    for row in rows:
        pools.setdefault(primary_reason(row["review_reasons"]), []).append(row)
    for pool in pools.values():
        pool.sort(key=lambda r: str(r["id"]))
    alloc = allocate({r: len(p) for r, p in pools.items() if p}, n)
    chosen: list[dict] = []
    for reason, k in alloc.items():
        chosen += random.Random(f"{seed}:{reason}").sample(pools[reason], k)
    return chosen


async def _has_review_note(conn) -> bool:
    """Whether the database has been migrated past `b1c4e7a09d52`. An export
    only reads, and is run against a database before that migration reaches
    it (the pilot was exported from `app` while the migration was still a
    branch), so it must not require the column it would show."""
    found = (await conn.execute(text(
        "select 1 from information_schema.columns where table_name = 'lexeme_senses' "
        "and column_name = 'review_note' and table_schema = current_schema()"))).first()
    return found is not None


async def _fetch_flagged(conn, reason: str | None) -> list[dict]:
    note = LexemeSense.review_note if await _has_review_note(conn) else literal("").label("review_note")
    stmt = (core_select(
        LexemeSense.id, LexemeSense.lexeme_id, LexemeSense.sense_rank, LexemeSense.definition_en,
        LexemeSense.definition_source, LexemeSense.definition_en_pre_cald, LexemeSense.cefr,
        LexemeSense.cefr_source, LexemeSense.cald_cefr, LexemeSense.cefr_pre_cald,
        LexemeSense.meaning_uz, LexemeSense.meaning_uz_alt, LexemeSense.meaning_uz_material,
        LexemeSense.review_reasons, note,
        Lexeme.lemma, Lexeme.pos, Lexeme.is_phrase, Lexeme.is_proper_noun,
        Lexeme.frequency_band, Lexeme.frequency_source, Lexeme.domain_tags,
    ).join(Lexeme, LexemeSense.lexeme_id == Lexeme.id)
        .where(LexemeSense.needs_review.is_(True), LexemeSense.approved_at.is_(None)))
    if reason:
        stmt = stmt.where(LexemeSense.review_reasons.any(reason))
    return [dict(r._mapping) for r in (await conn.execute(stmt)).all()]


def _chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


async def build_records(conn, flagged: list[dict]) -> list[dict]:
    """The export record of each flagged sense: everything a reviewer needs
    and nothing it does not (no ids it cannot use, no timestamps, no
    learners)."""
    lists = frequency_lists()
    lexeme_ids = sorted({r["lexeme_id"] for r in flagged}, key=str)
    sense_ids = [r["id"] for r in flagged]
    lemmas = sorted({r["lemma"] for r in flagged})

    others: dict[uuid.UUID, list[dict]] = defaultdict(list)
    rows_by_lexeme: dict[uuid.UUID, list[Any]] = defaultdict(list)
    for chunk in _chunks(lexeme_ids, 400):
        for r in (await conn.execute(
                core_select(LexemeSense.id, LexemeSense.lexeme_id, LexemeSense.sense_rank,
                            LexemeSense.definition_en, LexemeSense.cefr)
                .where(LexemeSense.lexeme_id.in_(chunk)).order_by(LexemeSense.sense_rank))).all():
            others[r.lexeme_id].append(dict(r._mapping))
        for r in (await conn.execute(
                core_select(MaterialVocabulary.id, MaterialVocabulary.lexeme_id,
                            MaterialVocabulary.sense_id, MaterialVocabulary.lemma,
                            MaterialVocabulary.surface, MaterialVocabulary.pos,
                            MaterialVocabulary.example, MaterialVocabulary.meaning_en,
                            MaterialVocabulary.meaning_uz, MaterialVocabulary.cefr_level,
                            MaterialVocabulary.cefr_level_pre_cald, MaterialVocabulary.hidden)
                .where(MaterialVocabulary.lexeme_id.in_(chunk)).order_by(MaterialVocabulary.id))).all():
            rows_by_lexeme[r.lexeme_id].append(r)

    siblings: dict[str, list[dict]] = defaultdict(list)
    known_lemmas: set[str] = set()
    for chunk in _chunks(lemmas, 400):
        for lx in (await conn.execute(
                core_select(Lexeme.id, Lexeme.lemma, Lexeme.pos)
                .where(Lexeme.lemma.in_(chunk)))).all():
            known_lemmas.add(lx.lemma)
            siblings[lx.lemma].append({"lexeme_id": lx.id, "pos": lx.pos})
    sibling_senses: dict[uuid.UUID, list[dict]] = defaultdict(list)
    sibling_ids = [s["lexeme_id"] for group in siblings.values() for s in group]
    for chunk in _chunks(sibling_ids, 400):
        for r in (await conn.execute(
                core_select(LexemeSense.id, LexemeSense.lexeme_id, LexemeSense.sense_rank,
                            LexemeSense.definition_en, LexemeSense.cefr)
                .where(LexemeSense.lexeme_id.in_(chunk)).order_by(LexemeSense.sense_rank))).all():
            sibling_senses[r.lexeme_id].append(dict(r._mapping))
    # Form lexemes (`accumulating`): which merged forms still have a lexeme of
    # their own is a fact the merge reason needs.
    forms = {r.lemma for rows in rows_by_lexeme.values() for r in rows} - known_lemmas
    for chunk in _chunks(sorted(forms), 400):
        for lx in (await conn.execute(
                core_select(Lexeme.lemma).where(Lexeme.lemma.in_(chunk)))).all():
            known_lemmas.add(lx.lemma)

    open_reports: dict[uuid.UUID, list[str]] = defaultdict(list)
    for chunk in _chunks(sense_ids, 400):
        for r in (await conn.execute(
                core_select(TranslationReport.lexeme_sense_id, TranslationReport.note)
                .where(TranslationReport.lexeme_sense_id.in_(chunk),
                       TranslationReport.status == "open"))).all():
            open_reports[r.lexeme_sense_id].append(r.note)

    records = []
    for r in flagged:
        lex_rows = rows_by_lexeme.get(r["lexeme_id"], [])
        mine = [x for x in lex_rows if x.sense_id == r["id"]]
        usable = sorted((x for x in mine if x.example), key=lambda x: (x.hidden, str(x.id)))
        reasons = r["review_reasons"]
        details: dict[str, Any] = {}
        if "cald_cefr_far" in reasons:
            gap = (abs(CEFR_LEVELS.index(r["cefr"]) - CEFR_LEVELS.index(r["cald_cefr"]))
                   if r["cefr"] in CEFR_LEVELS and r["cald_cefr"] in CEFR_LEVELS else None)
            details["cald_cefr_far"] = {"ours": r["cefr"], "dictionary": r["cald_cefr"],
                                        "bands_apart": gap}
        if "material_level_gap" in reasons:
            levels = Counter((x.cefr_level_pre_cald or x.cefr_level) for x in mine
                             if (x.cefr_level_pre_cald or x.cefr_level))
            details["material_level_gap"] = {"ours": r["cefr"], "material_row_levels": dict(levels)}
        if "ngsl_conflict" in reasons:
            details["ngsl_conflict"] = {"ours": r["cefr"], "band": r["frequency_band"],
                                        "ngsl_rank": lists.ngsl_rank.get(r["lemma"])}
        for verdict in ("judge_different", "judge_unsure"):
            if verdict in reasons:
                details[verdict] = {
                    "meaning": "two translators' Uzbek for this sense were compared twice and "
                               + ("clearly disagreed" if verdict == "judge_different"
                                  else "could not be called the same")
                               + "; meaning_uz is the preferred one, meaning_uz_alt the other"}
        if "pos_mismatch" in reasons:
            details["pos_mismatch"] = {
                "lexeme_pos": r["pos"],
                "pos_of_material_rows_in_this_sense": dict(Counter(x.pos for x in mine)),
                "pos_of_all_material_rows_of_lexeme": dict(Counter(x.pos for x in lex_rows)),
            }
        if "lemma_merge" in reasons:
            by_form: dict[str, dict] = {}
            for x in lex_rows:
                if x.lemma == r["lemma"]:
                    continue
                form = by_form.setdefault(x.lemma, {
                    "form": x.lemma, "surfaces": set(), "rows_in_lexeme": 0,
                    "rows_in_this_sense": 0, "has_own_lexeme": x.lemma in known_lemmas})
                form["surfaces"].add(x.surface)
                form["rows_in_lexeme"] += 1
                form["rows_in_this_sense"] += x.sense_id == r["id"]
            merged = [{**f, "surfaces": sorted(f["surfaces"])[:5]}
                      for f in sorted(by_form.values(), key=lambda f: f["form"])]
            details["lemma_merge"] = {
                "headword": r["lemma"],
                "merged_forms_seen_in_material_rows": merged,
                "note": ("the merge itself is not stored; these are the material rows "
                         "of this lexeme whose written lemma differs from the headword"
                         if merged else
                         "no material row differs from the headword: the merge happened "
                         "among forms that have no material row, so nothing more is recorded"),
            }
        record: dict[str, Any] = {
            "sense_id": str(r["id"]), "lexeme_id": str(r["lexeme_id"]), "lemma": r["lemma"],
            "pos": r["pos"], "is_phrase": r["is_phrase"], "is_proper_noun": r["is_proper_noun"],
            "sense_rank": r["sense_rank"],
            "definition_en": r["definition_en"], "definition_source": r["definition_source"],
            "cefr": r["cefr"], "cefr_source": r["cefr_source"], "cald_cefr": r["cald_cefr"],
            "frequency": {
                "band": r["frequency_band"], "source": r["frequency_source"],
                "ngsl_rank": lists.ngsl_rank.get(r["lemma"]),
                "on_nawl": r["lemma"] in lists.nawl, "domain_tags": list(r["domain_tags"] or []),
            },
            "meaning_uz": r["meaning_uz"], "meaning_uz_alt": r["meaning_uz_alt"],
            "meaning_uz_material": r["meaning_uz_material"],
            "review_reasons": reasons, "reason_details": details,
            "other_senses": [
                {"sense_id": str(o["id"]), "rank": o["sense_rank"], "pos": r["pos"],
                 "cefr": o["cefr"], "definition": clip(o["definition_en"], DEFINITION_CLIP)}
                for o in others.get(r["lexeme_id"], []) if o["id"] != r["id"]][:OTHER_SENSES_MAX],
            "usage_count": len(mine),
            "usages": [
                {"row_id": str(x.id), "sentence": clip(x.example, SENTENCE_CLIP),
                 "written_as": x.surface, "row_pos": x.pos, "row_cefr": x.cefr_level,
                 "meaning_en": x.meaning_en, "meaning_uz": x.meaning_uz}
                for x in usable[:USAGES_MAX]],
        }
        if r["definition_en_pre_cald"]:
            record["definition_en_pre_cald"] = r["definition_en_pre_cald"]
        if r["cefr_pre_cald"]:
            record["cefr_pre_cald"] = r["cefr_pre_cald"]
        if r["review_note"]:
            record["review_note"] = r["review_note"]
        if open_reports.get(r["id"]):
            record["open_learner_reports"] = open_reports[r["id"]]
        if "pos_mismatch" in reasons or "lemma_merge" in reasons:
            record["same_lemma_other_lexemes"] = [
                {"lexeme_id": str(s["lexeme_id"]), "pos": s["pos"],
                 "senses": [{"sense_id": str(o["id"]), "cefr": o["cefr"],
                             "definition": clip(o["definition_en"], DEFINITION_CLIP)}
                            for o in sibling_senses.get(s["lexeme_id"], [])][:OTHER_SENSES_MAX]}
                for s in siblings.get(r["lemma"], []) if s["lexeme_id"] != r["lexeme_id"]]
        records.append(record)
    return records


_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def parse_exclude_file(path: Path) -> set[uuid.UUID]:
    """Sense ids to leave out. A JSONL file (a batch, a decisions file) gives
    each line's ``sense_id`` and nothing else -- a batch line also names other
    senses of the lexeme, which are NOT excluded. Any other line is searched
    for uuids, so a plain list of ids works."""
    found: set[uuid.UUID] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            parsed = json.loads(line)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            sense_id = _parse_uuid(parsed.get("sense_id"))
            if sense_id is not None:
                found.add(sense_id)
        else:
            found.update(uuid.UUID(m) for m in _UUID_RE.findall(line))
    return found


async def export(
    conn, out_dir: Path, *, database: str, reason: str | None = None,
    sample: int | None = None, seed: int = 1, exclude: set[uuid.UUID] | None = None,
    batch_size: int = 150, tag: str = "batch",
) -> dict:
    """Write ``{tag}_NNN.jsonl`` batches and ``{tag}_manifest.json`` (and the
    rubric) to ``out_dir``; return the manifest. Read-only on ``conn``."""
    if reason is not None and reason not in REVIEW_REASONS:
        raise ValueError(f"unknown reason {reason!r}; one of {list(REVIEW_REASONS)}")
    flagged = await _fetch_flagged(conn, reason)
    available = len(flagged)
    flagged = [r for r in flagged if r["id"] not in (exclude or set())]
    if sample is not None:
        flagged = stratified_sample(flagged, sample, seed)
    flagged.sort(key=lambda r: (REASON_PRIORITY.index(primary_reason(r["review_reasons"]))
                                if primary_reason(r["review_reasons"]) in REASON_PRIORITY else 99,
                                r["lemma"], r["sense_rank"], str(r["id"])))
    records = await build_records(conn, flagged)

    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob(f"{tag}_[0-9][0-9][0-9].jsonl"):
        stale.unlink()  # a shorter export must not leave the old tail behind
    (out_dir / "REVIEW_RUBRIC.md").write_text(REVIEW_RUBRIC, encoding="utf-8")
    batches = []
    for number, chunk in enumerate(_chunks(records, batch_size), start=1):
        name = f"{tag}_{number:03d}.jsonl"
        with (out_dir / name).open("w", encoding="utf-8") as fh:
            for record in chunk:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        batches.append({
            "file": name, "senses": len(chunk),
            "by_primary_reason": dict(Counter(primary_reason(c["review_reasons"]) for c in chunk)),
        })
    manifest = {
        "tag": tag, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "database": database,
        "filters": {"reason": reason, "sample": sample, "seed": seed if sample else None,
                    "excluded": len(exclude or ()), "batch_size": batch_size},
        "flagged_available": available, "senses": len(records),
        "by_primary_reason": dict(Counter(primary_reason(c["review_reasons"]) for c in records)),
        "by_any_reason": dict(Counter(x for c in records for x in c["review_reasons"])),
        "batches": batches,
        "decisions": "one JSON object per sense -- see REVIEW_RUBRIC.md",
    }
    (out_dir / f"{tag}_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


# --- The rubric -------------------------------------------------------------

REVIEW_RUBRIC = """\
# Lexicon review rubric

You are reviewing flagged senses of an English vocabulary lexicon built for
IELTS learners whose first language is Uzbek. Each line of a batch file
(`batch_NNN.jsonl` / `pilot_NNN.jsonl`) is ONE sense with what you need to
judge it. You return ONE decision per sense. A person (or you again) can undo
every decision; the cost of a wrong approval is a learner studying something
false, the cost of a `human` is a few seconds of a person's time. So:
**when unsure, `human`.**

## What you may change, and what you may not

* You MAY change a sense's **CEFR level**, its **Uzbek** (`meaning_uz`,
  `meaning_uz_alt`), and -- only when the tooling was run with
  `--allow-material-fixes` -- the pos/sense link of a material row.
* You NEVER rewrite a definition (`definition_en` is not a key you can send).
  If a definition is wrong for the headword, that is a `human` with a note.
* You never invent a sense, delete one, or merge lexemes.

## The decision (one JSON object per line, `decisions_NNN.jsonl`)

```json
{"sense_id": "<uuid from the record>",
 "action": "approve" | "fix" | "human",
 "cefr": "A1".."C2",                 // fix only, optional
 "meaning_uz": "tarjima, sinonim",   // fix only, optional
 "meaning_uz_alt": "boshqa",         // fix only, optional; "" empties it
 "material_fixes": [                 // fix only, optional, see below
   {"kind": "relink_sense" | "relink_lexeme", "row_id": "<uuid>", "to_sense_id": "<uuid>"}],
 "confidence": "high" | "medium" | "low",
 "note": "one sentence: why"}
```

* `approve`: the sense is fine as it stands. No other keys. Clears the flag
  and locks the sense against dictionary re-imports.
* `fix`: set only the keys that change; omitted keys stay as they are. A fix
  that changes nothing is rejected (use `approve`). Same effect as approve
  otherwise.
* `human`: you cannot decide. The sense stays flagged, and your `note`
  (required, say WHAT a person must look at) is shown to them in Studio.
* `confidence: low` is only allowed with `human`.
* A sense that has `open_learner_reports` can only be `human`.
* Unknown keys are rejected, so a typo cannot silently do nothing. Invalid
  decisions are skipped and listed; the rest still apply.

## CEFR

`cefr` is how hard THIS SENSE is to READ or HEAR for an IELTS learner -- not
how hard it is to use in writing. Weigh, in this order:

1. **Frequency**: `frequency.band` (core = NGSL top 1000, common = top 2000,
   wider, academic = NAWL, off-list) and `ngsl_rank`. A core word is very
   rarely above B1 in its main sense.
2. **Concreteness**: a picture-able everyday noun (`nest`, `glue`, `tractor`)
   is A2-B1 however rare. Abstract and technical words sit higher.
3. **The dictionary's level (`cald_cefr`) as EVIDENCE, not truth.** English
   Vocabulary Profile levels describe what learners WRITE, so everyday
   concrete nouns are often rated too high there, and productive-only senses
   too. When ours and the dictionary's disagree by two or more bands, decide
   on the other evidence; the dictionary is right when the sense is abstract,
   formal or specialised and ours is lower.
4. The material rows' levels (`usages[].row_cefr`, `reason_details.
   material_level_gap`) are weak, older evidence: the seed only graded
   B1-C1, so an A1/A2 sense is two bands from B2 "by construction".
5. A sense of a common word that is rare or specialised (the second sense of
   `spring`) is graded as THAT sense.

Keep the level if it is right (`approve`). Change it only when you can say
why in the note. One band is rarely worth a change; two or more usually is.
A name (`is_proper_noun`) has no level: never send `cefr` for it.

## Uzbek

`meaning_uz` is what the learner reads on the card. It must be:

* real, standard **Latin-script** Uzbek words (no Cyrillic, no
  transliterated English, no explanations in sentences, no English);
* for THIS sense (read `definition_en`, not just the lemma), in the right
  part of speech and valency: a verb as an infinitive (`yopishtirmoq`), a
  noun as a noun, an adjective as an adjective; transitive vs intransitive
  where Uzbek distinguishes;
* **1-4 short equivalents**, comma-separated, each under 40 characters,
  commonest first, every one fitting the definition. Apostrophes as `'`
  (`o'zbek`, `g'isht`, `qo'ng'iroq`).

`meaning_uz_alt` is the other translator's candidate, kept for a reviewer.
Set it to `""` when `meaning_uz` is settled, or to a genuinely different
good candidate; never equal to `meaning_uz`.

If you are not confident of a word's exact Uzbek (a rare technical term, a
regional word), do not guess: `human`.

## Reasons -- what each flag asks of you

* `cald_cefr_far` (largest): the dictionary's definition was applied but its
  level was 2+ bands from ours, so ours was kept. Decide the level (see
  above). Usually `approve` (ours is right) or `fix` with `cefr`.
* `lemma_merge`: the lexeme was formed by merging inflected forms into one
  headword by a mechanical rule. Look at `reason_details.lemma_merge`: are
  the merged forms really the SAME word (`accumulating` -> `accumulate`:
  yes; `engineering` -> `engineer`: no)? If the merge is right, judge the
  sense normally. If the merge is wrong, or you cannot tell, `human` with a
  note naming the form.
* `judge_unsure` / `judge_different`: the two Uzbek translations could not
  be shown to agree. Read the definition, pick or write the right Uzbek and
  `fix` it; if both are fine, `approve`; if neither is right and you are not
  sure of the correct word, `human`. `judge_different` deserves more care.
* `pos_mismatch`: the material rows use the headword as another part of
  speech, or define a different word. Look at
  `reason_details.pos_mismatch` and `usages`. If the sense is right for the
  lexeme's pos and the rows are simply tagged loosely (`phr` vs head pos
  never counts), `approve`. If rows really belong to the other pos and the
  other lexeme exists (`same_lemma_other_lexemes`), a material fix may be
  offered (below); otherwise `human`.
* `material_level_gap`: the sense's level is 2+ bands from the material
  rows' majority. Decide the level as above.
* `ngsl_conflict`: rank-1 sense graded C1/C2 on a core word. Almost always a
  mis-grade: check the definition really is an advanced sense; usually `fix`
  with a lower `cefr`, or `human` if the sense is genuinely advanced and
  the ordering looks wrong.

A sense can carry several reasons: satisfy all of them.

## Material fixes (only if enabled)

Two kinds, nothing else exists:

* `relink_sense`: a material row of this sense moves to ANOTHER sense of the
  SAME lexeme (`to_sense_id` from `other_senses`).
* `relink_lexeme`: a row moves to a sense of the existing lexeme with the
  same lemma and the other pos (`to_sense_id` from
  `same_lemma_other_lexemes`); the row takes that pos.

`row_id` comes from `usages` (only those are shown). At most 5 per decision,
only inside a `fix`. Both change only where a row points -- nothing is
created or deleted. Use them only when the sentence plainly shows the row
is a different sense/pos; otherwise `human`.

## Style of the note

One sentence, plain English, no quotation of dictionary text (the files are
private but the notes are stored in the database and shown in Studio).
Say what you saw: "dictionary B2 but a concrete everyday noun, A2",
"merge joins two different words (`housing`/`house`)", "Uzbek alt is a
different sense, kept the first".

## Examples (invented)

```json
{"sense_id": "...", "action": "fix", "cefr": "A2", "confidence": "high", "note": "concrete everyday noun, dictionary level is a writing level"}
{"sense_id": "...", "action": "approve", "confidence": "high", "note": "level and Uzbek both fit"}
{"sense_id": "...", "action": "fix", "meaning_uz": "yopishtirmoq, yelimlamoq", "meaning_uz_alt": "", "confidence": "medium", "note": "first candidate was the intransitive sense"}
{"sense_id": "...", "action": "human", "confidence": "low", "note": "rows mix two parts of speech and I cannot tell which is intended"}
```
"""

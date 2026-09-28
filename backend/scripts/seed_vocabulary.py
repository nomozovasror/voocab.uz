"""A dev-only vocabulary that exercises every practice state at once.

Stage 1 and 2 of the vocabulary module (``app/services/practice.py``) have a
dozen states that only exist after weeks of real use: a word demoted off the
top rung, a leech one lapse away, a card mastered enough to unlock its active
twin, a set-aside whose 30 days have quietly run out. Nobody can click
through all of that by hand from an empty account. This script builds it.

Usage (from ``backend/``)::

    uv run python -m scripts.seed_vocabulary                    # add it
    uv run python -m scripts.seed_vocabulary --reset             # remove it, then add it back
    uv run python -m scripts.seed_vocabulary --email a@b.c       # a different learner

Refuses to run unless ``DEV_LOGIN_ENABLED`` is on (``--force`` overrides it),
the same guard ``scripts/seed_practice.py`` uses, for the same reason: that
setting is the one thing in the config that already means "this is a
development machine".

## How it remembers what it wrote

There is no ``seeded`` column on ``saved_words`` and there should not be one
-- it is schema nobody else would ever read, for a fact only this script
cares about. Nor can the LEMMA be marked (``"zz_demo_apple"``): the whole
point is to save real words out of the real catalogue, by lemma, through the
real save path, so a fabricated lemma would just fail to match anything.

So the marker is a **manifest**: at seed time, this script deterministically
selects its ~40 lemmas from the real ``material_vocabulary`` table (see
``_load_pools``), skipping any lemma the learner already has -- checked
*before* selection, so a pre-existing word is never even considered, let
alone touched. What it ends up writing is then recorded, once, in
``scripts/.seed_vocabulary_state.json`` (gitignored; this repo's ``.env`` is
already a sibling example of a file that lives here and never in git),
keyed by email:

    {"dev@voocab.local": {"word_ids": ["3c...", ...], "lemmas": ["abandon", ...], "seeded_at": "..."}}

``word_ids`` -- ``SavedWord.id`` (P4) -- is the key ``--reset`` actually
deletes by; ``lemmas`` rides along only for the printed report and for a
human reading the file, because a lemma is no longer unique to one saved
word (`bank` the river and `bank` the financial institution are two rows)
and is no longer a safe way to find "the word THIS script wrote" back.
``--reset`` reads the file back and deletes *exactly* those ids' saved
words, their contexts and their review logs -- nothing chosen by re-running
the same selection query (the catalogue could have changed under it) and
nothing that belongs to a word the manifest never claimed. A learner's
pre-existing 8 words and 13 logs are never in the file, so they are never in
the delete. Running ``seed`` again with a manifest already on disk for that
email is a no-op ("already seeded, nothing to do") rather than a second
attempt at selection -- true idempotency, not merge logic that would have to
reconcile two different lemma lists.

## Building the states without waiting weeks

Every word is created through ``app.services.vocabulary.save`` from a real,
public material's real ``MaterialVocabulary`` row (real ``pos``, real
``cefr_level``, a real example sentence, real ``meaning_core_en`` -- the
fields the distractor pipeline and the recall gap both read), exactly the
path a learner's own "save this word" tap uses. Every review is then driven
through the real ``app.services.practice.record_answer`` -- the same
grading, the same ladder, the same FSRS scheduler, the same leech
arithmetic a real answer goes through.

The one thing that cannot be borrowed from real use is *time*: FSRS's
stability only grows when a review actually happens days after the last
one, and a leech needs lapses spread over weeks. So ``datetime.now`` is
monkeypatched, for the duration of this script only, in the two modules
that call it to timestamp a review (``app.services.practice`` -- every log
and every card's ``due``/``last_review`` -- and ``app.models.vocabulary`` --
``created_at`` defaults), via a small controllable clock (see
``_frozen_clock``). Every review this script records is a *real* call to
*real* grading logic; only the clock it was told the time was is fake, and
it is always set to a real moment in the last three to four weeks, walked
forward review by review exactly as a learner's calendar would be.

FSRS's own fuzzing (``enable_fuzzing=True`` on the shared scheduler) means
the exact stability or interval a given rating sequence produces cannot be
predicted to the day from outside the library. Rather than fight that, each
recipe below simulates a realistic sequence and then calls one of the
``_ensure_*`` helpers, which check the outcome and nudge only the single
numeric column that matters (``passive_stability`` into its band,
``passive_due``/``active_due`` into "now" or "later") if the fuzz landed it
just outside the requested bucket. Nothing else about the card -- its state,
its level, its whole log history -- is touched by these helpers; they exist
only so "stability 3-15 days" means 3-15 days on every run, not "usually".
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime as _datetime_module
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlmodel import select

from app.core.config import settings
from app.core.database import async_session_factory
from app.models.lexicon import LexemeSense
from app.models.material import Material
from app.models.user import User
from app.models.vocabulary import (
    SavedWord,
    SavedWordContext,
    MaterialVocabulary,
    VocabularyReviewLog,
    VocabularySettings,
)
import app.models.vocabulary as vocab_models
from app.services import distractors as distractors_service
from app.services import practice as practice_service
from app.services import vocabulary as vocabulary_service

DEFAULT_EMAIL = "dev@voocab.local"
MANIFEST_PATH = Path(__file__).parent / ".seed_vocabulary_state.json"

#: The parts of speech and CEFR levels good enough to build a recognise
#: item's four options against (see ``app.services.distractors``'s own
#: filter) and to write a believable recall gap from.
QUALITY_POS = ("n", "v", "adj", "adv", "phr")
QUALITY_CEFR = ("B1", "B2", "C1")

#: How many quality rows to pull before grouping by lemma in Python -- a
#: generous slice of the alphabet's front, since the pools only ever need
#: about forty entries and the candidate table has thousands.
POOL_FETCH_LIMIT = 6000


# --- The frozen clock --------------------------------------------------------


class _Clock:
    """A settable "now", read by :class:`_FakeDateTime.now`."""

    def __init__(self, value: datetime) -> None:
        self.value = value


CLOCK = _Clock(datetime.now(timezone.utc))
_RealDateTime = _datetime_module.datetime


class _FakeDateTime(_RealDateTime):
    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        value = CLOCK.value
        return value.astimezone(tz) if tz is not None else value


@contextlib.contextmanager
def _frozen_clock(start: datetime):
    """Make ``datetime.now()`` inside the two modules that timestamp a
    review return :data:`CLOCK`'s value instead of the wall clock, for the
    body of the ``with`` block. Restored unconditionally, so a script that
    dies mid-seed never leaves the process's notion of "now" patched."""
    CLOCK.value = start
    real_practice_dt = practice_service.datetime
    real_model_dt = vocab_models.datetime
    practice_service.datetime = _FakeDateTime  # type: ignore[assignment]
    vocab_models.datetime = _FakeDateTime  # type: ignore[assignment]
    try:
        yield CLOCK
    finally:
        practice_service.datetime = real_practice_dt  # type: ignore[assignment]
        vocab_models.datetime = real_model_dt  # type: ignore[assignment]


# --- The manifest -------------------------------------------------------------


def _load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {}
    return json.loads(MANIFEST_PATH.read_text())


def _save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


# --- Picking real words to save ----------------------------------------------


async def _existing_lemmas(session, user_id: uuid.UUID) -> set[str]:
    rows = await session.exec(select(SavedWord.lemma).where(SavedWord.user_id == user_id))
    return set(rows.all())


async def _load_pools(
    session, exclude: set[str]
) -> tuple[list[tuple[str, list[MaterialVocabulary]]], list[tuple[str, list[MaterialVocabulary]]]]:
    """``(multi, single)`` -- lemmas with a real gloss good enough to study,
    grouped by how many of the catalogue's public materials carry them.

    Grouped by ``(lemma, sense_id)``, not by lemma alone (P4): a "multi"
    pool entry feeds ``_add_context``, whose whole point is a SECOND
    material meeting the SAME saved word -- but ``vocabulary_service.save``
    now keys a word on ``entry.sense_id``, so two rows sharing a lemma but
    NOT a sense (``bank`` the river in one material, ``bank`` the financial
    institution in another) would silently mint two separate saved words
    instead of one word with two contexts, which is the one shape the
    multi-context recipes below (context rotation, the word page) exist to
    seed. A row with no sense linked at all cannot be paired this way
    honestly and is dropped rather than guessed at.

    Ordered by lemma, which is what makes two runs against the same,
    unchanged corpus pick the same forty words -- "deterministic" in the
    module docstring's sense. Nothing here writes anything; the manifest is
    what makes a LATER, changed corpus irrelevant to what ``--reset`` has to
    find again.
    """
    rows = await session.exec(
        select(MaterialVocabulary)
        .join(Material, MaterialVocabulary.material_id == Material.id)
        .where(
            MaterialVocabulary.hidden.is_(False),
            MaterialVocabulary.pos.in_(QUALITY_POS),
            MaterialVocabulary.cefr_level.in_(QUALITY_CEFR),
            MaterialVocabulary.meaning_core_en != "",
            MaterialVocabulary.example != "",
            Material.visibility == "public",
        )
        .order_by(MaterialVocabulary.lemma, MaterialVocabulary.material_id)
        .limit(POOL_FETCH_LIMIT)
    )
    groups: dict[tuple[str, uuid.UUID], list[MaterialVocabulary]] = {}
    for entry in rows.all():
        if entry.lemma in exclude or entry.sense_id is None:
            continue
        groups.setdefault((entry.lemma, entry.sense_id), []).append(entry)
    multi = [(lemma, g) for (lemma, _sense_id), g in groups.items() if len(g) >= 2]
    single = [(lemma, g) for (lemma, _sense_id), g in groups.items() if len(g) == 1]
    return multi, single


class _Pools:
    """Two queues of (lemma, entries) to pop from as recipes claim words --
    keeps every bucket builder below from re-deriving "which word is next"."""

    def __init__(self, multi, single):
        self._multi = list(multi)
        self._single = list(single)

    def single(self) -> tuple[str, MaterialVocabulary]:
        lemma, entries = self._single.pop(0)
        return lemma, entries[0]

    def multi(self) -> tuple[str, MaterialVocabulary, MaterialVocabulary]:
        lemma, entries = self._multi.pop(0)
        return lemma, entries[0], entries[1]


# --- Saving and answering, through the real services --------------------------


async def _save(session, user: User, entry: MaterialVocabulary, *, when: datetime) -> SavedWord:
    CLOCK.value = when
    await vocabulary_service.save(
        session, user_id=user.id, material_id=entry.material_id, lemmas=[entry.lemma]
    )
    row = await session.exec(
        select(SavedWord).where(SavedWord.user_id == user.id, SavedWord.lemma == entry.lemma)
    )
    return row.one()


async def _add_context(session, user: User, entry: MaterialVocabulary, *, when: datetime) -> None:
    """A second meeting of an already-saved word, in a second material --
    what the multi-context words test (context rotation, the word page)."""
    CLOCK.value = when
    await vocabulary_service.save(
        session, user_id=user.id, material_id=entry.material_id, lemmas=[entry.lemma]
    )


async def _primary_context(session, word: SavedWord) -> SavedWordContext | None:
    row = await session.exec(
        select(SavedWordContext)
        .where(SavedWordContext.saved_word_id == word.id)
        .order_by(SavedWordContext.created_at)
        .limit(1)
    )
    return row.first()


def _elapsed_ms(lemma: str, exercise_type: str) -> int:
    """A believable answer time -- not a stopwatch, just varied enough that
    the daily-budget average (``practice._avg_seconds``) is computed from
    real spread rather than one repeated number."""
    base = 4000 + (abs(hash((lemma, exercise_type))) % 9000)
    if exercise_type in ("recall", "produce"):
        base += 4000
    return base


async def _answer(
    session,
    user: User,
    word: SavedWord,
    direction: str,
    exercise_type: str,
    verdict: str,
    when: datetime,
    *,
    claim_known: bool = False,
) -> dict | None:
    """One real ``record_answer`` call, at a chosen moment, graded to land
    on the ``verdict`` asked for -- ``given`` is computed the same way the
    grader itself would recognise as right or wrong, never a stored answer
    string copied from elsewhere.

    The right text/definition for `recognise`/`recall` is read from the
    word's own `LexemeSense` (P4) -- `SavedWord.meaning_core_en` is dead --
    the same live read `record_answer` itself does, so the option id this
    script computes and the one grading recomputes always agree.
    """
    CLOCK.value = when
    context = await _primary_context(session, word)
    sense = await session.get(LexemeSense, word.lexeme_sense_id)
    if exercise_type == "recognise":
        context_id = None
        right_text = (
            practice_service._recognise_right_text(word, context, direction, sense)
        )
        given = (
            distractors_service.option_id(word.id, right_text)
            if verdict == "correct"
            else "0" * 16
        )
    elif exercise_type == "recall":
        context_id = context.id if context else None
        gap = practice_service.resolve_gap(word, context, sense)
        # A generic, unrelated wrong answer rather than a mangled version of
        # the right one -- close enough to the accepted spelling and the
        # mistakes classifier (``MAX_SPELLING_EDITS``) would call it `close`
        # instead of `wrong`, grading it Hard rather than Again and never
        # counting as the genuine lapse several recipes below need.
        given = gap.answer if verdict == "correct" else "xxxnotitxxx"
    else:  # produce
        context_id = context.id if context else None
        forms = await practice_service._accepted_produce_forms(session, word)
        given = forms[0] if verdict == "correct" else "xxxnotitxxx"
    elapsed_ms = _elapsed_ms(word.lemma, exercise_type)
    return await practice_service.record_answer(
        session,
        user,
        word_id=word.id,
        context_id=context_id,
        direction=direction,
        exercise_type=exercise_type,
        given=given,
        elapsed_ms=elapsed_ms,
        claim_known=claim_known,
    )


def _level(word: SavedWord, direction: str) -> str:
    return practice_service._current_level(word, direction)


async def _lapse_cycle(
    session, user: User, word: SavedWord, *, wrong_at: datetime, recover_at: datetime | None
) -> None:
    """One lapse and, unless ``recover_at`` is ``None``, the correct answer
    that climbs back to wherever it was -- see :data:`PASSIVE_LADDER`: a
    wrong answer at the top rung (``recall``) demotes to ``recognise``, and
    one correct answer there re-promotes (the word has reached ``recall``
    before, so the streak needed is 1, not 2)."""
    level = _level(word, "passive")
    await _answer(session, user, word, "passive", level, "wrong", wrong_at)
    if recover_at is not None:
        level = _level(word, "passive")
        await _answer(session, user, word, "passive", level, "correct", recover_at)


# --- Safety nets: nudge the one column a bucket actually needs ----------------


def _due_of(word: SavedWord, direction: str) -> datetime | None:
    return getattr(word, f"{direction}_due")


async def _ensure_due_now(session, word: SavedWord, direction: str, real_now: datetime) -> None:
    await session.refresh(word)
    due = _due_of(word, direction)
    if due is None or due > real_now:
        setattr(word, f"{direction}_due", real_now - timedelta(hours=1))
        session.add(word)
        await session.commit()


async def _ensure_due_later(
    session, word: SavedWord, direction: str, real_now: datetime, days: int
) -> None:
    await session.refresh(word)
    due = _due_of(word, direction)
    if due is None or due <= real_now + timedelta(hours=12):
        setattr(word, f"{direction}_due", real_now + timedelta(days=days))
        session.add(word)
        await session.commit()


async def _ensure_stability(
    session, word: SavedWord, direction: str, lo: float, hi: float, fallback: float
) -> None:
    await session.refresh(word)
    value = getattr(word, f"{direction}_stability")
    if value is None or not (lo <= value <= hi):
        setattr(word, f"{direction}_stability", fallback)
        session.add(word)
        await session.commit()


# --- The recipes ---------------------------------------------------------------
#
# Each takes the pools, builds however many words its state needs, and
# returns the lemmas it touched (for the manifest and the closing report).
# `days` below are always "ago" relative to `real_now`, walked forward
# through the frozen clock exactly as a learner's calendar would be.


async def _seed_new(session, user, pools: _Pools, real_now: datetime, *, multi: bool) -> list[str]:
    lemmas = []
    for i in range(12):
        if multi and i == 0:
            lemma, e1, e2 = pools.multi()
            await _save(session, user, e1, when=real_now - timedelta(days=1))
            await _add_context(session, user, e2, when=real_now - timedelta(days=1))
        else:
            lemma, entry = pools.single()
            await _save(session, user, entry, when=real_now - timedelta(days=1 + i))
        lemmas.append(lemma)
    return lemmas


async def _seed_recognise_streak1(
    session, user, pools: _Pools, real_now: datetime, *, multi: bool
) -> list[str]:
    lemmas = []
    for i in range(6):
        if multi and i == 0:
            lemma, e1, e2 = pools.multi()
            word = await _save(session, user, e1, when=real_now - timedelta(days=10))
            await _add_context(session, user, e2, when=real_now - timedelta(days=9))
        else:
            lemma, entry = pools.single()
            word = await _save(session, user, entry, when=real_now - timedelta(days=10))
        await _answer(session, user, word, "passive", "recognise", "correct", real_now - timedelta(days=8))
        await _ensure_due_now(session, word, "passive", real_now)
        lemmas.append(lemma)
    return lemmas


async def _seed_demoted(session, user, pools: _Pools, real_now: datetime) -> list[str]:
    lemmas = []
    for _ in range(3):
        lemma, entry = pools.single()
        word = await _save(session, user, entry, when=real_now - timedelta(days=20))
        await _answer(session, user, word, "passive", "recognise", "correct", real_now - timedelta(days=18))
        await _answer(session, user, word, "passive", "recognise", "correct", real_now - timedelta(days=15))
        # Reached `recall` -- now demoted off it, and left there: the next
        # thing that happens to this word is the learner practising it live.
        await _answer(session, user, word, "passive", "recall", "wrong", real_now - timedelta(days=8))
        await _ensure_due_now(session, word, "passive", real_now)
        lemmas.append(lemma)
    return lemmas


_RECALL_STABILITY_TARGETS = [4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 7.0, 11.0]


async def _seed_recall_band(
    session, user, pools: _Pools, real_now: datetime, *, multi: bool
) -> list[str]:
    lemmas = []
    for i in range(8):
        if multi and i == 0:
            lemma, e1, e2 = pools.multi()
            word = await _save(session, user, e1, when=real_now - timedelta(days=20))
            await _add_context(session, user, e2, when=real_now - timedelta(days=19))
        else:
            lemma, entry = pools.single()
            word = await _save(session, user, entry, when=real_now - timedelta(days=20))
        await _answer(session, user, word, "passive", "recognise", "correct", real_now - timedelta(days=18))
        # Promotes to `recall` on this one -- two consecutive correct
        # `recognise` answers.
        await _answer(session, user, word, "passive", "recognise", "correct", real_now - timedelta(days=15))
        await _ensure_stability(
            session, word, "passive", 3.0, 15.0, _RECALL_STABILITY_TARGETS[i]
        )
        await _ensure_due_now(session, word, "passive", real_now)
        lemmas.append(lemma)
    return lemmas


async def _master(session, user, entry, real_now, start_days_ago: int) -> SavedWord:
    """Passive `recall`, stability well past the mastered/unlock line --
    shared by the mastered-word recipe and the active-unlock recipe, which
    both need the identical passive history before anything active can
    start."""
    word = await _save(session, user, entry, when=real_now - timedelta(days=start_days_ago))
    await _answer(
        session, user, word, "passive", "recognise", "correct",
        real_now - timedelta(days=start_days_ago - 2),
    )
    await _answer(
        session, user, word, "passive", "recognise", "correct",
        real_now - timedelta(days=start_days_ago - 5),
    )
    await _answer(
        session, user, word, "passive", "recall", "correct",
        real_now - timedelta(days=start_days_ago - 15),
    )
    await _ensure_stability(
        session, word, "passive", practice_service.MASTERED_STABILITY_DAYS, 90.0, 30.0
    )
    return word


async def _seed_mastered(
    session, user, pools: _Pools, real_now: datetime, *, multi: bool
) -> list[str]:
    lemmas = []
    for i in range(4):
        if multi and i == 2:  # one of the "due later" pair
            lemma, e1, e2 = pools.multi()
            word = await _master(session, user, e1, real_now, start_days_ago=25)
            await _add_context(session, user, e2, when=real_now - timedelta(days=9))
        else:
            lemma, entry = pools.single()
            word = await _master(session, user, entry, real_now, start_days_ago=25)
        if i < 2:
            await _ensure_due_now(session, word, "passive", real_now)
        else:
            await _ensure_due_later(session, word, "passive", real_now, days=7 + i)
        lemmas.append(lemma)
    return lemmas


async def _seed_active(session, user, pools: _Pools, real_now: datetime, settings_row) -> list[str]:
    """Two active `recognise` cards and one active `produce` card, all due
    now -- unlocked by temporarily setting ``direction: "both"`` (the way
    the real gate is opened), restored by the caller once every active card
    here has started for real."""
    lemmas = []
    settings_row.direction = "both"
    session.add(settings_row)
    await session.commit()

    for _ in range(2):
        lemma, entry = pools.single()
        word = await _master(session, user, entry, real_now, start_days_ago=25)
        await _answer(session, user, word, "active", "recognise", "correct", real_now - timedelta(days=5))
        await _ensure_due_now(session, word, "active", real_now)
        lemmas.append(lemma)

    lemma, entry = pools.single()
    word = await _master(session, user, entry, real_now, start_days_ago=25)
    await _answer(session, user, word, "active", "recognise", "correct", real_now - timedelta(days=11))
    await _answer(session, user, word, "active", "recognise", "correct", real_now - timedelta(days=9))
    await _ensure_due_now(session, word, "active", real_now)
    lemmas.append(lemma)
    return lemmas


async def _seed_near_leech(session, user, pools: _Pools, real_now: datetime) -> str:
    lemma, entry = pools.single()
    word = await _save(session, user, entry, when=real_now - timedelta(days=25))
    await _answer(session, user, word, "passive", "recognise", "correct", real_now - timedelta(days=23))
    await _answer(session, user, word, "passive", "recognise", "correct", real_now - timedelta(days=20))
    # 2 lapses older than the 14-day leech window, 3 inside it: 5 in total,
    # one short of either threshold (6 lifetime, or 4 within 14 days).
    older = [18, 16]
    recent = [10, 6, 2]
    for days_ago in older + recent:
        await _lapse_cycle(
            session, user, word,
            wrong_at=real_now - timedelta(days=days_ago),
            recover_at=real_now - timedelta(days=days_ago) + timedelta(minutes=30),
        )
    await _ensure_due_now(session, word, "passive", real_now)
    return lemma


async def _seed_leech(session, user, pools: _Pools, real_now: datetime) -> str:
    lemma, entry = pools.single()
    word = await _save(session, user, entry, when=real_now - timedelta(days=28))
    await _answer(session, user, word, "passive", "recognise", "correct", real_now - timedelta(days=26))
    await _answer(session, user, word, "passive", "recognise", "correct", real_now - timedelta(days=23))
    older = [21, 19]
    recent = [12, 9, 5]
    for days_ago in older + recent:
        await _lapse_cycle(
            session, user, word,
            wrong_at=real_now - timedelta(days=days_ago),
            recover_at=real_now - timedelta(days=days_ago) + timedelta(minutes=30),
        )
    # The sixth lapse -- no recovery: `record_answer` itself flips the
    # status to `leech` the moment this one lands, the same as a real wrong
    # answer would.
    await _lapse_cycle(
        session, user, word,
        wrong_at=real_now - timedelta(days=1),
        recover_at=None,
    )
    return lemma


async def _seed_set_aside(session, user, pools: _Pools, real_now: datetime) -> list[str]:
    lemmas = []
    lemma, entry = pools.single()
    word = await _save(session, user, entry, when=real_now - timedelta(days=10))
    await _answer(session, user, word, "passive", "recognise", "correct", real_now - timedelta(days=8))
    word.status = "suspended"
    word.suspended_until = real_now + timedelta(days=12)
    session.add(word)
    await session.commit()
    lemmas.append(lemma)

    lemma, entry = pools.single()
    word = await _save(session, user, entry, when=real_now - timedelta(days=15))
    await _answer(session, user, word, "passive", "recognise", "correct", real_now - timedelta(days=13))
    word.status = "suspended"
    word.suspended_until = real_now - timedelta(days=1)
    session.add(word)
    await session.commit()
    lemmas.append(lemma)
    return lemmas


async def _seed_known(session, user, pools: _Pools, real_now: datetime) -> list[str]:
    lemmas = []
    # Bypassed outright, on a word that has never been practised.
    lemma, entry = pools.single()
    word = await _save(session, user, entry, when=real_now - timedelta(days=3))
    await _answer(
        session, user, word, "passive", "recall", "correct",
        real_now - timedelta(days=1), claim_known=True,
    )
    lemmas.append(lemma)

    # Practised for a while first, then marked known by hand (the words
    # list's bulk action) -- a real history behind the status, not a bypass.
    lemma, entry = pools.single()
    word = await _save(session, user, entry, when=real_now - timedelta(days=15))
    await _answer(session, user, word, "passive", "recognise", "correct", real_now - timedelta(days=13))
    await _answer(session, user, word, "passive", "recognise", "correct", real_now - timedelta(days=10))
    await _answer(session, user, word, "passive", "recall", "correct", real_now - timedelta(days=5))
    await session.refresh(word)
    word.status = "known"
    session.add(word)
    await session.commit()
    lemmas.append(lemma)
    return lemmas


# --- Orchestration --------------------------------------------------------------


async def seed(email: str) -> None:
    real_now = datetime.now(timezone.utc)
    manifest = _load_manifest()
    if manifest.get(email, {}).get("lemmas"):
        print(
            f"Already seeded for {email} ({len(manifest[email]['lemmas'])} words). "
            "Nothing to do -- use --reset to rebuild."
        )
        return

    async with async_session_factory() as session:
        user = (await session.exec(select(User).where(User.email == email))).first()
        if user is None:
            raise SystemExit(
                f"No user {email!r} -- sign in once (Dev login creates the row) "
                "before seeding their vocabulary."
            )

        existing = await _existing_lemmas(session, user.id)
        print(f"{email} already has {len(existing)} saved word(s); none of them will be touched.")

        multi_rows, single_rows = await _load_pools(session, exclude=existing)
        pools = _Pools(multi_rows, single_rows)

        settings_row = await session.get(VocabularySettings, user.id)
        if settings_row is None:
            settings_row = VocabularySettings(user_id=user.id)
            session.add(settings_row)
            await session.commit()
        original_direction = settings_row.direction

        lemmas: list[str] = []
        report: dict[str, list[str]] = {}

        with _frozen_clock(real_now):
            report["new"] = await _seed_new(session, user, pools, real_now, multi=True)
            report["recognise (streak 1)"] = await _seed_recognise_streak1(
                session, user, pools, real_now, multi=True
            )
            report["demoted from recall"] = await _seed_demoted(session, user, pools, real_now)
            report["recall, stability 3-15d"] = await _seed_recall_band(
                session, user, pools, real_now, multi=True
            )
            report["mastered (>=21d)"] = await _seed_mastered(
                session, user, pools, real_now, multi=True
            )
            report["active cards"] = await _seed_active(session, user, pools, real_now, settings_row)
            report["near-leech (5 lapses)"] = [await _seed_near_leech(session, user, pools, real_now)]
            report["leech"] = [await _seed_leech(session, user, pools, real_now)]
            report["set aside"] = await _seed_set_aside(session, user, pools, real_now)
            report["known"] = await _seed_known(session, user, pools, real_now)

        # Restored exactly, whatever it was before -- the active cards
        # above are meant to be found PAUSED if the learner's own setting
        # was `passive`, not switched on by this script.
        settings_row = await session.get(VocabularySettings, user.id)
        settings_row.direction = original_direction
        session.add(settings_row)
        await session.commit()

        for group in report.values():
            lemmas.extend(group)

        # The manifest's real key (P4): a lemma is no longer unique to one
        # saved word, so "the word this script wrote" is found by id, not by
        # re-matching a string that up to two rows could now share. Safe to
        # look up by lemma ONE more time, here, because within a single run
        # every lemma the pools handed out was distinct and excluded from
        # the learner's pre-existing words -- this is the one and only place
        # that assumption is still relied on.
        word_rows = await session.exec(
            select(SavedWord.id).where(
                SavedWord.user_id == user.id, SavedWord.lemma.in_(lemmas)
            )
        )
        word_ids = [str(word_id) for word_id in word_rows.all()]

    manifest[email] = {
        "word_ids": word_ids,
        "lemmas": sorted(set(lemmas)),
        "seeded_at": real_now.isoformat(),
    }
    _save_manifest(manifest)

    print(f"Seeded {len(lemmas)} words for {email}:")
    for state, group in report.items():
        print(f"  {state}: {', '.join(group)}")


async def reset(email: str) -> None:
    manifest = _load_manifest()
    entry = manifest.get(email)
    # `word_ids` is P4's own key; a manifest written before this migration
    # only ever had `lemmas`, and is read back the old way this one last
    # time so an existing dev database is not stranded unable to reset.
    word_ids: list[uuid.UUID] | None = None
    if entry and entry.get("word_ids"):
        word_ids = [uuid.UUID(raw) for raw in entry["word_ids"]]
    elif not entry or not entry.get("lemmas"):
        print(f"Nothing seeded here for {email}.")
        return
    lemmas = entry.get("lemmas", [])

    async with async_session_factory() as session:
        user = (await session.exec(select(User).where(User.email == email))).first()
        if user is None:
            print(f"No user {email!r} any more -- dropping the manifest entry.")
            manifest.pop(email, None)
            _save_manifest(manifest)
            return

        word_where = (
            SavedWord.id.in_(word_ids)  # type: ignore[attr-defined]
            if word_ids is not None
            else SavedWord.lemma.in_(lemmas)  # type: ignore[attr-defined]
        )
        words = (
            await session.exec(
                select(SavedWord).where(SavedWord.user_id == user.id, word_where)
            )
        ).all()
        found_ids = [w.id for w in words]

        removed_logs = 0
        if found_ids:
            for log in (
                await session.exec(
                    select(VocabularyReviewLog).where(
                        VocabularyReviewLog.saved_word_id.in_(found_ids)  # type: ignore[attr-defined]
                    )
                )
            ).all():
                await session.delete(log)
                removed_logs += 1
            await session.flush()

        removed_contexts = 0
        if found_ids:
            for context in (
                await session.exec(
                    select(SavedWordContext).where(
                        SavedWordContext.saved_word_id.in_(found_ids)  # type: ignore[attr-defined]
                    )
                )
            ).all():
                await session.delete(context)
                removed_contexts += 1
            await session.flush()

        for word in words:
            await session.delete(word)
        await session.commit()

        print(
            f"Removed {len(words)} words, {removed_contexts} contexts and "
            f"{removed_logs} review logs for {email} "
            f"(of {len(word_ids) if word_ids is not None else len(lemmas)} in the manifest)."
        )

    manifest.pop(email, None)
    _save_manifest(manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default=DEFAULT_EMAIL, help="the learner to seed (default: dev@voocab.local)")
    parser.add_argument("--reset", action="store_true", help="remove this script's words, then re-seed")
    parser.add_argument(
        "--force", action="store_true",
        help="run even where DEV_LOGIN_ENABLED is off (you had better be sure)",
    )
    args = parser.parse_args()

    if not settings.dev_login_enabled and not args.force:
        raise SystemExit(
            "Refusing to run: DEV_LOGIN_ENABLED is off, so this does not look "
            "like a development database. Pass --force if it is."
        )

    async def run() -> None:
        if args.reset:
            await reset(args.email)
        await seed(args.email)

    asyncio.run(run())


if __name__ == "__main__":
    main()

"""Recognise's four options: where the wrong three come from.

Split out of ``app.services.practice`` on purpose -- this module is a pure
candidate-and-filter pipeline over ``material_vocabulary``, imports no
``fsrs``, and is exactly the piece the plan says will be tuned once real
sessions are watched ("the user will raise the guard to 3 words if fallbacks
are frequent"). Keeping it apart means that tuning touches one file with no
scheduling logic in it to accidentally also change.

## Where a candidate may come from, and where it may not

Distractors are drawn ONLY from ``material_vocabulary`` -- the whole
catalogue's glosses, never the learner's OWN saved words. Two learners
studying the same word would otherwise see each other's vocabulary leak into
their multiple-choice options, and a learner's list is exactly the words
they do NOT yet know well, which makes them the worst possible source of
plausible-but-wrong answers.

## The five-step filter, in the order the brief gives it

1. same ``pos`` -- a noun among three verbs is not a distractor, it is a
   giveaway.
2. CEFR within one level either way (unrated candidates only when the word
   itself is unrated -- an A2 word should not be quizzed against a C1
   impostor, and an unrated one has nothing to be "within one level" of).
3. the word's own source material(s) sort first, then the rest of the
   public, unhidden catalogue -- a distractor from the passage just read is
   more plausible than one from nowhere, but the catalogue is the fallback
   because most words are met in only one or two materials.
4. the word's own lemma is excluded outright, and so is any candidate whose
   lemma shares the FAMILY of a lemma the learner currently has in
   ``learning`` -- ``emerge`` in `learning` excludes `emergence` from
   anybody's options, because a learner mid-way through one member of a
   word family should not be quizzed on whether they can tell it apart from
   another member they have not met yet.
5. the similarity guard: a candidate whose definition shares two or more
   content words with the right definition is dropped (two phrasings of the
   same idea is not a wrong answer, it is a second correct one), and so is
   an exact duplicate of an option already chosen.

## Fallback is a substitution, not a failure

Too short a definition (fewer than :data:`MIN_DEFINITION_WORDS` words) or too
few candidates surviving the guard (fewer than :data:`MIN_DISTRACTORS`) means
this encounter is served harder instead -- passive `recognise` becomes
`recall`, active `recognise` becomes `produce` -- rather than shown with bad
options. The caller (``app.services.practice``) is the one that knows how to
build that harder prompt; this module only ever answers "here are the
options" or "no, not this time, and here is why".

## Option ids give nothing away

Each option's id is ``HMAC-SHA256(app secret, f"{word_id}:{text}")``,
truncated to 16 hex characters. It is not the text, so nothing sent to the
browser is the answer written out in a different alphabet; it is not
reversible without the secret; and it is *stable* for the same word and
text, which is what lets the answer be graded by recomputing the RIGHT
option's id and comparing -- see ``practice.grade_choice`` -- rather than by
storing anything about the four options that were shown.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import random
import re
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import case
from sqlmodel import select

from app.core.config import settings
from app.core.database import AsyncSession
from app.models.material import Material
from app.models.vocabulary import MaterialVocabulary, SavedWord

logger = logging.getLogger("app.services.distractors")

#: CEFR order, so "within one level" is a distance over an index rather than
#: a string comparison that would put B1 after C1 alphabetically.
CEFR_ORDER: tuple[str, ...] = ("A1", "A2", "B1", "B2", "C1", "C2")

#: A right definition shorter than this has nothing to build four distinct
#: wrong options against -- see the module docstring's fallback section.
#: Named so the brief's own promise to raise it is one constant, not a
#: search-and-replace.
MIN_DEFINITION_WORDS = 3

#: How many distractors the guard must leave standing. Three, plus the right
#: answer, is the plan's four options.
MIN_DISTRACTORS = 3

#: A candidate sharing this many content words with the right definition is
#: treated as a second correct answer, not a wrong one, and dropped.
SIMILARITY_SHARED_WORDS = 2

#: Two lemmas are the same "family" for the learning-exclusion rule when
#: they share this many leading characters -- ``emerge``/``emergence`` share
#: 5 ("emerg"); shorter lemmas compare exactly instead (see
#: :func:`family_key`), so ``rise``/``risen`` are not silently fused into
#: one four-letter family that would swallow half the dictionary.
FAMILY_PREFIX_LEN = 5

#: How many catalogue rows step 1+2's SQL filter (pos, CEFR window) may pull
#: before step 4 (family) and the caller's step 5 (similarity) get to look
#: at any of them. A generous few hundred: four options never need more, and
#: this is what stops a common ``pos``/CEFR pair -- ``n``/``B2`` is
#: thousands of rows once the catalogue is large -- from being loaded whole
#: on every single recognise item. Source-material rows are ranked FIRST in
#: SQL (see the ``CASE`` in :func:`_candidates`), so raising or lowering
#: this constant can never starve step 3's preference: every source-material
#: row that survives steps 1/2/4 is still ahead of the cut.
CANDIDATE_FETCH_LIMIT = 300

#: Closed-class words carrying no content of their own -- dropped before the
#: similarity guard counts shared words, or "to" and "a" would count as
#: agreement between any two definitions in English.
STOP_WORDS: frozenset[str] = frozenset(
    """
    a an the of to in on at for with without into onto from by as is are
    was were be being been do does did have has had it its this that these
    those they them their he she his her him you your we our i my me not
    no so if but or and than then there here what which who whom when
    where why how all any some more most other another such only own same
    can will would should could may might must shall
    """.split()
)

Direction = Literal["passive", "active"]


def family_key(lemma: str) -> str:
    """The learning-exclusion family a lemma belongs to.

    Lemmas at or past :data:`FAMILY_PREFIX_LEN` compare by that prefix
    (``emerge``/``emergence`` -> ``emerg``); shorter ones compare exactly,
    so ``rise`` does not become a family that also contains ``risen``,
    ``risk`` and ``ritual``.
    """
    lemma = (lemma or "").lower()
    if len(lemma) < FAMILY_PREFIX_LEN:
        return lemma
    return lemma[:FAMILY_PREFIX_LEN]


_STEM_ENDINGS: tuple[str, ...] = ("ing", "edly", "ed", "es", "ly", "s")


def _stem(word: str) -> str:
    """A deliberately crude suffix strip -- see the brief's "simple suffix
    stripping". This is a similarity GUARD, not a lemmatiser: the cost of
    stemming two unrelated words onto the same stem is one dropped
    distractor, and the cost of a lemmatiser here would be a second copy of
    ``seed/vocabulary.py``'s rules with nothing to keep them in step."""
    for ending in _STEM_ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            return word[: -len(ending)]
    return word


_WORD_RE = re.compile(r"[a-zA-Z']+")


def content_words(text: str) -> set[str]:
    """Lower-cased, stop-words dropped, lightly stemmed -- the set two
    definitions are compared over for the similarity guard."""
    words = (match.group(0).lower() for match in _WORD_RE.finditer(text or ""))
    return {_stem(word) for word in words if word not in STOP_WORDS}


def word_count(text: str) -> int:
    """Plain word count, not content words -- the fallback threshold is
    about whether there is enough TEXT to build a quiz question on, not
    whether it is rich in meaning-bearing words."""
    return len((text or "").split())


def option_id(word_id: uuid.UUID, text: str) -> str:
    """The opaque id one option is shown under.

    Deterministic in ``word_id`` and the option's own text, and nothing
    else -- recomputing it at answer time (``practice.grade_choice``) for
    the RIGHT text and comparing is the whole of how a choice is graded,
    with nothing about which four options were shown ever stored server
    side. See the module docstring for why this is safe to send to the
    browser before the answer.
    """
    message = f"{word_id}:{text.strip().lower()}".encode()
    digest = hmac.new(
        settings.session_secret.encode(), message, hashlib.sha256
    ).hexdigest()
    return digest[:16]


def _cefr_index(level: str) -> int | None:
    return CEFR_ORDER.index(level) if level in CEFR_ORDER else None


def _cefr_window(word_level: str) -> list[str] | None:
    """Step 2, expressed as a SQL-able ``IN`` list rather than a per-row
    Python comparison: the finite set of CEFR codes within one level of
    ``word_level``, longest three entries at either end of
    :data:`CEFR_ORDER`. ``None`` means the word itself is unrated -- there
    is no window, and the caller instead asks for candidates that are ALSO
    unrated (see :func:`_candidates`), the same exception
    ``_within_one_level`` used to encode."""
    idx = _cefr_index(word_level)
    if idx is None:
        return None
    lo, hi = max(idx - 1, 0), min(idx + 1, len(CEFR_ORDER) - 1)
    return list(CEFR_ORDER[lo : hi + 1])


async def learning_family_keys(
    session: AsyncSession, user_id: uuid.UUID
) -> frozenset[str]:
    """Every family the learner currently has a word ``learning`` in --
    step 4 of the filter. Read once per session build (the caller shares
    this across every recognise item it builds), not once per word: a
    learner's `learning` bucket does not change mid-session."""
    rows = await session.exec(
        select(SavedWord.lemma).where(
            SavedWord.user_id == user_id, SavedWord.status == "learning"
        )
    )
    return frozenset(family_key(lemma) for lemma in rows.all())


async def _candidates(
    session: AsyncSession,
    *,
    pos: str,
    cefr_level: str,
    exclude_lemma: str,
    family_keys: frozenset[str],
    source_material_ids: frozenset[uuid.UUID] = frozenset(),
) -> list[MaterialVocabulary]:
    """Every row of the catalogue that survives steps 1, 2 and 4, ranked so
    step 3 (source material preference) is already correct without the
    caller re-sorting: rows from ``source_material_ids`` come first in SQL
    (a ``CASE`` in the ``ORDER BY``, not a Python sort over the whole pool),
    which is what lets :data:`CANDIDATE_FETCH_LIMIT` cap the fetch without
    ever starving that preference -- a source row that survives steps 1/2/4
    is ranked ahead of the cut whether or not it also happens to sort early
    by id. Step 5 (the similarity guard) is still applied by the caller,
    over this list, because it needs to know which options have already
    been chosen -- a property of the SELECTION, not the candidate pool.
    """
    window = _cefr_window(cefr_level)
    cefr_clause = (
        MaterialVocabulary.cefr_level.in_(window)
        if window is not None
        # The word itself is unrated: only other unrated candidates -- any
        # value outside the six real CEFR codes -- are "within one level"
        # of a level that does not exist.
        else MaterialVocabulary.cefr_level.notin_(CEFR_ORDER)
    )
    order_by = [MaterialVocabulary.id]
    if source_material_ids:
        order_by = [
            case(
                (MaterialVocabulary.material_id.in_(source_material_ids), 0),
                else_=1,
            ),
            MaterialVocabulary.id,
        ]
    query = (
        select(MaterialVocabulary)
        .join(Material, MaterialVocabulary.material_id == Material.id)
        .where(
            MaterialVocabulary.pos == pos,
            MaterialVocabulary.hidden.is_(False),
            Material.visibility == "public",
            MaterialVocabulary.lemma != exclude_lemma,
            cefr_clause,
        )
        .order_by(*order_by)
        .limit(CANDIDATE_FETCH_LIMIT)
    )
    rows = await session.exec(query)
    found = []
    for candidate in rows.all():
        if family_key(candidate.lemma) in family_keys:
            continue
        found.append(candidate)
    return found


def _definition_of(entry: MaterialVocabulary) -> str:
    return entry.meaning_core_en or entry.meaning_en


@dataclass(frozen=True)
class Option:
    id: str
    text: str


@dataclass(frozen=True)
class Built:
    """A finished recognise prompt's options, or the reason there are none.

    ``fallback_reason`` is ``None`` on success and one of
    ``"short_definition"``/``"too_few_candidates"`` otherwise -- the two
    named in the brief, and exactly what the caller logs at session build
    time.
    """

    options: list[Option] | None
    fallback_reason: Literal["short_definition", "too_few_candidates"] | None


async def build(
    session: AsyncSession,
    *,
    word_id: uuid.UUID,
    right_text: str,
    right_definition: str,
    pos: str,
    cefr_level: str,
    source_material_ids: frozenset[uuid.UUID],
    family_keys: frozenset[str],
    exclude_lemma: str,
    option_field: Literal["definition", "lemma"],
    rng_seed: int,
) -> Built:
    """Four options for one recognise item: the right one plus up to three
    survivors of the filter, or a fallback reason.

    ``right_text`` is what the CORRECT option shows -- a definition for
    passive recognise, the lemma itself for active. ``right_definition`` is
    always a definition, because the similarity guard compares meanings even
    when the options on screen are lemmas ("two synonyms as options would be
    the same unfairness", per the brief) -- the two arguments are the same
    string for passive and different ones for active.

    ``rng_seed`` shuffles deterministically rather than with the process
    RNG: the SAME item, built twice (once for the prompt, once implicitly by
    a client that reloads it), should not silently reorder itself, and a
    dedicated ``random.Random`` seeded per-call costs nothing a shared,
    stateful RNG could leak between requests.
    """
    if word_count(right_definition) < MIN_DEFINITION_WORDS:
        return Built(options=None, fallback_reason="short_definition")

    candidates = await _candidates(
        session,
        pos=pos,
        cefr_level=cefr_level,
        exclude_lemma=exclude_lemma,
        family_keys=family_keys,
        source_material_ids=source_material_ids,
    )
    # Source materials already sort first -- `_candidates`' own ORDER BY,
    # not a Python sort here, is what keeps that preference correct even
    # when `CANDIDATE_FETCH_LIMIT` caps how many rows were fetched at all.

    right_words = content_words(right_definition)
    chosen: list[MaterialVocabulary] = []
    chosen_texts: set[str] = set()
    for candidate in candidates:
        if len(chosen) >= MIN_DISTRACTORS:
            break
        definition = _definition_of(candidate)
        if len(right_words & content_words(definition)) >= SIMILARITY_SHARED_WORDS:
            continue
        text = candidate.lemma if option_field == "lemma" else definition
        normalised = text.strip().lower()
        if not normalised or normalised in chosen_texts:
            continue
        chosen_texts.add(normalised)
        chosen.append(candidate)

    if len(chosen) < MIN_DISTRACTORS:
        return Built(options=None, fallback_reason="too_few_candidates")

    texts = [right_text] + [
        (c.lemma if option_field == "lemma" else _definition_of(c)) for c in chosen
    ]
    order = list(range(len(texts)))
    # `random.Random(rng_seed)` rather than the shared process RNG -- a
    # dedicated, seeded instance is what makes the shuffle deterministic in
    # `rng_seed` alone (the SAME item, built twice, orders its options the
    # same way) without leaking state into -- or out of -- any other call.
    random.Random(rng_seed).shuffle(order)

    options = [Option(id=option_id(word_id, texts[i]), text=texts[i]) for i in order]
    return Built(options=options, fallback_reason=None)

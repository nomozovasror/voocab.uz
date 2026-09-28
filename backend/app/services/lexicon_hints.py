"""``lexeme_senses.needs_letter_hint`` -- whether recall's first-letter cue is
worth showing (`brief-vocabulary-tuzatish-browse.md` §B).

A bare first letter only narrows a guess down when there is a REAL guess to
narrow: ``shortage``/``scarcity``/``deficit``/``lack`` genuinely compete for
the same gap, and "starts with s" earns its place. A word with nothing else
in the catalogue that means roughly the same thing has no guess to narrow,
and showing the letter anyway just leaks the answer for free.

Two independent signals, either one sets the flag:

1. **Shares an OEWN synset with a sense of ANOTHER lexeme.** The clearest
   case -- two different headwords the dictionary itself considers the same
   concept.
2. **Carries a (near-)identical `definition_en`** to a sense of another
   lexeme, after the same word-level normalisation the distractor pipeline's
   own similarity guard uses (`app.services.distractors.content_words`) --
   near rather than exact because two independently-written glosses of the
   same idea rarely match character for character. "Near" is
   :data:`NEAR_IDENTICAL_DEFINITION_JACCARD`, a token-set Jaccard threshold,
   named so raising or lowering it is a one-line change rather than a
   search-and-replace.

Both are asked ACROSS lexemes only -- two senses of the SAME lexeme sharing
a synset or a definition is ordinary (a lexeme's own senses are already
deduplicated by `app.services.lexicon.link_row`'s own grouping) and answers
nothing about whether recall's guess needs narrowing.

## Full backfill vs. the worker's incremental hook

:func:`recompute_all` is the batch form -- every sense against every other,
run once by ``scripts/backfill_letter_hint.py`` and never again on a normal
day. :func:`recompute_for_lexemes` is what ``app.worker``'s enrichment loop
calls after it rewrites a batch of lexemes' senses (`app.services
.lexicon_enrich.enrich` just gave them fresh `definition_en`/
`oewn_synset_id` values, which may have changed which OTHER senses they now
match): it runs the identical comparison against the WHOLE catalogue in
memory, but writes the result only for the senses that belong to the
lexemes just touched.

That is a deliberate, documented gap, the same shape `app.services.lexicon
.link_row`'s own docstring already accepts for the inflectional merge rule:
a sense elsewhere in the catalogue that would NOW also qualify (because the
just-enriched sense started matching it) is not flagged until the next full
backfill notices. Flagging the other side too would mean writing to lexemes
nobody asked this call about, which is a wider blast radius than "the
lexemes this batch just enriched" for a flag that is allowed to be a
release behind.
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import or_
from sqlalchemy import update as sa_update
from sqlmodel import select

from app.core.database import AsyncSession
from app.models.lexicon import LexemeSense
from app.services.distractors import content_words

#: Two definitions are "near-identical" at this token-set Jaccard or above.
#: A named constant, not a literal, because the brief calls out this exact
#: threshold as one that will be revisited once real senses have been looked
#: at through it.
NEAR_IDENTICAL_DEFINITION_JACCARD = 0.9

#: How many senses one `IN (...)` bulk update carries at once -- a full
#: backfill's flagged set can run into the thousands, and Postgres (and
#: asyncpg's own parameter encoding) would rather see it in slices than one
#: enormous list.
_UPDATE_CHUNK = 1000


def _tokens(definition: str) -> frozenset[str]:
    """A definition's content words, for comparison only -- the same
    tokenisation the distractor pipeline's similarity guard already uses
    (`app.services.distractors.content_words`), reused rather than
    reinvented so "two definitions mean roughly the same thing" is answered
    one way in this codebase, not two that could quietly disagree."""
    return frozenset(content_words(definition))


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """The token-set Jaccard similarity of two definitions' content words.
    ``0.0`` when either is empty -- an empty definition is not "identical"
    to another empty one, it is simply nothing to compare, and treating two
    blanks as a match would flag every un-enriched provisional sense against
    every other one."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


_Row = tuple[uuid.UUID, uuid.UUID, str | None, str]  # sense_id, lexeme_id, synset, definition


def _compute_flags(rows: list[_Row]) -> dict[uuid.UUID, bool]:
    """``needs_letter_hint`` for every sense in ``rows``, checked against
    every OTHER row in the same list -- the shared core both
    :func:`recompute_all` and :func:`recompute_for_lexemes` run, so a sense
    scoped for writing by either caller is judged against the identical
    corpus.

    The synset check is a plain grouping (cheap: at most a few hundred
    lexemes ever share one synset). The definition check uses an inverted
    index -- content word -> candidate senses -- so a sense is only ever
    compared against the OTHER senses it shares at least one content word
    with, not the whole table: at a threshold of 0.9 two definitions cannot
    be near-identical without sharing almost every word anyway, so nothing
    a real match needs is lost by skipping candidates with zero overlap.
    """
    flags: dict[uuid.UUID, bool] = {row[0]: False for row in rows}

    # --- 1. Shares an OEWN synset with a sense of another lexeme. --------
    lexemes_by_synset: dict[str, set[uuid.UUID]] = defaultdict(set)
    for sense_id, lexeme_id, synset, _definition in rows:
        if synset:
            lexemes_by_synset[synset].add(lexeme_id)
    cross_lexeme_synsets = {
        synset for synset, lexeme_ids in lexemes_by_synset.items() if len(lexeme_ids) > 1
    }
    for sense_id, _lexeme_id, synset, _definition in rows:
        if synset in cross_lexeme_synsets:
            flags[sense_id] = True

    # --- 2. A (near-)identical definition, on a sense of another lexeme. -
    tokens_by_sense: dict[uuid.UUID, frozenset[str]] = {}
    inverted: dict[str, list[int]] = defaultdict(list)
    for index, (sense_id, _lexeme_id, _synset, definition) in enumerate(rows):
        tokens = _tokens(definition)
        tokens_by_sense[sense_id] = tokens
        for token in tokens:
            inverted[token].append(index)

    checked: set[tuple[int, int]] = set()
    for i, (sense_id_i, lexeme_id_i, _synset_i, _definition_i) in enumerate(rows):
        tokens_i = tokens_by_sense[sense_id_i]
        if not tokens_i:
            continue
        candidates: set[int] = set()
        for token in tokens_i:
            candidates.update(inverted[token])
        for j in candidates:
            if j <= i:
                continue
            pair = (i, j)
            if pair in checked:
                continue
            checked.add(pair)
            sense_id_j, lexeme_id_j, _synset_j, _definition_j = rows[j]
            if lexeme_id_i == lexeme_id_j:
                continue
            if jaccard(tokens_i, tokens_by_sense[sense_id_j]) >= NEAR_IDENTICAL_DEFINITION_JACCARD:
                flags[sense_id_i] = True
                flags[sense_id_j] = True

    return flags


async def _load_all_rows(session: AsyncSession) -> list[_Row]:
    rows = await session.exec(
        select(
            LexemeSense.id,
            LexemeSense.lexeme_id,
            LexemeSense.oewn_synset_id,
            LexemeSense.definition_en,
        )
    )
    return list(rows.all())


async def _load_seed_rows(
    session: AsyncSession, lexeme_ids: list[uuid.UUID]
) -> list[_Row]:
    """The senses OF ``lexeme_ids`` themselves -- what :func:`recompute_for_
    lexemes` actually writes, and the starting point for finding everything
    else that could possibly change their answer."""
    rows = await session.exec(
        select(
            LexemeSense.id,
            LexemeSense.lexeme_id,
            LexemeSense.oewn_synset_id,
            LexemeSense.definition_en,
        ).where(LexemeSense.lexeme_id.in_(lexeme_ids))
    )
    return list(rows.all())


async def _load_candidate_rows(
    session: AsyncSession, seed_rows: list[_Row]
) -> list[_Row]:
    """Every OTHER sense that could possibly flip one of ``seed_rows``' own
    flags -- so :func:`recompute_for_lexemes` never has to load the WHOLE
    catalogue to judge a handful of just-enriched lexemes, the thing this
    function exists to avoid.

    :func:`_compute_flags` only ever flags a pair of senses two ways: they
    share an OEWN synset, or their definitions' content words overlap
    enough to reach the Jaccard threshold -- which cannot happen at all
    without sharing at least one content word. A sense with neither -- not
    one of the seeds' own synsets, and not one of their definitions' own
    content words anywhere in ITS definition -- cannot be the OTHER half of
    either check for any seed row, so it is safe to leave unloaded; nothing
    it could have swung for a row in ``seed_rows`` is missed.

    The second half is the inverted index :func:`_compute_flags` builds in
    memory, run here as a query instead: a candidate whose ``definition_en``
    contains one of the seeds' own (stemmed) content words as a substring --
    which is enough, since :func:`app.services.distractors._stem` only ever
    STRIPS a suffix, so the stem is always a literal prefix of any inflected
    form of the word it came from, and a broader-than-necessary substring
    match costs a few extra rows loaded, never a missed one.
    """
    synsets = {synset for _sid, _lid, synset, _definition in seed_rows if synset}
    stems: set[str] = set()
    for _sid, _lid, _synset, definition in seed_rows:
        stems |= _tokens(definition)

    clauses = []
    if synsets:
        clauses.append(LexemeSense.oewn_synset_id.in_(synsets))
    if stems:
        clauses.append(
            or_(*(LexemeSense.definition_en.ilike(f"%{stem}%") for stem in stems))
        )
    if not clauses:
        return []
    rows = await session.exec(
        select(
            LexemeSense.id,
            LexemeSense.lexeme_id,
            LexemeSense.oewn_synset_id,
            LexemeSense.definition_en,
        ).where(or_(*clauses))
    )
    return list(rows.all())


async def _write_flags(
    session: AsyncSession, flags: dict[uuid.UUID, bool], sense_ids: set[uuid.UUID]
) -> int:
    """Write ``flags`` for exactly ``sense_ids`` (a subset of ``flags``'
    own keys), in two bulk updates -- true and false -- chunked so neither
    ``IN`` list grows past :data:`_UPDATE_CHUNK`. Returns how many were set
    ``True``."""
    true_ids = [sid for sid in sense_ids if flags.get(sid)]
    false_ids = [sid for sid in sense_ids if not flags.get(sid)]

    for value, ids in ((True, true_ids), (False, false_ids)):
        for start in range(0, len(ids), _UPDATE_CHUNK):
            chunk = ids[start : start + _UPDATE_CHUNK]
            if not chunk:
                continue
            await session.execute(
                sa_update(LexemeSense)
                .where(LexemeSense.id.in_(chunk))
                .values(needs_letter_hint=value)
            )
    await session.commit()
    return len(true_ids)


async def recompute_all(session: AsyncSession) -> int:
    """Recompute ``needs_letter_hint`` for EVERY sense in the catalogue --
    the one-off (or occasionally re-run) full backfill
    (`scripts/backfill_letter_hint.py`). Returns how many senses ended up
    flagged ``True``, which is the number the brief asks to be reported."""
    rows = await _load_all_rows(session)
    if not rows:
        return 0
    flags = _compute_flags(rows)
    return await _write_flags(session, flags, set(flags))


async def recompute_for_lexemes(
    session: AsyncSession, lexeme_ids: list[uuid.UUID]
) -> int:
    """Recompute ``needs_letter_hint`` for the senses of ``lexeme_ids`` only
    -- the worker's hook, called after `app.services.lexicon_enrich.enrich`
    has just rewritten their senses' `definition_en`/`oewn_synset_id`.

    Compared against every OTHER sense that could actually match one
    (:func:`_load_candidate_rows`), not the whole catalogue -- a worker
    batch is a handful of lexemes, and loading every sense in the database
    to judge them, every pass, is the cost this restriction removes without
    changing a single answer: the touched senses' own flags come out
    exactly what a full backfill would give them, because nothing left
    unloaded could have swung either check for them (see that function's
    own docstring). Only the senses OUTSIDE ``lexeme_ids`` are left
    unwritten, per the module docstring's documented gap -- unchanged from
    before this restriction, since it was always about which rows get
    WRITTEN, not which get loaded to judge them.
    """
    if not lexeme_ids:
        return 0
    seed_rows = await _load_seed_rows(session, lexeme_ids)
    if not seed_rows:
        return 0
    candidate_rows = await _load_candidate_rows(session, seed_rows)
    rows_by_id: dict[uuid.UUID, _Row] = {row[0]: row for row in seed_rows}
    for row in candidate_rows:
        rows_by_id.setdefault(row[0], row)
    flags = _compute_flags(list(rows_by_id.values()))
    touched = {row[0] for row in seed_rows}
    return await _write_flags(session, flags, touched)

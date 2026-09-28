"""`app.services.lexicon_hints` -- whether recall's first-letter cue is
worth showing (`brief-vocabulary-tuzatish-browse.md` §B).

Real DB, plain service calls -- no HTTP layer sits in front of this module.
"""

import uuid

import pytest
from sqlmodel import select

from app.core.database import async_session_factory
from app.models.lexicon import Lexeme, LexemeSense
from app.services import lexicon_hints


async def _make_lexeme(tag: str, **kwargs) -> Lexeme:
    async with async_session_factory() as session:
        lexeme = Lexeme(lemma=f"hint-{tag}", pos="n", **kwargs)
        session.add(lexeme)
        await session.commit()
        await session.refresh(lexeme)
        return lexeme


async def _make_sense(lexeme_id: uuid.UUID, **kwargs) -> LexemeSense:
    async with async_session_factory() as session:
        sense = LexemeSense(lexeme_id=lexeme_id, **kwargs)
        session.add(sense)
        await session.commit()
        await session.refresh(sense)
        return sense


async def _reload(sense_id: uuid.UUID) -> LexemeSense:
    async with async_session_factory() as session:
        sense = await session.get(LexemeSense, sense_id)
        assert sense is not None
        return sense


async def _cleanup(lexeme_ids: tuple[uuid.UUID, ...]) -> None:
    async with async_session_factory() as session:
        for lexeme_id in lexeme_ids:
            for sense in (
                await session.exec(
                    select(LexemeSense).where(LexemeSense.lexeme_id == lexeme_id)
                )
            ).all():
                await session.delete(sense)
            await session.flush()
            lexeme = await session.get(Lexeme, lexeme_id)
            if lexeme is not None:
                await session.delete(lexeme)
        await session.commit()


def test_jaccard_of_two_empty_sets_is_zero_not_a_match():
    assert lexicon_hints.jaccard(frozenset(), frozenset()) == 0.0


def test_jaccard_is_the_usual_ratio():
    a = frozenset({"shortage", "situation", "enough"})
    b = frozenset({"shortage", "situation", "supply"})
    # 2 shared / 4 union = 0.5
    assert lexicon_hints.jaccard(a, b) == 0.5


@pytest.mark.asyncio
async def test_recompute_all_flags_senses_sharing_a_synset_across_lexemes():
    tag = uuid.uuid4().hex[:8]
    lex_a = await _make_lexeme(f"synset-a-{tag}")
    lex_b = await _make_lexeme(f"synset-b-{tag}")
    lex_c = await _make_lexeme(f"synset-c-{tag}")
    sense_a = await _make_sense(
        lex_a.id, definition_en="a rare synonym pairing", oewn_synset_id="n001",
    )
    sense_b = await _make_sense(
        lex_b.id, definition_en="a completely different meaning entirely",
        oewn_synset_id="n001",
    )
    # A third, unrelated sense with no synset and nothing in common --
    # never flagged.
    sense_c = await _make_sense(
        lex_c.id, definition_en="an entirely unrelated idea about nothing shared",
    )
    try:
        async with async_session_factory() as session:
            flagged = await lexicon_hints.recompute_all(session)
        assert flagged >= 2

        assert (await _reload(sense_a.id)).needs_letter_hint is True
        assert (await _reload(sense_b.id)).needs_letter_hint is True
        assert (await _reload(sense_c.id)).needs_letter_hint is False
    finally:
        await _cleanup((lex_a.id, lex_b.id, lex_c.id))


@pytest.mark.asyncio
async def test_recompute_all_flags_near_identical_definitions_across_lexemes():
    tag = uuid.uuid4().hex[:8]
    lex_shortage = await _make_lexeme(f"shortage-{tag}")
    lex_scarcity = await _make_lexeme(f"scarcity-{tag}")
    lex_unrelated = await _make_lexeme(f"unrelated-{tag}")
    sense_shortage = await _make_sense(
        lex_shortage.id,
        definition_en="a situation in which there is not enough of something",
    )
    sense_scarcity = await _make_sense(
        lex_scarcity.id,
        definition_en="the situation in which there is not enough of something",
    )
    sense_unrelated = await _make_sense(
        lex_unrelated.id,
        definition_en="a formal ceremony held to mark an important occasion",
    )
    try:
        async with async_session_factory() as session:
            await lexicon_hints.recompute_all(session)

        assert (await _reload(sense_shortage.id)).needs_letter_hint is True
        assert (await _reload(sense_scarcity.id)).needs_letter_hint is True
        assert (await _reload(sense_unrelated.id)).needs_letter_hint is False
    finally:
        await _cleanup((lex_shortage.id, lex_scarcity.id, lex_unrelated.id))


@pytest.mark.asyncio
async def test_two_senses_of_the_same_lexeme_never_flag_each_other():
    """Sharing a synset or a definition is ordinary WITHIN one lexeme's own
    senses -- the rule only asks about ANOTHER lexeme."""
    tag = uuid.uuid4().hex[:8]
    lexeme = await _make_lexeme(f"self-{tag}")
    first = await _make_sense(
        lexeme.id, sense_rank=1, definition_en="a shared meaning",
        oewn_synset_id="n777",
    )
    second = await _make_sense(
        lexeme.id, sense_rank=2, definition_en="a shared meaning",
        oewn_synset_id="n777",
    )
    try:
        async with async_session_factory() as session:
            await lexicon_hints.recompute_all(session)
        assert (await _reload(first.id)).needs_letter_hint is False
        assert (await _reload(second.id)).needs_letter_hint is False
    finally:
        await _cleanup((lexeme.id,))


@pytest.mark.asyncio
async def test_recompute_for_lexemes_only_writes_the_touched_lexemes():
    """The worker's own hook: compared against the whole catalogue, but
    only the SENSES of the lexemes named are actually written -- the
    documented gap for the other side of a newly-formed match."""
    tag = uuid.uuid4().hex[:8]
    lex_a = await _make_lexeme(f"scoped-a-{tag}")
    lex_b = await _make_lexeme(f"scoped-b-{tag}")
    sense_a = await _make_sense(
        lex_a.id, definition_en="a rarely used matching phrase", oewn_synset_id="n555",
    )
    sense_b = await _make_sense(
        lex_b.id, definition_en="a rarely used matching phrase", oewn_synset_id="n555",
    )
    try:
        async with async_session_factory() as session:
            changed = await lexicon_hints.recompute_for_lexemes(session, [lex_a.id])
        assert changed == 1
        assert (await _reload(sense_a.id)).needs_letter_hint is True
        # `lex_b` was never in the scoped call -- its sense is untouched
        # (still `False`, the column's default), even though a full
        # backfill would flag it too.
        assert (await _reload(sense_b.id)).needs_letter_hint is False
    finally:
        await _cleanup((lex_a.id, lex_b.id))


@pytest.mark.asyncio
async def test_recompute_for_lexemes_with_no_ids_is_a_no_op():
    async with async_session_factory() as session:
        assert await lexicon_hints.recompute_for_lexemes(session, []) == 0


@pytest.mark.asyncio
async def test_recompute_for_lexemes_finds_a_near_identical_definition_without_loading_the_whole_catalogue():
    """The restricted candidate query (`_load_candidate_rows`) must still
    reach a match that shares no synset at all -- only overlapping content
    words -- exactly as a full-catalogue load would have, for item 8's
    "keep results identical" requirement."""
    tag = uuid.uuid4().hex[:8]
    lex_shortage = await _make_lexeme(f"restrict-shortage-{tag}")
    lex_scarcity = await _make_lexeme(f"restrict-scarcity-{tag}")
    lex_unrelated = await _make_lexeme(f"restrict-unrelated-{tag}")
    sense_shortage = await _make_sense(
        lex_shortage.id,
        definition_en="a situation in which there is not enough of something",
    )
    sense_scarcity = await _make_sense(
        lex_scarcity.id,
        definition_en="the situation in which there is not enough of something",
    )
    # Present in the database at the same time, sharing neither a synset
    # nor a content word with either -- must NOT be pulled in as a
    # candidate, and must NOT end up flagged (it is never touched).
    sense_unrelated = await _make_sense(
        lex_unrelated.id,
        definition_en="a formal ceremony held to mark an important occasion",
    )
    try:
        async with async_session_factory() as session:
            changed = await lexicon_hints.recompute_for_lexemes(
                session, [lex_shortage.id]
            )
        assert changed == 1
        assert (await _reload(sense_shortage.id)).needs_letter_hint is True
        assert (await _reload(sense_unrelated.id)).needs_letter_hint is False
    finally:
        await _cleanup((lex_shortage.id, lex_scarcity.id, lex_unrelated.id))


@pytest.mark.asyncio
async def test_recompute_for_lexemes_matches_a_full_backfill_over_the_same_senses():
    """The restricted call and the full backfill must agree on every
    touched sense -- narrower candidate loading is an optimisation, not a
    different rule."""
    tag = uuid.uuid4().hex[:8]
    lex_a = await _make_lexeme(f"parity-a-{tag}")
    lex_b = await _make_lexeme(f"parity-b-{tag}")
    lex_c = await _make_lexeme(f"parity-c-{tag}")
    sense_a = await _make_sense(
        lex_a.id, definition_en="a rare synonym pairing", oewn_synset_id="n909",
    )
    sense_b = await _make_sense(
        lex_b.id, definition_en="a completely different meaning entirely",
        oewn_synset_id="n909",
    )
    sense_c = await _make_sense(
        lex_c.id, definition_en="an entirely unrelated idea about nothing shared",
    )
    try:
        async with async_session_factory() as session:
            full_flags = lexicon_hints._compute_flags(
                await lexicon_hints._load_all_rows(session)
            )
        async with async_session_factory() as session:
            await lexicon_hints.recompute_for_lexemes(session, [lex_a.id])

        assert (await _reload(sense_a.id)).needs_letter_hint == full_flags[sense_a.id]
        assert full_flags[sense_a.id] is True
    finally:
        await _cleanup((lex_a.id, lex_b.id, lex_c.id))

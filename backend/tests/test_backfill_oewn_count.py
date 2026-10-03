"""`scripts.backfill_oewn_count`: writes the count, fills a NULL rank, never
renumbers an existing rank, and is idempotent."""

import uuid

import pytest
from sqlmodel import select

from app.core.database import async_session_factory
from app.models.lexicon import Lexeme, LexemeSense
from app.services import lexicon_enrich as le
from scripts import backfill_oewn_count


@pytest.mark.asyncio
async def test_backfill_writes_count_keeps_rank_fills_null_rank_and_is_idempotent(monkeypatch) -> None:
    lemma = f"bfc{uuid.uuid4().hex[:10]}"
    monkeypatch.setattr(le, "load_oewn", lambda: {(lemma, "n"): [
        {"synset": "s-a", "rank": 1, "definition": "a", "count": 0},
        {"synset": "s-b", "rank": 2, "definition": "b", "count": 9},
    ]})
    async with async_session_factory() as session:
        lx = Lexeme(lemma=lemma, pos="n")
        session.add(lx)
        await session.flush()
        a = LexemeSense(lexeme_id=lx.id, definition_en="a", meaning_uz="A", oewn_synset_id="s-a",
                        oewn_rank=7)
        b = LexemeSense(lexeme_id=lx.id, definition_en="b", meaning_uz="B", oewn_synset_id="s-b")
        session.add_all([a, b])
        await session.commit()
        ids = (a.id, b.id)
    try:
        for _ in range(2):  # the second run changes nothing
            await backfill_oewn_count.main(False)
            async with async_session_factory() as session:
                got = {s.id: s for s in (await session.exec(
                    select(LexemeSense).where(LexemeSense.id.in_(ids)))).all()}
            assert (got[ids[0]].oewn_rank, got[ids[0]].oewn_count) == (7, 0)  # rank untouched
            assert (got[ids[1]].oewn_rank, got[ids[1]].oewn_count) == (2, 9)  # NULL rank filled
    finally:
        async with async_session_factory() as session:
            for sid in ids:
                row = await session.get(LexemeSense, sid)
                if row:
                    await session.delete(row)
            lx_row = await session.get(Lexeme, lx.id)
            if lx_row:
                await session.delete(lx_row)
            await session.commit()

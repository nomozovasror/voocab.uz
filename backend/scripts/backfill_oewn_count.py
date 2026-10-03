"""Fill ``lexeme_senses.oewn_count`` (and ``oewn_rank`` only where it is NULL)
from the OEWN extract. An existing rank is never renumbered.

    uv run python -m scripts.backfill_oewn_count            # apply
    uv run python -m scripts.backfill_oewn_count --dry-run  # count only

Matched by (lexeme.lemma, lexeme.pos, sense.oewn_synset_id) against
`lexicon_enrich.load_oewn()`. Idempotent. Senses with no OEWN synset
(model senses) keep NULL -- "no data", which the lookup shows as no label.
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import update as sa_update
from sqlmodel import select

from app.core.database import async_session_factory
from app.models.lexicon import Lexeme, LexemeSense
from app.services import lexicon_enrich as le


async def main(dry_run: bool) -> None:
    oewn = le.load_oewn()
    async with async_session_factory() as session:
        rows = (await session.exec(
            select(LexemeSense.id, LexemeSense.oewn_rank, LexemeSense.oewn_count,
                   LexemeSense.oewn_synset_id, Lexeme.lemma, Lexeme.pos)
            .join(Lexeme, Lexeme.id == LexemeSense.lexeme_id)
            .where(LexemeSense.oewn_synset_id.is_not(None))
        )).all()
        print(f"{len(rows)} senses carry an OEWN synset")
        updated = missing = 0
        for sense_id, rank, count, synset, lemma, pos in rows:
            entry = next((e for e in oewn.get((lemma, pos), []) if e["synset"] == synset), None)
            if entry is None:
                missing += 1
                continue
            values: dict[str, int] = {}
            if count != entry["count"]:
                values["oewn_count"] = entry["count"]
            if rank is None:
                values["oewn_rank"] = entry["rank"]
            if not values:
                continue
            updated += 1
            if not dry_run:
                await session.execute(
                    sa_update(LexemeSense).where(LexemeSense.id == sense_id).values(**values))
        if not dry_run:
            await session.commit()
    print(f"{'would update' if dry_run else 'updated'} {updated}; "
          f"{missing} synset(s) not in the current extract")


if __name__ == "__main__":
    asyncio.run(main("--dry-run" in sys.argv))

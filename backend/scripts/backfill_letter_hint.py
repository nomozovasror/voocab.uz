"""One-off (or occasionally re-run) full backfill of
``lexeme_senses.needs_letter_hint`` (`app.services.lexicon_hints`).

Run from ``backend/``::

    uv run python -m scripts.backfill_letter_hint

Every sense in whatever database ``DATABASE_URL`` points at is checked
against every other -- see `app.services.lexicon_hints.recompute_all` for
the comparison itself (shared OEWN synset, or a near-identical definition,
with another LEXEME's sense). Prints how many senses ended up flagged
``True``, which is the number the brief asks this backfill to report.

Point ``DATABASE_URL`` at a throwaway copy of the dev database to get that
number without writing to the database anybody is actually using -- this
script commits, it does not merely read:

    createdb -h localhost -U postgres -T app app_letter_hint_check
    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/app_letter_hint_check \\
        uv run alembic upgrade head
    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/app_letter_hint_check \\
        uv run python -m scripts.backfill_letter_hint
    dropdb -h localhost -U postgres app_letter_hint_check

The worker's own enrichment loop (`app.worker._lexicon_enrich_once`) keeps
individual lexemes' flags fresh as they are re-enriched, but only for the
lexemes it just touched (`app.services.lexicon_hints.recompute_for_lexemes`,
see its own docstring for the documented gap) -- this script is what
catches every sense back up to a full-corpus comparison, and is the right
thing to re-run after a large batch of new lexemes has landed.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.database import async_session_factory
from app.services import lexicon_hints

logger = logging.getLogger("scripts.backfill_letter_hint")


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    async with async_session_factory() as session:
        flagged = await lexicon_hints.recompute_all(session)
    print(f"needs_letter_hint: {flagged} sense(s) flagged True")


if __name__ == "__main__":
    asyncio.run(main())

"""One collection per book, in the order the book prints its tests.

    cd backend && uv run --no-sync python -m scripts.seed_collections
    cd backend && uv run --no-sync python -m scripts.seed_collections --reset

The catalogue answers what exists; a collection answers what to do in what
order, and 256 loose papers is exactly the library that cannot say that about
itself. Fourteen books go in as fourteen sequences -- Test 1 Part 1 through to
the last part of the last test -- which is also the order somebody checking
this corpus wants to walk it in.

Idempotent, and keyed by TITLE like `import_section.py` is: a second run
re-points the same fourteen collections at the same materials rather than
making fourteen more. The order is rewritten every time, because the order is
the thing a collection is for and a material imported late should not sit at
the end of its book.

`cover_seed` is set to the book's catalogue id rather than left to fall back
on the collection's own uuid. A cover is a pure function of one string, and
the uuid changes if a collection is ever deleted and rebuilt -- which would
quietly re-cover the whole shelf. The seed does not change, so Cambridge 14 is
the same book on every machine and after every rebuild.
"""

import argparse
import asyncio
import logging
import pathlib
import re
import sqlite3
import uuid

from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.collection import Collection, CollectionItem
from app.models.material import Material
from app.services import collections as collections_service

CATALOGUE = pathlib.Path(__file__).resolve().parent.parent.parent / "seed" / "catalogue.db"
#: The same owner every seeded material is imported under.
OWNER = uuid.UUID("d2b9f563-9669-4fb3-b6dc-51536c8baac1")

logger = logging.getLogger("seed_collections")


def books() -> list[dict]:
    """Each book, its sections in printed order, and how to describe it."""
    conn = sqlite3.connect(CATALOGUE)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT b.number, b.title, s.test_no, s.section_no "
        "FROM book b JOIN section s ON s.book_number = b.number "
        "ORDER BY b.number, s.test_no, s.section_no").fetchall()
    conn.close()
    out: dict[int, dict] = {}
    for row in rows:
        book = out.setdefault(row["number"], {
            "number": row["number"], "title": row["title"], "sections": []})
        book["sections"].append((row["test_no"], row["section_no"]))
    return list(out.values())


def summarise(book: dict) -> str:
    """One line saying what the book is, which is what a summary is for."""
    tests = len({test for test, _ in book["sections"]})
    return (f"{len(book['sections'])} listening sections — "
            f"{tests} complete {'test' if tests == 1 else 'tests'}, four parts each")


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reset", action="store_true",
                    help="remove the collections this script made, and nothing else")
    ap.add_argument("--owner", default=str(OWNER))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    owner = uuid.UUID(args.owner)

    async with async_session_factory() as session:
        titles = {m.title: m for m in (await session.scalars(
            select(Material).where(Material.author_id == owner))).all()}

        for book in books():
            wanted = [titles.get(f"{book['title']} — Test {test}, Part {part}")
                      for test, part in book["sections"]]
            found = [m for m in wanted if m is not None]
            missing = len(wanted) - len(found)

            existing = (await session.scalars(select(Collection).where(
                Collection.author_id == owner,
                Collection.title == book["title"]))).first()

            if args.reset:
                if existing is not None:
                    await collections_service.delete(session, existing)
                    logger.info("removed %s", book["title"])
                continue

            if not found:
                logger.info("%s: no materials imported yet, skipped", book["title"])
                continue

            if existing is None:
                existing = await collections_service.create(
                    session, owner, title=book["title"], summary=summarise(book))
            else:
                existing.summary = summarise(book)
            # Stable across a delete and a rebuild; see the module docstring.
            existing.cover_seed = f"book-{book['number']}"
            session.add(existing)
            await session.commit()

            await collections_service.set_items(
                session, existing, [m.id for m in found])
            logger.info("%s: %d material(s)%s", book["title"], len(found),
                        f", {missing} not imported yet" if missing else "")

        if not args.reset:
            total = len((await session.scalars(select(CollectionItem))).all())
            logger.info("%d collection item(s) in all", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

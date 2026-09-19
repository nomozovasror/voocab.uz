"""One collection per book per paper, in the order the book prints its tests.

    cd backend && uv run --no-sync python -m scripts.seed_collections
    cd backend && uv run --no-sync python -m scripts.seed_collections --reset

The catalogue answers what exists; a collection answers what to do in what
order, and 447 loose papers is exactly the library that cannot say that about
itself. Fourteen books go in as twenty-eight sequences -- Test 1 Part 1
through to the last part of the last test, and Test 1 Reading Passage 1
through to the last passage of the last test -- which is also the order
somebody checking this corpus wants to walk it in.

**Two per book, not one.** A collection is a sequence through ONE paper:
``next_material_id`` is the first of its items the learner has not sat, and
the picker that fills it offers that paper's catalogue. A book whose course
alternated a listening part with a reading passage would be a course whose
order had stopped meaning anything -- and a learner sitting down to read
would be handed a recording.

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


#: What each paper's course is called, what its pieces are called on the
#: material titles that identify them, and how many make a whole test. One
#: table rather than two code paths: everything below differs between the
#: papers in these four strings and nowhere else.
PAPERS = {
    "listening": {"table": "section", "number": "section_no",
                  "piece": "Part", "per_test": 4, "noun": "listening sections",
                  "each": "four parts each", "suffix": ""},
    "reading": {"table": "passage", "number": "passage_no",
                "piece": "Reading Passage", "per_test": 3,
                "noun": "reading passages", "each": "three passages each",
                "suffix": " — Reading"},
}


def books(skill: str) -> list[dict]:
    """Each book, its pieces of one paper in printed order."""
    paper = PAPERS[skill]
    conn = sqlite3.connect(CATALOGUE)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"SELECT b.number, b.title, s.test_no, s.{paper['number']} AS piece_no "
        f"FROM book b JOIN {paper['table']} s ON s.book_number = b.number "
        f"ORDER BY b.number, s.test_no, s.{paper['number']}").fetchall()
    conn.close()
    out: dict[int, dict] = {}
    for row in rows:
        book = out.setdefault(row["number"], {
            "number": row["number"], "title": row["title"], "pieces": []})
        book["pieces"].append((row["test_no"], row["piece_no"]))
    return list(out.values())


def summarise(book: dict, skill: str) -> str:
    """One line saying what the book is, which is what a summary is for."""
    paper = PAPERS[skill]
    tests = len({test for test, _ in book["pieces"]})
    return (f"{len(book['pieces'])} {paper['noun']} — "
            f"{tests} complete {'test' if tests == 1 else 'tests'},"
            f" {paper['each']}")


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

        for skill, paper in PAPERS.items():
            for book in books(skill):
                title = f"{book['title']}{paper['suffix']}"
                wanted = [
                    titles.get(f"{book['title']} — Test {test},"
                               f" {paper['piece']} {piece}")
                    for test, piece in book["pieces"]
                ]
                found = [m for m in wanted if m is not None]
                missing = len(wanted) - len(found)

                existing = (await session.scalars(select(Collection).where(
                    Collection.author_id == owner,
                    Collection.title == title))).first()

                if args.reset:
                    if existing is not None:
                        await collections_service.delete(session, existing)
                        logger.info("removed %s", title)
                    continue

                if not found:
                    logger.info("%s: no materials imported yet, skipped", title)
                    continue

                if existing is None:
                    existing = await collections_service.create(
                        session, owner, title=title,
                        summary=summarise(book, skill), skill=skill)
                else:
                    existing.summary = summarise(book, skill)
                # Stable across a delete and a rebuild; see the module
                # docstring. The paper is IN the seed, so a book's two
                # courses are two different books on the shelf rather than
                # one cover printed twice.
                existing.cover_seed = f"book-{book['number']}{paper['suffix']}"
                session.add(existing)
                await session.commit()

                await collections_service.set_items(
                    session, existing, [m.id for m in found])
                logger.info("%s: %d material(s)%s", title, len(found),
                            f", {missing} not imported yet" if missing else "")

        if not args.reset:
            total = len((await session.scalars(select(CollectionItem))).all())
            logger.info("%d collection item(s) in all", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

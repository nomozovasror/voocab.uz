"""Rename every seeded material to the title its importer now generates.

    cd backend && uv run --no-sync python -m scripts.retitle_seeded --dry-run
    cd backend && uv run --no-sync python -m scripts.retitle_seeded

A one-off, and it exists because **the title is the key the importers dedup
on**. ``import_section`` and ``import_passage`` both look a material up by
the string they would generate for it; change that string and the next run
does not update 447 materials, it creates 447 more beside them.

So the rename happens here, once, from the catalogue: every book, test and
part or passage is asked what it used to be called and what it is called
now, and the material carrying the old name is given the new one. Nothing is
created and nothing is deleted — a material whose old title is not in the
database was never imported, and one whose new title is already there has
been renamed already, which is what makes this safe to run twice.

The old shapes, for the record:

    listening   "Cambridge IELTS 11 — Test 4, Part 2"
    reading     "Cambridge IELTS 11 — Test 4, Reading Passage 2"

and the new:

    listening   "C11 T4 · Part 2"
    reading     "An Introduction to Film Sound — C11 T4 P2"

The book's full name is not lost: it is the COLLECTION's title, one course
per book per paper, and a material reached from anywhere else is reached by
its own name — which for a reading passage is the name the book prints over
it, and for a listening part was never anything but a coordinate.
"""

import argparse
import asyncio
import json
import pathlib
import sqlite3
import sys

from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.material import Material

from scripts.import_section import book_code

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
SEED = REPO / "seed"


def renames() -> list[tuple[str, str]]:
    """(old title, new title) for every seeded section and passage."""
    conn = sqlite3.connect(SEED / "catalogue.db")
    conn.row_factory = sqlite3.Row
    out: list[tuple[str, str]] = []

    for row in conn.execute(
            "SELECT s.book_number, s.test_no, s.section_no, b.title AS book "
            "FROM section s JOIN book b ON b.number = s.book_number "
            "ORDER BY s.book_number, s.test_no, s.section_no"):
        old = f"{row['book']} — Test {row['test_no']}, Part {row['section_no']}"
        new = (f"{book_code(row['book_number'])} T{row['test_no']}"
               f" · Part {row['section_no']}")
        out.append((old, new))

    for row in conn.execute(
            "SELECT p.id, p.book_number, p.test_no, p.passage_no, b.title AS book "
            "FROM passage p JOIN book b ON b.number = p.book_number "
            "ORDER BY p.book_number, p.test_no, p.passage_no"):
        old = (f"{row['book']} — Test {row['test_no']},"
               f" Reading Passage {row['passage_no']}")
        where = (f"{book_code(row['book_number'])} T{row['test_no']}"
                 f" P{row['passage_no']}")
        # The passage's own name, from the same file the importer reads it
        # from — so a material renamed here and one imported fresh come out
        # with the same string.
        path = SEED / "work" / row["id"] / "passage.json"
        named = ""
        if path.exists():
            named = (json.loads(path.read_text()).get("title") or "").strip()
        out.append((old, f"{named} — {where}" if named else where))

    conn.close()
    return out


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="say what would change and change nothing")
    args = ap.parse_args()

    async with async_session_factory() as session:
        held = {m.title: m for m in
                (await session.scalars(select(Material))).all()}

        done = moved = clashed = 0
        for old, new in renames():
            if new in held:
                done += 1
                continue
            material = held.get(old)
            if material is None:
                continue
            # Never onto a name something else already answers to. Two
            # materials with one title would make the importers' dedup pick
            # whichever the database returned first.
            print(f"  {old}\n    -> {new}")
            if not args.dry_run:
                material.title = new
                session.add(material)
            held[new] = material
            moved += 1
        if not args.dry_run:
            await session.commit()

    print(f"\n{moved} renamed{' (dry run)' if args.dry_run else ''},"
          f" {done} already carried the new title")
    if clashed:
        print(f"{clashed} skipped: the new title was already taken",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

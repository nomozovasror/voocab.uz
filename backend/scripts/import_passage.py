"""Write a seeded reading passage into the app database.

    uv run python -m scripts.import_passage cam11-t1-p2 --owner <user-uuid>

The reading half of ``import_section``. It writes far less, because a paper
you read has far less: there is no recording, so no blob, no transcript, no
segments and no replay spans -- what is left is a material, one part carrying
the passage, and the questions answered from it.

What it writes, for one passage:

* a ``Material`` of type ``reading`` with no audio asset at all. That column
  is nullable and a reading material is the reason it is: publishing asks for
  a recording only of a paper that is heard
  (``_paper_blockers`` in ``app/services/publishing.py``).
* one ``Part`` whose ``passage`` column holds the text -- title, source line,
  and the paragraphs with the letters the book prints beside them.
* its question groups, through the same ``import_questions`` the listening
  importer uses and therefore through the same schemas. A seed script that
  inserted rows behind those would be the one caller allowed to write a
  material the editor could never have produced.

Private, like every other seeded material, and for the same reason: this is
copyrighted source, and it is in the database to prove the pipeline works.
``publish_seeded.py`` is where that decision is made, once, for everything.
"""

import argparse
import asyncio
import json
import logging
import pathlib
import sqlite3
import sys
import uuid

from sqlmodel import select

from app.core.database import async_session_factory
from app.models.material import Material
from app.models.part import Part
from app.models.user import User

from scripts.import_section import import_questions

logger = logging.getLogger("scripts.import_passage")

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
SEED = REPO / "seed"

#: The number this passage's first question carries on the whole paper. An
#: Academic Reading paper runs 1 to 40 straight through its three passages,
#: in a shape the exam fixes rather than the book -- so a seeded Passage 2
#: numbered from 1 would print "Question 1" where the answer key says 14.
FIRST_NUMBER = {1: 1, 2: 14, 3: 27}


def read_passage(passage_id: str) -> tuple[dict, dict, str]:
    """The catalogue row, the passage text, and the material's title."""
    conn = sqlite3.connect(SEED / "catalogue.db")
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT p.*, b.title AS book_title FROM passage p "
        "JOIN book b ON b.number = p.book_number WHERE p.id = ?",
        (passage_id,)).fetchone()
    conn.close()
    if row is None:
        raise SystemExit(f"{passage_id} is not in the catalogue")

    path = SEED / "work" / passage_id / "passage.json"
    if not path.exists():
        raise SystemExit(
            f"{passage_id}: no passage text. Run seed/read_passages.py first.")
    held = json.loads(path.read_text())
    if not held.get("paragraphs"):
        raise SystemExit(f"{passage_id}: the passage text is empty")

    # Exactly the shape `Part.passage` documents, and nothing else: the
    # faults the reader recorded are its own bookkeeping and have no business
    # in the app's database.
    passage = {
        "title": held.get("title"),
        "subtitle": held.get("subtitle"),
        "source": held.get("source"),
        "paragraphs": [{"label": one.get("label"), "text": one["text"]}
                       for one in held["paragraphs"]],
    }
    # The book's own title, as the listening importer uses, and for the same
    # reason: it is the key this script dedups on, so a title built from the
    # book NUMBER would call IELTS Trainer "Cambridge IELTS 101" and a change
    # to it later would seed a second copy instead of updating the first.
    title = (f"{row['book_title']} — Test {row['test_no']},"
             f" Reading Passage {row['passage_no']}")
    return dict(row), passage, title


async def import_passage(passage_id: str, owner_id: uuid.UUID) -> None:
    row, passage, title = read_passage(passage_id)
    first_number = FIRST_NUMBER[row["passage_no"]]

    async with async_session_factory() as session:
        if await session.get(User, owner_id) is None:
            raise SystemExit(f"no user {owner_id}")

        # Re-running must not leave a second copy behind. There is no natural
        # key on a material, so the title this script generates is the key it
        # looks itself up by -- the same bargain import_section makes.
        material = (await session.exec(
            select(Material).where(Material.author_id == owner_id,
                                   Material.title == title))).first()
        if material is None:
            material = Material(
                author_id=owner_id, type="reading", title=title,
                audio_asset_id=None,
                visibility="private",  # copyrighted source; never public from here
            )
            session.add(material)
            await session.flush()
            part = Part(material_id=material.id, order_index=0,
                        title=f"Reading Passage {row['passage_no']}",
                        passage=passage, first_number=first_number)
            session.add(part)
            await session.flush()
            logger.info("created material %s", material.id)
        else:
            part = (await session.exec(
                select(Part).where(Part.material_id == material.id)
                .order_by(Part.order_index))).first()
            if part is None:
                raise SystemExit(
                    f"{passage_id}: material {material.id} has no part; it was "
                    "not written by this script")
            logger.info("material %s already existed", material.id)

        # Written on EVERY import, not only on creation. A re-import is what
        # happens after the passage was read again -- a transcription that
        # stopped early, a lettering fixed -- and keeping the old text because
        # the material already existed is how a corrected passage silently
        # fails to reach the page. Same rule as the listening importer's
        # transcript.
        part.passage = passage
        part.title = f"Reading Passage {row['passage_no']}"
        part.first_number = first_number
        session.add(part)

        written = await import_questions(session, part.id, passage_id)
        if written:
            # Every authoring write bumps the counter the editor checks
            # against.
            material.version += 1
            session.add(material)

        await session.commit()
        material_id = str(material.id)

    words = sum(len(one["text"].split()) for one in passage["paragraphs"])
    print(f"{passage_id} -> material {material_id} "
          f"({len(passage['paragraphs'])} paragraphs, {words} words, "
          f"{written} questions, private)")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("passage_id", nargs="?")
    ap.add_argument("--book", type=int,
                    help="every passage of one book that has been read")
    ap.add_argument("--all", action="store_true",
                    help="every passage that has a text and questions on disk")
    ap.add_argument("--owner", required=True, type=uuid.UUID)
    args = ap.parse_args()

    if args.passage_id:
        ids = [args.passage_id]
    else:
        conn = sqlite3.connect(SEED / "catalogue.db")
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id FROM passage"
            + (" WHERE book_number = ?" if args.book else "")
            + " ORDER BY book_number, test_no, passage_no",
            (args.book,) if args.book else ()).fetchall()
        conn.close()
        # Only what is actually ready. A passage whose text or questions have
        # not been read is not a failure to report here -- it is a stage that
        # has not run, and the readers' own --report says so.
        ids = [row["id"] for row in rows
               if (SEED / "work" / row["id"] / "passage.json").exists()
               and (SEED / "work" / row["id"] / "questions.json").exists()]
        if not ids:
            print("nothing ready to import; run seed/read_passages.py, "
                  "seed/read_passage_questions.py and seed/build_questions.py",
                  file=sys.stderr)
            return 1

    failed: list[str] = []
    for passage_id in ids:
        try:
            asyncio.run(import_passage(passage_id, args.owner))
        except (Exception, SystemExit) as failure:  # noqa: BLE001
            print(f"{passage_id} FAILED  {failure}", file=sys.stderr)
            failed.append(passage_id)
    if failed:
        print(f"\n{len(failed)} passage(s) failed: {', '.join(failed)}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

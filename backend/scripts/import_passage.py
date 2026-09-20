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
from app.services import difficulty as difficulty_service
from app.services import vocabulary as vocabulary_service

from scripts.import_section import book_code, import_questions

logger = logging.getLogger("scripts.import_passage")

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
SEED = REPO / "seed"

#: The tasks a paragraph's LETTER is the answer to.
#:
#: A book letters its paragraphs when, and only when, something asks the
#: candidate to name one. So the questions say whether the letters on a
#: passage are the book's -- and four of this corpus's 191 carry letters no
#: question uses, every one of them invented by a reader that was told not
#: to: "The psychology of innovation" came back lettered A to K off a page
#: whose margin is empty.
#:
#: Dropped rather than kept, because a letter nothing is answered with is
#: either decoration or a lie, and there is no way to tell which from here.
#: A passage the book really does letter and never asks about loses nothing
#: a learner can act on.
#: Matching FEATURES is not one of them: its answers are letters from its
#: own box -- "A Dr Helmut Fischer, B Anthony Berwick" -- naming a person or
#: a study rather than a paragraph.
BY_LETTER = {"matching_information", "matching_headings"}

#: The number this passage's first question carries on the whole paper. An
#: Academic Reading paper runs 1 to 40 straight through its three passages,
#: in a shape the exam fixes rather than the book -- so a seeded Passage 2
#: numbered from 1 would print "Question 1" where the answer key says 14.
FIRST_NUMBER = {1: 1, 2: 14, 3: 27}


def read_passage(passage_id: str) -> tuple[dict, dict, str, str]:
    """The catalogue row, the passage text, its reference and its title."""
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

    # Whether anything on this paper is answered by naming a paragraph. See
    # BY_LETTER.
    built = SEED / "work" / passage_id / "questions.json"
    asks_by_letter = False
    if built.exists():
        asks_by_letter = any(
            group.get("type") in BY_LETTER
            for group in json.loads(built.read_text()).get("groups", []))

    # Exactly the shape `Part.passage` documents, and nothing else: the
    # faults the reader recorded are its own bookkeeping and have no business
    # in the app's database.
    passage = {
        "title": held.get("title"),
        "subtitle": held.get("subtitle"),
        "source": held.get("source"),
        "paragraphs": [
            {"label": one.get("label") if asks_by_letter else None,
             "text": one["text"]}
            for one in held["paragraphs"]
        ],
    }
    # "An Introduction to Film Sound — C11 T4 P2".
    #
    # The passage's OWN name first, because that is what a reader picks by
    # and what survives truncation in a list of a hundred and ninety-one.
    # The book and the test after it, short: the book's full name is in the
    # collection, one course per book, and repeating it on every card is
    # thirty-odd characters saying the same thing twelve times over.
    #
    # Where a passage has no title of its own the code stands alone rather
    # than a blank leading a dash. Every passage in this corpus has one --
    # `read_passages.py` goes to the sheet before to find it -- so this is
    # for a book that has not been read yet, not for one of these.
    # Two things, in two columns. The reference says which test in which
    # book; the title is what the book calls the passage. They used to be run
    # together -- "An Introduction to Film Sound — C11 T4 P2" -- and the card
    # printed the pair as one heading, the importers used the pair as a key,
    # and `seed_status` picked the reference back out with a regular
    # expression. See the `b3e91a7c40d2` migration.
    reference = (f"{book_code(row['book_number'])} T{row['test_no']}"
                 f" P{row['passage_no']}")
    # Every passage in this corpus prints a title. A book that did not would
    # leave the reference standing as the name, which is honest: it is the
    # only thing anybody knows to call it.
    title = (passage.get("title") or "").strip() or reference
    return dict(row), passage, reference, title


async def import_vocabulary(session, material_id: uuid.UUID,
                            part_id: uuid.UUID, passage_id: str) -> int:
    """The passage's glossed words, where `read_vocabulary.py` has left any.

    Optional, and silent when there is nothing: `vocab` is an optional stage
    in `run_reading.py` for the reason written there -- a passage with no
    glosses is still a passage worth sitting -- so an import that insisted on
    finding the file would turn a loss of help into a loss of the paper.

    Re-run on every import, like the passage text and the questions. A
    passage re-read is a passage whose offsets have moved, and glosses left
    over from the previous reading would point at the wrong words. What
    survives is anything an author has touched, which the service decides
    from the `source` column rather than this script.
    """
    path = SEED / "work" / passage_id / "vocabulary.json"
    if not path.exists():
        return 0
    read = json.loads(path.read_text())
    written, kept = await vocabulary_service.replace_extracted(
        session, material_id=material_id, part_id=part_id,
        rows=read.get("entries") or [])
    if kept:
        logger.info("kept %d author-edited entries", kept)

    # How much of the passage is outside the frequency lists. Measured while
    # the text was being read and recoverable from nowhere else -- the lists
    # live in the seed venv, not the backend's -- so this is the one chance
    # to record it. It gives a material nobody has sat a difficulty band
    # instead of "New", until twenty answers replace the guess.
    share = (read.get("profile") or {}).get("off_list_share")
    if share is not None:
        await difficulty_service.set_vocabulary_load(
            session, material_id, float(share))
    return written


async def import_passage(passage_id: str, owner_id: uuid.UUID) -> None:
    row, passage, reference, title = read_passage(passage_id)
    first_number = FIRST_NUMBER[row["passage_no"]]

    async with async_session_factory() as session:
        if await session.get(User, owner_id) is None:
            raise SystemExit(f"no user {owner_id}")

        # Re-running must not leave a second copy behind, and the REFERENCE is
        # what it looks itself up by -- the same bargain import_section makes.
        # It used to be the title, which meant the key was a display string:
        # renaming the corpus had to be done as a migration rather than a
        # re-import, twice, because a re-import would not have recognised its
        # own work.
        # WITH the type. "C10 T1 P1" is Cambridge 10's first test, first
        # paper -- and every test has two of those, a listening Part 1 and a
        # reading Passage 1. The reference names a place in a book; which of
        # the two papers is the material's own type, and looking one up
        # without saying which finds the other one half the time.
        material = (await session.exec(
            select(Material).where(Material.author_id == owner_id,
                                   Material.type == "reading",
                                   Material.reference == reference))).first()
        if material is None:
            material = Material(
                author_id=owner_id, type="reading", title=title,
                reference=reference,
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
        # The title too, for the same reason: a passage re-read with its
        # opening recovered is a passage whose printed title has only just
        # been found.
        material.title = title
        session.add(material)

        part.passage = passage
        part.title = f"Reading Passage {row['passage_no']}"
        part.first_number = first_number
        session.add(part)

        glossed = await import_vocabulary(session, material.id, part.id,
                                          passage_id)

        written = await import_questions(session, part.id, passage_id)
        if written:
            # Every authoring write bumps the counter the editor checks
            # against.
            material.version += 1
            session.add(material)

        await session.commit()
        material_id = str(material.id)
        # What it IS, not what a fresh one would be. Re-importing does not
        # withdraw a published material -- publishing is publish_seeded's
        # decision and this script does not take it back -- so saying
        # "private" unconditionally was a line that told the operator the
        # opposite of what had happened.
        seen = material.visibility

    words = sum(len(one["text"].split()) for one in passage["paragraphs"])
    print(f"{passage_id} -> material {material_id} "
          f"({len(passage['paragraphs'])} paragraphs, {words} words, "
          f"{written} questions, {glossed} glossed, {seen})")


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

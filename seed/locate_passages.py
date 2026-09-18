"""Group a book's reading pages into passages, and write them to the catalogue.

`locate_pages.py` already read every page of every book and asked what it was.
Eight hundred and twenty-nine came back `reading`, and most of them carry the
two things this needs: the running header that names the test, and the heading
that names the passage. So the first pass here spends nothing at all -- it
reads the page maps already sitting in `work/` and groups them.

    seed/.venv/bin/python seed/locate_passages.py            # every book
    seed/.venv/bin/python seed/locate_passages.py --book 11
    seed/.venv/bin/python seed/locate_passages.py --report   # what is missing

**Grouping is arithmetic, not a second reading.** A page headed READING
PASSAGE 2 starts passage 2; the pages after it with no heading of their own
belong to it, which is the rule `locate_pages` already uses for listening
sections. Passages run 1, 2, 3 and start over, so a run of them is one test --
nothing is inferred that the book does not print.

What it does NOT do is guess. A book whose pages carry no passage heading
comes back empty and says so, because the alternative -- splitting 62 pages
into runs of three and hoping -- is the kind of confident wrong answer this
pipeline exists to avoid. Those go to a narrowed re-read (`--read`), which is
the same lesson every stage here learned: ask the one question that is left.

## General Training is not this exam

Two books print a General Training Reading paper beside the Academic one.
It is a different test with different passages, and thirty-three pages of it
would otherwise arrive as academic material nobody could sit. They are
dropped, by name, off the page the book prints it on.
"""

import argparse
import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

SEED = Path(__file__).resolve().parent
WORK = SEED / "work"

#: "READING PASSAGE 2", in the shapes the fourteen books print it.
HEADING = re.compile(r"READING\s+PASSAGE\s+([0-9]+|I{1,3})\b", re.I)
ROMAN = {"I": 1, "II": 2, "III": 3}

#: The other paper. Named on the page, so it is dropped by what it says rather
#: than by which pages somebody counted.
GENERAL_TRAINING = re.compile(r"General\s+Training", re.I)


def passage_number(text: str | None) -> int | None:
    """Which passage this page's heading names, or None where it names none."""
    match = HEADING.search(text or "")
    if not match:
        return None
    raw = match.group(1).upper()
    return ROMAN.get(raw) or (int(raw) if raw.isdigit() else None)


def page_maps(book: int) -> list[tuple[int, list[dict]]]:
    """Every cached page map for this book, as (document id, pages)."""
    out = []
    for path in sorted(WORK.glob(f"pagemap-book{book}-doc*.json")):
        doc_id = int(path.stem.split("doc")[-1])
        out.append((doc_id, json.loads(path.read_text())))
    return out


def academic_reading(pages: list[dict]) -> list[dict]:
    """The pages of the Academic Reading paper, in page order.

    Bridged the way `locate_pages` bridges a run of audioscripts: ONE page
    inside a run of reading pages that came back as something else is a
    misreading, not the end of the paper. Cambridge 11's Reading runs pdf 15
    to 28 without a break, and four of those came back `audioscript` or
    `listening_questions` -- so passage 2 was located as two pages of a
    three-page passage, and the text in between would simply never have been
    read.

    One page, and only with reading on BOTH sides. Two in a row is the paper
    really ending, and absorbing those would pull the writing task in after
    it.
    """
    by_index = {page["index"]: page for page in pages}

    def is_reading(page: dict | None) -> bool:
        if page is None or page.get("kind") != "reading":
            return False
        return not GENERAL_TRAINING.search(
            f"{page.get('header') or ''} {page.get('heading') or ''}"
        )

    kept = []
    for index in sorted(by_index):
        page = by_index[index]
        if is_reading(page):
            kept.append(page)
        elif is_reading(by_index.get(index - 1)) and is_reading(
            by_index.get(index + 1)
        ):
            # Bridged. It keeps whatever the page map said it was, so the
            # misreading stays visible; what changes is only that the passage
            # it sits in no longer has a hole in it.
            kept.append(page)
    return kept


def group(pages: list[dict], first_test: int = 1) -> list[dict]:
    """Runs of pages, one per passage, from the headings the book prints.

    A heading starts a passage. A page without one continues whichever was
    last started. A number that does not go up starts the next TEST, which is
    the same arithmetic `locate_pages` uses on listening sections: they run
    1..4 and begin again, so a run is a test.

    Repeating the same number is the running header being read twice, not a
    second passage: only a CHANGE begins anything.
    """
    found: list[dict] = []
    current: dict | None = None
    test = first_test
    last: int | None = None

    for page in pages:
        number = passage_number(page.get("heading"))
        if number is not None and number != last:
            if last is not None and number <= last:
                test += 1
            current = {"test": test, "passage": number, "pages": []}
            found.append(current)
            last = number
        if current is not None:
            current["pages"].append(page["index"])

    # A passage ENDS; it does not run until the next one begins.
    #
    # "No heading continues the last passage" is right inside the paper and
    # wrong at the end of it: after passage 3 comes the writing task, and the
    # next READING PASSAGE 1 heading may be forty pages away, in the next
    # test. Left unbounded, every third passage swallowed the rest of the
    # book — one came out at sixty-one pages.
    #
    # So each keeps its leading CONTIGUOUS run and no more. The reading paper
    # is a continuous block of sheets, so a jump is another test's pages that
    # happen to be reading too, and they belong to whichever passage the
    # heading hunt finds them under -- not to this one.
    for one in found:
        pages = one["pages"]
        end = 1
        while end < len(pages) and pages[end] == pages[end - 1] + 1:
            end += 1
        one["pages"] = pages[:end]
    return found


def locate(book: int) -> tuple[list[dict], list[dict]]:
    """This book's passages, and the documents that gave up none.

    Book 20 is four files of one test each, so a document is a test there and
    the run restarts per file. Everywhere else one file holds every test and
    the runs are continuous -- the same "one universe or four" the listening
    locator settled.
    """
    maps = page_maps(book)
    per_document = len(maps) > 1
    passages: list[dict] = []
    barren: list[dict] = []

    for position, (doc_id, pages) in enumerate(maps, start=1):
        reading = academic_reading(pages)
        if not reading:
            continue
        found = group(reading, first_test=position if per_document else 1)
        if not found:
            barren.append({"doc_id": doc_id, "pages": len(reading)})
            continue
        for one in found:
            one["doc_id"] = doc_id
        passages += found

    return passages, barren


def write(conn: sqlite3.Connection, book: int, passages: list[dict]) -> int:
    """Upsert what was found. Nothing is deleted: a passage located by hand,
    or by a re-read, is not undone by a run that could not see it."""
    written = 0
    for one in passages:
        # Three to a paper. A fourth is a misread, and writing it would put a
        # passage nobody can sit into the corpus rather than a line in the
        # report saying the book was read wrong.
        if not 1 <= one["passage"] <= 3:
            continue
        conn.execute(
            """INSERT INTO passage
                   (id, book_number, test_no, passage_no, document_id, pages,
                    located_by)
               VALUES (?, ?, ?, ?, ?, ?, 'heading')
               ON CONFLICT(id) DO UPDATE SET
                   document_id = excluded.document_id,
                   pages       = excluded.pages,
                   located_by  = excluded.located_by""",
            (
                f"cam{book}-t{one['test']}-p{one['passage']}",
                book,
                one["test"],
                one["passage"],
                one["doc_id"],
                json.dumps(one["pages"]),
            ),
        )
        written += 1
    return written


def report(conn: sqlite3.Connection) -> None:
    """What is located and what is not, per book.

    `want` is four tests of three unless the catalogue says otherwise: the
    Guide prints eight and the two Trainers six, and the number of listening
    sections already records which -- sixteen sections is four tests.
    """
    rows = conn.execute(
        """SELECT b.number,
                  (SELECT COUNT(*) FROM section  s WHERE s.book_number = b.number) AS sections,
                  (SELECT COUNT(*) FROM passage  p WHERE p.book_number = b.number) AS found
           FROM book b ORDER BY b.number"""
    ).fetchall()

    print(f"{'book':<7}{'tests':>7}{'want':>7}{'found':>7}{'left':>7}")
    total_want = total_found = 0
    for row in rows:
        tests = row["sections"] // 4
        want = tests * 3
        total_want += want
        total_found += row["found"]
        left = want - row["found"]
        print(
            f"{row['number']:<7}{tests:>7}{want:>7}{row['found']:>7}"
            f"{left if left else '-':>7}"
        )
    print(f"\n{total_found} of {total_want} passages located"
          f" ({total_want - total_found} left)")

    # Located is not the same as right. A reading passage is two to five
    # sheets of text and questions; one page is a heading the grouper found
    # and a passage it did not, and eight is two passages read as one. Named
    # rather than dropped, because which of the two it is can only be settled
    # by looking at the page -- and a count that quietly excluded them would
    # be the report agreeing with itself.
    odd = [
        (row["id"], len(json.loads(row["pages"] or "[]")))
        for row in conn.execute("SELECT id, pages FROM passage ORDER BY id")
        if not 2 <= len(json.loads(row["pages"] or "[]")) <= 8
    ]
    if odd:
        print(f"\n{len(odd)} located but not plausible — a passage is 2 to 5 pages:")
        for passage_id, count in odd:
            print(f"  {passage_id:<16} {count} page{'' if count == 1 else 's'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", type=int, help="one book, rather than all of them")
    parser.add_argument("--report", action="store_true",
                        help="print what is located and what is not, and stop")
    args = parser.parse_args()

    conn = sqlite3.connect(SEED / "catalogue.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    if args.report:
        report(conn)
        return

    books = (
        [args.book]
        if args.book
        else [r["number"] for r in conn.execute("SELECT number FROM book ORDER BY number")]
    )

    barren_books: list[int] = []
    for book in books:
        passages, barren = locate(book)
        written = write(conn, book, passages)
        conn.commit()
        by_test: dict[int, int] = defaultdict(int)
        for one in passages:
            by_test[one["test"]] += 1
        odd = sorted(t for t, n in by_test.items() if n != 3)
        note = f"  tests with not-three: {odd}" if odd else ""
        print(f"book {book:<4} {written:>3} passages"
              f"{'  (nothing found)' if not written else ''}{note}")
        if barren:
            barren_books.append(book)
            for one in barren:
                print(f"    doc {one['doc_id']}: {one['pages']} reading pages,"
                      " no passage heading on any of them")

    if barren_books:
        print(f"\nBooks needing a narrowed re-read: {barren_books}")
    print()
    report(conn)


if __name__ == "__main__":
    main()

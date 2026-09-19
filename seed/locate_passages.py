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

import vision

SEED = Path(__file__).resolve().parent
REPO = SEED.parent
MATERIALS = REPO / "Materials"
WORK = SEED / "work"

#: "READING PASSAGE 2", in the shapes the fourteen books print it.
HEADING = re.compile(r"READING\s+PASSAGE\s+([0-9]+|I{1,3})\b", re.I)
ROMAN = {"I": 1, "II": 2, "III": 3}

#: The other paper. Named on the page, so it is dropped by what it says rather
#: than by which pages somebody counted.
GENERAL_TRAINING = re.compile(r"General\s+Training", re.I)

#: A page that shows how a task works rather than setting it. The two Trainers
#: print their teaching pages beside the real tests and number their exercises
#: from 1 — so a teaching sheet reading "Questions 1-6" is indistinguishable
#: from a test's passage 1 by its numbers alone, and thirteen of Trainer 2's
#: eighteen passages came out grouped around them. The header says which it
#: is: "Training Test 1" against "Exam Practice Test 1".
#:
#: The same expression `locate_pages` uses, lookbehind included — "General
#: Training" is a paper, not a lesson.
TEACHING = re.compile(r"(?<!general )\btraining\b", re.I)

#: The most sheets a reading passage runs to. Three of text and two of
#: questions is the usual shape; five and a bit is the longest real one in
#: fourteen books.
MAX_PAGES = 8

#: The test, where the page prints it: "Test 1 READING", "Exam Practice Test
#: 3", "Test1-reading-passage1". Printed evidence beats the run-counting
#: below, which can only infer a boundary and is fooled by any page whose
#: numbers were misread.
TEST_IN_HEADER = re.compile(r"\bTest\s*(\d{1,2})\b", re.I)


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
        said = f"{page.get('header') or ''} {page.get('heading') or ''}"
        return not (GENERAL_TRAINING.search(said) or TEACHING.search(said))

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

    return bound(found)


def bound(found: list[dict]) -> list[dict]:
    """Each passage keeps its leading CONTIGUOUS run of pages, and no more.

    A passage ENDS; it does not run until the next one begins.
    #
    "No heading continues the last passage" is right inside the paper and
    wrong at the end of it: after passage 3 comes the writing task, and the
    next READING PASSAGE 1 heading may be forty pages away, in the next test.
    Left unbounded, every third passage swallowed the rest of the book — one
    came out at sixty-one pages.

    The reading path needs it for a different reason and gets it from the same
    rule: there, pages are assigned by the question numbers printed on them,
    so ONE misread page lands in a passage it is nowhere near. Trainer 2's
    test 2 came out holding pages 75-79, 84 and 88. Dropping the strays leaves
    a passage short rather than wrong, and the report says which.
    """
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


def test_count(conn: sqlite3.Connection, book: int) -> int:
    """How many tests this book has, off what is already catalogued.

    Every test is four listening sections, and all 256 of those were
    inventoried from the files themselves — so this is a fact about the book
    rather than a number anybody typed.
    """
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM section WHERE book_number = ?", (book,)
    ).fetchone()
    return (row["n"] or 0) // 4


def write(conn: sqlite3.Connection, book: int, passages: list[dict],
          how: str = "heading") -> tuple[int, list[str]]:
    """Upsert what was found, and name what was refused.

    Nothing is deleted: a passage located by hand, or by a re-read, is not
    undone by a run that could not see it.
    """
    tests = test_count(conn, book)
    written = 0
    refused: list[str] = []
    for one in passages:
        # Three to a paper. A fourth is a misread, and writing it would put a
        # passage nobody can sit into the corpus rather than a line in the
        # report saying the book was read wrong.
        if not 1 <= one["passage"] <= 3:
            continue
        # A book has as many tests as it has, and the grouping cannot discover
        # more. "Numbers that do not go up are the next test" is the only
        # thing that says where a test ends, and it is fooled twice over:
        #
        #  * Book 10 prints a GENERAL TRAINING reading paper after its four
        #    academic tests. It is a different exam, it is laid out exactly
        #    like the real ones, and it arrived as tests 5 and 6.
        #  * The Trainer's teaching pages carry question numbers of their own,
        #    and four stray single pages arrived as tests 7 and 8.
        #
        # Both are caught by the same line, because both claim a test the book
        # does not have. Refused and named — a count that silently dropped
        # them would be the report agreeing with itself.
        # A passage is a handful of sheets. Forty is not one passage read
        # long; it is a block of pages that all claimed to be passage 1 and
        # never progressed — which is what the Official Guide's teaching
        # section looks like from here. It prints eighty pages of short
        # exercises before its eight tests, each numbered from 1 in its own
        # right, and they carry no running header to be told apart by.
        #
        # Refused for the same reason a test the book does not have is: it
        # would put into the corpus something nobody can sit. The report then
        # says the test is short a passage, which is true and visible, rather
        # than showing it complete and wrong.
        if len(one["pages"]) > MAX_PAGES:
            refused.append(
                f"cam{book}-t{one['test']}-p{one['passage']}"
                f" ({len(one['pages'])} pages)"
            )
            continue
        if tests and one["test"] > tests:
            refused.append(
                f"cam{book}-t{one['test']}-p{one['passage']}"
                f" ({len(one['pages'])} page{'' if len(one['pages']) == 1 else 's'})"
            )
            continue
        conn.execute(
            """INSERT INTO passage
                   (id, book_number, test_no, passage_no, document_id, pages,
                    title, located_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   document_id = excluded.document_id,
                   pages       = excluded.pages,
                   title       = COALESCE(excluded.title, passage.title),
                   located_by  = excluded.located_by""",
            (
                f"cam{book}-t{one['test']}-p{one['passage']}",
                book,
                one["test"],
                one["passage"],
                one["doc_id"],
                json.dumps(one["pages"]),
                one.get("title"),
                how,
            ),
        )
        written += 1
    return written, refused


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

    # A test missing one of its three, with the other two present. Different
    # from a book nothing was found in: here the paper IS located and one
    # passage of it is not, which is either a grouping that dropped it or a
    # sheet the scanner never took. The two look identical from here and only
    # the pages can tell them apart, so this names it rather than deciding.
    held: dict[tuple[int, int], set[int]] = defaultdict(set)
    for row in conn.execute("SELECT book_number, test_no, passage_no FROM passage"):
        held[(row["book_number"], row["test_no"])].add(row["passage_no"])
    gaps = sorted(
        (book, test, sorted({1, 2, 3} - numbers))
        for (book, test), numbers in held.items()
        if numbers and len(numbers) < 3
    )
    if gaps:
        print(f"\n{len(gaps)} test(s) located with a passage missing:")
        for book, test, absent in gaps:
            which = ", ".join(f"p{n}" for n in absent)
            print(f"  book {book} test {test}: {which}")


# --- Asking the page itself -------------------------------------------------

#: The one question left, and nothing else.
#:
#: Every stage in this pipeline learned the same lesson: a general question
#: gets a general answer. `locate_pages` asked each page what it WAS and got
#: "reading" for all 829 of these, which is true and not what is needed now.
#: What is needed is which passage of which test — and on the books that come
#: here, the heading does not say, so the page has to be asked about the two
#: things that do: the number its questions carry, and the paper it belongs
#: to.
#:
#: Question numbers, because an Academic Reading paper runs 1 to 40 across
#: three passages in a fixed shape: roughly 1-13, 14-26, 27-40. A page headed
#: "Questions 14-19" is passage 2 whatever its heading says, and that is
#: arithmetic rather than a guess.
ASK = """This is one page of an IELTS book. Answer about THIS PAGE ONLY.

Give me, as JSON and nothing else:

{"paper": "reading" | "listening" | "writing" | "speaking" | "other",
 "numbers": [the question numbers printed on this page, as integers],
 "title": "the passage's own title, if this page prints one, else null",
 "test": the test number if the page prints one, else null,
 "continues": true if this page is the middle or end of a passage that
              started earlier (no title, no question numbers at the top),
              else false}

Rules:
- "numbers" is what is PRINTED beside the questions, not a count. A page with
  "Questions 14-19" gives [14,15,16,17,18,19]. A page of prose with no
  questions on it gives [].
- Do not infer the test number from the question numbers. Every test numbers
  its reading questions 1 to 40, so they say nothing about which test it is.
- "title" is the passage's own heading, like "The kākāpō" — not "READING
  PASSAGE 2" and not a running header."""


def passage_of(numbers: list[int]) -> int | None:
    """Which passage a page's question numbers put it in.

    An Academic Reading paper numbers 1 to 40 straight through its three
    passages, and the boundaries fall in a narrow band — 13 or 14, and 26 or
    27. So the LOWEST number on the page settles it, and a page whose numbers
    straddle a boundary belongs to the passage its first question is in.

    None where there are no numbers: a page of pure prose is part of whichever
    passage it continues, which is the caller's arithmetic and not this one's.
    """
    if not numbers:
        return None
    first = min(numbers)
    if first <= 13:
        return 1
    if first <= 26:
        return 2
    return 3


def read_document(conn, book: int, doc_id: int, rel_path: str,
                  indices: list[int], test_hint: int | None) -> list[dict]:
    """Ask each of a document's reading pages the narrow question, and group.

    Pages are read ONE AT A TIME, which is the measurement `locate_pages`
    already made and paid for: a twelve-up contact sheet costs the same tokens
    as one page and gets a twelfth of the detail, and on twelve pages it
    classified five correctly and invented two.
    """
    # Cached, like every other reading in this pipeline. The grouping below
    # got its rule wrong on the first run — the text pages come BEFORE the
    # questions, not after — and fixing it should not cost the pages again.
    cache = WORK / f"passages-book{book}-doc{doc_id}.json"
    if cache.exists():
        answers = json.loads(cache.read_text())
        print(f"    {len(answers)} pages (cached)")
    else:
        pdf = MATERIALS / rel_path
        images = vision.render(pdf, indices, WORK / f"passages-book{book}-doc{doc_id}")
        headers = {page["index"]: page.get("header")
                   for page in academic_reading(
                       [p for _, pages in page_maps(book) for p in pages])}
        answers = []
        for index, image in zip(indices, images):
            reply = vision.ask_json(ASK, [image])
            reply["index"] = index
            # What the BOOK prints in its running head, carried through from
            # the page map. Not what the model concluded: asked for the test
            # number it returns the first question number, which is the same
            # slip `locate_pages` records for listening.
            reply["header"] = headers.get(index)
            answers.append(reply)
            shown = reply.get("numbers") or []
            print(f"    {index:>4}  {str(reply.get('paper')):<9}"
                  f" {('q' + str(min(shown)) + '-' + str(max(shown))) if shown else '—':<10}"
                  f" {reply.get('title') or ''}")
        cache.write_text(json.dumps(answers, indent=2, ensure_ascii=False))

    # Group what came back. The rule is the shape of the paper, and the first
    # run got it backwards.
    #
    # A reading passage is printed TEXT FIRST, questions after — three or four
    # sheets of prose with nothing numbered on them, then two of questions. So
    # a page with no question numbers belongs to the passage whose questions
    # come NEXT, not to the one whose questions came last. Read the other way,
    # every passage took the following passage's text and passage 1 lost its
    # own.
    #
    # So number-less pages are held and handed to whichever passage claims
    # them. What is left holding at the end of a document is the tail — a
    # page after the last question — and goes to the passage it followed.
    found: list[dict] = []
    by_passage: dict[tuple[int, int], dict] = {}
    waiting: list[dict] = []
    test = test_hint or 1
    last: int | None = None
    current: dict | None = None

    for reply in answers:
        if reply.get("paper") not in (None, "reading"):
            continue
        # The test, where the book prints it. Counting runs is inference and
        # can only be fooled — one page whose numbers were misread starts a
        # test that does not exist, which is what put thirteen of Trainer 2's
        # passages under six wrong headings. "Exam Practice Test 3" is not
        # inference.
        printed = TEST_IN_HEADER.search(reply.get("header") or "")
        if printed:
            said = int(printed.group(1))
            if said != test:
                test = said
                last = None
                current = None

        number = passage_of([int(n) for n in reply.get("numbers") or []
                             if isinstance(n, (int, float))])
        if number is None:
            waiting.append(reply)
            continue

        if number != last:
            # Numbers that do not go up are the next test beginning. Only
            # where the page prints no test of its own — inference is the
            # fallback, not the rule.
            if last is not None and number <= last and not printed:
                test += 1
            key = (test, number)
            current = by_passage.get(key)
            if current is None:
                current = {"test": test, "passage": number, "pages": [],
                           "title": None, "doc_id": doc_id}
                by_passage[key] = current
                found.append(current)
            last = number

        assert current is not None
        for held in waiting:
            current["pages"].append(held["index"])
            if not current["title"] and held.get("title"):
                current["title"] = held["title"]
        waiting = []
        current["pages"].append(reply["index"])
        if not current["title"] and reply.get("title"):
            current["title"] = reply["title"]

    # Anything still held followed the last question of the document.
    if waiting and current is not None:
        current["pages"] += [held["index"] for held in waiting]

    for one in found:
        one["pages"].sort()
    return bound(found)


def reread(conn: sqlite3.Connection, book: int) -> list[dict]:
    """Every reading page of a book, asked the narrow question.

    Only for the books the heading pass could not group. It costs one request
    per page — at book 103's ninety-three pages, the most expensive single
    thing in the reading pipeline, and still cents.
    """
    documents = {
        row["id"]: row["rel_path"]
        for row in conn.execute(
            "SELECT id, rel_path FROM document WHERE book_number = ? ORDER BY id",
            (book,),
        )
    }
    maps = page_maps(book)
    per_document = len(maps) > 1
    found: list[dict] = []

    for position, (doc_id, pages) in enumerate(maps, start=1):
        indices = [page["index"] for page in academic_reading(pages)]
        if not indices:
            continue
        rel_path = documents.get(doc_id)
        if rel_path is None:
            print(f"    doc {doc_id}: not in the catalogue, skipped")
            continue
        print(f"  doc {doc_id}: reading {len(indices)} pages")
        found += read_document(
            conn, book, doc_id, rel_path, indices,
            test_hint=position if per_document else None,
        )
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", type=int, help="one book, rather than all of them")
    parser.add_argument("--report", action="store_true",
                        help="print what is located and what is not, and stop")
    parser.add_argument("--read", action="store_true",
                        help="ask the pages themselves, for books whose "
                             "headings say nothing. Costs one request a page")
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
        if args.read:
            print(f"book {book}:")
            passages = reread(conn, book)
            written, refused = write(conn, book, passages, how="read")
            conn.commit()
            print(f"book {book:<4} {written:>3} passages, read off the page")
            if refused:
                print(f"    {len(refused)} refused — this book has"
                      f" {test_count(conn, book)} tests: {', '.join(refused)}")
            continue
        passages, barren = locate(book)
        written, refused = write(conn, book, passages)
        conn.commit()
        by_test: dict[int, int] = defaultdict(int)
        for one in passages:
            by_test[one["test"]] += 1
        odd = sorted(t for t, n in by_test.items() if n != 3)
        note = f"  tests with not-three: {odd}" if odd else ""
        print(f"book {book:<4} {written:>3} passages"
              f"{'  (nothing found)' if not written else ''}{note}")
        if refused:
            print(f"    {len(refused)} refused — this book has"
                  f" {test_count(conn, book)} tests: {', '.join(refused)}")
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

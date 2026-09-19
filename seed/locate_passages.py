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

#: The kinds of page that END a reading paper rather than interrupt it.
#:
#: These books print the papers in the order they are sat — listening,
#: reading, writing, speaking — so a reading paper cannot resume after the
#: writing task. What CAN sit inside one is a page the classifier called
#: something harmless, or, in the Trainers, a teaching page between the
#: passages of a test.
#:
#: This is what tells the two apart. Book 102's test 8 ends at sheet 312 with
#: writing and speaking after it, and the General Training paper begins three
#: sheets later; the Trainers put one `intro` page between their passages.
#: A gap measured in sheets cannot separate those two — three either way —
#: and what is IN the gap separates them exactly.
ENDS_THE_PAPER = {"writing", "speaking", "listening_questions", "audioscript",
                  "listening_answer_key", "reading_answer_key", "answer_list"}

#: How far apart two sheets can be and still be one paper.
#:
#: The Trainers print a page between the passages of a test — a tip, a
#: worked example — so a paper arrives as three blocks of four or five
#: sheets, none of which reaches question 27 on its own and none of which is
#: long enough to be a paper. Both of the rules below then threw all three
#: away, and the two Trainers lost eight tests between them.
#:
#: Three, because that is what those books actually print, and because the
#: nearest thing it could wrongly join is four pages away: book 10's General
#: Training paper begins four sheets after its last academic test.
BLOCK_GAP = 3

#: The fewest sheets a whole Academic Reading paper can be printed on. Three
#: passages of two pages each is six; five is below anything real and above
#: the strays.
#:
#: A stray page reaching question 27 is not a paper, and the cost of treating
#: it as one is not that page — it is the NUMBERING. Book 17 has four tests
#: and six accepted blocks, two of them single sheets, so its real test 4 was
#: numbered 5 and refused as a test the book does not have. The two passages
#: that vanished were never misread; they were correctly read and filed under
#: a test that does not exist.
MIN_BLOCK_PAGES = 5

#: The kinds of page that cannot be a misread reading sheet, whatever sits
#: either side of them.
#:
#: These books print the papers in the order they are sat, so the writing
#: task is where the reading paper stops — and it is the one thing a widened
#: bridge could swallow. Everything else in ENDS_THE_PAPER is a page the
#: classifier might have got wrong; these two are the paper after this one.
HARD_END = {"writing", "speaking"}

#: How long a run of non-reading pages inside a reading paper can be and
#: still be a misreading rather than the end of it.
#:
#: One was not enough. Cambridge 17 prints its third passage over five
#: sheets and the page map called three of them `listening_questions` and
#: `other` — pages 61 and 62 back to back — so the passage came out as page
#: 60 alone, and the questions to 40 with it. Book 12's test 2 lost the
#: other end the same way: the sheet carrying "Questions 4-9" of passage 1
#: was filed as a listening page, and passage 1 was located as one sheet.
#:
#: Three, because that is the longest such run in the corpus, and because
#: the bridged pages are then READ: a page the model says is listening is
#: dropped again in the block. The bridge widens what gets asked; it does
#: not widen what is believed.
BRIDGE_RUN = 3

#: What a bridge may not cross at the EDGE of a reading run, on top of
#: HARD_END.
#:
#: Inside a run of reading sheets anything can be a misreading -- there is
#: reading printed either side of it. Outside one there is not, so the stop
#: has to name every page this corpus prints near a reading paper and could
#: mistake for one. An answer key is the dangerous one: it carries the
#: numbers 1 to 40 and is about reading, so a model asked what paper it
#: belongs to says reading, and it would arrive as a fourth sheet of passage
#: 3. What is left bridgeable at an edge is what is actually confusable --
#: `other`, `intro`, and the listening question pages the classifier reached
#: for when a reading sheet carried no heading it recognised.
EDGE_STOP = {"writing", "speaking", "audioscript", "listening_answer_key",
             "reading_answer_key", "answer_list"}

#: What the report will believe of a located passage, in sheets. The corpus
#: as it stands runs 3 to 6; the band is wider than that on purpose, because
#: this is the check that says a grouping came out wrong and it should fire
#: on a real fault rather than on the next book being printed differently.
#:
#: Written down once, so the number in the message cannot drift from the
#: number in the test -- it said "2 to 5" while checking 2 to 8 for a while,
#: which is a report contradicting itself in the one line whose whole job is
#: to be doubted.
PLAUSIBLE = (2, 8)

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

    def said(page: dict) -> str:
        return f"{page.get('header') or ''} {page.get('heading') or ''}"

    def general_training(page: dict | None) -> bool:
        """The OTHER EXAM, named on the page."""
        return page is not None and bool(GENERAL_TRAINING.search(said(page)))

    def teaching(page: dict | None) -> bool:
        """A lesson in this book, named on the page."""
        return page is not None and bool(TEACHING.search(said(page)))

    def is_reading(page: dict | None) -> bool:
        return page is not None and page.get("kind") == "reading"

    # The two named exams are not one rule, and running them as one cost
    # four whole tests.
    #
    # GENERAL TRAINING is another paper, printed as its own run of sheets,
    # and only half of them carry the name. Dropping the named half left the
    # silent half looking like academic reading, close enough to the test
    # beside it to be read as one paper -- book 102's test 8 came out
    # eighteen sheets long, holding the GT paper printed three pages after
    # it. So its sheets stay in the stream and the BLOCK drops them: one
    # named sheet marks the whole run for what it is.
    #
    # A TRAINER'S LESSON is a single sheet printed BETWEEN the passages of
    # the test beside it, and it is always named -- "Training Test 1"
    # against "Exam Practice Test 1". It is not a run and it cannot be
    # judged as one: book 103's test 1 is twenty sheets of which six are
    # lessons, so condemning that block left the book showing four tests of
    # six. It drops as a PAGE, and the hole it leaves is what BLOCK_GAP is
    # for -- the passages either side of it stay contiguous.
    #
    # Both are statements about READING sheets. A page the classifier called
    # writing is not in this paper whatever its running head says, and
    # admitting it on the strength of the word "Training" put thirty-five of
    # Trainer 1's writing and speaking sheets into the stream to be read one
    # API call at a time.
    order = sorted(by_index)
    reading = [index for index in order if is_reading(by_index[index])]

    # A short run of non-reading pages with reading on BOTH sides is a
    # misreading, not the end of the paper. Bridged, it keeps whatever the
    # page map said it was -- so the misreading stays visible; what changes
    # is only that the passage it sits in no longer has a hole in it.
    bridged: set[int] = set()
    for before, after in zip(reading, reading[1:]):
        span = range(before + 1, after)
        if not len(span) or len(span) > BRIDGE_RUN:
            continue
        inside = [by_index.get(index) for index in span]
        if any(page is None
               or page.get("kind") in HARD_END
               or general_training(page)
               or teaching(page)
               for page in inside):
            continue
        bridged.update(span)

    # The same misreading at the EDGE of a run, where there is no reading
    # page on the far side to vouch for it.
    #
    # A paper's last passage ends in the writing task, so its final sheets
    # have reading before them and nothing after. Cambridge 17's test 1 put
    # three of them there — `other`, then two `listening_questions`, one of
    # them headed "Questions 36-40" — and the passage was located as the
    # single sheet that still said READING PASSAGE 3. Book 12's test 2 lost
    # the leading edge the same way, the sheet headed "Questions 4-9".
    #
    # Reaching outward asks those pages rather than believing either answer:
    # what comes back "listening" is dropped again by the block.
    inside = sorted(set(reading) | bridged)
    for index in inside:
        for step in (-1, 1):
            if (index + step) in inside:
                continue  # not an edge in this direction
            for distance in range(1, BRIDGE_RUN + 1):
                at = index + step * distance
                page = by_index.get(at)
                if (page is None or at in inside
                        or page.get("kind") in EDGE_STOP
                        or general_training(page) or teaching(page)):
                    break
                bridged.add(at)

    return [by_index[index] for index in order
            if (is_reading(by_index[index]) or index in bridged)
            and not teaching(by_index[index])]


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
    """Write what was found for this book, and name what was refused.

    A run for a book REPLACES that book. It is not an upsert: the run
    computes the whole paper from the book's own pages, so anything it did
    not find this time it does not believe any more.
    """
    tests = test_count(conn, book)
    # A run for a book REPLACES that book, because that is what it computes:
    # the whole paper, from its own pages. Upserting and leaving the rest
    # behind meant rows from earlier, buggier runs survived — book 17 wrote
    # ten passages and the report showed twelve, two of them from a grouping
    # that had since been fixed. A report that improves when the code gets
    # worse is worse than no report.
    conn.execute("DELETE FROM passage WHERE book_number = ?", (book,))
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
        if not PLAUSIBLE[0] <= len(json.loads(row["pages"] or "[]")) <= PLAUSIBLE[1]
    ]
    if odd:
        print(f"\n{len(odd)} located but not plausible — a passage is"
              f" {PLAUSIBLE[0]} to {PLAUSIBLE[1]} pages:")
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
    # A gap somebody has already been to the page about. The catalogue's
    # `finding` table is where this pipeline keeps what it learned and could
    # not fix, and one of them is addressed at a passage: the Guide's test 6
    # is four sheets short in the scan, so its passage 2 is not missing from
    # the grouping -- it is missing from the book.
    #
    # Printed BESIDE the gap rather than subtracted from it. A report that
    # quietly stopped counting what it had an excuse for would be the report
    # agreeing with itself, which is the one thing this file is for.
    accounted = {
        row["subject"]: row["summary"]
        for row in conn.execute(
            "SELECT subject, summary FROM finding WHERE severity != 'resolved'")
    }
    if gaps:
        print(f"\n{len(gaps)} test(s) located with a passage missing:")
        for book, test, absent in gaps:
            for number in absent:
                known = accounted.get(f"cam{book}-t{test}-p{number}")
                print(f"  book {book} test {test}: p{number}"
                      + (f" — {known}" if known else ""))


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


#: The last question of each passage. An Academic Reading paper numbers 1 to
#: 40 straight through in a fixed shape, so these three numbers are the exam
#: rather than a property of any book.
BAND_END = {1: 13, 2: 26, 3: 40}


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
    # Cached BY PAGE, not by document, and the difference cost a whole test.
    #
    # The cache was one file per document, taken as the answer for that
    # document. Then `academic_reading` learned to keep the other exam's
    # sheets and to bridge a misread one, so book 101's reading went from 79
    # pages to 112 — and the run kept answering off the 79. The first block
    # of the book, sixteen sheets holding a complete test, was never in the
    # cache and therefore never in the grouping: the book showed five tests
    # and its test 1 began at page 69.
    #
    # Keyed by index, the two can no longer disagree. A page that has been
    # asked is not asked again; a page that has not is asked now and joins
    # the file. It is also what makes an interrupted batch resume at the page
    # it stopped on rather than at the document.
    cache = WORK / f"passages-book{book}-doc{doc_id}.json"
    known: dict[int, dict] = {}
    if cache.exists():
        for reply in json.loads(cache.read_text()):
            if isinstance(reply.get("index"), int):
                known[reply["index"]] = reply
    missing = [index for index in indices if index not in known]
    if not missing:
        print(f"    {len(indices)} pages (cached)")
    else:
        if known:
            print(f"    {len(indices) - len(missing)} pages (cached),"
                  f" {len(missing)} to read")
        pdf = MATERIALS / rel_path
        images = vision.render(pdf, missing, WORK / f"passages-book{book}-doc{doc_id}")
        headers = {page["index"]: page.get("header")
                   for page in academic_reading(
                       [p for _, pages in page_maps(book) for p in pages])}
        for index, image in zip(missing, images):
            reply = vision.ask_json(ASK, [image])
            reply["index"] = index
            # What the BOOK prints in its running head, carried through from
            # the page map. Not what the model concluded: asked for the test
            # number it returns the first question number, which is the same
            # slip `locate_pages` records for listening.
            reply["header"] = headers.get(index)
            known[index] = reply
            shown = reply.get("numbers") or []
            print(f"    {index:>4}  {str(reply.get('paper')):<9}"
                  f" {('q' + str(min(shown)) + '-' + str(max(shown))) if shown else '—':<10}"
                  f" {reply.get('title') or ''}")
            # Written after every page, so a batch that dies eight hours in
            # keeps everything it paid for.
            cache.write_text(json.dumps(
                [known[i] for i in sorted(known)], indent=2, ensure_ascii=False))
    answers = [known[index] for index in indices if index in known]

    # Group what came back, one BLOCK of pages at a time.
    #
    # A block is a run of contiguous reading sheets, and a real Academic
    # Reading paper is exactly that: three passages printed back to back,
    # numbered 1 to 40 straight through. So a block whose questions never
    # reach past 13 is not a paper — it is a teaching exercise numbered from
    # 1 in its own right, and the Official Guide prints eighty pages of them
    # before its eight tests. Read as one stream they all claimed passage 1,
    # and the Guide's test 1 came out as a single forty-page entry that
    # looked complete.
    #
    # The rule is what the exam IS rather than what the page looks like,
    # which is why it also settles the Trainers without knowing anything
    # about them.
    # Which of this book's pages name the other EXAM, off the page map — the
    # cached answers predate the header being carried through, and this is
    # the book's own word either way. Teaching pages are not here: they were
    # dropped one at a time upstream, where they belong (`academic_reading`).
    other = {
        page["index"]
        for _, pages in page_maps(book)
        for page in pages
        if GENERAL_TRAINING.search(
            f"{page.get('header') or ''} {page.get('heading') or ''}"
        )
    }

    kinds = {
        page["index"]: page.get("kind")
        for _, pages in page_maps(book)
        for page in pages
    }

    blocks: list[list[dict]] = []
    for reply in answers:
        if reply.get("paper") not in (None, "reading"):
            continue
        joins = False
        if blocks:
            previous = blocks[-1][-1]["index"]
            span = range(previous + 1, reply["index"])
            joins = len(span) <= BLOCK_GAP and not any(
                kinds.get(index) in ENDS_THE_PAPER for index in span
            )
        if joins:
            blocks[-1].append(reply)
        else:
            blocks.append([reply])

    def numbers_of(reply: dict) -> list[int]:
        return [int(n) for n in reply.get("numbers") or []
                if isinstance(n, (int, float))]

    # A block can hold the END of the paper before it.
    #
    # Reaching outward at the edges is what put it there: Cambridge 20 prints
    # one test per PDF and each file opens on the back of the previous test's
    # last reading sheet, and Cambridge 11's test 1 ends three sheets before
    # test 2 begins. Those pages ARE reading, so they are kept -- but they
    # are another paper, and read as part of this one their questions 34-40
    # opened a passage 3 that the real passage 3 was then appended to. Eleven
    # passages came out one page long.
    #
    # Split where the numbers go DOWN, which is the same arithmetic the
    # heading pass uses on passage numbers and `locate_pages` uses on
    # listening sections: a paper runs 1 to 40 once, so a number lower than
    # the one before it is the next paper starting. Pages with no numbers on
    # them follow the split rather than lead it, because a passage is printed
    # text first.
    def papers_in(block: list[dict]) -> list[list[dict]]:
        fragments: list[list[dict]] = []
        current: list[dict] = []
        waiting: list[dict] = []
        last = 0
        for reply in block:
            number = passage_of(numbers_of(reply))
            if number is None:
                waiting.append(reply)
                continue
            if number < last:
                fragments.append(current)
                current = []
            current += waiting + [reply]
            waiting = []
            last = number
        current += waiting
        if current:
            fragments.append(current)
        return [fragment for fragment in fragments if fragment]

    def is_paper(fragment: list[dict]) -> bool:
        """A whole Academic Reading paper, rather than a run of sheets.

        A General Training paper is judged WHOLE. Half its sheets carry the
        name and half do not, so asking each one on its own keeps the half
        that is silent -- which is how six GT passages arrived as the Guide's
        test 8, complete with plausible titles: "Some places to visit", "The
        benefits of having a business mentor". One named sheet in a run of
        sheets is the run saying what it is.

        What is left has to reach its third passage and be printed on more
        than a handful of sheets. Nothing else in these books is both -- not
        a teaching exercise numbered from 1, and not the four sheets of
        another test's ending.
        """
        if any(reply["index"] in other for reply in fragment):
            return False
        numbers = [n for reply in fragment for n in numbers_of(reply)]
        return (bool(numbers) and max(numbers) >= 27
                and len(fragment) >= MIN_BLOCK_PAGES)

    def printed_test(fragment: list[dict]) -> int | None:
        """The test number in this paper's running head, if it prints one."""
        for reply in fragment:
            match = TEST_IN_HEADER.search(reply.get("header") or "")
            if match:
                return int(match.group(1))
        return None

    # A split that leaves something which is not a paper was not a paper
    # boundary. Trainer 2's test 2 has a sheet with no question numbers
    # printed on it at all, read as "1-5" three times out of three -- a
    # hallucination off the teaching list beside it -- and the numbers going
    # down cut the paper in two. The tail held questions 36 to 40, and it
    # went with it.
    #
    # Merged back rather than dropped, because within a block the pages
    # either side of a bad split belong together. A leading fragment with
    # nothing before it has nowhere to merge and is dropped as it was: that
    # is Cambridge 20's PDFs, which open on the previous test's last sheet.
    papers: list[list[dict]] = []
    for block in blocks:
        for fragment in papers_in(block):
            if is_paper(fragment):
                papers.append(fragment)
            elif papers and fragment[0]["index"] > papers[-1][-1]["index"]:
                papers[-1] += fragment

    # What the running head prints is the test's number IN ITS SERIES, not
    # its number in this book.
    #
    # Cambridge 12 carries on from Cambridge 11 and heads its four tests
    # "Test 5" to "Test 8" -- a fact the catalogue already records as a
    # finding, because the answer keys have to be matched to tests by order
    # for the same reason. Believed literally, every one of book 12's twelve
    # passages claimed a test the book does not have and all twelve were
    # refused.
    #
    # So the printed numbers are shifted to start at one, and only when they
    # have to be: a book whose heads already fit is left exactly as it is.
    # If they do not fit after shifting either, nothing is shifted and the
    # refusals stand -- a run of numbers too long for the book is not a
    # series that starts somewhere else, it is a misreading, and inventing an
    # offset for it would file passages under tests nobody can name.
    tests = test_count(conn, book)
    heads = [number for number in map(printed_test, papers) if number]
    offset = 0
    if tests and heads and max(heads) > tests and max(heads) - min(heads) < tests:
        offset = min(heads) - 1

    found: list[dict] = []
    test = test_hint or 1
    seen_test = False

    for paper in papers:
        # The test, where the book prints it in the running head. Failing
        # that, one paper is one test and they come in order -- which is the
        # same arithmetic the heading pass uses, applied to whole papers
        # rather than to pages, so a single misread page can no longer start
        # a test that does not exist.
        printed = printed_test(paper)
        if printed is not None:
            test = printed - offset
        elif seen_test:
            test += 1
        seen_test = True

        by_passage: dict[int, dict] = {}
        waiting: list[dict] = []
        current: dict | None = None
        #: Passages whose last question has been seen. A passage does not
        #: resume after it.
        finished: set[int] = set()

        for reply in paper:
            numbers = numbers_of(reply)
            number = passage_of(numbers)
            # The lowest number on the page settles which passage it is in
            # -- unless that passage has already printed its last question,
            # in which case the low number is a misreading and the high one
            # is the page.
            #
            # Cambridge 11's test 4 has a sheet of passage 2's questions 14
            # to 18 that came back "7-16". Passage 1 had ended at 13 two
            # sheets earlier, so believing the 7 gave passage 1 seven pages
            # -- three of them passage 2's text and questions -- and left
            # passage 2 as the two sheets that were left. Four more passages
            # across Cambridge 20 had the same shape.
            if (number is not None and number in finished
                    and (higher := passage_of([max(numbers)])) is not None
                    and higher > number):
                number = higher
            if number is None:
                # A passage is printed TEXT FIRST and questions after, so a
                # page with no numbers belongs to the passage whose questions
                # come NEXT. Read the other way, every passage took the
                # following one's text and passage 1 lost its own.
                waiting.append(reply)
                continue

            current = by_passage.get(number)
            if current is None:
                current = {"test": test, "passage": number, "pages": [],
                           "title": None, "doc_id": doc_id}
                by_passage[number] = current
                found.append(current)

            for held in waiting:
                current["pages"].append(held["index"])
                if not current["title"] and held.get("title"):
                    current["title"] = held["title"]
            waiting = []
            current["pages"].append(reply["index"])
            if not current["title"] and reply.get("title"):
                current["title"] = reply["title"]
            if numbers and max(numbers) >= BAND_END[number]:
                finished.add(number)

        # Anything still held followed the last question of the paper.
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

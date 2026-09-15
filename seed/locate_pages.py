"""Ask a model what every page of a book is, and write down where things are.

    seed/.venv/bin/python seed/locate_pages.py 11

The last thing that was being done by hand. `read_questions.py` needs
``--questions 7,8 --key 123``; this is what works those out, for all sixteen
sections of a book at once, and puts them in the catalogue.

**One page per request, not a contact sheet.** A twelve-up sheet was the
obvious saving and it does not work: the model spends a fixed token budget on
an image whatever it contains -- 1,488 tokens for a sheet of twelve against
1,813 for a single page -- so each thumbnail gets a twelfth of the detail. On
the twelve pages measured it classified five correctly, invented an answer key
and two audioscripts that were not there, and drifted a section out of step in
the middle. Page by page, the same twelve came back twelve out of twelve.

**Continuation pages are the reason this is not just a regex over headings.**
A section runs across two or three pages and only the first carries "SECTION 3
Questions 21-30"; the rest carry the task and nothing else. The model reports
those as ``continuation`` with no test or section, and they are filled forward
onto whichever heading last appeared. Read as standalone pages they would
either be dropped or, worse, attached to the next heading down.
"""

import argparse
import base64
import json
import pathlib
import re
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor

import pymupdf

import vision

SEED = pathlib.Path(__file__).resolve().parent
REPO = SEED.parent
MATERIALS = REPO / "Materials"
WORK = SEED / "work"

#: 150 is enough for the headings; the token cost is the same at any dpi (the
#: model resizes), so this is chosen for legibility and upload size alone.
DPI = 150
#: Four at a time. The budget is 250k tokens a minute and a page costs about
#: 1,800, so this is nowhere near it -- it is chosen to keep a 140-page book
#: near a minute rather than four.
WORKERS = 4

#: Transcribe, do not interpret. The first version asked for the test number
#: and got the first question number instead -- "Questions 15-20" came back as
#: test 15, "Questions 11-20" as test 11. The page does not say which test it
#: belongs to anywhere except the running header, so that is what gets read,
#: verbatim, and the arithmetic happens in Python.
PROMPT = """One page of a Cambridge IELTS book. JSON only, no prose:

{"header":"<the running header line at the very top, verbatim, or null>",
 "heading":"<the big bold heading like 'SECTION 3   Questions 21-30', verbatim, or null>",
 "kind":"...",
 "answer_key_test":<int|null>}

"header" is the small line across the top of the page. In these books it reads
like "Test 2" on one side and "Listening" or "Reading" on the other. Copy
whatever is there, both sides, ignoring any watermark or website address.

"heading" is the task heading in large bold type, if the page has one. Copy it
exactly, including the word SECTION or PART and the question range -- older
books say "SECTION 3  Questions 21-30" and newer ones "PART 3  Questions
21-30". Null if the page just carries on a task from the page before.

kind: listening_questions | listening_answer_key | audioscript | reading |
      writing | speaking | contents | intro | blank | other

"answer_key_test" is filled in ONLY on a listening_answer_key page: the test
number printed above the answers, as in "TEST 3". Null everywhere else."""

#: Asked to classify a page, the model answers the audioscript pages of some
#: books with their running title -- "Audioscripts" -- rather than the PART
#: heading further down, and books 15 and 19 lost nineteen sections between
#: them that way. A general question got a general answer; this asks the one
#: thing that is actually needed.
SCRIPT_PROMPT = """This page is from the audioscripts at the back of an IELTS book.
JSON only, no prose:

{"starts": [{"part": <the section or part number, 1-4>,
             "test": <the PRACTICE TEST number printed above it, or null>}]}

List EVERY section whose audioscript begins on this page, in the order they
appear. One begins where the page prints a heading like "SECTION 3", "PART 3"
or "LISTENING SECTION 3", usually under a "TEST 2" or "Practice Test 2" line.

"test" is that practice test's number. Null where the heading belongs to
something that is not a practice test: the Official Cambridge Guide prints the
recording scripts for its teaching units in the same run of pages, under
headings like "Listening skills" and "3 Using notes to follow a talk", and
those are not part of any test.

Usually there is one. There can be two: a section's script ends partway down
the page and the next one starts below it. There can be none, where the page
only carries on a conversation that started earlier -- then "starts" is [].

The running title of these pages -- "Audioscripts", "Test 2 Transcript" -- is
NOT a heading. Ignore it."""

HEADER_TEST = re.compile(r"\btest\s*(\d)\b", re.I)
HEADER_LISTENING = re.compile(r"\blistening\b", re.I)
#: "SECTION 3" in Cambridge 10-14 and "PART 3" from Cambridge 15 on -- IELTS
#: renamed the listening sections to parts, and a regex that knows only the
#: older word finds nothing in half the corpus. Cambridge 20's re-typeset
#: headings ("Test1-listening-part2") fall out of the same pattern.
SECTION_HEADING = re.compile(r"\b(?:section|part)\s*[-–—]?\s*(\d)\b", re.I)
#: IELTS Trainer prints each of its first two tests twice: once as "Test 1
#: Training", which teaches the task with worked examples, and once as "Test 1
#: Exam practice", which is the paper. Only the paper has a recording -- the
#: training exercises are the short tracks the manifest leaves behind -- so a
#: training page swept into a section would put questions in front of a
#: learner that nothing in their audio answers. "General Training" is the
#: other IELTS module and has nothing to do with it; Cambridge 10 prints
#: eighteen such pages and every one of them is Reading.
TRAINING = re.compile(r"(?<!general )\btraining\b", re.I)


KEY_PROMPT = """This page is from the answer keys at the back of a Cambridge IELTS
book. These books print the LISTENING key and the READING key for a test on
facing pages, and they look alike: both are a numbered list of forty answers.

One page can carry both -- the tail of the reading key above the start of the
listening one -- so answer about each list of answers on the page separately.

1. Does the page list ANSWERS against question numbers -- short words or
   letters, one per number -- rather than questions to be answered?
2. For each such list: which numbers does it run from and to ON THIS PAGE, and
   which paper is it for? Say "listening" or "reading" ONLY if the page says
   so. The heading may be in another language, or there may be none at all --
   then say "unknown". Do NOT guess the paper from the answers themselves.
3. Copy the heading above each list verbatim, in whatever script it is
   printed.
4. Which test does the page belong to, as printed ("TEST 2", "Test 6")? Null
   if no test number is printed here.

Reply with only {"lists": [{"paper": "listening|reading|unknown",
"first": <number>, "last": <number>, "heading": "<verbatim|null>"}],
"test": <number|null>}."""


NUMBER_PROMPT = """One page of an IELTS practice test. Two things about it.

1. Which paper is it from? Both papers number their questions 1 to 40, so the
   numbers cannot tell them apart -- the page can. A READING page carries a
   long prose passage, or questions about one. A LISTENING page carries a
   form, a table, a set of notes, a map or a list of options to pick from,
   with nothing to read for meaning. If it is neither, say "other".

2. List EVERY question number printed on it, in order: the numbers down the
   left of each question, and the numbers inside the gaps of a table, a form
   or a set of notes. Read the numbers themselves -- do not infer them from a
   "Questions 11-16" heading, which some books do not print and which does not
   always say where the page ends.

Reply with only {"paper": "listening|reading|other", "numbers": [...]}"""


#: What a page announces itself as, in the words IELTS books use. Only ever
#: applied to a text layer that has been looked at first -- see `--text`.
AS_TEXT = (
    (re.compile(r"\bKEY\s+Test\s*(\d)", re.I),            "listening_answer_key"),
    (re.compile(r"\bAnswer\s*key\b", re.I),                "listening_answer_key"),
    (re.compile(r"\bAudioscript|\bRecording script|\bTranscript\b", re.I), "audioscript"),
    (re.compile(r"\bListening\s+Part\s*[1-4]\b", re.I),   "listening_questions"),
    (re.compile(r"\bReading\s+Passage\b", re.I),           "reading"),
    (re.compile(r"\bWriting\s+Task\b", re.I),              "writing"),
    (re.compile(r"\bSpeaking\s+Part\b", re.I),             "speaking"),
    (re.compile(r"\bContents\b", re.I),                     "contents"),
)
#: The running line of an IELTS Trainer page carries the whole address, but
#: extraction returns its two halves in either order and sometimes only one:
#: page 10 ends "Training Test 1 -" and page 11 ends "Listening Part 1". So
#: they are read separately and put back together.
WHICH_TEST = re.compile(r"((?:Training|Exam\s+Practice)\s+Test\s*\d)", re.I)
WHICH_PART = re.compile(r"(Listening\s+Part\s*[1-4])", re.I)


def from_text(pdf: pathlib.Path, index: int) -> dict:
    """What one page is, read off its own text layer instead of asked.

    A page read this way costs nothing and takes no quota, which on a free
    tier of 500 requests a day is the difference between finishing a book and
    waiting until tomorrow: IELTS Trainer 2 is 232 sheets, and 229 of them
    carry real text.

    NOT the default, and not switched on by `document.has_text_layer` either.
    Cambridge 17 has a text layer and it is poisoned -- 3,864 Cyrillic
    homoglyphs sitting inside English words -- so "there is text" and "the
    text says what the page says" are different claims, and only a person who
    has looked can make the second. Hence a flag.
    """
    with pymupdf.open(pdf) as doc:
        text = " ".join(doc[index].get_text().split())
    if not text:
        return {"kind": "blank", "header": None, "heading": None,
                "answer_key_test": None, "index": index}
    kind = next((name for pattern, name in AS_TEXT if pattern.search(text)), "other")
    which, part = WHICH_TEST.search(text), WHICH_PART.search(text)
    # The LAST "KEY Test n" on the page, not the first. Trainer 2 prints a
    # rotated tab down the edge of every key page and extraction flattens it
    # into the text ahead of the heading -- "KEY Test 1 st 1 Te Tes T KEY Test
    # 4 LiSTEning PART 1" is page 214, which is test 4's key and came back as
    # test 1's.
    key_test = None
    for key_test in re.finditer(r"\bKEY\s+Test\s*(\d)", text, re.I):
        pass
    # No heading, deliberately. Extraction flattens the running line into the
    # body, so "Listening Part 2" turns up in the text of a page that prints
    # no heading at all -- and resolve() stops a section's run at the next
    # page carrying a section heading, which threw away every continuation
    # sheet in the book: Test 5's questions 15 to 20 are on page 144 and the
    # section came back as page 143 alone. The running line is already in
    # `header`, which is where this book keeps the address anyway.
    return {"kind": kind,
            # The two halves, kept apart so the missing one can be filled in
            # from the page before by `carry_address` -- a book's running line
            # does not change in the middle of a spread.
            "which_test": which.group(1) if which else None,
            "which_part": part.group(1) if part else None,
            "header": " ".join(x.group(1) for x in (which, part) if x) or None,
            "heading": None,
            "answer_key_test": int(key_test.group(1)) if key_test else None,
            "index": index}


def carry_address(pages: list[dict]) -> list[dict]:
    """Fill in the half of the running line a page's text layer dropped.

    Extraction returns the two halves of "Training Test 1 | Listening Part 1"
    in either order and often only one, so seven of Trainer 2's first thirteen
    listening pages came back with no test at all -- and a page with no test
    on it is a page `teaching()` cannot tell from the exam paper, which is how
    three of its Training sheets became Test 1.

    Carried FORWARD only. A page before the first address has nothing to
    inherit and keeps none."""
    said = None
    for page in sorted(pages, key=lambda p: p["index"]):
        if page.get("which_test"):
            said = page["which_test"]
        elif said and page.get("which_part"):
            page["which_test"] = said
            page["header"] = f"{said} {page['which_part']}"
    return pages


def classify(pdf: pathlib.Path, index: int, dpi: int = DPI) -> dict:
    """What one page is. Never raises: a page nobody could read is 'other',
    which shows up as a gap in the report rather than killing a book."""
    with pymupdf.open(pdf) as doc:
        png = doc[index].get_pixmap(dpi=dpi).tobytes("png")
    tmp = WORK / f".page-{index}.png"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(png)
    try:
        out = vision.ask_json(PROMPT, [tmp])
    except SystemExit as why:
        # NOT "other". A page nobody could read and a page that really is
        # something else are different facts, and recording them as one hid a
        # book: 34 of Cambridge 20's 35 test-2 pages came back "other" from
        # failed requests, and every pass downstream believed it. Marked
        # unread instead, so a re-run knows to ask again and the report can
        # say how many there were.
        out = {"kind": None, "unread": str(why)[:120]}
    finally:
        tmp.unlink(missing_ok=True)
    out["index"] = index
    return out


def script_runs(pages: list[dict]) -> dict[tuple[int, int], list[int]]:
    """Which pages hold each section's audioscript.

    Sliced between SECTION headings rather than page by page, because the
    audioscripts are one unbroken block at the back of the book and two things
    go wrong if each page has to classify itself into it. A page misread as
    something else leaves a hole -- Cambridge 11 lost Test 3 Section 4 that
    way. And a section's script does not end where its page does: Section 1
    finishes partway down the page where Section 2 begins, so the run has to
    include the next section's first page and let the reader stop at the
    heading.
    """
    starts = []
    for page in sorted(pages, key=lambda p: p["index"]):
        if page.get("kind") != "audioscript":
            continue
        named = page.get("script_test")
        for part in page.get("script_parts") or []:
            starts.append((page["index"], int(part), named))
        if page.get("script_parts"):
            continue
        heading = SECTION_HEADING.search(page.get("heading") or "")
        if heading:
            starts.append((page["index"], int(heading.group(1)), named))
    if not starts:
        return {}

    # Counting runs of 1,2,3,4 numbers the tests only if the block holds
    # nothing else. The Official Cambridge Guide prints the recording scripts
    # for its teaching units in the same run of pages, ahead of the practice
    # tests, and counting through those put Practice Test 2 Section 1 --
    # printed plainly as such, with its track number -- into test 4. Where the
    # pages say which test they belong to, that is used and the unnumbered
    # headings are dropped as not being part of a test at all.
    if any(named for _, _, named in starts):
        # The test is printed once, over its Section 1; Sections 2, 3 and 4
        # carry the section heading alone. So a named start sets which test
        # the pages after it belong to, and an unnamed one belongs to the last
        # test named -- which is also what drops the unit material, since
        # nothing before the first named start belongs to a test at all.
        runs, current = [], None
        for index, section, named in starts:
            if named:
                current = named
            if current is None:
                continue
            runs.append((index, current, section))
    else:
        test, previous, runs = 0, 99, []
        for index, section, _ in starts:
            if section <= previous:
                test += 1
            previous = section
            runs.append((index, test, section))

    held = {p["index"] for p in pages if p.get("kind") == "audioscript"}
    last = max(held)

    def between(first: int, stop: int) -> list[int]:
        """The audioscript pages from one heading to the next, and no others.

        For a Cambridge book every page in that range is an audioscript page
        and this is just `range`. IELTS Trainer interleaves: each test's four
        transcript pages sit after that test's nine pages of answer key, so
        the range from Test 1 Section 4 to Test 2 Section 1 spans the whole of
        Test 2's key -- thirteen pages of answers that would be read as if
        somebody had spoken them.

        It stops at the first page that is not one rather than skipping over
        it. The only reason the next section's heading page is included at all
        is that this section's tail sits above that heading on the same sheet,
        and a heading twelve pages and an answer key later shares nothing with
        anything here."""
        run = []
        for index in range(first, stop + 1):
            if index not in held:
                break
            run.append(index)
        return run

    out: dict[tuple[int, int], list[int]] = {}
    for position, (index, test, section) in enumerate(runs):
        # Up to and INCLUDING the next section's first page: the tail of this
        # one is on it, above that heading.
        stop = runs[position + 1][0] if position + 1 < len(runs) else last
        out[(test, section)] = between(index, stop)

    # A heading the reader missed leaves one section with no span at all --
    # Cambridge 11 lost Test 3 Section 4 that way. Rather than drop it, give it
    # the block its neighbours bracket and let whatever reads the pages find
    # the heading itself. Marked, because a guessed span is not a found one.
    known = sorted(out)
    for test in {t for t, _ in known}:
        for section in range(1, 5):
            if (test, section) in out:
                continue
            before = out.get((test, section - 1))
            after = (out.get((test, section + 1))
                     or out.get((test + 1, 1))
                     or [last])
            if before:
                out[(test, section)] = between(before[0], after[-1])
                out[("guessed", test, section)] = True
    return out


def teaching(page: dict) -> bool:
    """A page that shows how the task works rather than setting it."""
    return bool(TRAINING.search(f"{page.get('header') or ''} {page.get('heading') or ''}"))


def resolve(pages: list[dict]) -> list[dict]:
    """Work out which test and section each listening page belongs to.

    Off the SECTION heading and the order of the book, and off nothing else.

    Not off the running header: these books print it alternately, "Test 2" on
    one side and "Listening" on the other, so a page carries one or the other
    and never both. Requiring "Listening" threw away every odd-numbered page
    and left nine sections of sixteen.

    Not off anything the model concludes either. Asked for the test number it
    returns the first question number -- "Questions 15-20" comes back as test
    15. The heading transcribes cleanly, the sections run 1,2,3,4 and start
    over, and a test is one such run. That is enough, and it is all printed.
    """
    starts = []
    for page in sorted(pages, key=lambda p: p["index"]):
        if page.get("kind") != "listening_questions" or teaching(page):
            continue
        # The printed test number comes off the running line either way. It
        # is not used to number the tests -- Cambridge 12 calls its four tests
        # 5 to 8 -- only to tell a repeated section number apart from a new
        # test that happens to start at one.
        printed = HEADER_TEST.search(page.get("header") or "")
        printed = int(printed.group(1)) if printed else None
        heading = SECTION_HEADING.search(page.get("heading") or "")
        if heading:
            starts.append((page["index"], int(heading.group(1)), printed))
            continue
        # The running line, when the heading carries no section number. IELTS
        # Trainer puts the whole address there -- "Test 2 Exam practice |
        # Listening Section 3" -- and leaves the heading to say "Questions
        # 26-30", so the rule above finds nothing and the book comes back
        # 2 sections of 24. No Cambridge page is touched by this: not one of
        # the 176 already located has a section number in its running line.
        inline = SECTION_HEADING.search(page.get("header") or "")
        if inline:
            starts.append((page["index"], int(inline.group(1)), printed))

    # A section number that does not advance means the next test has begun.
    test, previous_section, previous_test = 0, 99, None
    runs = []
    for index, section, printed in starts:
        # Where the section comes from the running line, EVERY page of a
        # section carries it, not just the first -- so the same number
        # arriving again is the rest of that section, not the next test
        # starting at it. Only a different printed test number says otherwise.
        if (runs and section == previous_section
                and printed in (None, previous_test)):
            continue
        if section <= previous_section:
            test += 1
        previous_section, previous_test = section, printed
        runs.append({"index": index, "test": test, "section": section})

    by_index = {p["index"]: p for p in pages}
    for page in pages:
        page["test"] = page["section"] = None
    for position, run in enumerate(runs):
        stop = runs[position + 1]["index"] if position + 1 < len(runs) else 10 ** 9
        index = run["index"]
        # The heading page, then every page directly after it that is still
        # listening and carries no heading of its own.
        while index < stop:
            page = by_index.get(index)
            if page is None or page.get("kind") != "listening_questions":
                break
            if index != run["index"] and SECTION_HEADING.search(page.get("heading") or ""):
                break
            if teaching(page):
                break
            page["test"], page["section"] = run["test"], run["section"]
            index += 1
    return pages


def sheet_of(docs, page: dict) -> pathlib.Path:
    """The PDF a page came from.

    A page is identified by its document AND its index, never by the index
    alone. For nine of these books that distinction costs nothing, because
    there is one document; Cambridge 20 is four PDFs of one test each, where
    "page 2" names four different sheets. The narrow passes below re-read
    pages by number, and rendering all of them from the first document is how
    a pass reads test 1's page 2 four times and writes each answer onto
    whichever entry it met first.
    """
    row = next(d for d in docs if d["id"] == page.get("doc_id"))
    return MATERIALS / row["rel_path"]


def save_all(book: int, docs, found: list[dict]) -> None:
    """Write every document's page map back to its own cache."""
    for row in docs:
        pages = [p for p in found if p.get("doc_id") == row["id"]]
        if pages:
            (WORK / f"pagemap-book{book}-doc{row['id']}.json").write_text(
                json.dumps(sorted(pages, key=lambda p: p["index"]), indent=2))


def settle(pages: list[dict], tests: list[int], conn, book: int,
           roster: dict[tuple[int, int], str]
           ) -> tuple[int, list[int], dict[int, int]]:
    """Turn one universe of pages into catalogue rows; returns how many it
    wrote, where the audioscripts start, and the key page of each test.

    A universe is a run of page indices that mean something together. For nine
    of these books that is the whole book: one PDF, four tests, one index
    space. Cambridge 20 is four PDFs of one test each, so "page 2" names four
    different pages and the test number is a property of the FILE rather than
    of anything printed on the sheet. Splitting on that is what lets both
    shapes go through the same code: the caller says what a universe is and
    which tests it covers, and none of the reasoning below has to know.
    """
    # Answer keys are matched to tests BY ORDER, not by the number printed on
    # them. Cambridge 12 numbers its tests 5 to 8, continuing from Cambridge 11
    # rather than starting again, so a book's own numbering says nothing about
    # which of its four tests a page belongs to. The printed number is still
    # read -- it is what tells four key pages apart from the fifth page that
    # spills over -- but only the order is trusted.
    # `has_key` because one sheet can be two things. Cambridge 20 prints part
    # 4's questions down the top of a page and the whole listening key
    # underneath, and `kind` holds one word: calling it the key lost the
    # questions, calling it questions lost the key. The page keeps its kind and
    # carries a flag for the other role.
    listening = sorted(p["index"] for p in pages
                       if p.get("kind") == "listening_answer_key" or p.get("has_key"))
    # Either mark means the same thing: somebody has separated the listening
    # key from the reading one, so the printed test number is no longer the
    # only evidence and order can be trusted. Asking only about the reading
    # kind missed the files where the separation was recorded the other way.
    if any(p.get("kind") == "reading_answer_key" or p.get("has_key") for p in pages):
        # --keys has separated the two papers, so order alone settles it, which
        # is what this comment has claimed all along. Consecutive pages are one
        # test's key spilling over, so each RUN is a test and its first page is
        # the one to read. This does not need a printed test number, and book
        # 14 -- whose test 2 listening key has none -- is why that matters.
        runs = []
        for index in listening:
            if runs and index == runs[-1][-1] + 1:
                runs[-1].append(index)
            else:
                runs.append([index])
        in_order = [run[0] for run in runs]
    else:
        # Without that pass a reading key is indistinguishable from a listening
        # one, so the printed number is all there is to go on.
        claimed: dict[int, int] = {}
        for page in sorted(pages, key=lambda p: p["index"]):
            # A one-test file needs no number on the page for the same reason
            # its question sheets do not: there is only one test it can be.
            n = page.get("answer_key_test") or (tests[0] if len(tests) == 1 else None)
            if page.get("kind") == "listening_answer_key" and n and n not in claimed:
                claimed[n] = page["index"]
        in_order = [claimed[n] for n in sorted(claimed)]
    # Numbered by the tests this universe actually covers, not by position in
    # it. For a whole-book universe those are the same thing -- 1, 2, 3, 4 --
    # and for Cambridge 20's one-test files they are not: every key came back
    # as test 1's, so tests 2 to 4 looked up their own number and found
    # nothing.
    keys = dict(zip(tests, in_order))
    if len(keys) < len(tests):
        # Order could not cover the book, so it is not evidence here. It fails
        # on the Guide for two reasons at once: its eight keys are one test to
        # a page and CONSECUTIVE, so the run rule above -- consecutive pages
        # are one test's key spilling over -- merges seven of them into one;
        # and two other listening keys sit in the same back matter, one for the
        # coursebook units and one for the General Training test, which order
        # cannot tell from a practice test's.
        #
        # What the Guide does print is the test number, on seven of its eight.
        # That is used only in this case -- where order has already come back
        # short -- so a book order CAN settle is untouched, which is every
        # Cambridge edition including the two the order rule was written for.
        named: dict[int, int] = {}
        for page in sorted(pages, key=lambda p: p["index"]):
            number = page.get("answer_key_test")
            if page["index"] in listening and number in tests and number not in named:
                named[number] = page["index"]
        if named:
            # A test the book numbered nowhere takes the last unclaimed key
            # page that falls before the next test's -- which is where its own
            # key has to be, the keys running in order. The Guide prints no
            # number on test 1's, and test 1's is the sheet immediately before
            # test 2's.
            spare = [i for i in listening if i not in named.values()]
            for test in tests:
                if test in named:
                    continue
                below = max((named[t] for t in named if t < test), default=-1)
                above = min((named[t] for t in named if t > test), default=1 << 62)
                fits = [i for i in spare if below < i < above]
                if fits:
                    named[test] = fits[-1]
                    spare.remove(fits[-1])
            print(f"  {len(dict(zip(tests, in_order)))} key page(s) by order for "
                  f"{len(tests)} tests; using the printed test numbers instead")
            keys = named
    # The START OF THE LONGEST RUN, not the first page anywhere that looks like
    # one. The audioscripts are forty consecutive pages at the back; a single
    # page misread as one in the middle of the book would otherwise become the
    # answer, and did -- index 21 against a true 102.
    marked = sorted(p["index"] for p in pages if p.get("kind") == "audioscript")
    # A single page inside a long run of audioscripts that came back as
    # something else is a misreading, not the end of the run. Book 17 called
    # one page "reading" -- it prints PART 4 and eight margin numbers -- and
    # the run stopped there, so every section after it got a guessed span and
    # one of them was transcribed from the wrong pages entirely. Bridged, and
    # the bridged page is treated as what the pages either side of it are.
    runs, current = [], []
    for index in marked:
        if current and index - current[-1] <= 2:
            current.extend(range(current[-1] + 1, index + 1))
        else:
            current = [index]
            runs.append(current)
    longest = max(runs, key=len, default=[])
    within = {p["index"]: p for p in pages}
    # One more page at the end of the block, where the page after it is an
    # answer key. The audioscripts run until the keys begin, so a single sheet
    # between them belongs to the block whatever it was called -- book 13's
    # last page of PART 4 came back as "reading" and its section was left
    # transcribed from one page instead of two. Bounded to one page and to
    # that position: anywhere else, a misreading should stay visible rather
    # than be absorbed.
    if longest:
        after = longest[-1] + 1
        beyond = within.get(after + 1, {})
        if (after in within and within[after].get("kind") != "audioscript"
                and not (within[after].get("kind") or "").endswith("answer_key")
                and (beyond.get("kind") or "").endswith("answer_key")):
            longest = longest + [after]

    for index in longest:
        page = within.get(index)
        if page is not None and page.get("kind") != "audioscript":
            page["kind"] = "audioscript"
            page["bridged"] = True
    scripts = longest

    scripts_by_section = script_runs(pages)

    print(f"\n{'section':<14}{'question pages':<20}{'key':<6}{'audioscript pages'}")
    written = 0
    for test in tests:
        for section in range(1, 5):
            # In a universe that IS one test, a page needs no printed test
            # number to belong to it -- being in that file is the evidence,
            # and Cambridge 20 prints no test number on its question pages at
            # all. Where a universe holds four tests the page must say which.
            sheets = sorted(p["index"] for p in pages
                            if p.get("kind") == "listening_questions"
                            and (p.get("test") == test or len(tests) == 1)
                            and section in (p.get("sections") or [p.get("section")]))
            key = keys.get(test)
            # From the catalogue, never built from the book number. Three of
            # these books are not "cam" anything -- the Trainer's sections are
            # trn-t1-s1 -- and a constructed id UPDATEs nothing and says it
            # wrote the row anyway.
            sid = roster.get((test, section))
            if sid is None:
                continue
            script = scripts_by_section.get((test, section), [])
            guessed = scripts_by_section.get(("guessed", test, section))
            flag = "" if sheets and key is not None else "   <- INCOMPLETE"
            if guessed:
                flag += "   <- script span guessed, heading not found"
            print(f"{sid:<14}{str(sheets):<20}{str(key):<6}{str(script)}{flag}")
            if sheets and key is not None:
                conn.execute(
                    "UPDATE section SET question_pages = ?, key_page = ?, script_pages = ? "
                    "WHERE id = ?",
                    (json.dumps(sheets), key, json.dumps(script) if script else None, sid))
                written += 1

    return written, scripts, keys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("book", type=int)
    ap.add_argument("--refresh", action="store_true",
                    help="re-read the pages instead of using the cached pass")
    ap.add_argument("--scripts", action="store_true",
                    help="re-read only the audioscript pages, asking directly which "
                         "test and part each one starts")
    ap.add_argument("--numbers", action="store_true",
                    help="re-read the listening pages, asking only which question "
                         "numbers are on each, and take the part from those")
    ap.add_argument("--keys", action="store_true",
                    help="re-read only the answer key pages, asking directly "
                         "whether each is the listening key or the reading one")
    ap.add_argument("--text", action="store_true",
                    help="read each page off its own text layer instead of asking "
                         "a model -- free, and only for a book whose text has been "
                         "looked at (NOT Cambridge 17, whose layer is poisoned)")
    ap.add_argument("--unread", action="store_true",
                    help="re-read only the pages the last pass could not read at "
                         "all, keeping every page it could")
    ap.add_argument("--recheck", action="store_true",
                    help="re-read, at higher resolution, only the pages around a "
                         "section that came out empty")
    args = ap.parse_args()

    conn = sqlite3.connect(SEED / "catalogue.db")
    conn.row_factory = sqlite3.Row
    docs = conn.execute(
        "SELECT DISTINCT d.id, d.rel_path FROM document d WHERE d.book_number = ? "
        "ORDER BY d.rel_path", (args.book,)).fetchall()
    if not docs:
        raise SystemExit(f"no documents for book {args.book}")

    # What this book actually holds, rather than the four-tests-of-four every
    # Cambridge edition happens to be. The Official Cambridge Guide prints
    # eight practice tests in one volume.
    roster = {(r["test_no"], r["section_no"]): r["id"] for r in conn.execute(
        "SELECT id, test_no, section_no FROM section WHERE book_number = ? "
        "ORDER BY test_no, section_no", (args.book,))}
    if not roster:
        raise SystemExit(f"no sections for book {args.book}")
    in_book = sorted({test for test, _ in roster})

    found: list[dict] = []
    for doc_row in docs:
        pdf = MATERIALS / doc_row["rel_path"]
        cache = WORK / f"pagemap-book{args.book}-doc{doc_row['id']}.json"
        if cache.exists() and not args.refresh:
            pages = json.loads(cache.read_text())
            print(f"{doc_row['rel_path']}: {len(pages)} pages (cached)")
        else:
            with pymupdf.open(pdf) as doc:
                count = len(doc)
            how = "off the text layer" if args.text else "..."
            print(f"{doc_row['rel_path']}: reading {count} pages {how}")
            if args.text:
                pages = carry_address([from_text(pdf, i) for i in range(count)])
            else:
                with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                    pages = list(pool.map(lambda i: classify(pdf, i), range(count)))
            cache.write_text(json.dumps(pages, indent=2))
        for page in resolve(pages):
            page["doc_id"] = doc_row["id"]
            found.append(page)

    def read_one(page: dict, prompt: str, tag: str, dpi: int = DPI) -> tuple[dict, dict]:
        """One page, rendered from its own document, and what a model said
        about it. Returns the page itself rather than its index, because an
        index alone does not name a page in a book that is four files."""
        shot = WORK / f".{tag}-{page.get('doc_id')}-{page['index']}.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        with pymupdf.open(sheet_of(docs, page)) as doc:
            if not 0 <= page["index"] < doc.page_count:
                # A page map that outlived the book it describes, or one an
                # earlier run mixed two documents into. Said and skipped: a
                # stale entry should cost its own page, not the whole book.
                print(f"  page {page['index']} is not in "
                      f"{sheet_of(docs, page).name}; skipped", file=sys.stderr)
                return page, {}
            shot.write_bytes(doc[page["index"]].get_pixmap(dpi=dpi).tobytes("png"))
        try:
            return page, vision.ask_json(prompt, [shot])
        except SystemExit:
            return page, {}
        finally:
            shot.unlink(missing_ok=True)

    if args.unread:
        # A page that came back 429 is not a page that has been read. The
        # first pass over the Guide's 398 sheets ran out of quota at index 286
        # and recorded the remaining 106 as unread, which is the whole point
        # of recording them that way rather than as "other" -- the alternative
        # is re-reading a book to recover a quarter of it. Nothing else in the
        # map is touched.
        stuck = [p for p in found if p.get("kind") is None]
        if not stuck:
            print("every page was read")
        else:
            print(f"re-reading {len(stuck)} page(s) that came back unread")
            by_doc = {}
            for page in stuck:
                by_doc.setdefault(page["doc_id"], []).append(page)
            for doc_id, pages in by_doc.items():
                pdf = sheet_of(docs, pages[0])
                with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                    for fresh in pool.map(lambda p: classify(pdf, p["index"]), pages):
                        page = next(p for p in stuck if p["index"] == fresh["index"]
                                    and p["doc_id"] == doc_id)
                        page.update(fresh)
            still = sum(1 for p in found if p.get("kind") is None)
            print(f"  {len(stuck) - still} read this time, {still} still unread")
            found = resolve(found)
            for page in found:
                page.setdefault("doc_id", docs[0]["id"])
            save_all(args.book, docs, found)

    if args.scripts:
        marked = [p for p in found if p.get("kind") == "audioscript"]
        print(f"re-reading {len(marked)} audioscript page(s), asking directly")
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for page, said in pool.map(
                    lambda p: read_one(p, SCRIPT_PROMPT, "script"), marked):
                begins = [s for s in (said.get("starts") or []) if isinstance(s, dict)]
                parts = [int(s["part"]) for s in begins
                         if isinstance(s.get("part"), int) and 1 <= s["part"] <= 4]
                if not parts:
                    continue
                # Both of them, where a page carries two. IELTS Trainer prints
                # a test's four scripts on four pages and lets each run over
                # the fold, so half its pages begin one section and end
                # another -- and a reader that can only report one heading
                # reported the second, leaving the first with no span at all.
                page["script_parts"] = parts
                page["heading"] = " ".join(f"PART {n}" for n in parts)
                named = next((s["test"] for s in begins if s.get("test")), None)
                if named:
                    page["header"] = f"Test {named}"
                    page["script_test"] = int(named)
        save_all(args.book, docs, found)

    if args.numbers:
        # A page belongs to a part because of the numbers on it. That is
        # normally read off the PART heading, and Cambridge 20 prints none:
        # its four sheets carry questions 1-15, 16-24, 25-30 and 31-40, so the
        # first of them is a page and a half of paper with nothing anywhere
        # saying where part 1 stops. The numbers say it -- 1-10 is part 1,
        # 11-20 part 2, and so on.
        #
        # A page can therefore belong to TWO parts, which is why this writes a
        # list. `read_questions.py` drops whatever falls outside the part it
        # was asked for, so a shared sheet is read twice and each reading
        # keeps its own half.
        # Not only the pages the first pass called listening. On a book it does
        # not recognise, that pass is exactly what has gone wrong -- Cambridge
        # 20 came back with three listening pages in test 1 and none at all in
        # tests 2 and 3. What can be relied on instead is the order of an IELTS
        # paper: listening comes first, so every page before the first reading
        # page is a candidate. A page with no question numbers on it answers
        # with none and costs a twentieth of a cent.
        sheets = []
        for row in docs:
            pages = sorted((p for p in found if p.get("doc_id") == row["id"]),
                           key=lambda p: p["index"])
            after = next((p["index"] for p in pages
                          if p.get("kind") in ("reading", "writing", "speaking")),
                         len(pages))
            sheets += [p for p in pages
                       if p["index"] < after or p.get("kind") == "listening_questions"]
        print(f"re-reading {len(sheets)} listening page(s), asking only for numbers")
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for page, said in pool.map(
                    lambda p: read_one(p, NUMBER_PROMPT, "numbers"), sheets):
                numbers = sorted({n for n in (said.get("numbers") or [])
                                  if isinstance(n, int) and 1 <= n <= 40})
                # Both papers number 1 to 40, so the numbers alone put reading
                # questions into listening sections -- Cambridge 20's test 2
                # offered eight reading pages that way. The page says which it
                # is; the numbers say which part of it.
                if not numbers or said.get("paper") != "listening":
                    continue
                parts = sorted({(n - 1) // 10 + 1 for n in numbers})
                page["sections"] = parts
                page["section"] = parts[0]
                # A page with listening question numbers on it IS a listening
                # question page, whatever the first pass called it.
                page["kind"] = "listening_questions"
                print(f"  {sheet_of(docs, page).stem} page {page['index']}: "
                      f"questions {numbers[0]}-{numbers[-1]} -> part"
                      f"{'s' if len(parts) > 1 else ''} "
                      f"{', '.join(str(p) for p in parts)}")
        save_all(args.book, docs, found)

    if args.keys:
        # A listening key and a reading key are the same page to a classifier:
        # forty numbered answers under a heading it cannot always see. Cambridge
        # 14 printed test 2's listening key with no test number on it, so the
        # reading key on the next page claimed test 2 -- and three sections
        # went into the database answered from the wrong paper. Nothing failed;
        # the answers were simply wrong. So this asks the one thing that tells
        # the two apart, rather than inferring it from a stride or a shape.
        # A book with four tests wants four listening keys. Fewer than that
        # means the first pass did not find them, not that the book has none,
        # and the narrow question is worth asking of more pages rather than of
        # the two it happened to label. Cambridge 20 labelled one.
        wanted = len({p.get("doc_id") for p in found}) if len(docs) > 1 else len(in_book)
        candidates = [p for p in found
                      if (p.get("kind") or "").endswith("answer_key")
                      or p.get("kind") == "answer_list"]
        if len([p for p in candidates
                if p.get("kind") == "listening_answer_key"]) < wanted:
            # Nothing the first pass called a key at all, which is what a book
            # printing its key under a heading the classifier does not know
            # looks like -- Cambridge 20 buries it among writing and speaking
            # material. Everything it could not place is asked instead: more
            # requests than the usual case, and only in the case where the
            # usual one has already come back empty.
            placed = {"listening_questions", "reading", "writing", "audioscript",
                      "intro", "contents"}
            candidates = [p for p in found if p.get("kind") not in placed]
        print(f"re-reading {len(candidates)} answer key page(s), asking directly")

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for page, said in pool.map(
                    lambda p: read_one(p, KEY_PROMPT, "key"), candidates):
                lists = [l for l in (said.get("lists") or []) if isinstance(l, dict)]
                if not lists:
                    continue
                papers = {(l.get("paper") or "unknown").lower() for l in lists}
                page["answer_lists"] = lists
                if said.get("test"):
                    page["answer_key_test"] = said["test"]
                if "listening" in papers:
                    page["kind"] = "listening_answer_key"
                elif papers == {"reading"}:
                    # Reading answers and no listening ones. Kept in the map as
                    # what it is, so it stops being a candidate for a test
                    # rather than disappearing.
                    page["kind"] = "reading_answer_key"
                    page["answer_key_test"] = None
                else:
                    # An answer list under a heading that names no paper --
                    # Cambridge 20 prints its key under 答案 and nothing else.
                    # Which paper it belongs to cannot be read off the page,
                    # and guessing from the answers is what put a whole test of
                    # reading answers into book 14. The recording settles it:
                    # a listening answer is a word the speaker says. That check
                    # lives in verify.py and needs the audio, so this stops
                    # here and says what it found.
                    page["kind"] = "answer_list"
        save_all(args.book, docs, found)

    if args.recheck:
        # A section comes out empty when the one page carrying its heading was
        # misread -- one page in a book, not a systematic failure. Re-reading
        # just those, larger, is cheaper and more honest than inferring the
        # span from its neighbours: a guessed heading is a guessed section.
        located = {}
        for page in found:
            if page.get("test") and page.get("section"):
                located.setdefault((page["test"], page["section"]), []).append(page["index"])
        gaps: set[int] = set()
        # The two pages either side of the hole are re-read even though they
        # are spoken for. That is not an exception to the rule below, it is
        # the failure itself: a section goes missing because the page carrying
        # its heading was read as the previous section's last page or the
        # next one's first, and there is often no unclaimed page between them
        # at all. Excluding them left `--recheck` with nothing to do on
        # exactly the books it was written for.
        edges: set[int] = set()
        for test in in_book:
            for section in range(1, 5):
                if (test, section) in located:
                    continue
                before = located.get((test, section - 1)) or located.get((test - 1, 4))
                after = located.get((test, section + 1)) or located.get((test + 1, 1))
                if before and after:
                    gaps.update(range(max(before), min(after) + 1))
                    edges.update({max(before), min(after)})
        gaps = {i for i in gaps if i in edges or i not in
                {p["index"] for p in found if p.get("test")}}
        if gaps:
            pdf = MATERIALS / docs[0]["rel_path"]
            print(f"re-reading {len(gaps)} page(s) at 220 dpi: {sorted(gaps)}")
            by_index = {p["index"]: p for p in found}
            for index in sorted(gaps):
                fresh = classify(pdf, index, dpi=220)
                by_index[index].update(fresh)
            found = resolve(list(by_index.values()))
            cache = WORK / f"pagemap-book{args.book}-doc{docs[0]['id']}.json"
            cache.write_text(json.dumps(sorted(found, key=lambda p: p["index"]), indent=2))

    # One universe per document where a document is a test, otherwise one for
    # the book. `by_test` comes from the sections themselves, which is the only
    # place that already knows which file holds which test.
    universes = [(found, in_book)]
    if len(docs) > 1:
        by_doc: dict[int, int] = {}
        for row in conn.execute(
                "SELECT document_id, test_no FROM section WHERE book_number = ? "
                "AND document_id IS NOT NULL", (args.book,)):
            by_doc[row["document_id"]] = row["test_no"]
        universes = [([p for p in found if p.get("doc_id") == doc], [test])
                     for doc, test in sorted(by_doc.items(), key=lambda kv: kv[1])]

    written, scripts, keys = 0, [], {}
    for pages, tests in universes:
        wrote, its_scripts, its_keys = settle(pages, tests, conn, args.book, roster)
        written += wrote
        scripts = scripts or its_scripts
        keys.update(its_keys)

    if scripts:
        conn.execute("UPDATE document SET audioscript_page = ? WHERE book_number = ?",
                     (scripts[0], args.book))
    conn.commit()
    conn.close()
    print(f"\n{written}/{len(roster)} sections located; audioscripts start at index "
          f"{scripts[0] if scripts else '?'} ({len(scripts)} pages); answer keys at "
          f"{ {t: keys[t] for t in sorted(keys)} }")
    return 0 if written == len(roster) else 1


if __name__ == "__main__":
    sys.exit(main())

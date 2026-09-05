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

HEADER_TEST = re.compile(r"\btest\s*(\d)\b", re.I)
HEADER_LISTENING = re.compile(r"\blistening\b", re.I)
#: "SECTION 3" in Cambridge 10-14 and "PART 3" from Cambridge 15 on -- IELTS
#: renamed the listening sections to parts, and a regex that knows only the
#: older word finds nothing in half the corpus. Cambridge 20's re-typeset
#: headings ("Test1-listening-part2") fall out of the same pattern.
SECTION_HEADING = re.compile(r"\b(?:section|part)\s*[-–—]?\s*(\d)\b", re.I)


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
    except SystemExit:
        out = {"kind": "other"}
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
        heading = SECTION_HEADING.search(page.get("heading") or "")
        if heading:
            starts.append((page["index"], int(heading.group(1))))
    if not starts:
        return {}

    test, previous, runs = 0, 99, []
    for index, section in starts:
        if section <= previous:
            test += 1
        previous = section
        runs.append((index, test, section))

    last = max(p["index"] for p in pages if p.get("kind") == "audioscript")
    out: dict[tuple[int, int], list[int]] = {}
    for position, (index, test, section) in enumerate(runs):
        # Up to and INCLUDING the next section's first page: the tail of this
        # one is on it, above that heading.
        stop = runs[position + 1][0] if position + 1 < len(runs) else last
        out[(test, section)] = list(range(index, stop + 1))

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
                out[(test, section)] = list(range(before[0], after[-1] + 1))
                out[("guessed", test, section)] = True
    return out


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
        if page.get("kind") != "listening_questions":
            continue
        heading = SECTION_HEADING.search(page.get("heading") or "")
        if heading:
            starts.append((page["index"], int(heading.group(1))))

    # A section number that does not advance means the next test has begun.
    test, previous_section = 0, 99
    runs = []
    for index, section in starts:
        if section <= previous_section:
            test += 1
        previous_section = section
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
            page["test"], page["section"] = run["test"], run["section"]
            index += 1
    return pages


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("book", type=int)
    ap.add_argument("--refresh", action="store_true",
                    help="re-read the pages instead of using the cached pass")
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
            print(f"{doc_row['rel_path']}: reading {count} pages ...")
            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                pages = list(pool.map(lambda i: classify(pdf, i), range(count)))
            cache.write_text(json.dumps(pages, indent=2))
        for page in resolve(pages):
            page["doc_id"] = doc_row["id"]
            found.append(page)

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
        for test in range(1, 5):
            for section in range(1, 5):
                if (test, section) in located:
                    continue
                before = located.get((test, section - 1)) or located.get((test - 1, 4))
                after = located.get((test, section + 1)) or located.get((test + 1, 1))
                if before and after:
                    gaps.update(range(max(before) , min(after) + 1))
        gaps = {i for i in gaps if i not in
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

    # Answer keys are matched to tests BY ORDER, not by the number printed on
    # them. Cambridge 12 numbers its tests 5 to 8, continuing from Cambridge 11
    # rather than starting again, so a book's own numbering says nothing about
    # which of its four tests a page belongs to. The printed number is still
    # read -- it is what tells four key pages apart from the fifth page that
    # spills over -- but only the order is trusted.
    claimed: dict[int, int] = {}
    for page in sorted(found, key=lambda p: p["index"]):
        n = page.get("answer_key_test")
        if page.get("kind") == "listening_answer_key" and n and n not in claimed:
            claimed[n] = page["index"]
    in_order = [claimed[n] for n in sorted(claimed)]
    keys = {position + 1: index for position, index in enumerate(in_order[:4])}
    # The START OF THE LONGEST RUN, not the first page anywhere that looks like
    # one. The audioscripts are forty consecutive pages at the back; a single
    # page misread as one in the middle of the book would otherwise become the
    # answer, and did -- index 21 against a true 102.
    marked = sorted(p["index"] for p in found if p.get("kind") == "audioscript")
    runs, current = [], []
    for index in marked:
        if current and index == current[-1] + 1:
            current.append(index)
        else:
            current = [index]
            runs.append(current)
    longest = max(runs, key=len, default=[])
    scripts = longest

    scripts_by_section = script_runs(found)

    print(f"\n{'section':<14}{'question pages':<20}{'key':<6}{'audioscript pages'}")
    written = 0
    for test in range(1, 5):
        for section in range(1, 5):
            pages = sorted(p["index"] for p in found
                           if p.get("kind") == "listening_questions"
                           and p.get("test") == test and p.get("section") == section)
            key = keys.get(test)
            sid = f"cam{args.book}-t{test}-s{section}"
            script = scripts_by_section.get((test, section), [])
            guessed = scripts_by_section.get(("guessed", test, section))
            flag = "" if pages and key is not None else "   <- INCOMPLETE"
            if guessed:
                flag += "   <- script span guessed, heading not found"
            print(f"{sid:<14}{str(pages):<20}{str(key):<6}{str(script)}{flag}")
            if pages and key is not None:
                conn.execute(
                    "UPDATE section SET question_pages = ?, key_page = ?, script_pages = ? "
                    "WHERE id = ?",
                    (json.dumps(pages), key, json.dumps(script) if script else None, sid))
                written += 1

    if scripts:
        conn.execute("UPDATE document SET audioscript_page = ? WHERE book_number = ?",
                     (scripts[0], args.book))
    conn.commit()
    conn.close()
    print(f"\n{written}/16 sections located; audioscripts start at index "
          f"{scripts[0] if scripts else '?'} ({len(scripts)} pages); answer keys at "
          f"{ {t: keys[t] for t in sorted(keys)} }")
    return 0 if written == 16 else 1


if __name__ == "__main__":
    sys.exit(main())

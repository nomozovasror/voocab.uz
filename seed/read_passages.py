"""Read a located passage's TEXT off the page.

    seed/.venv/bin/python seed/read_passages.py cam11-t1-p2
    seed/.venv/bin/python seed/read_passages.py --book 11
    seed/.venv/bin/python seed/read_passages.py --report

Writes `work/<passage id>/passage.json` -- the object that becomes a part's
`passage` column, and the thing every reading question is answered from:

    {"title": "The Lost City",
     "subtitle": null,
     "source": "Adapted from ...",
     "paragraphs": [{"label": "A", "text": "..."}, ...]}

`locate_passages.py` has already said which pdf pages this passage is printed
on. This stage does not go looking: it reads those pages and nothing else.

## The letters are not decoration

Two of Reading's own tasks are answered BY a paragraph's letter -- "which
paragraph contains the following information" has options A to G -- so the
lettering is part of the answer key, not part of the layout. A passage stored
as one block of prose would have to be re-split to ask those questions, and a
re-split that disagreed with the printed lettering by one would mark every one
of those answers wrong. So the letter is read off the page with the paragraph
it belongs to, and `label` is null only where the book prints no letters,
which is most passages.

## What is on the page and is not the passage

A passage's pages carry its questions too, and on some books the start of the
next passage. Both are somebody else's stage: `read_questions.py` reads the
questions, and the next passage has pages of its own. What is asked for here
is the prose between the title and the first "Questions 1-6" heading, and the
prompt says so in the terms the page uses.

The running heads, the page numbers and the tailieutienganh.net watermark are
printed and are not the passage. They go the same way the audioscript's do.
"""

import argparse
import json
import pathlib
import re
import sqlite3
import sys

import vision

SEED = pathlib.Path(__file__).resolve().parent
REPO = SEED.parent
MATERIALS = REPO / "Materials"
WORK = SEED / "work"

#: Three images a request, the same limit and the same reason as the
#: audioscript reader: it is a COUNT rather than a size, so a passage printed
#: over more pages is read in overlapping windows and stitched rather than
#: rendered smaller.
PAGES_PER_CALL = 3
PASSAGE_DPI = 130

#: Who to ask when the first provider will not reproduce a page.
#:
#: `content_filter: RECITATION` is Gemini recognising a published passage,
#: and it is a property of the IMAGE rather than of the question: narrowing
#: the ask to three paragraphs, to one column, and cropping the sheet in half
#: were all refused on Cambridge 10's page 25, where narrowing worked for the
#: answer key. What is left is to ask somebody else, and nvidia's free tier
#: reads the same sheet at once.
#:
#: Second choice on purpose. It takes one image a request against gemini's
#: three, and the README records it being measured twice and not adopted --
#: for the NARROW question, which this is not: transcribing prose is the one
#: thing every vision model does well, and the word count and the lettering
#: check below are what say whether it did.
FALLBACK = "nvidia"

#: How many times a passage may be read before its faults are reported
#: rather than chased.
#:
#: Two, and the second is worth making because the faults here are
#: MEASURABLE rather than matters of taste: a passage is 350 to 1400 words
#: and a lettered one is lettered throughout, so "fewer faults" is a fact
#: about the reading and not a preference. A third read would be sampling
#: until the check goes quiet, which is a different thing from being right.
READS = 2

#: What an Academic Reading passage runs to. Cambridge's own specification is
#: 2,150 to 2,750 words across the three passages of a paper, so one passage
#: is roughly 700 to 950 -- and a transcription that comes back at 200 has
#: stopped early, which is the failure this stage is most likely to have and
#: the one that is invisible in the output.
WORDS = (350, 1400)

PROMPT = """These images are consecutive pages of an IELTS Academic Reading paper.

Read ONLY the READING PASSAGE printed on them -- the continuous prose a
candidate reads. Do not read the questions.

Return ONE JSON object, no prose and no code fence:

{{"title": "<the passage's own heading, like 'The Lost City'>",
  "subtitle": "<the italic line under the title, if there is one, else null>",
  "source": "<a credit line like 'Adapted from New Scientist', else null>",
  "paragraphs": [
    {{"label": "<the letter printed beside this paragraph, like A, or null>",
      "text": "<the whole paragraph, verbatim, as one line>"}}
  ]}}

Rules that matter:

* **Stop at the questions.** The passage ends where a heading like "Questions
  {first}-{last}", "Complete the summary below" or "Do the following
  statements agree" begins. Everything from there on is somebody else's job.
  If a page is nothing but questions, it contributes no paragraphs.
* **The first page may open partway through the PREVIOUS passage**, above this
  one's title. Everything above the title belongs to that passage: skip it.
* **The letter beside a paragraph is part of the answer key.** Where the book
  letters its paragraphs A, B, C down the margin, copy each letter into
  "label" against its own paragraph. Where it letters nothing, every "label"
  is null -- do not invent letters and do not renumber.
* **One entry per printed paragraph, in order.** A paragraph that runs over a
  page break or a column break is ONE entry. Do not merge two paragraphs and
  do not split one.
* **Verbatim.** Copy the words as printed, including the spelling the book
  uses. Do not summarise, modernise or correct anything.
* Footnotes marked with * belong at the end of the paragraph they are printed
  under, in that paragraph's text.
* **Printed and unspoken goes:** page numbers, the running head ("Test 3",
  "Reading"), and any website watermark across the page are not the passage.
"""

#: The heading that ends the passage, as the books print it. Used on the
#: OUTPUT rather than on the page -- a paragraph that came back beginning
#: "Questions 14-19" is the model having read past the end, and dropping it
#: here costs nothing where re-asking costs a page.
QUESTIONS = re.compile(
    r"^\s*(Questions?\s+\d|Complete the|Do the following|Choose (the|TWO|THREE)|"
    r"Reading Passage \d|Write your answers|You should spend)", re.I)

#: What the page prints that is not the passage, on a line of its own.
FURNITURE = re.compile(
    r"^\s*(test\s*\d+|reading|tailieutienganh\.net|giasuIELTS\.vn|\d{1,3})\s*$",
    re.I)


def band(passage_no: int) -> tuple[int, int]:
    """The questions this passage carries, so the prompt can name them."""
    return {1: (1, 13), 2: (14, 26), 3: (27, 40)}[passage_no]


def clean(paragraphs: list[dict]) -> list[dict]:
    """Drop what is not the passage, and keep the order of what is."""
    out: list[dict] = []
    for one in paragraphs:
        text = " ".join((one.get("text") or "").split())
        if not text or QUESTIONS.match(text) or FURNITURE.match(text):
            continue
        label = (one.get("label") or "").strip() or None
        if label and not re.fullmatch(r"[A-Za-z]|[ivxlIVXL]+", label):
            label = None
        out.append({"label": label.upper() if label else None, "text": text})
    return out


def lettering(paragraphs: list[dict]) -> str | None:
    """What is wrong with the letters, or None where nothing is.

    A passage is lettered throughout or not at all, and the letters run A, B,
    C without a gap. Half-lettered is the model having lost the margin
    partway down, and a gap is a paragraph it merged into its neighbour --
    both of which would put a matching-information answer against the wrong
    paragraph, which is the one thing these labels exist to prevent.
    """
    labels = [one["label"] for one in paragraphs]
    if not any(labels):
        return None
    if not all(labels):
        return (f"{sum(1 for l in labels if l)} of {len(labels)} paragraphs"
                " carry a letter")
    want = [chr(ord("A") + i) for i in range(len(labels))]
    if labels != want:
        return f"letters run {''.join(labels)}, not {''.join(want)}"
    return None


def read_passage(row: sqlite3.Row, *, model: str) -> tuple[dict, list[str]]:
    """Read one passage off its pages, and say what looks wrong with it."""
    pages = json.loads(row["pages"] or "[]")
    first, last = band(row["passage_no"])
    prompt = PROMPT.format(first=first, last=last)
    work = WORK / row["id"]

    # Overlapping windows, exactly as the audioscript reader does it: each
    # carries the last page of the one before, so a paragraph that straddles a
    # page break is seen whole by at least one call.
    windows = [pages[i:i + PAGES_PER_CALL]
               for i in range(0, max(1, len(pages) - 1), PAGES_PER_CALL - 1)] or [pages]

    # A refused window is asked one sheet at a time.
    #
    # `content_filter: RECITATION` is the provider recognising a published
    # passage and declining to reproduce it, and it is deterministic for the
    # same images and the same ask -- so retrying unchanged spends a request
    # to be refused again. What works is asking for LESS of it, which the
    # answer-key reader found independently: all forty answers of a key page
    # were refused four times out of four, and each band of thirteen was
    # answered at once.
    #
    # A single sheet refused on its own is genuinely out of reach, and the
    # passage then fails rather than being written short -- which is what the
    # word count exists to prevent.
    title = subtitle = source = None
    paragraphs: list[dict] = []
    for window in windows:
        shots = vision.render(MATERIALS / row["pdf"], window, work / "pages",
                              dpi=PASSAGE_DPI, jpeg=True)
        try:
            read = vision.ask_json(prompt, shots, model=model, max_tokens=8000)
        except vision.Refused:
            if len(shots) == 1:
                raise
            print(f"{'':<16} refused {len(shots)} sheets together;"
                  " asking one at a time")
            read = {"paragraphs": []}
            for one in shots:
                try:
                    page = vision.ask_json(prompt, [one], model=model,
                                           max_tokens=8000)
                except vision.Refused:
                    # The sheet itself is what it will not reproduce, so
                    # there is nothing left to narrow. Asked of somebody
                    # else, it is an ordinary page.
                    print(f"{'':<16} sheet refused; asking {FALLBACK}")
                    page = vision.ask_json(prompt, [one], provider=FALLBACK,
                                           max_tokens=8000)
                for field in ("title", "subtitle", "source"):
                    read[field] = read.get(field) or page.get(field)
                read["paragraphs"] = (read.get("paragraphs") or []) + (
                    page.get("paragraphs") or [])
        title = title or (read.get("title") or "").strip() or None
        subtitle = subtitle or (read.get("subtitle") or "").strip() or None
        source = source or (read.get("source") or "").strip() or None
        got = clean(read.get("paragraphs") or [])
        # Stitch on the overlap. A window repeats the page before it, so a
        # paragraph already held is dropped -- matched on its opening words
        # rather than the whole of it, because a paragraph split by a page
        # break comes back whole from one window and truncated from the other.
        seen = {one["text"][:60] for one in paragraphs}
        paragraphs += [one for one in got if one["text"][:60] not in seen]

    passage = {"title": title, "subtitle": subtitle, "source": source,
               "paragraphs": paragraphs}

    words = sum(len(one["text"].split()) for one in paragraphs)
    faults = []
    if not paragraphs:
        faults.append("no paragraphs")
    elif not WORDS[0] <= words <= WORDS[1]:
        faults.append(f"{words} words, outside {WORDS[0]}-{WORDS[1]}")
    if not title:
        faults.append("no title")
    if (wrong := lettering(paragraphs)):
        faults.append(wrong)
    return passage, faults


def passages(conn: sqlite3.Connection, where: str, args: tuple) -> list:
    return conn.execute(
        "SELECT p.*, d.rel_path pdf FROM passage p "
        "JOIN document d ON d.id = p.document_id "
        f"WHERE {where} ORDER BY p.book_number, p.test_no, p.passage_no",
        args).fetchall()


def report(conn: sqlite3.Connection) -> None:
    """Which passages have their text, and what is wrong with the ones that do."""
    rows = passages(conn, "1 = 1", ())
    read = missing = 0
    faults: list[tuple[str, str]] = []
    failed: list[str] = []
    for row in rows:
        path = WORK / row["id"] / "passage.json"
        if not path.exists():
            missing += 1
            continue
        read += 1
        held = json.loads(path.read_text())
        for fault in held.get("faults") or []:
            faults.append((row["id"], fault))
    print(f"{read} of {len(rows)} passages read ({missing} left)")
    if faults:
        print(f"\n{len(faults)} thing(s) to look at:")
        for passage_id, fault in faults:
            print(f"  {passage_id:<16} {fault}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("passage_id", nargs="?", help="one passage, like cam11-t1-p2")
    ap.add_argument("--book", type=int, help="every located passage of one book")
    ap.add_argument("--report", action="store_true",
                    help="what has been read and what looks wrong, then stop")
    ap.add_argument("--force", action="store_true",
                    help="read again a passage already on disk")
    ap.add_argument("--model", default=vision.DEFAULT_MODEL)
    args = ap.parse_args()

    conn = sqlite3.connect(SEED / "catalogue.db")
    conn.row_factory = sqlite3.Row

    if args.report:
        report(conn)
        return 0

    if args.passage_id:
        rows = passages(conn, "p.id = ?", (args.passage_id,))
        if not rows:
            print(f"{args.passage_id} is not located. Run locate_passages.py first.",
                  file=sys.stderr)
            return 1
    elif args.book:
        rows = passages(conn, "p.book_number = ?", (args.book,))
    else:
        rows = passages(conn, "1 = 1", ())

    failed: list[str] = []
    for row in rows:
        path = WORK / row["id"] / "passage.json"
        # Nothing is read twice. A pass over the corpus that stops halfway is
        # simply run again, which is the rule every stage here keeps.
        if path.exists() and not args.force:
            print(f"{row['id']:<16} already read")
            continue
        # One passage should cost one passage. A page that comes back empty,
        # a provider that refuses, a reply that will not parse -- all of them
        # used to end the run wherever it had got to, and the corpus is 191
        # passages long. Nothing is written for a passage that failed, so the
        # next run simply picks it up again.
        try:
            best = None
            for attempt in range(READS):
                passage, faults = read_passage(row, model=args.model)
                if best is None or len(faults) < len(best[1]):
                    best = (passage, faults)
                if not faults:
                    break
                if attempt + 1 < READS:
                    print(f"{'':<16} {len(faults)} fault(s); reading again")
            passage, faults = best
        except (Exception, SystemExit) as failure:  # noqa: BLE001
            print(f"{row['id']:<16} FAILED  {failure}")
            failed.append(row["id"])
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**passage, "faults": faults},
                                   indent=2, ensure_ascii=False))
        # The title goes back to the catalogue, where the report can see it:
        # locate_passages could only take the title off a page that printed
        # one above its questions, and five passages have none.
        if passage["title"]:
            conn.execute("UPDATE passage SET title = ? WHERE id = ?",
                         (passage["title"], row["id"]))
            conn.commit()
        words = sum(len(one["text"].split()) for one in passage["paragraphs"])
        print(f"{row['id']:<16} {len(passage['paragraphs']):>2} paragraphs,"
              f" {words:>4} words  {passage['title'] or '—'}"
              + (f"\n{'':<16} ! {'; '.join(faults)}" if faults else ""))

    if failed:
        print(f"\n{len(failed)} passage(s) failed and were not written:"
              f" {', '.join(failed)}")
        print("Run the same command again to pick them up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

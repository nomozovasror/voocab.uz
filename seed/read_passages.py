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

#: The most of a passage one paragraph may hold before the split that made
#: it is not believed.
#:
#: A re-split is only as good as the letters it is cut on, and a passage the
#: book does not letter at all invites the model to invent some. Cambridge
#: 20's test 2 passage 1 came back with four -- it has no question answered
#: by a paragraph letter, so there is nothing on the page to letter -- and
#: cutting on them produced a "paragraph" of 692 words out of 972.
#:
#: Forty-five per cent, which is well clear of both: the twelve passages
#: this rule re-split correctly hold between sixteen and thirty-one per cent
#: in their largest, and the invented one held seventy-one.
LOPSIDED = 0.45

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


LETTERS_PROMPT = """\
These images are the pages of ONE IELTS Academic Reading passage whose \
paragraphs are lettered in the margin: A to {last}, {count} of them in all, \
running across these pages in ONE sequence.

Do not start again at A on each page. A page that begins partway through \
the passage begins partway through the sequence, and the letter printed \
beside its first paragraph says where.

Read ONLY the letters and where each one starts. Do not transcribe the \
passage.

JSON only, no prose and no code fence:

{{"paragraphs": [{{"label": "<the letter, like A>",
                 "opening": "<the first SIX words of that paragraph, \
verbatim>"}}]}}

Only the paragraphs on THESE pages, in the order they are printed. Do not \
invent a letter for a paragraph that has none."""


def fold(text: str) -> tuple[str, list[int]]:
    """The text reduced to letters, digits and single spaces, and where each
    kept character came from.

    Matching has to survive a quotation mark read as a different quotation
    mark, a dash for a hyphen, a double space. Slicing has to happen in the
    ORIGINAL, or the passage a learner reads is the flattened one.
    """
    kept: list[str] = []
    where: list[int] = []
    for i, ch in enumerate(text):
        if ch.isalnum():
            kept.append(ch.lower())
            where.append(i)
        elif kept and kept[-1] != " ":
            kept.append(" ")
            where.append(i)
    return "".join(kept).strip(), where


def cut_at(text: str, openings: list[str]) -> list[str] | None:
    """`text` split where each opening begins, or None if it cannot be.

    None rather than a best effort. An opening that is not found, or found
    out of order, means the letters and the prose are not describing the
    same thing -- and a passage split in the wrong place is worse than one
    split too finely, because the letters would then be confidently wrong.
    """
    flat, where = fold(text)
    at: list[int] = []
    cursor = 0
    for opening in openings:
        needle, _ = fold(opening)
        if not needle:
            return None
        found = flat.find(needle, cursor)
        if found < 0:
            return None
        at.append(where[found])
        cursor = found + 1
    if not at:
        return None
    # The first paragraph starts at the beginning whatever was matched, so
    # nothing before the first letter is dropped -- there should be nothing,
    # and if there is, it belongs to that paragraph rather than to nobody.
    at[0] = 0
    bounds = at + [len(text)]
    return [text[bounds[i]:bounds[i + 1]].strip() for i in range(len(at))]


def relabel(passage: dict, row: sqlite3.Row, *, model: str) -> bool:
    """Split the passage where the BOOK letters it, and label the pieces.

    The narrow question left after a passage has been read twice and still
    comes back lettered partway down. Transcribing a page and reading its
    margin are two jobs, and the margin is the one that gets dropped when
    the first is long.

    It re-SPLITS rather than re-labels, and that is the whole of why it
    works. The reader breaks a passage wherever the page breaks a line --
    Cambridge 20's test 4 passage 1 came back in fifteen paragraphs where
    the book letters eleven -- so there is no arrangement of A to K that
    fits fifteen pieces. The letters are not decoration on a split somebody
    else chose; they ARE the split, and the answer to "which paragraph
    contains the following information" is a letter, so the two have to be
    the same thing.

    Nothing is invented and nothing is positional: each letter comes back
    with the first words of its own paragraph, and the prose is cut where
    those words are. If the letters are not a complete run of A, B, C, or if
    any opening cannot be found in order, nothing is changed at all.

    Returns whether the passage was re-split.
    """
    # How many letters to expect, and it matters. Asked without a count the
    # model letters each IMAGE from A -- page 2 of a passage comes back
    # "A, B, C" for paragraphs the book calls D, E, F -- and merging those
    # keeps only the first page's. Told the run and told not to restart, it
    # reads the margin.
    #
    # The count is the reading's own paragraph count, which is the thing in
    # doubt; it is a hint rather than an answer, and what comes back is still
    # checked -- a complete run, every opening found in order, and no piece
    # holding half the passage.
    # Two counts to try, the book's first. The answer key names the last
    # paragraph anything points at, which is evidence; the reading's own
    # count is a guess, and it is wrong in exactly the case this matters --
    # Cambridge 20's test 4 passage 2 has six lettered paragraphs and came
    # back in seven, the last being the tail of F split off at a column
    # break. Asked for seven the model obliges and the answer is refused;
    # asked for six it reads the margin.
    #
    # Whichever is tried, what comes back is checked the same way: a
    # complete run, every opening found in order, no piece holding half the
    # passage.
    counts = [n for n in (letters_wanted(row["id"]),
                          len(passage["paragraphs"])) if n > 1]
    for count in dict.fromkeys(counts):
        if _relabel_at(passage, row, count, model=model):
            return True
    return False


def _relabel_at(passage: dict, row: sqlite3.Row, count: int, *,
                model: str) -> bool:
    """One attempt at `relabel`, told how many letters to expect."""
    pages = text_pages(row)
    work = WORK / row["id"]
    asked = LETTERS_PROMPT.format(count=count,
                                  last=chr(ord("A") + max(0, count - 1)))
    found: dict[str, str] = {}
    for start in range(0, max(1, len(pages) - 1), PAGES_PER_CALL - 1):
        window = pages[start:start + PAGES_PER_CALL]
        if not window:
            continue
        shots = vision.render(MATERIALS / row["pdf"], window, work / "pages",
                              dpi=PASSAGE_DPI, jpeg=True)
        replies = []
        try:
            replies = [vision.ask_json(asked, shots, model=model,
                                       max_tokens=2000)]
        except vision.Refused:
            # The same refusal the transcription hits, and the same answer:
            # ask the other provider, one sheet at a time. Which is also why
            # the openings are matched rather than counted -- that provider
            # reads a sheet at a time and letters each one from A.
            for one in shots:
                try:
                    replies.append(vision.ask_json(
                        asked, [one], provider=FALLBACK, max_tokens=2000))
                except SystemExit:
                    continue
        except SystemExit:
            continue
        for said in replies:
            for one in said.get("paragraphs") or []:
                label = str(one.get("label") or "").strip().upper()
                head = str(one.get("opening") or "").strip()
                # First seen wins. Windows overlap, and where a sheet is
                # read on its own it is lettered from A again -- so a later
                # window's "A" is the same paragraph some earlier window
                # already called H.
                if len(label) == 1 and label.isalpha() and head:
                    found.setdefault(label, head)

    want = [chr(ord("A") + i) for i in range(len(found))]
    if not found or sorted(found) != want:
        return False

    pieces = cut_at("\n\n".join(one["text"] for one in passage["paragraphs"]),
                    [found[label] for label in want])
    if pieces is None or any(not piece for piece in pieces):
        return False
    sizes = [len(piece.split()) for piece in pieces]
    if sizes and max(sizes) > LOPSIDED * sum(sizes):
        # One piece holding half the passage is not a paragraph, and the
        # letters it was cut on were not the book's. See LOPSIDED.
        return False

    passage["paragraphs"] = [{"label": label, "text": piece}
                             for label, piece in zip(want, pieces)]
    return True


BEFORE = 3


TITLE_PROMPT = """\
This image is a page of an IELTS Academic Reading paper. A new Reading \
Passage may BEGIN partway down it, under a heading like "READING PASSAGE 3".

JSON only: {"title": "<the title of the passage that BEGINS on this page, in \
large bold type -- not a running header and not 'READING PASSAGE 3'; null if \
no passage begins here>"}"""


def title_before(row: sqlite3.Row, first: int, *, model: str) -> str | None:
    """The passage's title, off the sheet BEFORE the one it is located on.

    Cambridge 20's re-typeset packs several things onto one sheet -- already
    a finding -- so a passage can begin halfway down the page its predecessor
    ends on. The grouper gives that sheet to the passage whose QUESTIONS are
    on it, which is the right call for the questions and takes the next
    passage's title with it: three of the four untitled passages in the
    corpus are Cambridge 20's, and each one's text begins mid-sentence.

    One page and one question. A title is the only thing taken from it --
    the prose is already whole, since the reader was given the sheet the
    passage continues on.
    """
    if first <= 0:
        return None
    shots = vision.render(MATERIALS / row["pdf"], [first - 1],
                          WORK / row["id"] / "pages", dpi=PASSAGE_DPI,
                          jpeg=True)
    try:
        said = vision.ask_json(TITLE_PROMPT, shots, model=model,
                               max_tokens=300)
    except SystemExit:
        return None
    title = str(said.get("title") or "").strip()
    return title or None


def opening_before(row: sqlite3.Row, first: int, prompt: str, *, model: str
                   ) -> tuple[list[dict], str | None]:
    """The pages before a SHORT passage that are the rest of it.

    A passage is three hundred and fifty words at least. One that comes back
    at two hundred and forty, in two paragraphs, beginning mid-sentence, did
    not begin where the grouper thinks it did: Cambridge 12's test 2 opens on
    a sheet the page map called `other`, four pages before the one the
    passage was bounded to, so its first two pages of prose and its title
    were never read.

    Walked back a page at a time, and it STOPS AT THE TITLE -- a passage
    begins where its own heading is printed, so the sheet carrying one is
    the last one taken. A sheet that is not this paper's prose ends the walk
    with nothing taken from it, which is what keeps the passage before this
    one out.
    """
    out: list[dict] = []
    title: str | None = None
    for back in range(1, BEFORE + 1):
        index = first - back
        if index < 0:
            break
        shots = vision.render(MATERIALS / row["pdf"], [index],
                              WORK / row["id"] / "pages", dpi=PASSAGE_DPI,
                              jpeg=True)
        try:
            said = vision.ask_json(prompt, shots, model=model, max_tokens=8000)
        except SystemExit:
            break
        got = clean(said.get("paragraphs") or [])
        if not got:
            break
        out = got + out
        title = (str(said.get("title") or "").strip() or None) or title
        if title:
            break
    return out, title


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

    # A passage shorter than any real one did not begin where it was bounded
    # to -- see `opening_before`. Done before the title is chased, because
    # the sheet that carries the opening usually carries the title too.
    # A passage whose lettering starts above A is missing its opening, and
    # says so exactly: the book letters from A, so a first paragraph called
    # C means two were never read. Cambridge 20's test 4 passage 2 came back
    # at 799 words -- a plausible length, so the word count had nothing to
    # object to -- lettered C, D, E, F.
    lettered = [one["label"] for one in paragraphs if one["label"]]
    late = bool(lettered) and lettered[0] not in ("A", "a")

    words = sum(len(one["text"].split()) for one in paragraphs)
    if pages and (words < WORDS[0] or late):
        earlier, found = opening_before(row, min(pages), prompt, model=model)
        if earlier:
            print(f"{'':<16} {len(earlier)} paragraph(s) read off the"
                  f" {len(earlier) and 'sheets'} before")
            paragraphs = earlier + paragraphs
            passage["paragraphs"] = paragraphs
            title = title or found
            passage["title"] = title

    # A passage with no title of its own may have left it on the sheet
    # before -- see `title_before`.
    if not title and pages:
        title = title_before(row, min(pages), model=model)
        if title:
            print(f"{'':<16} title read off the sheet before: {title!r}")
            passage["title"] = title

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


#: The tasks a paragraph's LETTER is the answer to.
#:
#: Matching FEATURES is not one of them, and putting it here was a mistake
#: worth recording: its answers are letters, but they are letters from its
#: own box -- "A Dr Helmut Fischer, B Anthony Berwick" -- and name a person
#: or a study rather than a paragraph. A passage is lettered for the two
#: tasks that ask the candidate to point AT a paragraph, and for nothing
#: else.
BY_LETTER = {"matching_information", "matching_headings"}
#:
#: The same set the importer keeps; here it decides which passages MUST
#: be lettered.


def plain(title: str) -> str:
    """A title stripped to what two readings of it have in common."""
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def text_pages(row: sqlite3.Row) -> list[int]:
    """The passage's sheets that carry its PROSE, not its questions.

    The margin letters are printed beside the text and nowhere else, so a
    question sheet has nothing to offer the letter reader and plenty to
    mislead it: a matching task prints its own lettered box, and Cambridge
    20's test 4 passage 2 came back with an "A" taken from the options
    beside the questions rather than from the margin beside a paragraph.

    Which sheets those are is already on disk -- `locate_passages.py` asked
    every one of them which numbers it prints. A sheet carrying any of this
    passage's numbers is a question sheet.

    The other end needs the opposite correction. A passage whose text begins
    halfway down the sheet that finishes the PREVIOUS passage's questions is
    not recorded as owning that sheet -- the locator hands a sheet to
    whichever paper's numbers it prints -- so its first paragraphs, A and B
    in Cambridge 20's test 4 passage 2, are on a page this function would
    never look at. The locator wrote down the title it saw on each sheet,
    and the sheet printing THIS passage's title is where its prose starts.
    """
    pages = json.loads(row["pages"] or "[]")
    first, last = band(row["passage_no"])
    cache = (WORK / f"passages-book{row['book_number']}"
                    f"-doc{row['document_id']}.json")
    if not cache.exists():
        return pages
    named = (WORK / row["id"] / "passage.json")
    titled = ""
    if named.exists():
        titled = plain(json.loads(named.read_text()).get("title") or "")

    asking, opens = set(), set()
    for reply in json.loads(cache.read_text()):
        seen = [int(n) for n in reply.get("numbers") or []
                if isinstance(n, (int, float))]
        if any(first <= n <= last for n in seen):
            asking.add(reply["index"])
        if titled and plain(reply.get("title") or "") == titled:
            opens.add(reply["index"])

    before = [index for index in opens
              if pages and index < pages[0] and index >= pages[0] - BEFORE]
    kept = [index for index in before + pages if index not in asking]
    return sorted(set(kept)) or pages


def letters_wanted(passage_id: str) -> int:
    """How many lettered paragraphs the QUESTIONS say this passage has.

    The answer key names them: "which paragraph contains the following
    information" is answered F, so the passage has at least six. That is the
    book's own word on a number the reading can only guess at, and it is
    usually exactly right -- these tasks ask about every paragraph or all
    but one.

    Zero where nothing asks. A passage nobody points at has no count to
    check against, and the reading's own is all there is.
    """
    built = WORK / passage_id / "questions.src.json"
    if not built.exists():
        return 0
    top = 0
    for group in json.loads(built.read_text()).get("groups", []):
        if group.get("type") not in BY_LETTER:
            continue
        for question in group.get("questions", []):
            key = str(question.get("key") or "").strip().upper()
            if len(key) == 1 and key.isalpha():
                top = max(top, ord(key) - ord("A") + 1)
            # Matching headings names the paragraph in the ITEM rather than
            # in the answer -- "Paragraph C" -- and the answer is a numeral.
            said = str(question.get("prompt") or "").strip().upper()
            if said.startswith("PARAGRAPH ") and len(said) == 11:
                top = max(top, ord(said[-1]) - ord("A") + 1)
    return top


def needs_letters(passage_id: str) -> bool:
    """Whether anything on this paper is answered by naming a paragraph.

    `lettering` cannot ask this. It sees the prose and nothing else, so a
    passage with no letters at all reads as fine to it -- which is right for
    the hundred that have none and wrong for the one whose questions say
    "which paragraph contains the following information". Thirteen passages
    sat in that gap: a task asking for a letter over a passage carrying
    none, which a learner cannot answer at all.
    """
    built = WORK / passage_id / "questions.src.json"
    if not built.exists():
        return False
    return any(group.get("type") in BY_LETTER
               for group in json.loads(built.read_text()).get("groups", []))


def letters_pass(rows, *, model: str) -> int:
    """Re-split the passages whose lettering the reading does not match.

    Its own pass because the prose is already right: re-reading a page to
    fix a margin costs the page and risks the transcription, and what is
    wrong here is only where the paragraphs were broken. Nothing but
    `paragraphs` is touched -- the title, the source and the word count come
    out the same, which is what makes this safe to run over a corpus that is
    already imported.
    """
    done = left = 0
    for row in rows:
        path = WORK / row["id"] / "passage.json"
        if not path.exists():
            continue
        held = json.loads(path.read_text())
        faulted = any("letter" in fault for fault in held.get("faults") or [])
        bare = (needs_letters(row["id"])
                and not any(one["label"] for one in held["paragraphs"]))
        if not (faulted or bare):
            continue
        # A book that letters a passage letters every paragraph of it. So a
        # partial lettering is always wrong, and where NOTHING asks for a
        # letter there is nothing to re-split TO -- the count the re-split
        # aims at comes from the answer key, and this paper's key names no
        # paragraph. Two labels on six paragraphs of "Whale Strandings" were
        # the reader's own, on a passage the Guide prints unlettered
        # (checked, all three sheets: no margin letters at all). Stripping
        # them leaves what the book prints; keeping them shows a learner an
        # A and a B and then four paragraphs with nothing.
        if not needs_letters(row["id"]):
            for one in held["paragraphs"]:
                one["label"] = None
            held["faults"] = [fault for fault in held["faults"]
                              if "letter" not in fault]
            path.write_text(json.dumps(held, indent=2, ensure_ascii=False))
            print(f"{row['id']:<16} unlettered -- nothing asks for a letter")
            done += 1
            continue

        before = len(held["paragraphs"])
        if relabel(held, row, model=model):
            held["faults"] = [fault for fault in held["faults"]
                              if "letter" not in fault]
            if (wrong := lettering(held["paragraphs"])):
                held["faults"].append(wrong)
            path.write_text(json.dumps(held, indent=2, ensure_ascii=False))
            labels = "".join(one["label"] or "?" for one in held["paragraphs"])
            print(f"{row['id']:<16} {before} -> {len(held['paragraphs'])}"
                  f" paragraphs, lettered {labels}")
            done += 1
        else:
            print(f"{row['id']:<16} the letters and the prose still disagree")
            left += 1
    print(f"\n{done} re-split, {left} left")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("passage_id", nargs="?", help="one passage, like cam11-t1-p2")
    ap.add_argument("--book", type=int, help="every located passage of one book")
    ap.add_argument("--report", action="store_true",
                    help="what has been read and what looks wrong, then stop")
    ap.add_argument("--force", action="store_true",
                    help="read again a passage already on disk")
    ap.add_argument("--letters", action="store_true",
                    help="only re-split a passage already read, where the "
                         "book's lettering and the reading disagree; the "
                         "prose is not read again")
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

    if args.letters:
        return letters_pass(rows, model=args.model)

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
            # A passage read twice and still lettered partway down gets one
            # narrow question about its margin alone -- see `relabel`.
            if any("letter" in fault for fault in faults):
                if relabel(passage, row, model=args.model):
                    print(f"{'':<16} letters read off the margin")
                    faults = [fault for fault in faults
                              if "letter" not in fault]
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

"""Read a whole practice test off a web page, with no vision model at all.

    seed/.venv/bin/python seed/read_html_test.py 21 1
    seed/.venv/bin/python seed/read_html_test.py 21 1 --reading
    seed/.venv/bin/python seed/read_html_test.py 21 1 --refetch

The other way in. `locate_passages.py`, `read_passages.py` and
`read_passage_questions.py` render a scanned page to an image and ask a model
what is on it; this reads a page that was never scanned in the first place.
ieltstrainingonline.com publishes each Cambridge test as WordPress markup, and
every single thing those three stages spend a vision call recovering is
already TEXT in it:

* the passage prose, one ``<p>`` per paragraph, with the margin letters A, B,
  C as their own ``<p>`` between them -- so "which section contains the
  following information" is answered against the book's own lettering rather
  than against a reader's guess at where a paragraph began;
* every question, with its layout intact -- a table completion is a
  ``<table>``, a set of notes is a run of bulleted ``<p>``, a word box is a run
  of ``<b>A</b> …`` pairs;
* the answer key, 1 to 40, in a collapsed ``<div class="et_pb_toggle_content">``
  at the foot of the page;
* for listening: the four part recordings as ``<audio>`` elements, and a link
  to the audioscript -- which marks each answer with an underline AND a ``(Q7)``
  beside it, which is exactly what forced alignment needs.

So this stage costs nothing and is exact where the vision path was
approximate. Cambridge 20's Passage 2 went into the corpus titled "to
Britain", because the reader met a title set over two lines and kept the
second; here a title is an ``<h2>`` and there is nothing to get wrong.

**What it does NOT do** is anything the rest of the pipeline already does. It
writes the same four files the vision stages write --

    seed/work/<id>/passage.json        the text                (reading)
    seed/work/<id>/questions.src.json  the questions and key   (both)
    seed/work/<id>/turns.json          the audioscript         (listening)
    Materials/Cambridge <N>/Test <T>/T<T>S<N>.mp3              (listening)

-- and registers the catalogue rows those files hang off. Everything after
that is unchanged: `build_questions.py` expands the key and runs the layout
check, `align.py` finds where each answer is spoken, and the two importers
write the materials.

Resumable the way `run_reading.py` is, and for the same reason: what has been
done is what is on disk. A page already fetched is read from
``seed/work/html/``, a recording already downloaded is not downloaded again,
and a work file already written is left alone unless ``--force``. Their server
is somebody's, and a re-run for one parsing fix should not cost them forty
megabytes.

## Never trust a heading on these pages

The Cambridge 21 listening page heads its answer key "Answer Cam **20**
Listening Test 01", and the link under it points at `cam-21`. The key is Cam
21's: checked against the Cam 20 Test 1 already in the corpus, not one of the
forty answers matches. It is a copy-paste error on their side, and it is the
reason nothing here is keyed off a heading or off the URL. What a page IS gets
decided by its content: every run ends by comparing what it has just read,
answer for answer, against every test already in `seed/work/`, and stops
rather than seeding a second copy of one under a new name.
"""

import argparse
import hashlib
import json
import pathlib
import re
import sqlite3
import sys
import time
import urllib.request

import soundfile as sf
from bs4 import BeautifulSoup, Comment, NavigableString, Tag

SEED = pathlib.Path(__file__).resolve().parent
REPO = SEED.parent
WORK = SEED / "work"
MATERIALS = REPO / "Materials"
#: Fetched pages, kept out of the per-item work directories because one page
#: is three passages or four sections and belongs to none of them.
PAGES = WORK / "html"

SITE = "https://ieltstrainingonline.com"
#: Divi wraps every authored block in this. One block is one thing on the
#: page -- a rubric, a set of notes, a passage -- which is what makes the
#: sheet readable as a sequence rather than as a soup of paragraphs.
BLOCK = "div.et_pb_text_inner"
#: A picture module. The map a labelling task is answered on is one of these,
#: and so is every piece of the site's own decoration -- which is why it is
#: never chosen by its filename. See `groups`.
PICTURE = "div.et_pb_image"
#: The answer key, one collapsed panel per passage or per part.
KEY_PANEL = "div.et_pb_toggle_content"

#: Their WordPress refuses a request with no browser in the User-Agent, with
#: a 403 and an HTML error page -- which parses, and parses to nothing.
AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


# --- the page -----------------------------------------------------------

#: The least time between two requests to their server, in seconds. A whole
#: book is eight pages, four audioscripts and sixteen recordings -- a hundred
#: megabytes -- and asking for all of it as fast as the socket allows is how
#: a small WordPress host decides this address is a scraper. The cache means
#: this is paid once per file rather than once per run.
COURTESY_S = 2.0
_last_asked = 0.0


def ask(url: str, timeout: int) -> bytes:
    """One request to their server, no sooner than COURTESY_S after the last."""
    global _last_asked
    wait = COURTESY_S - (time.monotonic() - _last_asked)
    if wait > 0:
        time.sleep(wait)
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    finally:
        _last_asked = time.monotonic()


def fetch(url: str, refetch: bool = False) -> str:
    """One page, from the cache unless asked for it again.

    Named by a hash of the URL and not by its slug: two of these slugs run to
    sixty characters and one of them ends in
    "-with-answer-and-audioscripts", which says nothing a directory listing
    needs and is different in every book.
    """
    PAGES.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(url.encode()).hexdigest()[:16]
    path = PAGES / f"{name}.html"
    if path.exists() and not refetch:
        return path.read_text(encoding="utf-8", errors="replace")
    print(f"  fetching {url}", file=sys.stderr)
    body = ask(url, timeout=60).decode("utf-8", errors="replace")
    path.write_text(body, encoding="utf-8")
    (PAGES / f"{name}.url").write_text(url + "\n")
    return body


#: Where each paper lists its tests. One page per paper, every book on it.
INDEX = {"reading": f"{SITE}/practice-tests-for-ielts-reading/",
         "listening": f"{SITE}/practice-tests-for-ielts-listening/"}
#: How the index wires a tile to the page it opens. The tiles are Divi
#: modules with no href at all -- the builder emits this array and binds the
#: click in JavaScript -- so the map is read out of the raw markup before
#: `content` throws the scripts away.
TILE_URL = re.compile(r'\{"class":"(et_pb_[a-z]+_\d+)","url":"(.*?)"')
#: The class that names one module, out of the eight a tile carries.
MODULE = re.compile(r"^et_pb_[a-z]+_\d+$")


def test_url(paper: str, book: int, test: int, refetch: bool = False) -> str:
    """Where one test lives, read off the index rather than built from a slug.

    Building it was the first version and it does not survive the corpus:
    Cambridge 21's reading tests are `practice-cam-21-reading-test-01`, every
    book from 10 to 20 adds `-with-answer`, the listening pages add
    `-with-answer-and-audioscripts`, and Cambridge 17's Reading Test 3 is
    `practice-c-17-reading-test-01` -- a typo on their side that no rule will
    ever produce. The index knows all four hundred of them.
    """
    raw = fetch(INDEX[paper], refetch)
    urls = {name: found.replace("\\/", "/")
            for name, found in TILE_URL.findall(raw)}
    wanted = f"Test {book}-{test}"
    for tile in content(raw).select("div.et_clickable"):
        if flat(tile) != wanted:
            continue
        for name in tile.get("class") or []:
            if MODULE.match(name) and name in urls:
                return urls[name]
    raise SystemExit(f"the {paper} index has no tile called {wanted!r}")


def content(html: str) -> Tag:
    """The authored part of the page.

    Scripts and styles go first, and not for tidiness: Divi inlines its
    builder's JSON configuration inside a ``<script>``, which carries copies
    of the visible text and would double every paragraph.
    """
    soup = BeautifulSoup(html, "html.parser")
    for junk in soup(["script", "style", "noscript"]):
        junk.decompose()
    # Divi leaves `<!-- divi:paragraph -->` markers in the body, and a
    # comment is a string node to the parser: the first line of every
    # passage's block read as "divi:paragraph" instead of its heading.
    for note in soup.find_all(string=lambda s: isinstance(s, Comment)):
        note.extract()
    for advert in soup.select("div.ielts-manual-ads, ins.adsbygoogle"):
        advert.decompose()
    entry = soup.select_one("div.entry-content")
    if entry is None:
        raise SystemExit("this page has no div.entry-content; the site's "
                         "template has changed")
    return entry


# --- runs of text, and which of them are bold ---------------------------

#: Everything structural on these pages is bold and everything spoken is not:
#: a gap's number, an option's letter, a section heading, a speaker's name.
#: The site sets the prose with an explicit `font-weight: 400` beside it, so
#: this is the page's own distinction rather than one imposed on it.
BOLD_TAGS = {"b", "strong"}


def marked_runs(node: Tag) -> list[tuple[str, bool, bool]]:
    """The text of one element, split at every change of weight or underline.

    ``<b>7</b><span>.......... and toiletries</span>`` comes back as
    ``[("7", True, False), (".......... and toiletries", False, False)]``,
    which is what lets a gap be told from a number the book printed as prose.

    The underline matters only in the audioscript, and there it matters a
    great deal: it is how this site says "this is the answer", and it is the
    evidence `build_questions.py` falls back on where a marker is missing.
    """
    out: list[tuple[str, bool, bool]] = []

    def walk(el, bold: bool, under: bool) -> None:
        for child in el.children:
            if isinstance(child, NavigableString):
                text = str(child).replace("\xa0", " ")
                if text:
                    out.append((text, bold, under))
            elif isinstance(child, Tag):
                if child.name == "br":
                    out.append((" ", bold, under))
                    continue
                walk(child, bold or child.name in BOLD_TAGS,
                     under or child.name == "u"
                     or "underline" in (child.get("style") or ""))

    walk(node, node.name in BOLD_TAGS, node.name == "u")
    return out


def runs(node: Tag) -> list[tuple[str, bool]]:
    """`marked_runs` without the underline, for everything but the script."""
    return [(text, bold) for text, bold, _ in marked_runs(node)]


ITALIC_TAGS = {"i", "em"}


def all_italic(node: Tag) -> bool:
    """Whether every word of an element is set in italics.

    The standfirst under a passage's title is italic and so is the odd book
    name inside the prose, which is why this asks about the WHOLE element:
    Cambridge 21's Passage 3 opens "Ulbe Bosma's *The World of Sugar* is a
    genuinely global history", and an element that merely CONTAINS an <i> put
    all 88 words of it in the subtitle.
    """
    def walk(el, italic: bool) -> bool:
        for child in el.children:
            if isinstance(child, NavigableString):
                if str(child).strip() and not italic:
                    return False
            elif isinstance(child, Tag):
                if not walk(child, italic or child.name in ITALIC_TAGS):
                    return False
        return True

    return walk(node, node.name in ITALIC_TAGS)


def tidy(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def flat(node: Tag) -> str:
    return tidy("".join(text for text, _ in runs(node)))


#: What a blank looks like once it has been typed by four different people:
#: full stops, the ellipsis character, and the odd underscore.
BLANK = re.compile(r"[.…_]{3,}")
#: The bullet the site sets its notes with. The dashes are in it because a
#: SUB-bullet is set with one -- "- Cabins:" and under it "– book one with a
#: window" -- and the grammar has one level of list, so both become the one
#: it has. Left alone the dash reads as the first character of the text.
BULLET = re.compile(r"^\s*[•‣●*\-–—‒]\s*")
#: A line that is nothing but an arrow. On a flow chart it is the step
#: boundary the `>` prefix stands for, and it is drawn rather than written --
#: so it goes, and the break it marks stays.
ARROW = re.compile(r"^[↓⇓→⇒⟶⭣↴\s]+$")
#: A gap number and the blank it names, with whatever the page sets between
#: them. Only a currency sign, a per-cent or whitespace may stand there: the
#: gap is "£ ............" as often as it is the dots alone, and anything
#: wordier means the number was prose and the blank somebody else's.
OWNS_A_BLANK = re.compile(r"\x00(\d+)\x00([\s£$€¥%#]*)[.…_]{3,}")


def gapped(parts: list[tuple[str, bool]], seen: list[int]) -> str:
    """One line with its blanks turned into ``{{N}}`` tokens.

    The token carries the number the PAPER prints -- 7, 31 -- and is
    renumbered to 1..N by :func:`renumbered` once the whole group has been
    read. Numbering as the gaps are MET was the first version and it is wrong
    on a table: a cell holding three lines is written as three rows, so the
    page is walked column by column and Part 1's sixth gap was met third.
    The template and the questions agreed with each other -- both said gap
    three -- so nothing downstream objected, and the material went in with
    question 3 holding question 6's answer.

    A bold number is only a gap where a blank follows it, which is why the
    two are matched as one thing (`OWNS_A_BLANK`) rather than the number
    being replaced where it stands. The prose is full of bold numbers that
    are not gaps -- a date, a price, a year -- and each one turned into a gap
    is a group with one more question than its answer key has answers.
    """
    written: list[str] = []
    for text, bold in parts:
        # The bullet is sometimes set INSIDE the bold with the number --
        # "<b>•   31</b>" -- so it is taken off before the digits are
        # recognised and put back afterwards. Left on, Part 4's first note
        # was a line of prose and the paper lost question 31 with nothing
        # anywhere saying so.
        lead, stripped = "", text.strip()
        if bold and BULLET.match(stripped):
            lead, stripped = "• ", BULLET.sub("", stripped)
        if bold and stripped.isdigit():
            written.append(f"{lead}\x00{int(stripped)}\x00")
            continue
        written.append(text)
    line = "".join(written)

    def claim(found: re.Match) -> str:
        number = int(found.group(1))
        if number not in seen:
            seen.append(number)
        # What stood between the number and its blank stays, and stays in
        # FRONT of the gap: the cost column prints "2 £ ............", which
        # is a gap for a number of pounds and reads "£ {{2}}".
        return f"{found.group(2)}{{{{{number}}}}}"

    line = OWNS_A_BLANK.sub(claim, line)
    # A bold number with no blank anywhere after it was never a gap. The
    # prose is full of them -- a date, a price, a year -- and each one turned
    # into a gap is a group with one more question than its key has answers.
    line = re.sub(r"\x00(\d+)\x00", r"\1", line)
    # Any blank left over belongs to no number and is a blank the page draws
    # for its own sake. The token is the gap now; a row of dots beside the
    # box the candidate types into is just noise.
    line = BLANK.sub("", line)
    # The book sets the sentence's full stop clear of the dots it follows --
    # "showed places in ................. ." -- so removing the dots leaves
    # the stop floating a space away from the gap.
    line = re.sub(r"\s+([.,;:!?])", r"\1", line)
    return tidy(line)


# --- the sheet, as a sequence of blocks ---------------------------------

#: "READING PASSAGE 2", "PART 3". The one heading that is safe to read: it
#: names a position inside the page rather than which book the page is.
DIVIDER = re.compile(r"^(READING PASSAGE|PART|SECTION)\s+(\d)\b", re.I)
#: "Questions 1-7", "Questions 21 and 22", "Question 40".
#:
#: Neither form is anchored at its end, because a rubric is four lines and
#: `flat` hands them over as one. The single-number form used to be, which
#: read Cambridge 21's Reading Test 2 as thirty-nine questions: its last is
#: printed alone under "Question 40 — Choose the correct letter", and that
#: line is a rubric wherever it stops. What keeps it from matching prose is
#: the word: a question item begins with its number, never with "Question".
RUBRIC = re.compile(r"^Questions?\s+(\d+)\s*(?:[-–—]|and|&)\s*(\d+)|"
                    r"^Questions?\s+(\d+)\b", re.I)


def sheet(entry: Tag) -> list[dict]:
    """Every authored block of the page, said to be one of three things.

    ``divider``  a "READING PASSAGE 2" or "PART 3" heading
    ``rubric``   the instruction line above a group of questions
    ``body``     everything else: a passage, or a group's questions

    Three kinds and not more, because the pages really are that regular: a
    rubric is always followed by exactly one body, and a divider is always
    followed by the passage or by the first rubric of its part.
    """
    out = []
    # Text modules and picture modules together, in the order the page sets
    # them. A picture is a module of its own here, a sibling of the text
    # rather than part of it, and its POSITION is the only thing that says
    # which group it belongs to -- see `groups`.
    for block in entry.select(f"{BLOCK}, {PICTURE}"):
        if "et_pb_image" in (block.get("class") or []):
            image = block.find("img")
            source = (image.get("src") or "").split("?")[0] if image else ""
            if source:
                out.append({"kind": "picture", "block": block, "src": source,
                            "text": ""})
            continue
        text = flat(block)
        if not text:
            continue
        # A block that is nothing but a link is the page's own navigation --
        # "Cam 21 Listening Test 03", "Answer Cam 21 Listening Test 02" --
        # and it sits after the last question with no heading in front of it.
        # Read as content it joined Part 4's notes, where its four titles
        # came out as four headings of a set of notes about cruise ships.
        #
        # By the markup and not by the wording: these four are a link and
        # nothing else, which is a fact about the page rather than a guess at
        # what a title means.
        link = block.find("a", href=True)
        if link is not None and flat(link) == text:
            continue
        # The block's FIRST LINE decides what it is, not the whole of it. The
        # reading page sets "READING PASSAGE 1" and "You should spend about
        # 20 minutes on Questions 1-13" in one block, so a match against the
        # whole text finds the heading nowhere and the rubric everywhere.
        lines = lines_of(block)
        head = DIVIDER.match(lines[0]["text"]) if lines else None
        if head:
            out.append({"kind": "divider", "number": int(head.group(2)),
                        "block": block, "text": lines[0]["text"]})
        elif RUBRIC.match(text):
            # Line by line, not as the one run `flat` gives: the rubric is
            # stored as the instructions and the paper prints it as four
            # lines -- "TRUE if the statement agrees with the information" is
            # one of them, and run together with the two beside it they read
            # as a sentence that says nothing.
            out.append({"kind": "rubric", "block": block,
                        "text": "\n".join(one["text"] for one in lines)})
        else:
            out.append({"kind": "body", "block": block, "text": text})
    return out


def parts_of(entry: Tag, word: str) -> list[dict]:
    """The blocks of each part or passage, in order, keyed by its number.

    The divider is what splits them, and anything before the first one is the
    page's own preamble. The tail of the page -- the "next test" links and the
    answer key's headings -- comes after the last question block and is
    dropped by taking only what a rubric claims.
    """
    found: dict[int, list[dict]] = {}
    current: list[dict] | None = None
    for item in sheet(entry):
        if item["kind"] == "divider" and re.match(word, item["text"], re.I):
            current = found.setdefault(item["number"], [])
            continue
        if current is not None:
            current.append(item)
    if not found:
        raise SystemExit(f"no {word} heading on this page")
    return [{"number": n, "items": found[n]} for n in sorted(found)]


# --- the answer key ------------------------------------------------------

#: A key line: the number in bold, the answer beside it. "21&22" where one
#: question is worth two marks.
KEY_LINE = re.compile(r"^(\d+(?:\s*[&,/]\s*\d+)*)\s*[.)]?\s*(.+)$", re.S)


def key_text(paragraph: Tag) -> str:
    """One key line's answer, with the site's typography undone.

    Two things it undoes, and both were found by the checks downstream
    refusing the result:

    The book prints alternatives separated by a slash -- "cafe / café". The
    site sets that slash in italics, and whatever font it was copied from
    renders it as a capital I. Left alone, "cafe I cafe" is one answer
    containing the word "I", and `parse_answer` expands it to exactly that.

    And "NOT GIVEN" arrives as "NOTGIVEN" on about one line in forty. The
    build refuses it -- rightly, since it is not one of the three words a
    true/false group offers -- and naming the failure three stages later
    costs more than fixing the space here.
    """
    pieces = []
    for text, _ in runs(paragraph):
        pieces.append(text)
    said = tidy("".join(pieces))
    said = re.sub(r"(?<=\S)\s+I\s+(?=\S)", " / ", said)
    said = re.sub(r"\bNOT\s*GIVEN\b", "NOT GIVEN", said, flags=re.I)
    return said


def answer_key(entry: Tag) -> dict[int, str]:
    """Every answer on the page, by the number the paper prints.

    One panel per passage or per part, and they are read as one run: which
    panel an answer is in says nothing the number does not already say, and
    the listening page's panels are titled "Part 1" while its heading claims
    a different book entirely.
    """
    key: dict[int, str] = {}
    for panel in entry.select(KEY_PANEL):
        for paragraph in panel.find_all("p"):
            line = flat(paragraph)
            if not line:
                continue
            match = KEY_LINE.match(line)
            if not match:
                continue
            numbers = [int(n) for n in re.findall(r"\d+", match.group(1))]
            answer = key_text(paragraph)
            # Strip the numbers back off: `flat` joined them to the answer.
            answer = KEY_LINE.match(answer).group(2).strip() if KEY_LINE.match(answer) else answer
            key[numbers[0]] = answer
            for spare in numbers[1:]:
                # "21&22 B, D" is ONE question worth two marks. The second
                # number is recorded as taken so a missing answer can be told
                # from a shared one.
                key[spare] = ""
    if not key:
        raise SystemExit("no answer key on this page")
    return key


# --- what kind of task a rubric describes -------------------------------

#: Read in order, first match wins. Ordered rather than a dict because
#: several of them overlap: "Complete the summary using the list of words"
#: is also "Complete the summary", and the box is what decides how it is
#: answered.
TASKS = (
    (r"complete the (?:table|flow.?chart)", "table_completion"),
    (r"complete the notes", "note_completion"),
    (r"complete the summary", "summary_completion"),
    (r"complete the sentences", "sentence_completion"),
    (r"complete each sentence with the correct ending", "matching_sentence_endings"),
    (r"complete the form", "form_completion"),
    (r"label the (?:map|plan)", "map_labelling"),
    (r"label the diagram", "diagram_labelling"),
    (r"answer the questions below", "short_answer"),
    (r"choose the correct heading", "matching_headings"),
    (r"which (?:section|paragraph) contains", "matching_information"),
    # "Look at the following statements (Questions 22-26) and the list of
    # people below." Its box names people, studies or books rather than
    # paragraphs, which is the whole difference from matching_information --
    # and the reason `import_passage.BY_LETTER` leaves it out when it decides
    # whether a passage's letters are real.
    (r"the list of (?:people|researchers|writers|scientists|academics|"
     r"experts|studies|books|places|statements)", "matching_features"),
    (r"choose the correct letter", "multiple_choice"),
    (r"choose (?:two|three) letters", "multiple_choice"),
    (r"do the following statements agree with the (?:views|claims)",
     "yes_no_not_given"),
    (r"do the following statements agree with the information",
     "true_false_not_given"),
    # Last, because it is the one that describes itself least: every
    # remaining "write the correct letter next to ..." is a box of options
    # answering a list of items, whatever the page calls the items.
    (r"(?:match each|write the correct letter|choose \w+ answers from the box)",
     "matching"),
)

#: A flow chart is a completion task whose template is drawn with ">" steps.
#: It shares "complete the table" above because the page words them the same
#: way; which of the two it is comes from the word the rubric used.
FLOW = re.compile(r"complete the flow.?chart", re.I)
#: "Choose ONE WORD ONLY", "NO MORE THAN THREE WORDS AND/OR A NUMBER".
WORD_LIMIT = (
    (r"\bone word\b", 1),
    (r"\b(?:no more than\s+)?two words\b", 2),
    (r"\b(?:no more than\s+)?three words\b", 3),
)
#: "Choose TWO letters, A-E" -- how many marks one question is worth.
PICK = re.compile(r"choose\s+(two|three)\s+letters", re.I)
#: "the list of words, A-I", "Write the correct letter, A-G". The letters the
#: box runs to, printed rather than counted from the answer key, which only
#: ever names the ones that happen to be right.
LETTER_RANGE = re.compile(r"letters?,?\s+([A-Z])\s*[-–—]\s*([A-Z])", re.I)
#: "sections, A-G" on a matching-information rubric says the same thing about
#: the PASSAGE's letters, which is where that group's box comes from.
SECTION_RANGE = re.compile(
    r"(?:sections?|paragraphs?),?\s+([A-Z])\s*[-–—]\s*([A-Z])", re.I)
#: "NB You may use any letter more than once."
REUSE = re.compile(r"more than once", re.I)
#: The headings box is numbered i, ii, iii, because its ITEMS are the
#: passage's lettered paragraphs -- an answer of "C" would name both.
ROMAN_BOX = re.compile(r"\b(?:i|ii|iii|iv|v)\s*[-–—]\s*[ivxl]+\b", re.I)
#: "Write your answers in boxes 1-7 on your answer sheet." A line about the
#: paper answer sheet, which a candidate sitting this on screen does not
#: have. Dropped, as it is throughout the corpus -- but only where it is the
#: WHOLE line: a true/false rubric says "In boxes 8-13 on your answer sheet,
#: write" and the three words it introduces are underneath it.
ANSWER_SHEET = re.compile(
    r"^write\b.*\bon\s+your\s+answer\s+sheet\.?$", re.I)


def rubric(text: str) -> dict:
    """What a group is, read off its instruction lines."""
    lo, hi = None, None
    span = RUBRIC.match(text)
    if span:
        if span.group(3):
            lo = hi = int(span.group(3))
        else:
            lo, hi = int(span.group(1)), int(span.group(2))
    # The "Questions 1-7" line itself is the pipeline's bookkeeping, not
    # something to print above the questions -- the app numbers them itself,
    # from the part's `first_number`. Every book in the corpus is stored
    # without it.
    body = "\n".join(
        line for line in (l.strip() for l in text.split("\n"))
        if line and not RUBRIC.match(line) and not ANSWER_SHEET.match(line))
    # "FALSE. if the statement contradicts the information" -- a stray stop
    # this page types after one of the three words. It is not a sentence
    # boundary and printing it puts an apparent typo of ours above six
    # questions.
    body = re.sub(r"^(TRUE|FALSE|YES|NO|NOT GIVEN)\.(?=\s)", r"\1", body,
                  flags=re.M)

    kind = None
    for pattern, name in TASKS:
        if re.search(pattern, text, re.I):
            kind = name
            break
    if kind == "table_completion" and FLOW.search(text):
        kind = "flow_chart_completion"

    limit = None
    for pattern, count in WORD_LIMIT:
        if re.search(pattern, text, re.I):
            limit = count
            break

    box = LETTER_RANGE.search(text) or SECTION_RANGE.search(text)
    letters = (ord(box.group(2).upper()) - ord(box.group(1).upper()) + 1
               if box else 0)
    picked = PICK.search(text)
    return {
        "type": kind,
        "first": lo,
        "last": hi,
        "instructions": body,
        "word_limit": limit,
        "letters": letters,
        "reuse": bool(REUSE.search(text)),
        "roman": bool(ROMAN_BOX.search(text)),
        "pick": {"two": 2, "three": 3}.get(
            (picked.group(1).lower() if picked else ""), 1),
    }


# --- a group's body ------------------------------------------------------

#: An option in a box: its letter in bold, what it says beside it. Several
#: can share one paragraph -- the site sets a two-column box as one line.
OPTION = re.compile(r"^[A-Z]$")
#: An item in a list: the paper's number in bold at the head of the line.
ITEM = re.compile(r"^\d+$")


def lines_of(block: Tag) -> list[dict]:
    """One entry per printed line, with its shape already decided.

    A ``<td>`` holding several ``<p>`` is several lines under one cell, which
    is how a table row that carries three facts about one course is printed
    -- and how it has to be written back, as the continuation rows
    `form-syntax.ts` draws with an empty label.
    """
    out = []
    titled = False
    for el in block.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "table"],
                             recursive=False):
        if el.name == "table":
            out.append({"shape": "table", "rows": table_rows(el),
                        "parts": [], "text": ""})
            continue
        parts = runs(el)
        text = tidy("".join(t for t, _ in parts))
        if not text:
            continue
        if el.name.startswith("h"):
            # The first heading tag of a block is the form's title and the
            # rest are headings inside it. Every one of them a title gave
            # Test 3's Part 1 two, one of them the word "Advice" -- which is
            # not what that block is called, it is a division inside it.
            out.append({"shape": "title" if not titled else "heading",
                        "parts": parts, "text": text})
            titled = True
        elif all(bold or not t.strip() for t, bold in parts):
            out.append({"shape": "heading", "parts": parts, "text": text})
        else:
            out.append({"shape": "line", "parts": parts, "text": text})
    return out


def table_rows(table: Tag) -> list[dict]:
    """A table as rows of cells of lines, and which rows span the whole width.

    Three levels deep because a real table completion is: Cambridge 21's
    Level 1 course has two things to learn, three things it costs and one
    thing at the end, all in one row of four cells. Flattened to one line per
    cell they run together into a sentence that says none of them.

    ``span`` is the row the book sets across every column. It is how these
    tables carry their own title -- Test 2's opens with a `colspan="3"`
    holding "Research into sleep and dreaming" -- and writing it out as a
    table row made it the HEADER, which pushed the real header ("Research
    findings | Comment") into the body and left the grid one cell wide at the
    top and three below.
    """
    rows = []
    for tr in table.find_all("tr"):
        row = []
        widest = 1
        for td in tr.find_all(["td", "th"]):
            widest = max(widest, int(td.get("colspan") or 1))
            inner = td.find_all("p", recursive=False)
            if inner:
                # The text that sits in the cell BEFORE its first <p> is the
                # first line of it -- the site writes the cell's opening line
                # bare and only wraps the continuations.
                lead = []
                for child in td.children:
                    if isinstance(child, Tag) and child.name == "p":
                        break
                    lead.extend(runs(child) if isinstance(child, Tag)
                                else [(str(child), False)])
                cell = [lead] if tidy("".join(t for t, _ in lead)) else []
                cell += [runs(p) for p in inner]
            else:
                cell = [runs(td)]
            row.append([line for line in cell
                        if tidy("".join(t for t, _ in line))])
        if row:
            rows.append({"cells": row, "span": len(row) == 1 and widest > 1})
    return rows


def box_of(lines: list[dict]) -> tuple[list[str], set[int]]:
    """The lettered options printed with a group, and which lines they were on.

    Returned with their line numbers so the same block can hold the box and
    the items it answers -- which is the normal shape for "write the correct
    letter next to Questions 17-20", where the box is printed above the list
    and the heading "Duties" between them.
    """
    found: dict[str, str] = {}
    used: set[int] = set()
    for index, line in enumerate(lines):
        if line["shape"] == "table":
            continue
        got: list[tuple[str, str]] = []
        letter = None
        said: list[str] = []
        for text, bold in line["parts"]:
            stripped = text.strip()
            if bold and OPTION.match(stripped):
                if letter:
                    got.append((letter, tidy("".join(said))))
                letter, said = stripped, []
            elif letter is not None:
                said.append(text)
            elif stripped:
                # Prose before the first letter: this is a sentence that
                # happens to contain a bold capital, not a box.
                got, letter = [], None
                break
        if letter:
            got.append((letter, tidy("".join(said))))
        if not got or any(not said for _, said in got):
            continue
        for one, said in got:
            found[one] = said
        used.add(index)
    if not found:
        return [], used
    # In the order they are lettered, with no holes: the box is stored as a
    # list and the server letters it by position, so a missing D would make
    # every answer after it name the wrong option.
    wanted = [chr(ord("A") + i) for i in range(len(found))]
    if sorted(found) != wanted:
        raise SystemExit(f"the options box runs {sorted(found)}, which is not "
                         f"A..{wanted[-1]}")
    return [found[one] for one in wanted], used


def items_of(lines: list[dict], skip: set[int]) -> list[dict]:
    """The numbered items of a matching or true/false group.

    The trailing row of dots is dropped -- it is where the letter is written
    on paper, and the app draws its own box.
    """
    out = []
    for index, line in enumerate(lines):
        if index in skip or line["shape"] != "line":
            continue
        parts = line["parts"]
        head = parts[0][0].strip() if parts else ""
        if not (parts[0][1] and ITEM.match(head)):
            continue
        # The blank goes; the full stop stays. An item's own punctuation is
        # part of the sentence the candidate judges -- every true/false
        # prompt in the corpus ends in one -- and stripping stops off the end
        # took it with the dots the first time round.
        said = tidy(BLANK.sub("", "".join(t for t, _ in parts[1:])))
        out.append({"paper_number": int(head), "prompt": said})
    return out


def choices_of(lines: list[dict]) -> list[dict]:
    """A multiple-choice group: each numbered stem with the options under it.

    The options belong to the question here rather than to the group, which
    is the one thing multiple choice does differently from everything else on
    the page -- four questions under one instruction line, each with its own
    A to D.
    """
    out: list[dict] = []
    for line in lines:
        if line["shape"] == "table":
            continue
        parts = line["parts"]
        head = parts[0][0].strip() if parts else ""
        if parts[0][1] and ITEM.match(head):
            out.append({"paper_number": int(head),
                        "prompt": tidy("".join(t for t, _ in parts[1:])),
                        "options": []})
            continue
        if parts[0][1] and OPTION.match(head) and out:
            out[-1]["options"].append(tidy("".join(t for t, _ in parts[1:])))
            continue
        if not out and line["shape"] == "line":
            # The stem of a "Choose TWO letters" group, which carries no
            # number of its own: the paper prints "Questions 21 and 22" above
            # it and the question is the pair.
            out.append({"paper_number": None, "prompt": line["text"],
                        "options": []})
    return out


def flat_table(rows: list) -> list[dict]:
    """A one-column table read back as the lines it is really made of.

    The site sets Part 1's "General information" notes as a ``<table>`` of
    one column, because a bordered box is how the book prints them. Written
    out as ``+`` rows it becomes a table whose header is the heading and
    whose body is five one-cell rows -- which is not what the page shows and
    not what "Complete the notes below" asks for. One column is not a table.
    """
    out = []
    for index, row in enumerate(rows):
        for line in (row["cells"][0] if row["cells"] else []):
            text = tidy("".join(t for t, _ in line))
            # The box's header row is its name -- "General information" --
            # which is the form's TITLE and not a heading inside it: there
            # is nothing above it for a heading to sit under.
            shape = ("title" if index == 0 and not BULLET.match(text)
                     else "line")
            out.append({"shape": shape, "parts": line, "text": text})
    return out


def template_of(lines: list[dict], skip: set[int], seen: list[int],
                flow: bool = False) -> str:
    """A completion group's body in the layout grammar `form-syntax.ts` reads.

    ``#`` is the form's title and ``##`` a heading inside it; a bulleted line
    is ``-``; a table is a run of ``+`` rows, the first of them the header;
    a flow chart is a run of ``>`` steps. Everything else is a full-width
    line, which is what a summary paragraph is.
    """
    out: list[str] = []
    #: What a flow chart's current step has collected so far. The page sets
    #: one step as several paragraphs -- "Initial aim", then the blank under
    #: it -- with an arrow between steps, so the arrow is the boundary and a
    #: paragraph is not. Written a step per paragraph, Test 2's chart came
    #: out as eight boxes of which four were empty.
    step: list[str] = []

    def flush() -> None:
        if step:
            out.append("> " + " ".join(step))
            step.clear()

    for index, line in enumerate(lines):
        if index in skip:
            continue
        if line["shape"] == "table":
            flush()
            if max((len(row["cells"]) for row in line["rows"]),
                   default=0) > 1:
                out.extend(table_template(line["rows"], seen))
            else:
                out.append(template_of(flat_table(line["rows"]), set(), seen,
                                       flow))
            continue
        if flow and ARROW.match(line["text"]):
            flush()
            continue
        written = gapped(line["parts"], seen)
        if not written:
            continue
        if line["shape"] == "title":
            flush()
            out.append(f"# {written}")
        elif line["shape"] == "heading":
            flush()
            out.append(f"## {written}")
        elif flow:
            step.append(BULLET.sub("", written))
        elif BULLET.match(line["text"]):
            out.append("- " + BULLET.sub("", written))
        else:
            out.append(written)
    flush()
    return "\n".join(out)


def table_template(rows: list, seen: list[int]) -> list[str]:
    """A table as ``+`` rows, one per printed line rather than per cell.

    A cell holding three lines makes three rows: the first carries the whole
    row, and the rest carry only that column, with the other columns left
    empty. That is what the grammar's continuation row means and what the
    page prints -- the course's name is written once and its three costs sit
    under each other beside it.

    Every row is padded to the widest row's width before it is written, so a
    continuation that only fills the third column still says so with two
    empty cells in front of it. The empties after the last filled cell are
    trimmed: `form-syntax.ts` pads a short row on the way in, and trailing
    bars are a row of nothing.
    """
    width = max((len(row["cells"]) for row in rows if not row["span"]),
                default=1)
    out = []
    for row in rows:
        if row["span"]:
            # A row across every column is the table's own caption, not a row
            # of it: written as one, it becomes the header and the real
            # header becomes data.
            said = " ".join(gapped(line, seen) for line in row["cells"][0])
            if said:
                out.append(("# " if not out else "## ") + said)
            continue
        cells = row["cells"]
        deep = max((len(cell) for cell in cells), default=0)
        for depth in range(max(deep, 1)):
            written = []
            for index in range(width):
                cell = cells[index] if index < len(cells) else []
                said = gapped(cell[depth], seen) if depth < len(cell) else ""
                # A bulleted line inside a cell keeps its bullet, in the
                # grammar's own spelling rather than the page's glyph: three
                # findings about whales are three lines of one cell and run
                # together into one sentence without it.
                written.append(BULLET.sub("- ", said) if BULLET.match(said)
                               else said)
            out.append(("+ " + " | ".join(written)).rstrip(" |") or "+")
    return out


def renumbered(template: str, seen: list[int]) -> tuple[str, dict[int, int]]:
    """The template with its gaps running 1..N, and which paper number each is.

    The backend asks a group's gaps to be 1..N with no holes, and the app
    prints gap N as the part's ``first_number`` plus N minus one -- so the
    order here is not cosmetic. It is the PAPER's order, not the order the
    gaps were met in: see `gapped`.
    """
    order = {paper: index + 1 for index, paper in enumerate(sorted(seen))}
    return (re.sub(r"\{\{(\d+)\}\}",
                   lambda m: "{{%d}}" % order[int(m.group(1))], template),
            order)


# --- a whole group -------------------------------------------------------


#: Answered ON a picture rather than into a template: the items are places
#: with a blank beside them, and the blank takes a letter off the map or a
#: word out of a box printed next to it.
#:
#: Read as ITEMS and not as a template, which is what the corpus already
#: holds for all 25 of them: the source carries `prompt` per question and an
#: empty template, and `build_questions.laid_out` turns those prompts into
#: "Exhibition {{1}}" and `as_rows` into "Exhibition | {{1}}". Written here
#: as a template instead, the item number and its blank sit at opposite ends
#: of the line and the gap lands in the wrong one.
ON_A_PICTURE = {"map_labelling", "diagram_labelling"}


def group(said: dict, body: list[dict], key: dict[int, str],
          picture: str | None = None) -> dict:
    """One instruction line and the questions under it, as `questions.src.json`.

    The shape is `read_passage_questions.py`'s, exactly, because
    `build_questions.py` is what reads it next and there is no reason for two
    readers of the same page to hand back two things.

    ``body`` is every block between this rubric and the next, concatenated:
    a flow chart is printed as its box and then its chart, and the two halves
    of one group are not two groups.
    """
    lines = [line for item in body for line in lines_of(item["block"])]
    kind = said["type"]
    if kind is None:
        raise SystemExit(f"unrecognised task: {said['instructions']!r}")

    out = {"type": kind, "instructions": said["instructions"],
           "word_limit": said["word_limit"], "template": "", "questions": []}
    if kind in ON_A_PICTURE:
        # Recorded even when it is None. A labelling group with no picture is
        # one `publish_blockers` refuses by name -- "attach the picture the
        # labels go on" -- and that is the right way for it to fail: loudly,
        # and after everything else about it has been read. Reaching further
        # up the page for the nearest image would hand the candidate whatever
        # the site had decorated the heading with.
        out["picture_src"] = picture

    if kind == "multiple_choice":
        asked = choices_of(lines)
        # A "Choose TWO letters" prints its stem above the options with no
        # number: the pair in the rubric IS the number. Put it back, or the
        # answer key has nothing to be matched against.
        for question in asked:
            if question["paper_number"] is None:
                question["paper_number"] = said["first"]
        if said["pick"] > 1 and len(asked) == 1:
            # The stem reads as part of the instruction line on a paper that
            # asks one question under one rubric, which is how the corpus
            # stores every other "choose two".
            out["instructions"] = (out["instructions"] + "\n"
                                   + asked[0]["prompt"]).strip()
        out["pick"] = said["pick"]
        out["questions"] = [
            {"number": i, "paper_number": q["paper_number"],
             "key": key.get(q["paper_number"], ""),
             "prompt": q["prompt"], "options": q["options"]}
            for i, q in enumerate(asked, start=1)]
        return out

    if kind in ("true_false_not_given", "yes_no_not_given"):
        asked = items_of(lines, set())
        out["questions"] = [
            {"number": i, "paper_number": q["paper_number"],
             "key": key.get(q["paper_number"], ""), "prompt": q["prompt"]}
            for i, q in enumerate(asked, start=1)]
        return out

    box, used = box_of(lines)
    if kind.startswith("matching") or kind in ON_A_PICTURE:
        asked = items_of(lines, used)
        if not box and said["letters"]:
            # Two tasks whose box is not printed as a list of words. A
            # matching-information group is answered from the passage's own
            # lettering -- "Reading Passage 2 has seven sections, A-G" -- and
            # a map is answered from the letters drawn on the map. Both say
            # how far the letters run in the rubric and print nothing to
            # read, so the letters ARE the options; `build_questions` knows a
            # box of bare letters from a box of words and turns the first
            # into `image_letters`.
            box = [chr(ord("A") + i) for i in range(said["letters"])]
        out["options"] = box
        out["word_limit"] = None
        if kind not in ON_A_PICTURE:
            out["label_style"] = "roman" if said["roman"] else "letters"
        out["questions"] = [
            {"number": i, "paper_number": q["paper_number"],
             "key": key.get(q["paper_number"], ""), "prompt": q["prompt"]}
            for i, q in enumerate(asked, start=1)]
        # "NB You may use any letter more than once" is how a paper SAYS it,
        # and not every paper says it. Part 2's abilities are three, its
        # duties are four and its key answers two of them C -- a task that
        # cannot be sat under the rule the missing line would have set, and
        # one publishing refuses twice over ("4 questions and only 3 options",
        # "Question 10 is answered with a letter another question already
        # uses"). So the box and the key are asked as well as the rubric:
        # either is proof, and both are on the page rather than inferred.
        if kind not in ON_A_PICTURE:
            keys = [(one["key"] or "").strip().lower()
                    for one in out["questions"]]
            named = [one for one in keys if one]
            out["reuse"] = bool(said["reuse"]
                                or (box and len(asked) > len(box))
                                or len(named) != len(set(named)))
        return out

    seen: list[int] = []
    out["template"], numbers = renumbered(
        template_of(lines, used, seen, flow=kind == "flow_chart_completion"),
        seen)
    if box:
        # A boxed summary is matching whose items are gaps in a paragraph.
        # Same two fields, same names, as a matching group's -- see
        # `QuestionGroupConfig.options`.
        out["options"] = box
        out["word_limit"] = None
    out["questions"] = [
        {"number": inside, "paper_number": paper, "key": key.get(paper, "")}
        for paper, inside in sorted(numbers.items(), key=lambda p: p[1])]
    return out


def groups(items: list[dict], key: dict[int, str]) -> list[dict]:
    """Every group of one passage or part, in the order the paper asks them.

    A group is its rubric and EVERYTHING up to the next rubric, which is
    more than one block often enough to matter: Test 2's flow chart is two,
    the box of endings in one and the chart in the other, and its map is
    three -- rubric, picture, list of places.

    Which is also the whole of the picture rule. The map belongs to the
    group whose rubric it follows, because that is where the book prints it
    and where the page puts it. Nothing here looks at a filename: the site's
    own decoration is a picture module like any other, and a blocklist would
    hand a candidate a logo as a map the first time they changed it.
    """
    out: list[dict] = []
    pending: dict | None = None
    body: list[dict] = []
    picture: str | None = None

    def close() -> None:
        nonlocal pending, body, picture
        if pending is not None:
            if not body:
                raise SystemExit(f"nothing under {pending['text']!r}")
            out.append(group(rubric(pending["text"]), body, key, picture))
        pending, body, picture = None, [], None

    for item in items:
        if item["kind"] == "rubric":
            close()
            pending = item
            continue
        if pending is None:
            continue
        if item["kind"] == "picture":
            # Only the FIRST, and only before the questions start. A second
            # picture under one rubric is a page this has never seen, and
            # guessing which of the two is the map is how a wrong one gets
            # published.
            if picture is None and not body:
                picture = item["src"]
            continue
        body.append(item)
    close()
    return out


# --- the passage ---------------------------------------------------------

#: A margin letter, printed as its own paragraph between two of the
#: passage's. Up to N because a Cambridge passage runs to fourteen sections
#: and a bare "O" or "I" in the prose would otherwise be read as one.
MARGIN = re.compile(r"^[A-N]$")


def passage_of(block: Tag) -> dict:
    """The text of one reading passage, with the letters the book prints.

    Paragraphs between two margin letters belong to the letter above them --
    a "section" of a lettered passage is often two or three paragraphs, and
    Cambridge 21's Passage 2 has three such. They are joined with a blank
    line rather than kept apart, because the corpus stores one entry per
    LETTER: 191 passages and not one of them repeats a label, and a matching
    group's box is a list of letters that has to be able to name a row.
    """
    title = None
    subtitle = None
    paragraphs: list[dict] = []
    label: str | None = None
    for el in block.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p"],
                             recursive=False):
        text = flat(el)
        if not text:
            continue
        if el.name.startswith("h") and title is None:
            title = text
            continue
        if MARGIN.match(text):
            label = text
            paragraphs.append({"label": label, "text": ""})
            continue
        if not re.search(r"[A-Za-z0-9]", text):
            # A rule across the page, typed as a row of dashes above the
            # footnotes. Not a paragraph, and one word long in the word
            # count of a passage that is meant to run to nine hundred.
            continue
        if subtitle is None and not paragraphs and all_italic(el):
            # The standfirst, which this book sets in italics under the
            # title: "Mark Rowe investigates attempts to reintroduce elms".
            subtitle = text
            continue
        if paragraphs and paragraphs[-1]["label"] == label and label is not None:
            joined = paragraphs[-1]["text"]
            paragraphs[-1]["text"] = f"{joined}\n\n{text}" if joined else text
        else:
            paragraphs.append({"label": None, "text": text})
    if title is None:
        raise SystemExit("this passage has no title")
    letters = [p["label"] for p in paragraphs if p["label"]]
    if letters and letters != [chr(ord("A") + i) for i in range(len(letters))]:
        raise SystemExit(f"the passage is lettered {letters}, which has a hole "
                         "in it; a matching group would answer the wrong rows")
    return {"title": title, "subtitle": subtitle, "source": None,
            "paragraphs": paragraphs, "faults": []}


# --- the audioscript -----------------------------------------------------

#: "WOMAN:", "PHIL:", "TUTOR:" -- the label in the left column, bold and
#: followed by a colon.
SPEAKER = re.compile(r"^([A-Z][A-Z ’'.-]{1,24}):$")
#: "(Q7)", "(Q21/22)" -- printed against the line where the answer is given.
#: The same thing Cambridge prints down its margin, which is why it goes into
#: `marker` unchanged: `markers.py` already understands every way of writing
#: two numbers in one.
MARKER = re.compile(r"\(\s*(Q\s*\d+(?:\s*[/&,]\s*(?:Q\s*)?\d+)*)\s*\)", re.I)


def turns_of(block: Tag) -> list[dict]:
    """One part's audioscript, as the turns forced alignment is run against.

    Exactly the shape `read_audioscript.py` writes, because `align.py` and
    `build_questions.py` both read it and neither should have to know which
    of the two produced it.

    The marker and the underlined answer come off the markup rather than off
    a model's reading of a scan: the site underlines the answer and prints
    ``(Q7)`` after it, so both are exact here. That is the whole of what makes
    replay spans reachable on this path.
    """
    out: list[dict] = []
    for paragraph in block.find_all("p"):
        parts = marked_runs(paragraph)
        if not parts:
            continue
        speaker = None
        head = tidy(parts[0][0])
        if parts[0][1] and SPEAKER.match(head):
            speaker = SPEAKER.match(head).group(1)
            parts = parts[1:]

        def keep(said: str, marker: str | None, answers: list[str]) -> None:
            said = tidy(said)
            if not said:
                return
            out.append({
                # A part with no speaker labels is a lecture, which is normal
                # for Parts 2 and 4. The name is what the transcript prints
                # and nothing downstream requires one, so the previous
                # speaker is carried rather than invented.
                "speaker": speaker or (out[-1]["speaker"] if out else "SPEAKER"),
                "text": said,
                "marker": marker,
                "answer": " ".join(answers) or None,
            })

        # One paragraph is not one turn. The site prints its markers INLINE,
        # one immediately after each underlined answer, so Part 4's second
        # paragraph carries Q32, Q33, Q34 and Q35 in a single speech. Taking
        # the paragraph whole leaves three of the four unmarked and gives the
        # fourth a span 95 seconds long -- which is not "hear it again", it
        # is the paragraph played back.
        #
        # So the turn is broken at every marker, exactly as
        # `read_audioscript.py` asks the model to break it: each piece ends
        # at the marker it is answered by, and the tail after the last marker
        # is an unmarked turn of its own.
        said: list[str] = []
        answers: list[str] = []
        for text, _, underlined in parts:
            at = 0
            for found in MARKER.finditer(text):
                said.append(text[at:found.start()])
                # Nobody says "(Q7)". Left in the text it hands the aligner a
                # word that was never spoken, and the aligner has to spend
                # real audio on it.
                keep("".join(said),
                     tidy(found.group(1)).upper().replace(" ", ""), answers)
                said, answers = [], []
                at = found.end()
            rest = text[at:]
            said.append(rest)
            if underlined and rest.strip():
                answers.append(tidy(rest))
        keep("".join(said), None, answers)
    return out


# --- the recordings ------------------------------------------------------


def recordings(entry: Tag) -> list[str]:
    """The four part recordings, in the order the page plays them."""
    found = []
    for audio in entry.find_all("audio"):
        source = audio.get("src") or next(
            (s.get("src") for s in audio.find_all("source") if s.get("src")), None)
        if source:
            # WordPress's player appends a cache-buster; the file is the same
            # file and a query string in a filename is not one.
            found.append(source.split("?")[0])
    return found


def download(url: str, path: pathlib.Path, least: int = 0) -> None:
    """One file, once. ``least`` is the size below which it is not the file.

    A WordPress host that has lost a media file answers with its themed 404
    page and a 200, which writes twelve kilobytes of HTML into an .mp3 and is
    then somebody else's problem three stages later.
    """
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {url}", file=sys.stderr)
    data = ask(url, timeout=300)
    if len(data) < least:
        raise SystemExit(f"{url} came back {len(data)} bytes, under the "
                         f"{least} this file has to be")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


#: The eight bytes a PNG opens with, then the header chunk that carries its
#: size. Read here rather than with a library because there is none in this
#: venv and the importer measures the file itself anyway -- what goes in
#: `questions.json` beside the path is for a person reading it later.
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def png_size(data: bytes) -> tuple[int, int] | None:
    if not data.startswith(PNG_MAGIC) or data[12:16] != b"IHDR":
        return None
    return (int.from_bytes(data[16:20], "big"),
            int.from_bytes(data[20:24], "big"))


def take_picture(built: list[dict], work: pathlib.Path, source: str) -> int:
    """Download each labelling group's map, and say where it went.

    Written as ``image-group<N>.png`` beside the questions, which is exactly
    what `extract_image.py` leaves for a scanned book and exactly what
    `import_section` looks for -- the two paths find a picture in completely
    different ways and hand back the same file under the same name.

    A group whose rubric had no picture under it keeps none. That is a
    material `publish_blockers` refuses by name, which is the loud failure
    this should have.
    """
    found = 0
    for index, one in enumerate(built):
        if "picture_src" not in one:
            continue
        url = one.pop("picture_src")
        if not url:
            print(f"note: group {index} is a {one['type']} and no picture "
                  f"follows its rubric on {source}; it will not publish",
                  file=sys.stderr)
            continue
        path = work / f"image-group{index}.png"
        # 4 kB, not the recording's half a megabyte: a site plan of line art
        # compresses to about forty, and their 404 page is twelve.
        download(url, path, least=4_000)
        sized = png_size(path.read_bytes())
        one["picture"] = {"path": path.name, "source": url,
                          **({"width": sized[0], "height": sized[1]}
                             if sized else {})}
        found += 1
    return found


def probe(path: pathlib.Path) -> dict:
    """What the catalogue's `section` row has to say about a recording.

    libsndfile's header-only read, which is what `manifest.py` uses on the
    rest of the corpus -- so a row written here says the same things in the
    same units as the 200 rows written by the inventory. ffprobe was the
    first version of this and it is the wrong dependency twice over: the
    aligner reads these files through soundfile anyway, and the ffmpeg on
    this machine is a broken Homebrew install that cannot start at all.
    """
    info = sf.info(path)
    return {
        "duration_ms": int(round(info.duration * 1000)),
        "container": info.format.upper(),
        "sample_rate": info.samplerate,
        "channels": info.channels,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


# --- the catalogue -------------------------------------------------------

BOOK_NOTE = ("read from ieltstrainingonline.com rather than from a PDF: the "
             "passages, the questions, the key and the audioscript are all "
             "text on the page, so no page of this book has been through a "
             "vision model. Catalogued as 'cambridge' because its audioscript "
             "numbers its answers, which is the only thing `kind` is read for")


def register_book(conn: sqlite3.Connection, number: int) -> None:
    conn.execute(
        "INSERT INTO book (number, title, kind, has_audioscript, note) "
        "VALUES (?, ?, 'cambridge', 1, ?) ON CONFLICT(number) DO NOTHING",
        (number, f"Cambridge IELTS {number}", BOOK_NOTE))


def register_passage(conn: sqlite3.Connection, passage_id: str, book: int,
                     test: int, number: int, title: str, url: str) -> None:
    conn.execute(
        """INSERT INTO passage (id, book_number, test_no, passage_no,
                                document_id, pages, key_page, title,
                                located_by, note)
           VALUES (?, ?, ?, ?, NULL, NULL, NULL, ?, 'read', ?)
           ON CONFLICT(id) DO UPDATE SET title = excluded.title,
                                         note = excluded.note""",
        (passage_id, book, test, number, title, url))


def register_section(conn: sqlite3.Connection, section_id: str, book: int,
                     test: int, number: int, rel_path: str, probed: dict,
                     url: str) -> None:
    conn.execute(
        """INSERT INTO section (id, book_number, test_no, section_no,
                                document_id, rel_path, sha256, duration_ms,
                                container, sample_rate, channels, convention,
                                question_pages, key_page, script_pages,
                                question_source, has_audioscript, note)
           VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, 'HTML',
                   NULL, NULL, NULL, ?, 1, NULL)
           ON CONFLICT(id) DO UPDATE SET
               rel_path = excluded.rel_path, sha256 = excluded.sha256,
               duration_ms = excluded.duration_ms,
               sample_rate = excluded.sample_rate,
               channels = excluded.channels,
               question_source = excluded.question_source""",
        (section_id, book, test, number, rel_path, probed["sha256"],
         probed["duration_ms"], probed["container"], probed["sample_rate"],
         probed["channels"], url))
    # `run_pipeline.py` walks the stage table, and a section with no rows in
    # it is a section that run never visits.
    for name in ("audioscript", "align", "questions", "answer_key", "import"):
        conn.execute(
            "INSERT INTO stage (section_id, name, status) VALUES (?, ?, 'pending') "
            "ON CONFLICT(section_id, name) DO NOTHING", (section_id, name))


# --- the duplicate check -------------------------------------------------


def fingerprint(key: dict[int, str]) -> str:
    """A whole paper's answer key, as one string to compare with another's.

    Content and not a heading, which is the rule this page taught: its key is
    headed "Answer Cam 20 Listening Test 01" and is nothing of the kind.
    """
    said = "|".join(f"{n}={re.sub(r'[^a-z0-9]', '', key.get(n, '').lower())}"
                    for n in range(1, 41))
    return hashlib.sha256(said.encode()).hexdigest()[:16]


def keys_on_disk(path: pathlib.Path) -> dict[int, str]:
    """One item's answer key, by the number the paper prints."""
    try:
        held = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return {question["paper_number"]: question.get("key") or ""
            for one in held.get("groups", [])
            for question in one.get("questions", [])
            if question.get("paper_number")}


def corpus_keys(skip: list[str]) -> dict[str, str]:
    """Every already-read item's answer key, as a fingerprint.

    Built once for the whole run rather than per item: the corpus is 650
    directories, and reading all of them again for each of the seven things
    one page produces is four and a half thousand file reads to answer the
    same question seven times.
    """
    out = {}
    for path in sorted(WORK.glob("*/questions.src.json")):
        if path.parent.name in skip:
            continue
        key = keys_on_disk(path)
        # Fewer than ten answers is a group, not a paper, and two groups
        # of four true/false answers collide by chance often enough to be
        # useless as evidence.
        if len(key) >= 10:
            out[fingerprint(key)] = path.parent.name
    return out


def already_seeded(corpus: dict[str, str], key: dict[int, str]) -> str | None:
    """The item in the corpus whose key this one duplicates, if there is one.

    A page that turns out to hold a test already seeded is a page to report
    rather than to import: a second copy of Cambridge 20 Test 1 under a
    Cambridge 21 title is worse than no Cambridge 21 at all, because nothing
    downstream would ever notice.
    """
    return corpus.get(fingerprint(key)) if len(key) >= 10 else None


# --- putting a test together ---------------------------------------------


def write(path: pathlib.Path, payload, force: bool) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        return False
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return True


def source_note(url: str, kind: str) -> dict:
    return {"url": url, "read_by": "html", "kind": kind}


def do_reading(book: int, test: int, refetch: bool, force: bool,
               conn: sqlite3.Connection) -> list[str]:
    url = test_url("reading", book, test, refetch)
    entry = content(fetch(url, refetch))
    key = answer_key(entry)
    found = parts_of(entry, "READING PASSAGE")
    if len(found) != 3:
        raise SystemExit(f"{len(found)} reading passages on this page, not 3")

    written = []
    for one in found:
        passage_id = f"cam{book}-t{test}-p{one['number']}"
        items = one["items"]
        # The passage is the first body block after the heading; everything
        # from there on is the question paper. Found by POSITION rather than
        # by `list.index`, which compares the dicts -- and a dict holding a
        # BeautifulSoup Tag compares by the tag's markup, so two blocks that
        # happen to print the same thing are the same block to it.
        at = next((i for i, item in enumerate(items)
                   if item["kind"] == "body"), None)
        if at is None:
            raise SystemExit(f"{passage_id}: no passage text")
        passage = passage_of(items[at]["block"])
        built = groups(items[at + 1:], key)
        asked = sum(len(g["questions"]) for g in built)
        print(f"{passage_id:<14} {passage['title'][:44]:<46} "
              f"{len(passage['paragraphs'])} paragraphs, "
              f"{'lettered' if passage['paragraphs'][0]['label'] else 'unlettered'}, "
              f"{len(built)} groups, {asked} questions")
        work = WORK / passage_id
        work.mkdir(parents=True, exist_ok=True)
        take_picture(built, work, url)
        write(work / "passage.json", passage, force)
        write(work / "questions.src.json",
              {"source": source_note(url, "reading"), "problems": [],
               "groups": built}, force)
        register_passage(conn, passage_id, book, test, one["number"],
                         passage["title"], url)
        written.append(passage_id)
    return written


def do_listening(book: int, test: int, refetch: bool, force: bool,
                 conn: sqlite3.Connection) -> list[str]:
    url = test_url("listening", book, test, refetch)
    entry = content(fetch(url, refetch))
    key = answer_key(entry)
    found = parts_of(entry, "PART")
    if len(found) != 4:
        raise SystemExit(f"{len(found)} listening parts on this page, not 4")

    audio = recordings(entry)
    if len(audio) != 4:
        raise SystemExit(f"{len(audio)} recordings on this page, not 4")

    # The audioscript's address comes off the page rather than being built
    # from the test number: the link says "audioscripts-cam-21-..." while the
    # text beside it says "Audioscript Cam 20", and only one of the two is
    # something a machine wrote.
    script_url = next(
        (a["href"] for a in entry.find_all("a", href=True)
         if re.search(r"audioscripts?-cam", a["href"], re.I)), None)
    scripts = []
    if script_url:
        scripts = parts_of(content(fetch(script_url, refetch)), "PART")
    else:
        print("note: this page links to no audioscript, so no section of it "
              "will get replay spans", file=sys.stderr)

    written = []
    for index, one in enumerate(found):
        section_id = f"cam{book}-t{test}-s{one['number']}"
        built = groups(one["items"], key)
        asked = sum(len(g["questions"]) for g in built)

        rel_path = (f"Cambridge {book}/Test {test}/"
                    f"T{test}S{one['number']}.mp3")
        # Half a megabyte at the least: one of these is six minutes of
        # speech and nothing that small is.
        download(audio[index], MATERIALS / rel_path, least=500_000)
        probed = probe(MATERIALS / rel_path)
        register_section(conn, section_id, book, test, one["number"],
                         rel_path, probed, url)

        turns = []
        script = next((s for s in scripts if s["number"] == one["number"]), None)
        if script:
            body = next((i for i in script["items"] if i["kind"] == "body"), None)
            if body is not None:
                turns = turns_of(body["block"])

        marked = sum(1 for t in turns if t["marker"])
        work = WORK / section_id
        work.mkdir(parents=True, exist_ok=True)
        pictures = take_picture(built, work, url)
        write(work / "questions.src.json",
              {"source": source_note(url, "listening"), "problems": [],
               "groups": built}, force)
        if turns:
            write(work / "turns.json", turns, force)
        print(f"{section_id:<14} {probed['duration_ms'] / 60000:>4.1f} min, "
              f"{len(built)} groups, {asked} questions, "
              f"{len(turns)} turns, {marked} marked"
              + (f", {pictures} picture(s)" if pictures else ""))
        written.append(section_id)
    return written


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("book", type=int)
    ap.add_argument("test", type=int)
    ap.add_argument("--reading", action="store_true",
                    help="only the three passages")
    ap.add_argument("--listening", action="store_true",
                    help="only the four parts")
    ap.add_argument("--refetch", action="store_true",
                    help="ask their server again instead of reading the cache")
    ap.add_argument("--force", action="store_true",
                    help="rewrite work files that are already on disk")
    args = ap.parse_args()

    # `isolation_level=None` -- every statement commits as it runs. The
    # default holds a write transaction open from the first INSERT to the
    # last, and this run spends twenty minutes downloading between them: for
    # all of that, `build_questions.py` in another shell cannot record a
    # stage, and says so with "database is locked" after it has already
    # written the file. A registration is a fact as soon as it is made, and
    # is also what makes a run that stops halfway resumable.
    conn = sqlite3.connect(SEED / "catalogue.db", isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    register_book(conn, args.book)

    written: list[str] = []
    both = not (args.reading or args.listening)
    if args.reading or both:
        written += do_reading(args.book, args.test, args.refetch, args.force, conn)
    if args.listening or both:
        written += do_listening(args.book, args.test, args.refetch, args.force, conn)

    corpus = corpus_keys(written)
    for work_id in written:
        key = keys_on_disk(WORK / work_id / "questions.src.json")
        twin = already_seeded(corpus, key)
        if twin:
            print(f"\nSTOP  {work_id}'s answer key is {twin}'s, answer for "
                  "answer. This page holds a test the corpus already has; "
                  "importing it would put a second copy in under a new name.",
                  file=sys.stderr)
            return 1

    conn.close()
    print(f"\n{len(written)} item(s) written. Next: build_questions.py on each, "
          "align.py on the sections, then the importers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

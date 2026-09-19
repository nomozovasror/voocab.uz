"""Read a section's questions and answer key off the page with a vision model.

    seed/.venv/bin/python seed/read_questions.py cam11-t1-s1 --questions 7,8 --key 123

Writes `questions.src.json` -- the same file a person would write by hand, and
the same one `build_questions.py` then checks and expands. Which is the point
of the split: this stage is allowed to be wrong, and the next stage is where
being wrong is caught.

Pages are given as ZERO-BASED pdf indices, because the number printed on the
page is not the index of the page. Cambridge 11's printed page 10 is index 7.

Two calls, not one. The questions come off the question pages and the key off
the key page, and they are two independent readings of the same ten answers --
so when the number of gaps and the number of key lines disagree, something was
misread and the build step says so. Asking for both in one call would throw
that check away for the sake of one fewer request.
"""

import argparse
import json
import subprocess
import html
import pathlib
import re
import sqlite3
import sys

import pymupdf

#: "11&12", "11-12", "11 and 12" -- how the key prints a question that takes
#: two of the paper's numbers. A "Choose TWO letters" is ONE question worth two
#: marks (see question_marks() in the backend), so the pair is not two entries
#: with one letter each; it is one entry with both.
#: "11&12", "11 and 12", "11-12" -- and "11/12", which is how IELTS Trainer 2
#: prints every pair it has.
PAIRED_KEY = re.compile(r"^\s*(\d+)\s*(?:&|and|[-–—/])\s*(\d+)\s*$")

import vision

SEED = pathlib.Path(__file__).resolve().parent
REPO = SEED.parent
MATERIALS = REPO / "Materials"
WORK = SEED / "work"

#: An IELTS listening paper numbers straight through: section 1 is questions
#: 1-10, section 2 is 11-20, and so on. Fixed by the exam, not by the book.
def paper_range(section_no: int) -> tuple[int, int]:
    return (section_no - 1) * 10 + 1, section_no * 10


QUESTION_PROMPT = """\
These images are consecutive pages of one section of a Cambridge IELTS \
Listening paper. Read the questions numbered {first} to {last}.

Return ONE JSON object, no prose and no code fence, shaped EXACTLY like this:

{{"groups": [ <one object per group, as described below> ]}}

The list is always there, even for a single group. A section may hold more \
than one -- "Questions 11-14" then "Questions 15-20" are two groups, in the \
order printed.

TWO GROUPS IN A ROW OFTEN CARRY THE SAME INSTRUCTION LINE. "Questions 11 and \
12: Choose TWO letters, A-E" followed by "Questions 13 and 14: Choose TWO \
letters, A-E" is two groups asking two different things, not one group \
repeated. What separates them is the numbers, never the wording. Return one \
object for each, and account for every number from {first} to {last}.

Every group has these fields:

  "type": one of the names below
  "instructions": the italic lines above the task, verbatim, newline-separated
  "word_limit": max words per answer as a number, or null

and then a shape that depends on which KIND of task it is. There are three.

**A) GAP-FILL** -- form_completion, note_completion, table_completion, \
sentence_completion, summary_completion, short_answer, flow_chart_completion. \
The candidate writes words into blanks:

  "template": "<the task, in the layout grammar below>",
  "questions": [{{"number": <1-based within this group>, "paper_number": <as printed>}}]

**B) MULTIPLE CHOICE** -- "Choose the correct letter, A, B or C". Each question \
has its own stem and its own options. There is NO template:

  "pick": <how many letters the candidate chooses, usually 1, or 2 for "Choose TWO letters">,
  "questions": [{{"number": 1, "paper_number": 21,
                 "prompt": "<the question stem, without the number>",
                 "options": ["<A's text>", "<B's text>", "<C's text>"]}}]

**C) MATCHING** -- a lettered box of options printed once above a list of \
items, each answered with a letter. Also NO template:

  "options": ["<A's text>", "<B's text>", ...],
  "reuse": <true if it says a letter may be used more than once, else false>,
  "questions": [{{"number": 1, "paper_number": 21, "prompt": "<the item, without the number>"}}]

map_labelling and diagram_labelling are answered on a PICTURE -- a map, a \
plan or a labelled drawing. Their instructions say "Label the map below", \
"Label the plan below" or "Label the diagram below". Name the type \
map_labelling or diagram_labelling, NEVER "matching", even when the task \
looks like one: a lettered box above a list of places is a map task if the \
letters are on a map. Give it whichever shape its answers take -- a lettered \
box is shape (C), blanks on the drawing are shape (A).

THE LAYOUT GRAMMAR for "template". Every line is one of:

  # Title                     the heading of the box
  ## Section heading          a bold sub-heading inside it
  - a bullet line             a bulleted line of the notes
  Label | value               a form row: label, bar, value
  + cell | cell | cell        a table row; the FIRST + line is the header row
  > step                      one box of a flow chart
  bare text                   a full-width line
  (blank)                     a blank line

THE LAYOUT GRAMMAR is only for shape (A). A gap is written {{{{N}}}} where N is \
the question's number WITHIN THIS GROUP, counting from 1. So a group covering \
questions 15-20 has gaps {{{{1}}}}..{{{{6}}}}. Multiple choice and matching have \
no template and no gap tokens at all -- their options go in the fields above.

TWO RULES THAT ARE EASY TO GET WRONG, both with examples.

1. The printed question number is NOT part of the template. The page prints \
the number next to the dotted line; the gap token replaces BOTH the number and \
the dots. The number is drawn separately.

     page:      the 1 ................. Room - seats 100
     correct:   - the {{{{1}}}} Room - seats 100
     WRONG:     - the 1 {{{{1}}}} Room - seats 100

2. A line must never BEGIN with + > or # unless you mean it to be a table row, \
a flow-chart step, or a heading, and must not contain | unless it is a \
labelled row. Book prose often begins with "+". Merge such a line into the one \
above it, where it belongs anyway.

     page:      Cost of Main Hall for Saturday evening: 2 £ ............
                + £250 deposit (3 ............ payment is required)
     correct:   - Cost of Main Hall for Saturday evening: £{{{{2}}}} + £250 \
deposit ({{{{3}}}} payment is required)
     WRONG:     - Cost of Main Hall for Saturday evening: £{{{{2}}}}
                + £250 deposit ({{{{3}}}} payment is required)

3. A BLANK WITH NO NUMBER BESIDE IT IS NOT A GAP. Only a numbered blank is \
one. IELTS Trainer prints "help is needed with 4 .......... and .........." -- \
one number, two blanks, one answer worth one mark. The second blank is part of \
the printed line, not question 5, and making it one shifts every gap after it \
onto the wrong answer.

     page:      help is needed with 4 .......... and ..........
     correct:   - help is needed with {{{{4}}}} and ..........
     WRONG:     - help is needed with {{{{4}}}} and {{{{5}}}}

   The Example's answer line is a blank with no number too, and is not a gap \
for the same reason.

Never put a gap in a table's header row -- it will not be drawn.

Transcribe the words exactly as printed. Ignore page headers, footers, page \
numbers, and any watermark (iyuce.com, "Edit by:", Chinese text) -- none of \
that is part of the task."""

#: A pair answered with letters -- "A, C" or "B/E" -- against one answered
#: with words. The label above them is the same "17&18 IN EITHER ORDER", and
#: they mean different things: one question worth two marks, or two questions.
PAIR_OF_LETTERS = re.compile(r"^[A-K](?:\s*[,/&;]\s*[A-K])*$", re.I)

#: A gap token in a template, the same shape `build_questions.py` reads.
GAP = re.compile(r"\{\{(\d+)\}\}")

#: How many pages past the one the catalogue names a key may run.
KEY_SPILL = 3
#: The most a key may run when it is read as text, where a page costs nothing
#: and the real bound is the next test's key.
KEY_PAGES = 12
#: Where one test's key ends: the next one's heading.
NEXT_TEST_KEY = re.compile(r"\bKEY\s+Test\s*(\d)", re.I)

KEY_TEXT_PROMPT = """\
Below is the extracted TEXT of the answer-key pages of an IELTS book -- the \
page the key for {label} starts on and the two after it, run together.

Find the answers to Listening questions {first} to {last} of that test, and \
nothing else.

Return ONE JSON object, no prose and no code fence:

{{"answers": {{"<number, or a pair like 11/12>": "<the answer EXACTLY as printed>"}}}}

Four things about these pages.

A PAIR is printed "11/12 A/B (in any order)". Return it under the pair, as \
"11/12", not under either number alone.

THE BOOK EXPLAINS EACH ANSWER on the same line as it -- "21 A Oliver suggests \
the introduction includes ...", "1 15(th) May / May 15(th) The woman explains \
that ...". The answer is only the part a candidate would write. Stop at it.

ITALIC PARAGRAPHS beginning "Distraction" are commentary between the answers, \
and the teaching exercises have their own numbered answers under headings like \
"Useful language: dates". Neither is the exam key.

A SECTION'S LAST FEW ANSWERS can be stranded at the top of the next page, \
above a heading about something else: "19 E 20 D Listening PART 3 Training ..." \
is questions 19 and 20 of PART 2.

TEXT
{text}"""

MISSING_KEY_PROMPT = """\
This image is the Listening answer key page of a Cambridge IELTS book.

Find the answers to questions {numbers} on it, and nothing else.

The page is TWO COLUMNS and these numbers are the ones a first reading could \
not find, so look where it would not have: the top of the RIGHT column, \
which continues from the bottom of the left one, and below any italic \
"Distraction" paragraph. The last few answers of a Listening section often \
sit in the corner of a page whose heading is about something else entirely, \
because the section before them ended there.

THE READING KEY IS ON THESE PAGES TOO, and it numbers its questions 1 to 40 \
just as the Listening key does. Take a number ONLY from the list that is the \
LISTENING key -- the one under a "LISTENING SECTION" heading, or running on \
from one on the page before. A list under "READING PASSAGE" is the wrong \
paper, however well its numbers match.

Return ONE JSON object, no prose and no code fence:

{{"answers": {{"<number>": "<the line EXACTLY as printed>"}}}}

Copy each line character for character, keeping every slash and parenthesis. \
Leave out any number you genuinely cannot see -- an invented answer is worse \
than a missing one."""

KEY_PROMPT = """\
This image is the Listening answer key page of a Cambridge IELTS book. Read \
ONLY the answers for {label}, questions {first} to {last}.

THE PAGE IS TWO COLUMNS. The left one runs top to bottom and the right one \
continues from it, so a test's forty answers can start on the left and finish \
on the right. Look down BOTH before deciding a number is not printed: missing \
the last few answers of a section is what happens when only one column is \
read.

ANSWERS ARE THE BOLD LINES. Between them sit italic paragraphs beginning \
"Distraction", explaining what the recording said to mislead the candidate. \
Those are commentary. They are not answers and they do not carry numbers.

SOME BOOKS EXPLAIN THE ANSWER ON THE SAME LINE AS IT. IELTS Trainer 2 prints

    21 A Oliver suggests the introduction includes something on which ...
    1 15(th) May / May 15(th) The woman explains that the film must be ...

The answer is only the part a candidate would write -- "A", and \
"15(th) May / May 15(th)". Everything after it is the book talking to the \
reader. Stop at it. Returning the whole line gives a question whose only \
accepted answer is a paragraph of English prose.

The page may also carry MORE THAN ONE numbered list. IELTS Trainer prints the \
answers to its teaching exercises down the left -- "Useful language: dates \
1 21(st) September, 2 1(st) February 1986" -- and the exam questions under \
"Exam practice". Only the exam practice list is the answer key. If no list on \
this page is the one asked for, return {{"answers": {{}}}} rather than the \
nearest thing to it.

Return EVERY number from {first} to {last} that is printed. A number you \
cannot find is better left out than guessed at, but do not leave one out \
because its line looked like the paragraph above it.

Return ONE JSON object, no prose and no code fence:

{{"answers": {{"<paper number>": "<the line EXACTLY as printed>"}}}}

Copy each line character for character, keeping every slash, parenthesis, and \
alternative. "(£)115 / a hundred (and) fifteen" must come back exactly like \
that -- do NOT expand, simplify, or choose between alternatives. Expanding \
them is another program's job and it needs the printed form to do it.

ONE LAYOUT TO WATCH FOR. Where a question takes two of the paper's numbers, \
the key prints the pair, then the words IN EITHER ORDER, and then the two \
letters on the lines BELOW it, indented:

    11&12   IN EITHER ORDER
            A
            C
    13      health problems

Those two letters are the answer. Return them together under the pair and drop \
the note:

    {{"11&12": "A, C", "13": "health problems"}}

Returning {{"11&12": "IN EITHER ORDER"}} loses the answer entirely."""


#: "Label the map below", "Label the plan below", "Label the diagram below" --
#: the one thing these tasks all say, and the one thing they all need. A map
#: task with a lettered box above it looks exactly like a matching task, and
#: two of IELTS Trainer's four came back named that way; the difference is
#: that a matching task can be published and a map task without its picture
#: cannot be answered at all.
LABELLING = re.compile(r"\blabel\s+the\s+(map|plan|diagram)\b", re.I)
#: "Complete the flow-chart below." A flow-chart with a lettered box above it
#: looks exactly like a matching task too, and four of the corpus's came back
#: named that way -- which loses the chart: its boxes and arrows live in the
#: template, and a matching group has none, so the learner is shown a bare
#: list of sentences with "{{1}}" still printed in them.
FLOW_CHART = re.compile(r"\bcomplete\s+the\s+flow[\s-]?chart\b", re.I)


def labelling(group: dict) -> str | None:
    """The type a group's own instructions say it is, where they say so."""
    instructions = group.get("instructions") or ""
    if FLOW_CHART.search(instructions):
        return "flow_chart_completion"
    said = LABELLING.search(instructions)
    if not said:
        return None
    return "diagram_labelling" if said.group(1).lower() == "diagram" else "map_labelling"


def repair(template: str, questions: list[dict]) -> tuple[str, list[str]]:
    """Two things the model gets wrong that a rule can fix without guessing.

    Both were still there after the prompt gained a worked example for each,
    which is the argument for fixing them here: the model transcribes what it
    sees line by line, and "merge this line into the one above" is not what
    the page looks like.

    1. **A lone `+` line is prose, not a table.** A table needs a header row
       and a body row, so a `+` line with no `+` neighbour cannot be one -- and
       as a one-row table it would be all header, where gaps are not drawn at
       all. The book prints "+ £250 deposit" as a continuation, so that is
       what it becomes.
    2. **The printed question number is not part of the template.** Only
       removed where the digits match that gap's own paper number, so a number
       that is part of the sentence ("seats 100") is never touched.
    """
    notes: list[str] = []

    # 0. A `+` in the middle of a line starts a row there. The reading runs a
    #    row's last cell together with the next row's first -- "Free {{3}} with
    #    every living room set + {{4}} And Oliver | Mid-range prices" is the end
    #    of one restaurant and the start of the next. Split only where what
    #    follows looks like a row (it has a cell bar), so a "+" that is really
    #    arithmetic stays where it is.
    split: list[str] = []
    #: Lines this rule created. Rule 1 below turns a `+` line with no `+`
    #: neighbour back into prose, and these have none -- the continuation they
    #: were cut from sits between them and the row above. Undoing the split
    #: immediately is what happened, so they are named and left alone.
    rows: set[int] = set()
    for line in template.split("\n"):
        head, sep, tail = line.partition(" + ")
        if sep and "|" in tail and not head.lstrip().startswith("#"):
            split.append(head.rstrip())
            rows.add(len(split))
            split.append("+ " + tail.lstrip())
            notes.append(f"split a row that ran into the next: {tail.strip()[:44]!r}")
        else:
            split.append(line)
    template = "\n".join(split)

    # 0b. A bare line inside a table is that row's next line, not prose. The
    #     page prints a company, then two or three lines of notes under it,
    #     then the next company; the reading gives the notes as plain lines,
    #     which end the run of `+` rows -- and the row after them becomes a new
    #     table's HEADER, where a gap is never drawn. Cambridge 20 lost seven
    #     of its ten that way.
    #
    #     A bar with nothing before it continues the row above, so the notes
    #     fill the rightmost cells: one bar in the line means it carries the
    #     last two columns, none means the last one. Which column a note
    #     belongs to is not printed anywhere, and the right-hand one is where
    #     these books put them.
    filled: list[str] = []
    columns = 0
    for line in template.split("\n"):
        bare = line.strip()
        if bare.startswith("+"):
            columns = columns or bare[1:].count("|") + 1
            filled.append(line)
            continue
        if columns and bare and not bare.startswith(("#", ">")):
            cells = bare.count("|") + 1
            if cells < columns:
                filled.append("+ " + "| " * (columns - cells) + bare)
                notes.append(f"a note under a table row was made part of it: "
                             f"{bare[:44]!r}")
                continue
        columns = 0 if not bare else columns
        filled.append(line)
    template = "\n".join(filled)

    # 0c. A gap in the FIRST table row means the table has no header.
    #
    #     The grammar reads the first `+` line as the header row and draws no
    #     gap in it -- which is right for a table that has one, and Cambridge
    #     15's nutmeg table does not: its first row is "Middle Ages | Nutmeg
    #     was brought to Europe by the {{1}}", data from the top. An empty
    #     header row above it costs nothing to draw and puts every row of the
    #     table back in the body.
    lines = template.split("\n")
    first = next((i for i, line in enumerate(lines)
                  if line.lstrip().startswith("+")), None)
    if first is not None and GAP.search(lines[first]):
        columns = lines[first].lstrip()[1:].count("|") + 1
        lines.insert(first, "+" + " |" * (columns - 1))
        notes.append("a table whose first row holds a gap was given an empty "
                     "header row")
        template = "\n".join(lines)

    lines = template.split("\n")
    out: list[str] = []
    for i, line in enumerate(lines):
        plus = line.lstrip().startswith("+")
        neighbour = any(
            lines[j].lstrip().startswith("+")
            for j in (i - 1, i + 1) if 0 <= j < len(lines))
        if plus and not neighbour and out and i not in rows:
            out[-1] = f"{out[-1].rstrip()} {line.lstrip()}"
            notes.append(f"merged a stray '+' line into the one above: {line.strip()[:52]!r}")
            continue
        out.append(line)

    # 3. A table's header row written as a heading. `# Name | Location | ...`
    #    above a run of `+` rows is that table's column names -- the model
    #    reads them as the block's title because on the page they are in bold
    #    above it. Left alone, the first BODY row becomes the header instead,
    #    and a header's gaps are never drawn: Cambridge 20's Test 1 lost gap 1
    #    that way. Only converted when the cell counts agree, which is what
    #    makes it a header rather than a coincidence.
    for i, line in enumerate(out[:-1]):
        head = line.lstrip()
        below = out[i + 1].lstrip()
        if not (head.startswith("# ") and below.startswith("+ ")):
            continue
        cells = head[2:].count("|")
        if cells and cells == below[2:].count("|"):
            out[i] = "+ " + head[2:]
            notes.append(f"a table's header row was written as a heading: "
                         f"{head[:52]!r}")

    template = "\n".join(out)

    for q in questions:
        paper, number = q.get("paper_number"), q.get("number")
        if paper is None or number is None:
            continue
        pattern = re.compile(rf"\b{paper}\s+(?=[£$€]?\{{\{{{number}\}}\}})")
        template, n = pattern.subn("", template)
        if n:
            notes.append(f"removed the printed number {paper} in front of gap {number}")
    return template, notes


def web_text(url: str) -> str:
    """A page's visible text, scripts included.

    These sites render the paper from JavaScript string literals, so stripping
    `<script>` first -- the obvious thing -- throws the questions away and
    leaves a page of navigation. The escapes are undone before the tags are,
    which turns those literals back into the markup they hold.
    """
    out = subprocess.run(
        ["curl", "-sS", "-L", "--max-time", "60", "-A", "Mozilla/5.0", url],
        capture_output=True, text=True, timeout=90)
    if out.returncode != 0:
        raise SystemExit(f"could not fetch {url}: {out.stderr[:200]}")
    page = (out.stdout.replace("\\'", "'").replace('\\"', '"')
            .replace("\\n", "\n").replace("\\/", "/"))
    page = re.sub(r"<(script|style)\b.*?</\1>", " ", page, flags=re.S | re.I)
    page = re.sub(r"<br\s*/?>|</p>|</li>|</h[1-6]>|</div>|</tr>", "\n", page, flags=re.I)
    page = re.sub(r"</t[dh]>", " | ", page, flags=re.I)
    page = html.unescape(re.sub(r"<[^>]+>", " ", page))
    return "\n".join(" ".join(l.split()) for l in page.split("\n") if l.strip())


def key_answers(said) -> dict:
    """The key as a number -> printed answer mapping, however it came back.

    The prompt asks for an object keyed by question number and usually gets
    one. Once in a few hundred pages the same model answers with a list of
    {"number": .., "answer": ..} instead -- the same information, a shape the
    prompt did not ask for -- and `.items()` on it took a section down with
    `'list' object has no attribute 'get'`, which names neither the page nor
    the problem. Both shapes say the same thing, so both are read; anything
    else fails by name."""
    answers = said.get("answers") if isinstance(said, dict) else said
    if isinstance(answers, dict):
        return answers
    if isinstance(answers, list):
        out = {}
        for row in answers:
            if not isinstance(row, dict):
                continue
            label = row.get("number", row.get("question", row.get("label")))
            value = row.get("answer", row.get("key", row.get("value")))
            if label is not None and value is not None:
                out[label] = value
        if out:
            return out
    raise SystemExit(
        f"the answer key came back as {type(answers).__name__}, not a mapping "
        "of question number to answer")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("section_id")
    ap.add_argument("--questions",
                    help="comma-separated ZERO-BASED pdf page indices; defaults to "
                         "what locate_pages.py put in the catalogue")
    ap.add_argument("--key", type=int,
                    help="ZERO-BASED pdf page index of the listening answer key; "
                         "defaults to the catalogue")
    ap.add_argument("--model", default=vision.DEFAULT_MODEL)
    ap.add_argument("--key-text", action="store_true",
                    help="read the answer key off the page's text layer rather "
                         "than its picture -- for a book whose text has been "
                         "looked at (NOT Cambridge 17, whose layer is poisoned)")
    ap.add_argument("--web", metavar="URL",
                    help="read the questions from this page's text instead of "
                         "the PDF's images; the answer key still comes from the "
                         "book")
    args = ap.parse_args()

    conn = sqlite3.connect(SEED / "catalogue.db")
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT s.*, d.rel_path pdf FROM section s JOIN document d ON d.id = s.document_id "
        "WHERE s.id = ?", (args.section_id,)).fetchone()
    conn.close()
    if row is None:
        raise SystemExit(f"{args.section_id} is not in the catalogue")

    pdf = MATERIALS / row["pdf"]
    work = WORK / args.section_id
    # The flags are an override now, not the interface. locate_pages.py reads
    # the book and writes these down; passing them by hand is for a section it
    # got wrong.
    pages = ([int(p) for p in args.questions.split(",")] if args.questions
             else json.loads(row["question_pages"] or "null") or [])
    key_page = args.key if args.key is not None else row["key_page"]
    if not pages or key_page is None:
        raise SystemExit(
            f"{args.section_id}: no pages in the catalogue. Run "
            f"seed/locate_pages.py {row['book_number']} first, or pass "
            "--questions and --key.")
    first, last = paper_range(row["section_no"])

    if args.web:
        # The page as TEXT, where a text of it exists. A vision model reading a
        # re-typeset table is guessing at where the columns are -- Cambridge
        # 20's Test 1 came back as one run-on line and would not build. The
        # same table as characters has no such doubt.
        #
        # The ANSWERS still come off the book's own key page below. A third
        # party's page is used for the shape of the questions and never for
        # what the answers are, so the worst a wrong page can do is fail the
        # coverage check.
        page_text = web_text(args.web)
        print(f"reading questions {first}-{last} from {args.web} "
              f"({len(page_text.split())} words) with {args.model}")
        read = vision.ask_json(
            QUESTION_PROMPT.format(first=first, last=last)
            + "\n\nThe page, as text:\n\n" + page_text[:60000], [],
            model=args.model, max_tokens=8000)
    else:
        shots = vision.render(pdf, pages, work / "pages")
        print(f"reading questions {first}-{last} from {len(shots)} page(s) with {args.model}")
        read = vision.ask_json(
            QUESTION_PROMPT.format(first=first, last=last), shots, model=args.model)
    # Asked for {"groups": [...]}, it sometimes answers with the single group
    # itself. The content is right either way, so it is wrapped rather than
    # rejected -- a whole section is not worth losing to a missing bracket.
    if "groups" not in read and read.get("questions"):
        read = {"groups": [read]}

    def read_key_text() -> dict:
        """The key, off the page's own text layer rather than its picture.

        For a book whose text has been looked at this is both cheaper and
        better. Trainer 2's key pages are dense two-column prose with the
        answers threaded through it, and read as pictures they lost a
        section's last two answers every time -- "19 E 20 D" sits at the top
        of the page AFTER the one the key starts on, above a heading for a
        different part, and four separate askings walked past it. The text has
        no columns to lose and no heading to be misled by.
        """
        # Up to where the NEXT test's key begins, not a fixed number of pages.
        # A test's key is as long as it is: Trainer 2 gives test 2 five pages
        # and the fixed three stopped one short of the page carrying its Part
        # 4 answers, so the model answered from another part's list -- ten
        # words about a forest against a recording about a 19th-century
        # engineer. Bounded anyway, because a missing boundary should cost a
        # few pages of text and not the rest of the book.
        def whose(text: str) -> int | None:
            """Which test's key this page is, by the LAST marker on it.

            Not the first, and not merely the presence of one: Trainer 2
            prints a rotated tab down the edge of every key page and
            extraction flattens it into the text, so "KEY Test 1 st 1 Te Tes T
            KEY Test 4" is page 214 -- test 4's. A boundary that fired on any
            "KEY Test" at all stopped after a single page.
            """
            found = None
            for found in NEXT_TEST_KEY.finditer(text):
                pass
            return int(found.group(1)) if found else None

        with pymupdf.open(pdf) as doc:
            pages, mine = [], None
            for index in range(key_page, min(key_page + KEY_PAGES, doc.page_count)):
                text = " ".join(doc[index].get_text().split())
                named = whose(text)
                if index == key_page:
                    mine = named
                elif mine is not None and named is not None and named != mine:
                    break
                pages.append(text)
        whole = "\n\n".join(pages)
        # Aimed at this section's own range rather than truncated from the
        # start. Twelve pages of key is more text than a request should carry,
        # and cutting the first 12,000 characters of it cut Test 2's
        # "Questions 31-40" out entirely -- it begins at 14,540. Asked for
        # answers it had not been shown, the model invented ten: a list of
        # words about a forest, against a recording about a 19th-century
        # engineer, none of them anywhere in the book.
        window = re.search(rf"Questions\s*{first}\s*[-–—]\s*{last}", whole)
        text = (whole[max(0, window.start() - 200):window.start() + 8000]
                if window else whole[:12000])
        print(f"reading the answer key from the text of pages "
              f"{key_page}-{key_page + len(pages) - 1}"
              f"{', aimed at Questions %d-%d' % (first, last) if window else ''}")
        said = key_answers(vision.ask_json(
            KEY_TEXT_PROMPT.format(
                label=f"Test {row['test_no']}, Section {row['section_no']}",
                first=first, last=last, text=text),
            [], model=args.model))
        # An answer that is not in the text it was read from was not read.
        # This is the one route where that can be checked -- the source is
        # right here -- and it is worth checking, because the failure it
        # catches is silent: ten plausible words, correctly formatted, for a
        # recording that never says any of them.
        flat = re.sub(r"[^a-z0-9 ]", " ", text.lower())
        invented = {label: value for label, value in said.items()
                    if not any(w in flat for w in
                               re.findall(r"[a-z]{4,}", str(value).lower()))
                    and re.search(r"[a-z]{4,}", str(value).lower())}
        for label in invented:
            print(f"  key {label} = {invented[label]!r} is not on the page it was "
                  "read from; dropped", file=sys.stderr)
            said.pop(label)
        return said

    def read_key(index: int, only: list[int] | None = None) -> dict:
        shot = vision.render(pdf, [index], work / "pages")
        prompt = KEY_PROMPT.format(
            label=f"Test {row['test_no']}, Section {row['section_no']}",
            first=first, last=last)
        if only:
            print(f"asking page index {index} again for only "
                  f"{', '.join(str(n) for n in only)}")
            prompt = MISSING_KEY_PROMPT.format(
                numbers=", ".join(str(n) for n in only))
        else:
            print(f"reading the answer key from page index {index}")
        return key_answers(vision.ask_json(prompt, shot, model=args.model))

    printed = read_key_text() if args.key_text else read_key(key_page)
    # Forty answers do not always fit on one sheet. Where the numbers this
    # section needs are not all on the page the catalogue names, the key ran
    # over onto the next one -- Cambridge 20 splits its listening key at
    # question 10, and the sections after that would otherwise come back with
    # no answers at all and no explanation. Asked for only when short, so a
    # book whose key fits pays nothing for the possibility that it might not.
    def short_of(n: int) -> bool:
        """Is this number missing -- counting a pair line as covering both?"""
        return n not in printed and not any(
            PAIRED_KEY.match(str(k)) and
            n in range(int(PAIRED_KEY.match(str(k)).group(1)),
                       int(PAIRED_KEY.match(str(k)).group(2)) + 1)
            for k in printed)

    def short() -> bool:
        return any(short_of(n) for n in range(first, last + 1))

    def absent() -> list[int]:
        return [n for n in range(first, last + 1) if short_of(n)]

    # The SAME page again, asked only for what is missing, before looking at
    # the next one. These keys are two columns and a section's answers can
    # start at the bottom of the left and finish at the top of the right --
    # Test 6's questions 11 to 16 are on one side of the fold and 17 to 20 on
    # the other -- and a reading that stops at the column break loses the tail
    # of a section while looking complete. Telling the prompt about the
    # columns helped and did not fix it; naming the four numbers does, which
    # is the same lesson as everywhere else here: a narrow question gets a
    # reliable answer.
    if short():
        printed = {**read_key(key_page, only=absent()), **printed}

    # Forward a page at a time while numbers are still missing. One page of
    # spill covers Cambridge, whose forty listening answers run over a fold at
    # most; IELTS Trainer prints its key ten questions to a column and puts
    # the Reading key, the Writing notes and the Speaking notes between one
    # test's listening sections and the next, so Section 4's answers can be
    # three sheets past the page the catalogue names. Bounded, and it stops as
    # soon as nothing is missing -- a book whose key fits pays for none of it.
    for ahead in range(1, KEY_SPILL + 1):
        if not short():
            break
        # Narrow, like the re-ask above and for the same reason. A whole-page
        # question asked of a spill page gets nothing: Test 5's questions 38
        # to 40 sit in the top corner of a sheet headed "READING PASSAGE 1",
        # and a reader told to find the Listening key for Section 4 on that
        # page reasonably answers that there is none.
        spill = read_key(key_page + ahead, only=absent())
        # The earlier page wins where both name a number: it is the one the
        # catalogue vouched for, and the later one may be another paper's.
        printed = {**spill, **printed}

    # A key line can be labelled for two numbers at once. int() on "11&12"
    # raised, which took eighteen sections down in the first full batch.
    answers: dict[int, str] = {}
    paired: dict[int, int] = {}          # second number -> first
    for label, value in printed.items():
        label = str(label)
        # A key line copied with its own number in front of it: asked for
        # question 20 on a page whose layout it had already been wrong about,
        # a reader answered {"20": "20 B"}, and "20 B" is not a letter. The
        # number is a label, not part of the answer, and it only ever appears
        # here because it is printed immediately to the left of the answer.
        value = re.sub(rf"^\s*{re.escape(label)}\s+", "", str(value))
        # A value that opens with its OWN pair label: {"13": "13/14 B/C (in
        # any order)"} is the line "13/14 B/C", read with only the first
        # number as the label. The pair is printed right there in the value,
        # so it is taken from it rather than guessed at -- and without it the
        # group asks one question where the paper asks two.
        moved = re.match(r"\s*(\d+)\s*[/&–-]\s*(\d+)\s+(\S.*)$", str(value))
        if moved and moved.group(1) == label.strip():
            label = f"{moved.group(1)}&{moved.group(2)}"
            value = moved.group(3)
        pair = PAIRED_KEY.match(label)
        if pair and not PAIR_OF_LETTERS.match(value.strip()):
            # A pair of WORDS is two blanks on the paper -- "37&38 IN EITHER
            # ORDER ships; horses" is a short-answer question the candidate
            # writes a word into twice, and either word is right in either
            # blank. Folding it the way a "choose TWO letters" is folded loses
            # question 38 entirely, which the build says out loud: "after
            # dropping, questions [38, 40] are missing".
            #
            # Told apart by the ANSWER, not by the group: a pick-two is
            # answered with letters and this is answered with words, and the
            # label looks identical either way.
            head, tail = int(pair.group(1)), int(pair.group(2))
            answers[head] = answers[tail] = value
            continue
        if pair:
            # NOT `first, second` -- that shadowed the section's own first
            # paper number and made the coverage check expect "29-30" for a
            # whole section, failing nineteen of them.
            head, tail = int(pair.group(1)), int(pair.group(2))
            answers[head] = value
            paired[tail] = head
            continue
        try:
            answers[int(str(label).strip())] = value
        except ValueError:
            print(f"  cannot read the key label {label!r}", file=sys.stderr)

    # The two readings are independent, so a disagreement is a misread page
    # rather than a quirk of one prompt. Reported, not silently patched.
    # Where the key pairs two numbers, the second one is not a question of its
    # own -- it is the second mark of the first. Drop any the reader emitted
    # for it, so the group's numbering stays 1..N with no hole.
    for group in read.get("groups", []):
        kept = [q for q in group.get("questions", [])
                if q.get("paper_number") not in paired]
        if len(kept) != len(group.get("questions", [])):
            for number, q in enumerate(kept, start=1):
                q["number"] = number
            group["questions"] = kept

    # A page can carry the tail of one part and the head of the next -- book
    # 15's test 1 prints questions 29-30 on the same sheet as 31-40 -- so a
    # section's pages are not exclusively its own, and reading them returns
    # the neighbour's questions too. Anything outside this section's numbers
    # belongs to the section that asked for it, not to this one.
    dropped = 0
    for group in read.get("groups", []) if isinstance(read, dict) else []:
        kept = [q for q in group.get("questions", [])
                if first <= (q.get("paper_number") or 0) <= last]
        dropped += len(group.get("questions", [])) - len(kept)
        group["questions"] = kept
    if isinstance(read, dict):
        read["groups"] = [g for g in read.get("groups", []) if g.get("questions")]
    if dropped:
        print(f"  {dropped} question(s) on these pages belong to another part, dropped")

    problems = []
    numbered = [q for g in read.get("groups", []) for q in g.get("questions", [])]
    papers = sorted(q.get("paper_number") for q in numbered)
    # `paired` is read off the whole key page, so it carries the pairs of every
    # part on it -- "33&34" from part 4 made a part 3 section look as though it
    # covered question 34. Only this section's own numbers count, on the same
    # reasoning that drops a neighbour's questions above.
    covered = sorted({n for n in set(papers) | set(paired) if first <= n <= last})
    if covered != list(range(first, last + 1)):
        problems.append(f"questions cover {covered}, expected {first}-{last}")
    # A pick-2 question answers two numbers with one key line, so the second
    # of the pair has no entry of its own and is not missing. `paired` covers
    # the pairs the key labelled "23&24"; this covers the ones it listed
    # singly, which is the same fold the groups get below.
    spanned = set()
    for group in read.get("groups", []) if isinstance(read, dict) else []:
        span = group.get("pick") or 1
        for question in group.get("questions", []):
            start = question.get("paper_number")
            if span > 1 and start is not None and answers.get(start):
                spanned.update(range(start + 1, start + span))
    missing = [n for n in range(first, last + 1)
               if n not in answers and n not in paired and n not in spanned]
    if missing:
        problems.append(f"the key is missing {missing}")

    groups = []
    for group in read.get("groups", []):
        questions = group.get("questions", [])
        # A "choose TWO letters" is ONE question over two of the paper's
        # numbers. The key usually says so by labelling the line "23&24", and
        # `paired` above handles that. Where it instead lists 23 and leaves 24
        # blank, the reading gives two questions and the second has no answer
        # -- which fails as "the key line was '' with no letters" and names
        # neither the pair nor the group. Folded here, where what the group
        # asks for is known.
        span = group.get("pick") or 1
        if span > 1 and len(questions) > 1:
            kept, skip = [], set()
            for i, q in enumerate(questions):
                number = q.get("paper_number")
                if number in skip:
                    continue
                if not answers.get(number):
                    kept.append(q)
                    continue
                kept.append(q)
                skip.update(range(number + 1, number + span))
            if len(kept) != len(questions):
                print(f"  {len(questions) - len(kept)} question(s) folded into "
                      f"the pick-{span} question they share a mark with")
                questions = kept
        template, notes = repair(group.get("template", ""), questions)
        for note in notes:
            print(f"  repaired: {note}")
        out = {
            "type": labelling(group) or group.get("type"),
            "instructions": group.get("instructions", ""),
            "word_limit": group.get("word_limit"),
            "template": template,
            "questions": [
                {"number": q.get("number"), "paper_number": q.get("paper_number"),
                 "key": answers.get(q.get("paper_number"), ""),
                 "marker": f"Q{q.get('paper_number')}",
                 # Carried only where the type has them; a gap-fill question
                 # has neither and a matching item has no options of its own.
                 **({"prompt": q["prompt"]} if q.get("prompt") else {}),
                 **({"options": q["options"]} if q.get("options") else {})}
                for q in questions
            ],
        }
        if group.get("pick"):
            out["pick"] = group["pick"]
        if group.get("options"):
            out["options"] = group["options"]
            out["reuse"] = bool(group.get("reuse"))
        groups.append(out)

    out = work / "questions.src.json"
    out.write_text(json.dumps({
        "source": {"question_page_indices": pages, "key_page_index": key_page,
                   "model": args.model, "read_by": "vision"},
        "groups": groups}, indent=2, ensure_ascii=False))

    for group in groups:
        print(f"  {group['type']}: {len(group['questions'])} questions, "
              f"word_limit={group['word_limit']}")
    for p in problems:
        print(f"PROBLEM  {p}", file=sys.stderr)

    # Written into the catalogue, not only into the file beside the work, so
    # "which sections did not come off the book's own pages" is one query
    # rather than a grep over a hundred and seventy directories. Its own
    # connection: the one opened at the top is closed as soon as the section
    # row is read, which is right -- a reading takes minutes and holding a
    # write lock across it would block every other section in a batch.
    with sqlite3.connect(SEED / "catalogue.db") as catalogue:
        catalogue.execute("UPDATE section SET question_source = ? WHERE id = ?",
                          (args.web, args.section_id))

    print(f"\nwrote {out.relative_to(REPO)} -- now run build_questions.py, "
          "which is where a misread page is caught")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

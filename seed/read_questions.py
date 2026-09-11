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

#: "11&12", "11-12", "11 and 12" -- how the key prints a question that takes
#: two of the paper's numbers. A "Choose TWO letters" is ONE question worth two
#: marks (see question_marks() in the backend), so the pair is not two entries
#: with one letter each; it is one entry with both.
PAIRED_KEY = re.compile(r"^\s*(\d+)\s*(?:&|and|[-–—])\s*(\d+)\s*$")

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

map_labelling and diagram_labelling are answered on a picture. If you meet \
one, still name the type, and use shape (A).

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

Never put a gap in a table's header row -- it will not be drawn.

Transcribe the words exactly as printed. Ignore page headers, footers, page \
numbers, and any watermark (iyuce.com, "Edit by:", Chinese text) -- none of \
that is part of the task."""

#: How many pages past the one the catalogue names a key may run.
KEY_SPILL = 3

KEY_PROMPT = """\
This image is the Listening answer key page of a Cambridge IELTS book. Read \
ONLY the answers for {label}, questions {first} to {last}.

The page may carry MORE THAN ONE numbered list. IELTS Trainer prints the \
answers to its teaching exercises down the left -- "Useful language: dates \
1 21(st) September, 2 1(st) February 1986" -- and the exam questions on the \
right under "Exam practice". Only the exam practice list is the answer key. \
If no list on this page is the one asked for, return {{"answers": {{}}}} \
rather than the nearest thing to it.

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

    def read_key(index: int) -> dict:
        shot = vision.render(pdf, [index], work / "pages")
        print(f"reading the answer key from page index {index}")
        return key_answers(vision.ask_json(
            KEY_PROMPT.format(
                label=f"Test {row['test_no']}, Section {row['section_no']}",
                first=first, last=last),
            shot, model=args.model))

    printed = read_key(key_page)
    # Forty answers do not always fit on one sheet. Where the numbers this
    # section needs are not all on the page the catalogue names, the key ran
    # over onto the next one -- Cambridge 20 splits its listening key at
    # question 10, and the sections after that would otherwise come back with
    # no answers at all and no explanation. Asked for only when short, so a
    # book whose key fits pays nothing for the possibility that it might not.
    def short() -> bool:
        return any(n not in printed and
                   not any(PAIRED_KEY.match(str(k)) and
                           n in range(int(PAIRED_KEY.match(str(k)).group(1)),
                                      int(PAIRED_KEY.match(str(k)).group(2)) + 1)
                           for k in printed)
                   for n in range(first, last + 1))

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
        spill = read_key(key_page + ahead)
        # The earlier page wins where both name a number: it is the one the
        # catalogue vouched for, and the later one may be another paper's.
        printed = {**spill, **printed}

    # A key line can be labelled for two numbers at once. int() on "11&12"
    # raised, which took eighteen sections down in the first full batch.
    answers: dict[int, str] = {}
    paired: dict[int, int] = {}          # second number -> first
    for label, value in printed.items():
        label = str(label)
        pair = PAIRED_KEY.match(label)
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
            "type": group.get("type"),
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

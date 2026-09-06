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
order printed. Every group has these fields:

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

KEY_PROMPT = """\
This image is the Listening answer key page of a Cambridge IELTS book. Read \
ONLY the answers for {label}, questions {first} to {last}.

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
    lines = template.split("\n")
    out: list[str] = []
    for i, line in enumerate(lines):
        plus = line.lstrip().startswith("+")
        neighbour = any(
            lines[j].lstrip().startswith("+")
            for j in (i - 1, i + 1) if 0 <= j < len(lines))
        if plus and not neighbour and out:
            out[-1] = f"{out[-1].rstrip()} {line.lstrip()}"
            notes.append(f"merged a stray '+' line into the one above: {line.strip()[:52]!r}")
            continue
        out.append(line)
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

    shots = vision.render(pdf, pages, work / "pages")
    print(f"reading questions {first}-{last} from {len(shots)} page(s) with {args.model}")
    read = vision.ask_json(
        QUESTION_PROMPT.format(first=first, last=last), shots, model=args.model)
    # Asked for {"groups": [...]}, it sometimes answers with the single group
    # itself. The content is right either way, so it is wrapped rather than
    # rejected -- a whole section is not worth losing to a missing bracket.
    if "groups" not in read and read.get("questions"):
        read = {"groups": [read]}

    key_shot = vision.render(pdf, [key_page], work / "pages")
    print(f"reading the answer key from page index {key_page}")
    key = vision.ask_json(
        KEY_PROMPT.format(label=f"Test {row['test_no']}, Section {row['section_no']}",
                          first=first, last=last),
        key_shot, model=args.model)
    # A key line can be labelled for two numbers at once. int() on "11&12"
    # raised, which took eighteen sections down in the first full batch.
    answers: dict[int, str] = {}
    paired: dict[int, int] = {}          # second number -> first
    for label, value in key.get("answers", {}).items():
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

    problems = []
    numbered = [q for g in read.get("groups", []) for q in g.get("questions", [])]
    papers = sorted(q.get("paper_number") for q in numbered)
    covered = sorted(set(papers) | set(paired))
    if covered != list(range(first, last + 1)):
        problems.append(f"questions cover {covered}, expected {first}-{last}")
    missing = [n for n in range(first, last + 1)
               if n not in answers and n not in paired]
    if missing:
        problems.append(f"the key is missing {missing}")

    groups = []
    for group in read.get("groups", []):
        questions = group.get("questions", [])
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
    print(f"\nwrote {out.relative_to(REPO)} -- now run build_questions.py, "
          "which is where a misread page is caught")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

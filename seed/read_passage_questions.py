"""Read a located passage's questions and its answers off the page.

    seed/.venv/bin/python seed/read_passage_questions.py cam11-t1-p2
    seed/.venv/bin/python seed/read_passage_questions.py --book 11
    seed/.venv/bin/python seed/read_passage_questions.py --report

Writes `work/<passage id>/questions.src.json` -- the same file
`read_questions.py` writes for a listening section, in the same shape, so
`build_questions.py` checks and expands both.

Two calls, not one, and the same reason as the listening reader: the
questions come off the passage's own pages and the answers off the key at the
back of the book. They are two independent readings of the same thirteen
answers, so when the number of gaps and the number of key lines disagree,
something was misread and the build step says so.

## Reading asks four shapes where listening asks three

The gap-fill family, multiple choice and matching are the same tasks on both
papers and are described to the model in the same words. What reading adds is
a fourth: a list of statements answered TRUE/FALSE/NOT GIVEN or
YES/NO/NOT GIVEN, whose three options are a property of the TYPE and are
never stored -- `FIXED_CHOICE_OPTIONS` on the server says what they are.
Storing them would let two groups of one type disagree about their own words,
and, because a group with options in its config is a LETTERED group, would
switch grading to matching letters against the word "TRUE".

Matching gains variants rather than shapes. Matching headings is lettered
with ROMAN numerals because its items are the passage's lettered paragraphs,
and an answer of "C" that named both a heading and a paragraph would be two
questions at once. What the model returns is the box as printed; which
alphabet it is in is read off the box.

## The key is one sheet for two papers

These books print "Listening and Reading Answer Keys" on one sheet per test:
forty listening answers and then forty reading ones. Asking for the whole
sheet and slicing would be a second chance to confuse the two -- and that
confusion has already cost this pipeline a whole test, when Cambridge 14's
listening questions were answered from the reading key. So the prompt names
the paper, names the numbers, and the key is read once per TEST and cached,
rather than once per passage from the same sheet three times.
"""

import argparse
import json
import pathlib
import re
import sqlite3
import sys

import vision
from locate_passages import page_maps

SEED = pathlib.Path(__file__).resolve().parent
REPO = SEED.parent
MATERIALS = REPO / "Materials"
WORK = SEED / "work"

#: The same limit, and the same reason, as every other reader here: three
#: images a request is a COUNT rather than a size.
PAGES_PER_CALL = 3
QUESTION_DPI = 150

#: How many sheets past the one the key starts on it may run.
#:
#: Cambridge prints one sheet per test and the next test's key is two pages
#: away, so the real bound is that -- the next key page, below. This is only
#: the cap for a book that prints no next key: IELTS Trainer 2 runs test 1's
#: key over 183 to 190, listening first and the reading half four sheets in,
#: and at three the reading key was never in the window at all.
KEY_SPILL = 8

#: Who to ask when the first provider will not reproduce a page. The same
#: fallback, and the same reasoning, as `read_passages.FALLBACK`.
FALLBACK = "nvidia"

#: How many times a passage's questions may be read before the problems are
#: reported rather than chased. Two: the second read is worth making because
#: the answer key is evidence the first can be measured against, and a third
#: would be sampling until the check goes quiet, which is a different thing
#: from being right.
READS = 2

#: The two types whose options are their NAME. Named here as well as on the
#: server because this is where a group is first called one, and a group of
#: these that came back carrying options would be graded as letters.
FIXED_CHOICE = {"true_false_not_given", "yes_no_not_given"}

#: An answer to one of them, however the key prints it.
#: The numerals a heading box is numbered with, in order. Twelve is more
#: than any paper prints and the cost of the spare ones is nothing.
ROMAN = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi",
         "xii"]

FIXED_CHOICE_ANSWER = re.compile(
    r"^\s*(TRUE|FALSE|NOT\s*GIVEN|YES|NO|T|F|NG|Y|N)\s*$", re.I)

QUESTION_PROMPT = """\
These images are consecutive pages of an IELTS Academic Reading paper. Read \
the questions numbered {first} to {last}, which belong to Reading Passage \
{passage}.

Do NOT read the passage itself, and do not read a question outside \
{first}-{last} -- a page may carry the end of the passage before this one or \
the start of the next.

Return ONE JSON object, no prose and no code fence, shaped EXACTLY like this:

{{"groups": [ <one object per group, as described below> ]}}

The list is always there, even for a single group. A passage usually carries \
three or four groups -- "Questions 14-18" then "Questions 19-22" then \
"Questions 23-26" -- in the order printed. What separates two groups is the \
NUMBERS, never the wording: two groups in a row often carry the same \
instruction line.

**A GROUP'S NUMBERS ARE THE ONES PRINTED IMMEDIATELY ABOVE IT**, in the \
"Questions N-M" heading that introduces it, and they are repeated in its own \
"Write your answers in boxes N-M". Work down the page one heading at a time \
and give each task the numbers of the heading it is under. Do NOT assume the \
first task is the lowest-numbered one, and do NOT carry a heading's numbers \
past the task it introduces.

  page:      Questions 1-7   Complete the sentences below.  ... 1 Some food
             plants, including ......., are already grown indoors. ...
             Questions 8-13  Do the following statements agree ...?
             ... 8 Methods for predicting the Earth's population ...
  correct:   sentence_completion covering 1-7, then true_false_not_given
             covering 8-13
  WRONG:     true_false_not_given covering 1-7, then sentence_completion
             covering 8-13

The numbered lines under a heading carry their own numbers too -- "8 Methods \
for predicting ..." is question 8. If the number beside a line disagrees with \
the heading you have given it, the line is right and you are under the wrong \
heading.

Every group has these fields:

  "type": one of the names below
  "instructions": the italic lines above the task, verbatim, newline-separated
  "word_limit": max words per answer as a number, or null

and then a shape that depends on which KIND of task it is. There are four.

**A) GAP-FILL** -- summary_completion, sentence_completion, note_completion, \
table_completion, short_answer, flow_chart_completion, diagram_labelling. The \
candidate writes words into blanks:

  "template": "<the task, in the layout grammar below>",
  "questions": [{{"number": <1-based within this group>, "paper_number": <as printed>}}]

**B) MULTIPLE CHOICE** -- "Choose the correct letter, A, B, C or D". Each \
question has its own stem and its own options. There is NO template:

  "pick": <how many letters the candidate chooses, usually 1, or 2 for "Choose TWO letters">,
  "questions": [{{"number": 1, "paper_number": 27,
                 "prompt": "<the question stem, without the number>",
                 "options": ["<A's text>", "<B's text>", "<C's text>", "<D's text>"]}}]

**C) MATCHING** -- a lettered box of options printed once above a list of \
items, each answered with a letter. Four tasks have this shape, and the type \
is which one:

  * matching_headings -- "Choose the correct heading for each paragraph". The \
    BOX is a list of headings numbered i, ii, iii (roman numerals) and the \
    ITEMS are the passage's paragraphs A, B, C.
  * matching_information -- "Which paragraph contains the following \
    information?". The box is the paragraph letters.
  * matching_features -- "Match each statement with the correct person/study".
  * matching_sentence_endings -- "Complete each sentence with the correct \
    ending, A-F".

  "options": ["<the FIRST option's text, without its letter or numeral>", ...],
  "label_style": "letters" or "roman" -- which the BOX is numbered with,
  "reuse": <true if it says an option may be used more than once, else false>,
  "questions": [{{"number": 1, "paper_number": 14, "prompt": "<the item, without the number>"}}]

**D) TRUE/FALSE/NOT GIVEN** -- "Do the following statements agree with the \
information in the passage?" (type true_false_not_given) or "... agree with \
the views of the writer?" (type yes_no_not_given). A list of statements, each \
answered with one of three fixed words. There is NO template and NO options \
list -- the three words are the type:

  "questions": [{{"number": 1, "paper_number": 14, "prompt": "<the statement, without the number>"}}]

  The instruction line says which it is. "TRUE / FALSE / NOT GIVEN" is \
  true_false_not_given; "YES / NO / NOT GIVEN" is yes_no_not_given. They are \
  not interchangeable and the page always says.

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
questions 19-22 has gaps {{{{1}}}}..{{{{4}}}}. Shapes B, C and D have no \
template and no gap tokens at all.

A SUMMARY WITH A BOX OF WORDS ABOVE IT is still summary_completion, not \
matching: the candidate writes a word into a blank and the box only says \
which words are allowed. Put the summary in "template" and the box in \
"options".

TWO RULES THAT ARE EASY TO GET WRONG.

1. The printed question number is NOT part of the template. The page prints \
the number next to the dotted line; the gap token replaces BOTH the number \
and the dots.

     page:      by 19 ................. the population had doubled
     correct:   by {{{{1}}}} the population had doubled
     WRONG:     by 19 {{{{1}}}} the population had doubled

2. A BLANK WITH NO NUMBER BESIDE IT IS NOT A GAP. Only a numbered blank is \
one.

Transcribe the words exactly as printed. Ignore page headers, footers, page \
numbers, and any watermark (tailieutienganh.net, giasuIELTS.vn, "Edit by:") \
-- none of that is part of the task."""

KEY_PROMPT = """\
These images are answer-key pages from an IELTS book. Report ONLY the answers \
to READING questions {first} to {last} of {label}, and nothing else.

These sheets usually carry BOTH papers -- forty Listening answers and then \
forty Reading ones, under headings that say which. Take the READING half. \
Both papers number their questions 1 to 40, so the numbers alone cannot tell \
them apart; the heading can, and taking the wrong half answers every question \
with somebody else's answer.

Return ONE JSON object, no prose and no code fence:

{{"answers": {{"<number, or a pair like 23/24>": "<the answer EXACTLY as printed>"}}}}

Three things about these pages.

A PAIR is printed "23/24 A/B (in either order)". Return it under the pair, as \
"23/24", not under either number alone.

A TRUE/FALSE/NOT GIVEN answer is printed as those words, or as TRUE, FALSE, \
NOT GIVEN / YES, NO, NOT GIVEN. Copy what is printed.

THE BOOK MAY EXPLAIN AN ANSWER on the same line as it. The answer is only the \
part a candidate would write. Stop at it.

If the answers to {first}-{last} of the READING paper are not on these pages, \
return {{"answers": {{}}}} rather than the listening ones."""


def band(passage_no: int) -> tuple[int, int]:
    """The questions this passage carries."""
    return {1: (1, 13), 2: (14, 26), 3: (27, 40)}[passage_no]


def key_pages(conn: sqlite3.Connection, row: sqlite3.Row) -> list[int]:
    """Where this test's READING key is printed, as pdf indices.

    A `reading_answer_key` page in the passage's OWN document wins: Cambridge
    20 is one PDF per test and each carries its own key, so there is no
    ambiguity to resolve. Everywhere else the two papers share a sheet and
    `locate_pages` called it the listening key, which is the page the section
    rows already name -- so the sheet is right and only the half is in
    question, and that is what the prompt is for.
    """
    keys = sorted(
        page["index"]
        for doc_id, pages in page_maps(row["book_number"])
        if doc_id == row["document_id"]
        for page in pages
        if page.get("kind") in ("reading_answer_key", "listening_answer_key",
                                "answer_list")
    )
    named = [
        page["index"]
        for doc_id, pages in page_maps(row["book_number"])
        if doc_id == row["document_id"]
        for page in pages
        if page.get("kind") == "reading_answer_key"
    ]
    if named:
        start = min(named)
    else:
        found = conn.execute(
            "SELECT key_page FROM section WHERE book_number = ? AND test_no = ?"
            " AND key_page IS NOT NULL LIMIT 1",
            (row["book_number"], row["test_no"])).fetchone()
        if not found:
            return []
        start = found["key_page"]
    # Stop at the NEXT test's key, not at a fixed number of sheets.
    #
    # Cambridge 11 prints one key sheet per test at 123, 125, 127 and 129, so
    # spilling three pages past test 1's handed the model test 2's as well --
    # forty more answers to the same question numbers, and no way for it to
    # know which forty were wanted. The keys are a list; the next one is where
    # this one ends.
    #
    # And the LAST test has no next key, so the cap is the only bound left --
    # which walked straight off the end of the book. Trainer 2's test 6 key
    # starts eight sheets from the back and came back "page 232 not in
    # document", taking all three of its passages with it.
    pages = conn.execute("SELECT pages FROM document WHERE id = ?",
                         (row["document_id"],)).fetchone()
    end = (pages["pages"] if pages and pages["pages"] else start + KEY_SPILL + 1)
    stop = next((index for index in keys if index > start), start + KEY_SPILL + 1)
    return list(range(start, min(stop, start + KEY_SPILL + 1, end)))


def read_key(conn, row, *, model: str, force: bool = False) -> dict:
    """This test's forty reading answers, read once and kept.

    Once per TEST rather than once per passage: the three passages of a paper
    are answered off one sheet, and reading it three times is three chances
    for the three thirteenths to disagree about which half of the page they
    came from.
    """
    cache = WORK / f"readingkey-book{row['book_number']}-t{row['test_no']}.json"
    if cache.exists() and not force:
        return json.loads(cache.read_text())
    pages = key_pages(conn, row)
    if not pages:
        raise SystemExit(
            f"book {row['book_number']} test {row['test_no']}: no key page in "
            "the catalogue. Run locate_pages.py for this book first.")
    label = f"Test {row['test_no']}"
    shots = vision.render(MATERIALS / row["pdf"], pages,
                          WORK / f"readingkey-book{row['book_number']}"
                                 f"-t{row['test_no']}",
                          dpi=QUESTION_DPI, jpeg=True)
    answers: dict[str, str] = {}
    # One BAND at a time, and this is not a preference.
    #
    # Asked for all forty of a key page, Gemini answers
    # `content_filter: RECITATION` and returns nothing -- deterministically,
    # four times out of four on Cambridge 11's page 124. It is refusing to
    # reproduce a published answer key whole. Asked for questions 1 to 13 of
    # the same image it answers immediately and correctly, and so does each
    # of the other two bands.
    #
    # Three requests a test rather than one, which is what the stage wanted
    # anyway: a passage is answered from its own thirteen, and the band is
    # how the prompt says which half of a two-paper sheet to read.
    for passage_no in (1, 2, 3):
        first, last = band(passage_no)
        for start in range(0, len(shots), PAGES_PER_CALL):
            window = shots[start:start + PAGES_PER_CALL]
            asked = KEY_PROMPT.format(label=label, first=first, last=last)
            try:
                said = vision.ask_json(asked, window, model=model,
                                       max_tokens=3000)
            except vision.Refused:
                # Already the narrowest this prompt goes -- thirteen answers
                # of one paper. What is left is to ask elsewhere.
                print(f"    key {first}-{last} refused; asking {FALLBACK}")
                said = {"answers": {}}
                for one in window:
                    page = vision.ask_json(asked, [one], provider=FALLBACK,
                                           max_tokens=3000)
                    got = page.get("answers") if isinstance(page, dict) else {}
                    said["answers"].update(got or {})
            got = said.get("answers") if isinstance(said, dict) else said
            if isinstance(got, list):
                got = {str(one.get("number")): one.get("answer")
                       for one in got if isinstance(one, dict)}
            for number, answer in (got or {}).items():
                if answer and str(number) not in answers:
                    answers[str(number)] = str(answer).strip()
    cache.write_text(json.dumps(answers, indent=2, ensure_ascii=False))
    return answers


def slice_key(answers: dict, first: int, last: int) -> tuple[dict, list[int]]:
    """The answers in this passage's band, and which of its numbers are absent.

    A pair is printed under both its numbers -- "23/24" -- and belongs to the
    band either of them is in.
    """
    mine: dict[int, str] = {}
    paired: set[int] = set()
    for label, answer in answers.items():
        numbers = [int(n) for n in re.findall(r"\d+", str(label))]
        if not numbers:
            continue
        if len(numbers) > 1:
            if any(first <= n <= last for n in numbers):
                mine[min(numbers)] = answer
                paired.update(numbers)
            continue
        if first <= numbers[0] <= last:
            mine[numbers[0]] = answer
    absent = [n for n in range(first, last + 1)
              if n not in mine and n not in paired]
    return mine, absent


def group_type(group: dict) -> str:
    """The type this group really is, corrected by what the page says.

    A model naming the task is guessing between names that look alike from a
    distance, and two of those mistakes are expensive. A true/false set
    called "matching" would be graded by letters against the word TRUE. A
    set of YES/NO/NOT GIVEN called true_false_not_given would print the wrong
    three words on screen -- the options come from the TYPE, so the type IS
    the wording.

    The instruction line is not ambiguous about either, so it decides.
    """
    said = f"{group.get('instructions') or ''} {group.get('type') or ''}"
    if re.search(r"\bYES\b.{0,12}\bNO\b.{0,16}NOT\s*GIVEN", said, re.I):
        return "yes_no_not_given"
    if re.search(r"\bTRUE\b.{0,12}\bFALSE\b.{0,16}NOT\s*GIVEN", said, re.I):
        return "true_false_not_given"
    return group.get("type") or "sentence_completion"


def label_style(group: dict) -> str | None:
    """Which alphabet the option box is numbered with, off the box itself.

    Matching headings is the only task here lettered with roman numerals,
    and it is lettered that way because its ITEMS are the passage's lettered
    paragraphs: an answer of "C" that named both a heading and a paragraph
    would be two questions at once. The model is asked which it sees rather
    than trusted to know which task implies which.
    """
    if group_type(group) not in {"matching_headings", "matching_information",
                                 "matching_features",
                                 "matching_sentence_endings", "matching"}:
        return None
    said = (group.get("label_style") or "").strip().lower()
    if said in ("roman", "letters"):
        return said
    return "roman" if group_type(group) == "matching_headings" else "letters"


def question_pages(row) -> list[int]:
    """The passage's sheets that carry its QUESTIONS, and not its text.

    `locate_passages.py` already asked every one of these sheets which
    numbers it prints, and the answers are in `work/`. A sheet with none of
    this passage's numbers on it is the passage itself, and sending it costs
    more than the request: asked to transcribe a task while three pages of
    prose are in front of it, the model writes sentences that are ABOUT the
    passage rather than the ones printed under the heading. Cambridge 11's
    test 1 came back with "Some experts fear that the {{2}} is not
    sufficient to feed the growing human population", which is nowhere on
    the page and is a question no key can answer.

    Falls back to every page, because a passage whose sheets were never
    cached is better read from too much than not at all -- and the number
    check below says when that has happened.
    """
    pages = json.loads(row["pages"] or "[]")
    first, last = band(row["passage_no"])
    cache = WORK / (f"passages-book{row['book_number']}"
                    f"-doc{row['document_id']}.json")
    if not cache.exists():
        return pages
    numbered = set()
    for reply in json.loads(cache.read_text()):
        seen = [int(n) for n in reply.get("numbers") or []
                if isinstance(n, (int, float))]
        if any(first <= n <= last for n in seen):
            numbered.add(reply["index"])
    return [index for index in pages if index in numbered] or pages


def read_window(shots: list[pathlib.Path], prompt: str, model: str) -> list[dict]:
    """One window's groups, halving again if the reply still will not parse.

    The recursion is what stops the ladder being a cliff: three sheets that
    fail become two and one, and only a single sheet that fails is a failure.
    """
    try:
        read = vision.ask_json(prompt, shots, model=model, max_tokens=8000)
        return (read.get("groups") or []) if isinstance(read, dict) else []
    except vision.Refused:
        raise
    except SystemExit:
        if len(shots) == 1:
            raise
        half = (len(shots) + 1) // 2
        out: list[dict] = []
        for part in (shots[:half], shots[half:]):
            if part:
                out += read_window(part, prompt, model)
        return out


def read_questions(row, *, model: str) -> tuple[list[dict], list[str]]:
    """Read this passage's question groups off the sheets that carry them."""
    pages = question_pages(row)
    first, last = band(row["passage_no"])
    prompt = QUESTION_PROMPT.format(first=first, last=last,
                                    passage=row["passage_no"])
    work = WORK / row["id"]
    windows = [pages[i:i + PAGES_PER_CALL]
               for i in range(0, max(1, len(pages) - 1), PAGES_PER_CALL - 1)] or [pages]

    groups: list[dict] = []
    problems: list[str] = []
    for window in windows:
        shots = vision.render(MATERIALS / row["pdf"], window, work / "pages",
                              dpi=QUESTION_DPI, jpeg=True)
        try:
            read = vision.ask_json(prompt, shots, model=model, max_tokens=8000)
        except vision.Refused:
            # The provider recognised the page and declined to reproduce it.
            # Narrowing does not help there -- see read_passages.FALLBACK --
            # so this goes straight to the other provider.
            print(f"{'':<16} refused; asking {FALLBACK}")
            read = {"groups": []}
            for one in shots:
                page = vision.ask_json(prompt, [one], provider=FALLBACK,
                                       max_tokens=6000)
                read["groups"] += (page.get("groups") or []) if isinstance(
                    page, dict) else []
        except SystemExit as unparseable:
            # A reply that will not parse after three tries, which on a
            # question page means one closer written wrong three thousand
            # characters in. Nothing repairs that safely: a repair that
            # parses is one that has dropped the groups after the fault, and
            # a partial read with no error is worse than none.
            #
            # A shorter reply has fewer places to go wrong, so the window is
            # HALVED rather than taken apart. Context is what makes a group
            # read correctly -- a task printed across two sheets, asked one
            # sheet at a time, came back as a true/false set whose answers
            # were letters -- so the ladder gives up as little of it as it
            # has to, and only reaches single sheets if halving was not
            # enough.
            if len(shots) == 1:
                raise
            print(f"{'':<16} {unparseable}; halving the window")
            half = (len(shots) + 1) // 2
            read = {"groups": []}
            for part in (shots[:half], shots[half:]):
                if not part:
                    continue
                read["groups"] += read_window(part, prompt, model)
        for group in read.get("groups", []) if isinstance(read, dict) else []:
            if not isinstance(group, dict):
                continue
            numbers = [q.get("paper_number") for q in group.get("questions") or []
                       if isinstance(q, dict)]
            numbers = [int(n) for n in numbers if isinstance(n, (int, float))]
            # Only this passage's questions. A window carries the sheet before
            # it, so the group before this passage's first comes back too --
            # and a group that belongs to the next passage arrives the same
            # way off the last sheet.
            if not numbers or not all(first <= n <= last for n in numbers):
                continue
            groups.append(group)

    # One claim per question, and the widest claim wins.
    #
    # Windows overlap by a sheet, so a group is read twice and the two
    # readings can differ in wording without being two groups. Narrowing an
    # unparseable window to single sheets makes that worse: a task printed
    # across two sheets comes back as two partial groups, and Cambridge 17's
    # test 3 produced seven groups for thirteen questions, with 14-17
    # claimed by a matching_headings and by a matching_information at once.
    #
    # So the candidates are sorted by how much of a task each saw and taken
    # greedily, skipping any that overlaps one already taken. The reading
    # that saw the whole group beats the one that saw half of it, which is
    # the same reason the windows overlap in the first place.
    chosen: list[dict] = []
    claimed: set[int] = set()
    for group in sorted(groups, key=lambda g: -len(g["questions"])):
        numbers = {int(q["paper_number"]) for q in group["questions"]}
        if numbers & claimed:
            continue
        claimed |= numbers
        chosen.append(group)
    groups = sorted(chosen, key=lambda g: min(int(q["paper_number"])
                                              for q in g["questions"]))
    # A "choose TWO letters" is ONE question worth two marks, and the paper
    # prints it against both numbers -- "21 and 22". Counting only the
    # number it starts at made a correctly read passage look like it was
    # missing every second question. The same arithmetic build_questions.py
    # does, for the same reason.
    covered: set[int] = set()
    for group in groups:
        span = int(group.get("pick") or 1)
        for question in group["questions"]:
            covered.update(range(int(question["paper_number"]),
                                 int(question["paper_number"]) + span))
    absent = [n for n in range(first, last + 1) if n not in covered]
    if absent:
        problems.append(f"no group covers {absent}")
    return groups, problems


#: A matching-headings answer with the paragraph's own letter in front of it.
#: The key prints the two together -- "B vii" against question 15, meaning
#: paragraph B takes heading vii -- and only the numeral is the answer. Left
#: as printed, `normalize_answer` compares "b vii" against the learner's
#: "vii" and marks every one of them wrong.
LETTER_THEN_NUMERAL = re.compile(r"^\s*[A-Z]\s+([ivxl]+)\s*$")


def tidy_key(answer: str, style: str | None) -> str:
    """The part of a key line a candidate would actually write."""
    if style == "roman" and (match := LETTER_THEN_NUMERAL.match(answer or "")):
        return match.group(1)
    return answer


def assemble(groups: list[dict], answers: dict[int, str]) -> list[dict]:
    """The groups in the shape `build_questions.py` reads."""
    out = []
    for group in groups:
        kind = group_type(group)
        style = label_style(group)
        questions = [q for q in group.get("questions") or [] if isinstance(q, dict)]
        built = {
            "type": kind,
            "instructions": group.get("instructions", ""),
            "word_limit": group.get("word_limit"),
            "template": group.get("template", "") if not (
                kind in FIXED_CHOICE or group.get("options")
                or group.get("pick")) else "",
            "questions": [
                {"number": q.get("number"), "paper_number": q.get("paper_number"),
                 "key": tidy_key(answers.get(q.get("paper_number"), ""), style),
                 **({"prompt": q["prompt"]} if q.get("prompt") else {}),
                 **({"options": q["options"]} if q.get("options") else {})}
                for q in questions
            ],
        }
        if group.get("pick"):
            built["pick"] = group["pick"]
        # A fixed-choice group stores NO options. Its three words are its
        # type, on the server and here, and a group carrying them would be
        # read as a lettered group and graded by matching letters against the
        # word "TRUE".
        if group.get("options") and kind not in FIXED_CHOICE:
            built["options"] = group["options"]
            built["reuse"] = bool(group.get("reuse"))
            if style:
                built["label_style"] = style
        out.append(built)
    return out


def check(groups: list[dict]) -> list[str]:
    """What is wrong with these groups, in the terms a person would fix.

    Everything here is something that would otherwise reach a learner as a
    broken question, which is the same bargain `build_questions.py` makes:
    this stage is allowed to be wrong, and being wrong is caught.
    """
    problems = []
    for group in groups:
        kind = group["type"]
        numbers = [q["paper_number"] for q in group["questions"]]
        blank = [q["paper_number"] for q in group["questions"] if not q["key"]]
        if blank:
            problems.append(f"{kind} {numbers[0]}-{numbers[-1]}:"
                            f" no answer for {blank}")
        if kind in FIXED_CHOICE:
            if group.get("options"):
                problems.append(f"{kind} {numbers[0]}: carries options, which"
                                " would grade it as letters")
            odd = [q["paper_number"] for q in group["questions"]
                   if q["key"] and not FIXED_CHOICE_ANSWER.match(q["key"])]
            if odd:
                problems.append(f"{kind} {numbers[0]}-{numbers[-1]}: {odd}"
                                " are answered with something that is not one"
                                " of the three words")
            missing = [q["paper_number"] for q in group["questions"]
                       if not q.get("prompt")]
            if missing:
                problems.append(f"{kind} {numbers[0]}-{numbers[-1]}:"
                                f" {missing} have no statement")
        if kind.startswith("matching"):
            if not group.get("options"):
                problems.append(f"{kind} {numbers[0]}-{numbers[-1]}: no option box")
            else:
                # Every answer has to name a place in the box. A roman box of
                # eight headings is answered i to viii and a lettered box of
                # five features A to E; an answer outside that range is the
                # key read off the wrong column, and it would mark the
                # question wrong however well the learner did.
                size = len(group["options"])
                allowed = (ROMAN[:size] if group.get("label_style") == "roman"
                           else [chr(ord("A") + i) for i in range(size)])
                stray = [q["paper_number"] for q in group["questions"]
                         if q["key"] and q["key"].strip().lower()
                         not in {one.lower() for one in allowed}]
                if stray:
                    problems.append(
                        f"{kind} {numbers[0]}-{numbers[-1]}: {stray} are"
                        f" answered with something outside a box of {size}")
        if kind == "multiple_choice":
            thin = [q["paper_number"] for q in group["questions"]
                    if len(q.get("options") or []) < 3]
            if thin:
                problems.append(f"multiple_choice {thin}: fewer than three"
                                " options")
    return problems


def report(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT id FROM passage ORDER BY id").fetchall()
    read = 0
    problems: list[tuple[str, str]] = []
    for row in rows:
        path = WORK / row["id"] / "questions.src.json"
        if not path.exists():
            continue
        read += 1
        held = json.loads(path.read_text())
        for problem in held.get("problems") or []:
            problems.append((row["id"], problem))
    print(f"{read} of {len(rows)} passages have their questions"
          f" ({len(rows) - read} left)")
    if problems:
        print(f"\n{len(problems)} thing(s) to look at:")
        for passage_id, problem in problems:
            print(f"  {passage_id:<16} {problem}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("passage_id", nargs="?")
    ap.add_argument("--book", type=int)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--force-key", action="store_true",
                    help="read this test's key again as well")
    ap.add_argument("--model", default=vision.DEFAULT_MODEL)
    args = ap.parse_args()

    conn = sqlite3.connect(SEED / "catalogue.db")
    conn.row_factory = sqlite3.Row

    if args.report:
        report(conn)
        return 0

    where, params = "1 = 1", ()
    if args.passage_id:
        where, params = "p.id = ?", (args.passage_id,)
    elif args.book:
        where, params = "p.book_number = ?", (args.book,)
    rows = conn.execute(
        "SELECT p.*, d.rel_path pdf FROM passage p "
        "JOIN document d ON d.id = p.document_id "
        f"WHERE {where} ORDER BY p.book_number, p.test_no, p.passage_no",
        params).fetchall()
    if not rows:
        print("nothing to read -- run locate_passages.py first", file=sys.stderr)
        return 1

    failed: list[str] = []
    for row in rows:
        path = WORK / row["id"] / "questions.src.json"
        if path.exists() and not args.force:
            print(f"{row['id']:<16} already read")
            continue
        try:
            key = read_key(conn, row, model=args.model, force=args.force_key)
            first, last = band(row["passage_no"])
            answers, absent = slice_key(key, first, last)
            missing = [f"the key is missing {absent}"] if absent else []

            # Read, checked, and read AGAIN if the key contradicts it.
            #
            # The answer key is evidence and the reading is an
            # interpretation, so a true/false set whose answers are letters
            # is not a hard question -- it is a group the page named
            # something else. Cambridge 17's test 3 read correctly once and
            # then, on the same images, called the same four questions a
            # true/false set: the model varies and the key does not.
            #
            # One extra read, and the better of the two is kept. The reading
            # with fewer contradictions is the one closer to the page; a tie
            # keeps the first, because nothing has been learned.
            best = None
            for attempt in range(READS):
                groups, found = read_questions(row, model=args.model)
                built = assemble(groups, answers)
                problems = missing + found + check(built)
                if best is None or len(problems) < len(best[1]):
                    best = (built, problems)
                if not problems:
                    break
                if attempt + 1 < READS:
                    print(f"{'':<16} {len(problems)} problem(s); reading again")
            built, problems = best
        except (Exception, SystemExit) as failure:  # noqa: BLE001
            print(f"{row['id']:<16} FAILED  {failure}")
            failed.append(row["id"])
            continue

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "source": {"question_page_indices": question_pages(row),
                       "key_page_indices": key_pages(conn, row),
                       "model": args.model, "read_by": "vision"},
            "problems": problems,
            "groups": built}, indent=2, ensure_ascii=False))
        print(f"{row['id']:<16} {len(built)} groups,"
              f" {sum(len(g['questions']) for g in built):>2} questions"
              + (f"\n{'':<16} ! {'; '.join(problems)}" if problems else ""))

    if failed:
        print(f"\n{len(failed)} passage(s) failed and were not written:"
              f" {', '.join(failed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

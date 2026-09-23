"""Turn a section's hand-read question source into what the importer writes.

    seed/.venv/bin/python seed/build_questions.py cam11-t1-s1

`questions.src.json` is what a person (or, later, the vision stage) takes off
the page: the template with its ``{{N}}`` gaps, the instruction lines, and each
question's answer **exactly as the key prints it** -- `(£)115 / a hundred (and)
fifteen`, not an expansion of it. Keeping the printed form is what makes the
expansion auditable: when a learner reports a right answer marked wrong, the
line to check is the one the book actually prints.

This produces `questions.json`, which holds the same questions with

* `correct_answers` expanded to every accepted phrasing, because
  `normalize_answer` compares strings and nothing else, and
* `replay_start_ms`/`replay_end_ms` filled in from the alignment, by matching
  each question's margin marker to the turn it sits on.

The checks below are the point of having a build step at all. Everything they
catch is something that would otherwise reach a learner as a broken question.
"""

import argparse
import json
import pathlib
import re
import sqlite3
import subprocess
import sys

import markers as marker_syntax
from answer_key import parse_answer

SEED = pathlib.Path(__file__).resolve().parent
WORK = SEED / "work"
GAP = re.compile(r"\{\{(\d+)\}\}")
#: What each group type's `config` may hold, as the backend schema names it.
#: Checked here because pydantic IGNORES a key it does not declare: writing
#: "pick" instead of "answers_per_question" produced a group that silently
#: asked for one answer while its question held two, and the error that
#: followed named neither field.
CONFIG_KEYS = {
    "multiple_choice": {"answers_per_question"},
    "matching": {"options", "allow_reuse"},
    "matching_headings": {"options", "allow_reuse", "label_style"},
    "matching_information": {"options", "allow_reuse", "label_style"},
    "matching_features": {"options", "allow_reuse", "label_style"},
    "matching_sentence_endings": {"options", "allow_reuse", "label_style"},
    # Nothing, and that is the point -- the three words are the TYPE. A
    # true/false group carrying options in its config is a LETTERED group to
    # `answers_are_letters`, which would grade it by matching letters against
    # the word "TRUE".
    "true_false_not_given": set(),
    "yes_no_not_given": set(),
}
DEFAULT_CONFIG_KEYS = {"template", "options", "image_letters", "image", "image_adapt"}

#: The types answered by picking a LABEL out of a box rather than writing
#: words. They carry no template, so the gap checks below do not apply to
#: them and their answer key is a label rather than a list of accepted
#: phrasings.
#:
#: Matching is one task under five names, exactly as the nine completion
#: types are one document under nine. What differs is the instruction line
#: and how the box is labelled.
MATCHING_TYPES = {"matching", "matching_headings", "matching_information",
                  "matching_features", "matching_sentence_endings"}
LETTERED = {"multiple_choice"} | MATCHING_TYPES

#: The box's other alphabet. Matching headings is numbered i, ii, iii because
#: its ITEMS are the passage's lettered paragraphs, so its box cannot be
#: lettered too -- an answer of "C" would name a heading and a paragraph at
#: once. The same tuple the server labels the box with
#: (`OPTION_ROMAN` in app/schemas/listening.py); written twice because these
#: two halves share no code, and the check below is what would notice.
ROMAN = ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x",
         "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix", "xx")

#: Answered with one of three words that come from the TYPE. Not lettered --
#: the candidate writes TRUE, and `grade_answer` compares it as a word -- and
#: not a gap-fill either, since there is no template and nothing to expand.
FIXED_CHOICE = {"true_false_not_given", "yes_no_not_given"}
FIXED_CHOICE_WORDS = {
    "true_false_not_given": ("TRUE", "FALSE", "NOT GIVEN"),
    "yes_no_not_given": ("YES", "NO", "NOT GIVEN"),
}
#: How a key abbreviates them. "NG" is the only one worth spelling out; T/F
#: and Y/N are initials of the word above them.
FIXED_CHOICE_SHORT = {"T": "TRUE", "F": "FALSE", "NG": "NOT GIVEN",
                      "Y": "YES", "N": "NO"}
#: A map or diagram task is answered EITHER way, and the page decides which.
#: Blanks drawn on the picture are written into, and take a template like any
#: gap-fill; a box of lettered places beside it is picked from, and takes no
#: template at all. Which one a group is shows in whether it has a box, so
#: that is what is asked -- not the type, which is the same for both.
LABELLING = {"map_labelling", "diagram_labelling", "flow_chart_completion"}
#: A span past which "hear it again" stops being that. The corpus median is
#: fourteen seconds; a minute is four times that and is what a Part 4
#: paragraph runs to.
LONG_SPAN = 60_000

#: How far a replay window may be stretched to take in the answer it is
#: about. A turn boundary is a judgement made twice -- once by whatever read
#: the page, once by the aligner -- and a couple of seconds of disagreement
#: between them is ordinary. Ten seconds covers every case the corpus has
#: (the worst is 8.1s) and refuses anything that would mean the marker is on
#: the wrong turn altogether, which is `in_order`'s business, not this one's.
REACH = 10_000


#: An option printed with the letter it is picked by: "A written records".
#: The app draws its own letters beside the box, so the letter left in the
#: text comes out twice -- "A. A written records".
OWN_LETTER = re.compile(r"^([A-K])[\s.):-]\s*(\S.*)$")


def unlettered(options: list[str]) -> list[str]:
    """The box without each option's own letter, where every option has one.

    All of them, in order from A, or none: one option beginning with a capital
    letter and a space is a sentence, and stripping its first word would be
    reading the box wrong rather than tidying it.
    """
    said = [OWN_LETTER.match(str(o).strip()) for o in options]
    if not all(said) or [m.group(1).upper() for m in said] != [
            chr(ord("A") + i) for i in range(len(said))]:
        return list(options)
    return [m.group(2).strip() for m in said]


#: A printed question number at the head of a labelling line. The app draws
#: its own, so "15 Scarecrow" would come out "15. 15 Scarecrow".
PRINTED_NUMBER = re.compile(r"^\s*\d{1,2}[.)]?\s+")


def as_rows(template: str) -> str:
    """A labelling sheet written the way the page prints it: name, then blank.

    "Write the correct letter, A-I, next to Questions 15-20" prints a list
    where every line is one place and one answer, and `newLabelRow` in the
    form grammar is that line: a ROW, with the thing being named on one side
    of a bar and the blank on the other. Written as one run of text -- "-
    Conference centre {{1}}" -- the name lands in the blank's own column and
    the studio draws six rows of "Name it" with nothing in them.

    Twenty-three of the corpus's twenty-five labelling groups were written
    that way, because it is what a reader hands back when it is asked for a
    template and not for a shape.

    Only a line with exactly ONE gap is turned: a sentence with two is not a
    labelling row, and a line with none is a fixed label on the figure --
    "Door", "Water-wheel" -- which belongs where it is. Headings and blank
    lines are left alone.
    """
    out = []
    for line in template.split("\n"):
        body = re.sub(r"^\s*[-*>]\s*", "", line)
        gaps = GAP.findall(body)
        if line.lstrip().startswith("#") or "|" in line or len(gaps) != 1:
            out.append(line)
            continue
        label = PRINTED_NUMBER.sub("", GAP.sub("", body)).strip(" .·…")
        out.append(f"{label} | {{{{{gaps[0]}}}}}" if label else line)
    return "\n".join(out)


def laid_out(group: dict) -> str:
    """A template for a labelling group that came back without one.

    The server stores a map task as a list of its items, each with a gap beside
    it, and draws the letters over the picture -- "15 Scarecrow {{1}}", "16
    Maze {{2}}". A group read as a matching task puts those item names on the
    questions instead and leaves the template empty, and an empty template is
    refused: "template must contain at least one gap token". The names are
    there either way, so the list is built from them rather than the page
    being read again. Where the picture carries the numbers itself and there
    are no names to list -- Trainer's Test 6 map is numbered 11 to 15 with the
    words in a box -- the gap is all there is, which is also what the page
    shows.
    """
    # A flow chart is drawn from ">" steps; a map's items are rows, which
    # `as_rows` below puts in their proper shape.
    mark = ">" if group["type"] == "flow_chart_completion" else "-"
    lines = []
    for number, question in enumerate(group.get("questions") or [], start=1):
        said = (question.get("prompt") or "").strip()
        if GAP.search(said):
            # The step already carries its gap, which is where the reader put
            # it when it called this a matching task: "Give staff examples of
            # {{1}} that will be helpful every day."
            lines.append(f"{mark} {said}")
        else:
            lines.append(f"{mark} {said} {{{{{number}}}}}".strip()
                         if said else f"{mark} {{{{{number}}}}}")
    return "\n".join(lines)


#: A letter, or a few, with the book's explanation running on after it:
#: "C The speaker says there'll be a huge turnout ...". IELTS Trainer 2 prints
#: its reasoning on the same line as every answer, and told to stop at the
#: answer the reader mostly does not.
LETTERS_THEN_PROSE = re.compile(r"^([A-K](?:\s*[,/&]\s*[A-K])*)\s+\S", re.I)


def just_the_letters(value: str) -> str:
    """The answer, where the key line carries the answer AND why it is right.

    Only ever applied where the group is already known to be answered with
    letters, so there is nothing to lose: a value that is not letters is not
    an answer this group can take, and the build refuses it either way. What
    changes is that it refuses a lot less often."""
    said = LETTERS_THEN_PROSE.match(value.strip())
    return said.group(1) if said else value


def from_a_box(group: dict) -> list[str]:
    """The list beside the picture, where there is one rather than letters on it.

    "Label the map below. Choose FIVE answers from the box and write the
    correct letter A-H" prints eight named places to pick from; "Label the
    plan below. Write the correct letter A-G" prints those letters on the plan
    and nothing else. Both come back with `options`, and in the second case
    they are the bare letters -- which is not a list to read, it is the
    alphabet.
    """
    options = [str(o).strip() for o in (group.get("options") or [])]
    if not options or all(len(o) == 1 and o.isalpha() for o in options):
        return []
    return options
#: A letter, as the key prints it. "17-18.AE" is handled where the group is
#: built, not here: it is a statement about how two numbers share one question.
#: A-K, not A-H. Eight is what a "choose the correct letter" offers and what
#: the first books in this corpus used; a matching group picks from a box that
#: can hold more, and Cambridge 20 answers one of them "I". The key came back
#: as a letter this pattern did not recognise, so it expanded to nothing and
#: took the section down without naming the letter it had refused.
LETTERS = re.compile(r"^[A-K](?:\s*[,/&]?\s*[A-K])*$", re.I)
#: "Write the correct letter A-I" -- how many letters are drawn on the picture.
#: Printed on the page, so read rather than counted from the answers: the key
#: only names the ones that happen to be right.
#:
#: The comma is optional and was not, which made the printed range almost
#: unreadable: the paper writes "Write the correct letter, A-I, next to
#: Questions 15-20" far more often than it writes it bare, so the fallback
#: below ran instead and counted the letters the ANSWERS use. Cambridge 21's
#: Melby Coal Mine map is lettered A to I and answered F, B, D, A, H, E --
#: eight letters counted for nine drawn, and the learner is offered a box
#: that is missing the one the map calls I.
LETTER_RANGE = re.compile(r"letters?,?\s+([A-Z])\s*[-–—]\s*([A-Z])", re.I)
#: The key prints "A, E  IN EITHER ORDER" against a pair. The phrase is a note
#: to the marker, not part of the answer.
KEY_NOTE = re.compile(r"\b(in either order|in any order)\b", re.I)


def gaps_that_render(template: str) -> set[int] | None:
    """The gap numbers the take page will actually draw, or None if the check
    could not run.

    The template is not plain text with ``{{N}}`` in it. `form-syntax.ts` reads
    a leading ``+`` as a table row, ``>`` as a flow-chart step, ``#`` as a
    heading and ``|`` as the split between a label and its value -- and book
    prose collides with every one of them. A gap in a table's HEADER row is not
    drawn at all, which is how "+ £250 deposit ({{3}} payment is required)",
    lifted straight off the page, turned a ten-question paper into a
    nine-question one with nothing anywhere reporting a problem.

    This runs that grammar rather than guessing at it. Guessing is what put the
    gap in a table in the first place.
    """
    script = SEED / "check_template.mjs"
    try:
        out = subprocess.run(
            ["node", "--experimental-strip-types", str(script)],
            input=template, capture_output=True, text=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return {int(n) for n in out.stdout.split() if n.isdigit()}


def to_group_numbering(group: dict) -> int | None:
    """Renumber a group the reading left on the paper's numbering, and say
    what it started at.

    A group's `number` is its position within the group -- the paper's own
    numbering lives in `paper_number`, which is what the margin markers and
    the answer key are matched on. The reading gets this right for the first
    group of a section for the trivial reason that the two agree there, and
    then hands back 5..10 for the second. The template says the same thing, so
    the group is consistent with itself and every check here passes; the
    backend then refuses the import, because its schema asks the gaps to run
    1..N.

    Only a contiguous run is shifted. Numbers with a hole in them are a
    misreading, and renumbering would hide it -- that is left to fail below.
    """
    numbers = [q["number"] for q in group["questions"]]
    gaps = [int(n) for n in GAP.findall(group.get("template") or "")]

    low = run_start(numbers)
    if low:
        for q in group["questions"]:
            # Where the reading gave no paper number, the number it did give
            # WAS the paper's -- that is the whole of this bug.
            q.setdefault("paper_number", q["number"])
            q["number"] -= low - 1

    # The two halves can slip apart: the reading numbers the questions from 1
    # and leaves the template on the paper's numbering, or the other way
    # round. Each is shifted on its own evidence, so the pair that disagreed
    # meets in the same place.
    start = run_start(gaps)
    if start:
        group["template"] = GAP.sub(
            lambda m: "{{%d}}" % (int(m[1]) - start + 1), group["template"])
    return low or start


def run_start(numbers: list[int]) -> int | None:
    """Where a contiguous run starts, if it starts anywhere but 1.

    Only a contiguous run is shifted. Numbers with a hole in them are a
    misreading, and renumbering would hide it -- that is left to fail below.
    """
    if not numbers or sorted(numbers) == list(range(1, len(numbers) + 1)):
        return None
    low, high = min(numbers), max(numbers)
    if len(set(numbers)) != len(numbers) or high - low + 1 != len(numbers):
        return None
    return low


#: A work id names a listening section (`cam11-t1-s1`) or a reading passage
#: (`cam11-t1-p2`), and the only difference to this file is which numbers of
#: the paper it is allowed to hold.
PAPER_BAND = re.compile(r"-([sp])(\d)$")


def band(work_id: str) -> tuple[int, int]:
    """The numbers this section or passage carries on its own paper.

    A Listening paper is ten questions to a part; a Reading paper is roughly
    thirteen to a passage and the boundaries are fixed by the exam, not by
    the book. Both are arithmetic on the id rather than anything read off a
    page, which is why a group belonging to the neighbour can be recognised
    and dropped below.
    """
    match = PAPER_BAND.search(work_id)
    if not match:
        raise SystemExit(f"{work_id} is neither a section nor a passage")
    kind, number = match.group(1), int(match.group(2))
    if kind == "s":
        return (number - 1) * 10 + 1, number * 10
    return {1: (1, 13), 2: (14, 26), 3: (27, 40)}[number]


def heard(section_id: str) -> dict[int, tuple[int, int]]:
    """Where a person heard an answer that neither the page nor the words fix.

    `work/<section id>/spans.json`, written by hand and never by this program,
    the same bargain `read_passage_questions.corrections` makes with a key the
    book got wrong:

        {"source": "<who listened, and to what>",
         "why": "<why neither of the two machines could settle it>",
         "spans": {"4": [198480, 203900]}}

    Keyed by PAPER number, in milliseconds, and applied after everything else
    so it wins.

    It exists because the two automatic sources can BOTH be silent and both
    be right to be. The Official Guide's test 3 part 1 numbers only seven of
    its ten answers in the audioscript, so question 4 has no marker; and its
    answer, "swimming", is said twice in the recording -- once by the
    receptionist listing what the club has ("a gym, a swimming pool, tennis")
    at 176s and once by Harry saying what he will do at 199s. `locate` gives
    nothing rather than guess between them, which is the right refusal: a
    replay that opens on the wrong sentence teaches somebody they misheard a
    line they never heard.

    What settles it is not more machinery but reading the two occurrences:
    one is the receptionist listing what the building contains, the other is
    the candidate answering the question the form asks. `source` says how it
    was established and by whom, in a file this program only ever reads --
    which is what keeps "the machine could not tell" and "somebody decided"
    two different things on disk.
    """
    path = WORK / section_id / "spans.json"
    if not path.exists():
        return {}
    said = json.loads(path.read_text()).get("spans") or {}
    return {int(number): (int(pair[0]), int(pair[1]))
            for number, pair in said.items()}


def in_order(questions: list[dict]) -> tuple[int, int]:
    """Keep the largest set of replay spans that a recording could produce,
    and drop the rest. Returns ``(moved, dropped)``.

    A paper asks its questions in the order the recording answers them --
    the rule `mark_answers.py` already enforces on its own placements -- so
    a group whose spans go backwards contains at least one that is wrong.
    Which one is the whole difficulty, and walking forward keeping the first
    gets it backwards about half the time.

    Cambridge 17 Test 1 Section 4 is the case that settles it. Questions 31
    to 37 are placed within seconds of where their own words are said, Q38's
    marker puts it at 374.7s, and the words answering Q39 and Q40 are said
    once each, at 343.2s and 362.4s. Keeping the earlier claim drops the two
    that agree with each other in favour of the one that agrees with
    nothing.

    So neither claim is privileged and the SET is chosen instead: the
    longest run of placements that ascends, with each question offering
    what it has -- the marker's span, the single place its answer is spoken,
    or nothing. Everything outside that run loses its span. A question with
    two candidates can take the one that fits, which is how Q38's marker is
    dropped while Q39 and Q40 keep the moments they are actually said.

    Ties go to the marker: it is a printed page read by a person, and the
    alignment is a machine's transcript of speech. Equal times are allowed --
    a "choose TWO" is answered in one breath, and the book prints "17&18"
    against a single line.
    """
    # Each question's candidates, best first, as (start, end, from_marker).
    offers: list[list[tuple[int, int, bool]]] = []
    for q in questions:
        options = []
        if q.get("replay_start_ms") is not None:
            options.append((q["replay_start_ms"], q["replay_end_ms"], True))
        heard = q.get("_heard_at")
        if heard and (not options or heard[0] != options[0][0]):
            options.append((heard[0], heard[1], False))
        offers.append(options)

    # Longest ascending assignment, by questions placed. Ten questions with
    # two offers each: the table is twenty wide and the search is a walk
    # back through it.
    best: list[tuple[int, int, int, int]] = []  # (placed, markers, i, c)
    picked: dict[tuple[int, int], tuple[int, int] | None] = {}
    score: dict[tuple[int, int], tuple[int, int]] = {}
    for i, options in enumerate(offers):
        for c, (lo, _hi, marked) in enumerate(options):
            run, markers, back = 1, int(marked), None
            for j in range(i):
                for d, (plo, _phi, pmarked) in enumerate(offers[j]):
                    if plo > lo or (j, d) not in score:
                        continue
                    had, hadm = score[(j, d)]
                    if (had + 1, hadm + int(marked)) > (run, markers):
                        run, markers, back = had + 1, hadm + int(marked), (j, d)
            score[(i, c)] = (run, markers)
            picked[(i, c)] = back
            best.append((run, markers, -i, c))
    if not best:
        return 0, 0

    run, markers, negative_i, c = max(best)
    keep: dict[int, tuple[int, int, bool]] = {}
    at: tuple[int, int] | None = (-negative_i, c)
    while at is not None:
        keep[at[0]] = offers[at[0]][at[1]]
        at = picked[at]

    moved = dropped = 0
    for i, q in enumerate(questions):
        q.pop("_heard_at", None)
        chosen = keep.get(i)
        if chosen is None:
            if q.get("replay_start_ms") is not None:
                dropped += 1
            q["replay_start_ms"] = q["replay_end_ms"] = None
            continue
        if q.get("replay_start_ms") != chosen[0]:
            moved += 1
        q["replay_start_ms"], q["replay_end_ms"] = chosen[0], chosen[1]
    return moved, dropped


def build(section_id: str) -> int:
    work = WORK / section_id
    src = json.loads((work / "questions.src.json").read_text())

    aligned = turns = None
    if (work / "aligned.json").exists():
        aligned = json.loads((work / "aligned.json").read_text())
        turns = json.loads((work / "turns.json").read_text())

    #: paper number -> the span of the turn its marker is printed against. Keyed
    #: by NUMBER rather than by the marker string, because one turn can carry
    #: two of them ("Q21/22") and both answers are given in it.
    spans: dict[int, tuple[int, int]] = {}
    if aligned and turns:
        for index, turn in enumerate(turns):
            wanted = marker_syntax.numbers(turn.get("marker"))
            if not wanted or marker_syntax.is_example(turn.get("marker")):
                continue
            words = [w for w in aligned if w["turn"] == index]
            if words:
                for n in wanted:
                    spans[n] = (words[0]["start_ms"], words[-1]["end_ms"])
    #: The spans a person settled by hand -- see `heard`. Held apart from
    #: `spans` deliberately. `spans` is the MARKER map, and the windows that
    #: rescue an unmarked answer are measured off its neighbours: dropping a
    #: hand-fixed span into it moved question 3's window forward past its own
    #: answer, and fixing question 4 broke question 3. A correction overrides
    #: the RESULT, never the machinery that produces it.
    by_hand = heard(section_id)

    # A section's questions are its own. The question pages of Section 1 and
    # Section 2 sit on the same sheets, so the reader hands back groups for
    # both -- and the answer key, asked only for this section's range, leaves
    # the other one's keys empty. Dropping them here rather than failing on an
    # empty key is the same rule the audioscript reader applies to a marker
    # outside its range: out of range is proof it belongs to the neighbour.
    by_hand_used = 0

    lo, hi = band(section_id)
    kept = []
    for group in src["groups"]:
        papers = [q.get("paper_number") for q in group.get("questions", [])
                  if q.get("paper_number")]
        if papers and not any(lo <= n <= hi for n in papers):
            print(f"note: dropping a {group['type']} group covering {min(papers)}-"
                  f"{max(papers)}; this section is {lo}-{hi}", file=sys.stderr)
            continue
        kept.append(group)
    src = {**src, "groups": kept}

    # What is left has to be the whole section. Dropping a neighbour's group is
    # right, and dropping so much that four questions stand in for ten is a
    # misread page -- and one that nothing downstream can see, because
    # publish_blockers() asks whether the questions present are sound, not
    # whether they are all of them. Two of Cambridge 20's sections went into
    # the database with two and four questions and were counted complete.
    # A "choose TWO letters" is ONE question worth two marks, so it covers two
    # of the paper's numbers -- the book prints "21&22" against it. Counting
    # only the number it starts at made a correct section look like it was
    # missing every second question.
    covered = set()
    for group in kept:
        span = group.get("pick") or 1
        for question in group["questions"]:
            start = question.get("paper_number")
            if start is not None:
                covered.update(range(start, start + span))
    short = [n for n in range(lo, hi + 1) if n not in covered]
    if covered and short:
        raise SystemExit(
            f"PROBLEM  after dropping, questions {short} of {lo}-{hi} are "
            "missing; the page was misread")

    # And the ones that ARE all there have to arrive in the order the book
    # prints them. A paper numbers its gaps in reading order -- left to
    # right, top to bottom -- so a group whose paper numbers descend at any
    # point is a group whose LAYOUT was read in some other order, and the
    # template is the wrong shape.
    #
    # It is always a table, and always the same misreading: a cell holding
    # several lines gets spread over several rows, so the cell's second line
    # lands after the whole of the next column -- and `Maori cloaks` was read
    # transposed outright, columns for rows. The content survives it (every
    # answer stays with its own gap) and the NUMBERING does not: five of that
    # table's seven gaps were printed under a number the book gives to a
    # different question, so a candidate checking their answers was comparing
    # two numberings.
    #
    # Three of 1 076 groups, found by this test after the fact. Refused here
    # rather than warned about, like the hole above it: a template that has
    # to be rewritten by hand is not something to discover from a screenshot.
    for group in kept:
        papers = [q.get("paper_number") for q in group["questions"]]
        if None in papers or papers == sorted(papers):
            continue
        raise SystemExit(
            f"PROBLEM  the {group['type']} group's gaps run {papers}, not in "
            "the order the paper numbers them; its layout was read out of "
            "order and the template needs rewriting by hand")

    def between(paper: int | None) -> tuple[int, int]:
        """The stretch of recording a question's answer has to fall inside.

        The paper asks its questions in the order the recording answers them,
        so a gap with no marker is bracketed by the nearest markers either
        side of it. That is not a guess about where the answer is -- it is
        what the numbering already says, and the markers it is built from are
        the ones the book printed.
        """
        if paper is None:
            return 0, 1 << 62
        # The NEAREST marker either side, and from where its turn starts rather
        # than where it ends. Two things this section got wrong:
        #
        # Two questions can share a turn -- the book prints "17&18" against one
        # line -- so an answer with no marker of its own often lies inside the
        # turn the marker before it names. Bounding at that turn's end puts the
        # window in the silence between two turns.
        #
        # And a book's markers are not always in order: cam12-t3-s4 prints Q37
        # on a later turn than Q38, so taking the furthest span below Q39
        # started its window after the word it was looking for. Q38 and Q40 are
        # what bound Q39, whatever the ones further out are doing.
        below = max((n for n in spans if n < paper), default=None)
        above = min((n for n in spans if n > paper), default=None)
        return (spans[below][0] if below is not None else 0,
                spans[above][1] if above is not None else 1 << 62)

    def locate(answers: list[str], window: tuple[int, int] = (0, 1 << 62)
               ) -> tuple[int, int] | None:
        """Where an answer's own words are said, for a gap the book did not mark.

        The margin marker is the better source and is used wherever it exists:
        it names the turn the answer is given in, which is what a learner wants
        to hear, and it is right even when the answer is a spelled-out number
        that the alignment mangles. This is the fallback for the questions no
        marker was found for -- roughly one in twenty after four rounds of
        chasing them.

        Only an UNAMBIGUOUS match counts. A phrase that appears twice in the
        recording could send a learner to either, and a replay at the wrong
        moment is worse than no replay button: it teaches them they misheard
        something they never heard.

        `window` narrows the recording before that rule is applied rather than
        relaxing it: a phrase said three times, once inside the stretch the
        numbering allows, is still said once where it could possibly count.
        """
        if not aligned:
            return None
        stream = [re.sub(r"[^a-z0-9]", "", w["word"].lower()) for w in aligned]
        lo, hi = window
        for answer in sorted(answers, key=len, reverse=True):
            wanted = [re.sub(r"[^a-z0-9]", "", w.lower()) for w in answer.split()]
            wanted = [w for w in wanted if w]
            if not wanted or len("".join(wanted)) < 4:
                continue
            hits = [i for i in range(len(stream) - len(wanted) + 1)
                    if stream[i:i + len(wanted)] == wanted
                    and lo <= aligned[i]["start_ms"] <= hi]
            if len(hits) == 1:
                at = hits[0]
                # A couple of seconds of run-up, so the answer is heard in the
                # sentence that carries it rather than bare.
                start = max(0, at - 12)
                return aligned[start]["start_ms"], aligned[at + len(wanted) - 1]["end_ms"]
        return None

    def reaches(answers: list[str], span: tuple[int, int]) -> tuple[int, int] | None:
        """The span widened to cover the answer, where it is spoken just
        outside it. Nothing where it already covers it, or where the nearest
        it is said is further than :data:`REACH`.

        A marker names the TURN, and a turn boundary is a judgement about
        where one paragraph ends -- drawn by a model reading a page, then
        drawn again by the aligner deciding which word starts it. Two seconds
        of disagreement is ordinary, and two seconds is all it takes for the
        replay to stop before the word it exists to play. Twenty-one answers
        across the corpus were outside their own window, every one of them by
        less than nine seconds: `cam18-t3-s4` says "thousands" at 164.0s and
        opened its replay at 172.1s.

        WIDENED rather than moved. The marker is the book's claim about which
        turn answers the question and it is not in doubt here -- what is in
        doubt is where that turn starts and stops. A span that has to travel
        further than `REACH` to reach its answer is a different problem, and
        `in_order` is what deals with that one.

        The nearest occurrence, not the only one: `locate` refuses a phrase
        said three times, which is right when it has nothing to go on, and
        wrong here where the marker has already said roughly where to look.
        """
        best = None
        for answer in sorted(answers, key=len, reverse=True):
            wanted = [re.sub(r"[^a-z0-9]", "", w.lower()) for w in answer.split()]
            wanted = [w for w in wanted if w]
            if not wanted or len("".join(wanted)) < 4:
                continue
            stream = [re.sub(r"[^a-z0-9]", "", w["word"].lower()) for w in aligned]
            for i in range(len(stream) - len(wanted) + 1):
                if stream[i:i + len(wanted)] != wanted:
                    continue
                at, end = aligned[i]["start_ms"], aligned[i + len(wanted) - 1]["end_ms"]
                if span[0] <= at <= span[1]:
                    return None
                gap = span[0] - end if end < span[0] else at - span[1]
                if gap <= REACH and (best is None or gap < best[0]):
                    best = (gap, at, end)
            if best is not None:
                break
        if best is None:
            return None
        _gap, at, end = best
        return min(span[0], at), max(span[1], end)


    # What the PICTURE stage put on the last build, kept by group index. A
    # rebuild is free and gets run often -- every time a span rule changes --
    # and it writes questions.json from questions.src.json, which has never
    # heard of the picture. Rebuilding all 200 sections after one such change
    # silently detached eighteen maps, and the only thing that noticed was
    # publish_blockers(): 200 content-complete became 182. The cut file is
    # still on disk and still right, so it is carried forward rather than
    # being re-cut.
    # NOT `drawn`: that name is already the count of letters printed on a
    # labelling picture, thirty lines down, and shadowing it made every build
    # in the corpus raise TypeError on `gi in drawn`. Which would have been
    # obvious, except the rebuild loop was run with its output discarded, so
    # 200 sections "rebuilt" and not one file changed.
    pictures: dict[int, dict] = {}
    built = work / "questions.json"
    if built.exists():
        for index, group in enumerate(json.loads(built.read_text()).get("groups", [])):
            if group.get("picture"):
                pictures[index] = group["picture"]

    problems: list[str] = []
    warnings: list[str] = []
    recovered = moved = tightened = moved_back = unplaced = widened = 0
    out_groups = []
    for gi, group in enumerate(src["groups"]):
        lettered = (group["type"] in LETTERED
                    or (group["type"] in LABELLING and bool(from_a_box(group)
                                                            or group.get("options"))))
        # A third kind, and it is neither of the other two. Its answer is a
        # WORD the candidate writes -- TRUE, NOT GIVEN -- so it is not
        # lettered; and it has no template, so the gap checks cannot apply.
        # Treated as lettered it would be scanned for the letters in "FALSE";
        # treated as a gap-fill it would be refused for having no template.
        fixed = group["type"] in FIXED_CHOICE
        labels = (ROMAN if (group.get("label_style") == "roman")
                  else tuple("abcdefghijklmnopqrstuvwxyz"))
        if not group.get("questions"):
            # An empty group is never what the page says. It reached the
            # database as a part carrying a group with nothing in it, which
            # publish_blockers reports as "add at least one question" -- true,
            # and no help at all in finding the page that was misread.
            problems.append(f"group {gi}: {group['type']} with no questions")
            continue
        shifted = to_group_numbering(group)
        if shifted:
            print(f"note: group {gi} was numbered {shifted} off the paper; "
                  "renumbered to start at 1", file=sys.stderr)
        numbers = [q["number"] for q in group["questions"]]
        # Where the previous question of this group was answered. A paper
        # asks its questions in the order the recording answers them -- the
        # rule `mark_answers.py` already enforces on its own placements --
        # so a span that starts before this one is evidence that the answer's
        # words were matched at the wrong occurrence. See `forward` below.
        floor = 0

        if not lettered and not fixed:
            gaps = [int(n) for n in GAP.findall(group.get("template") or "")]
            # The template and the questions are two readings of the same page,
            # and a disagreement means one of them was misread. The backend
            # refuses this too -- better to hear it here, by name.
            if sorted(gaps) != sorted(numbers):
                problems.append(
                    f"group {gi}: template gaps {sorted(gaps)} != question numbers "
                    f"{sorted(numbers)}")
            if len(gaps) != len(set(gaps)):
                problems.append(f"group {gi}: template repeats a gap number")

            rendered = gaps_that_render(group.get("template") or "")
            if rendered is None:
                print(f"note: could not run the layout check for group {gi} "
                      "(needs node and frontend/)", file=sys.stderr)
            elif set(gaps) - rendered:
                lost = sorted(set(gaps) - rendered)
                problems.append(
                    f"group {gi}: gaps {lost} are in the template but the take page "
                    f"would not draw them -- a line is colliding with the layout "
                    f"grammar (a leading '+', '>', '#', or a '|')")
        elif sorted(numbers) != list(range(1, len(numbers) + 1)):
            problems.append(
                f"group {gi}: question numbers {sorted(numbers)} are not 1..N")

        questions = []
        for q in group["questions"]:
            printed = KEY_NOTE.sub("", q["key"]).strip(" ,;")
            if lettered and labels is not ROMAN:
                printed = just_the_letters(printed)
            if lettered and not printed:
                # The key line was the note and nothing else, which means the
                # letters printed under it were not read. Better to say so than
                # to write a question with no answer.
                problems.append(
                    f"group {gi} q{q['number']}: the key line was {q['key']!r} with no "
                    "letters -- they are printed on the lines below it")
                continue
            if fixed:
                # One of three words, and which three is the TYPE's business.
                # The key abbreviates them as often as not -- "T", "NG" --
                # and a stored "T" is an answer the candidate has no way to
                # submit, so it is expanded to what the page offers.
                said = printed.strip().upper()
                said = FIXED_CHOICE_SHORT.get(said.replace(" ", ""), said)
                said = re.sub(r"\s+", " ", said)
                answers = [said] if said else []
                if said and said not in FIXED_CHOICE_WORDS[group["type"]]:
                    problems.append(
                        f"group {gi} q{q['number']}: {printed!r} is not one of "
                        f"{', '.join(FIXED_CHOICE_WORDS[group['type']])}, but this "
                        f"is a {group['type']} group")
            elif lettered and labels is ROMAN:
                # A roman box is answered with a numeral, and the numerals
                # are made of letters -- scanning "vii" for [A-K] finds
                # nothing at all, which is how a whole matching-headings
                # group came back with no answers.
                found = re.findall(r"\b[ivxl]+\b", printed, re.I)
                answers = [one.lower() for one in found
                           if one.lower() in ROMAN]
                if not answers:
                    problems.append(
                        f"group {gi} q{q['number']}: {printed!r} is not a roman "
                        f"numeral, but this box is numbered i, ii, iii")
            elif lettered:
                # A lettered answer is the KEY, not a list of phrasings: the
                # letters must be picked exactly, and expanding "A" the way a
                # gap-fill answer is expanded would be nonsense.
                answers = [c.lower() for c in re.findall(r"[A-K]", printed, re.I)]
                if not LETTERS.match(printed):
                    problems.append(
                        f"group {gi} q{q['number']}: {printed!r} is not a letter, but "
                        f"this is a {group['type']} group")
            else:
                answers = parse_answer(printed)
            if not answers:
                problems.append(f"group {gi} q{q['number']}: key {q['key']!r} expands to nothing")
            span = spans.get(q.get("paper_number"))
            if span is not None and not lettered:
                # Two independent claims about the same moment: the marker,
                # which is where a printed symbol sits beside a line, and the
                # answer's own words in the aligned recording. They agree for
                # about nine answers in ten. Where they do not overlap AT ALL,
                # the words win -- they are evidence and the marker is a
                # reading of a page.
                #
                # It is not a rare correction and it is not random. Thirteen
                # Part 4 sections across seven books had every marker landing
                # on the paragraph AFTER the one that answers the question,
                # by a median of 7 to 64 seconds: cam17-t1-s4 says "logic" at
                # 149s and sent the learner to 171-209s. A replay that starts
                # after the answer is worse than no replay, because it teaches
                # them they misheard something they never heard.
                said = locate(answers)
                if said and (said[1] < span[0] or said[0] > span[1]):
                    span = said
                    moved += 1
                elif span[1] - span[0] > LONG_SPAN:
                    # The marker is right and the turn it names is enormous.
                    # A Part 4 paragraph runs a minute or more, and "hear it
                    # again" that plays a minute is not hearing it again --
                    # the corpus median is fourteen seconds. Searching INSIDE
                    # the turn is also where the search is most likely to
                    # come back unambiguous, which is the only kind of answer
                    # locate() will give.
                    tighter = locate(answers, span)
                    if tighter:
                        span = tighter
                        tightened += 1
            if span is None and not lettered:
                # Unbracketed first, because a phrase said once in the whole
                # recording needs no help. The window is what rescues the
                # answer said twice, where only one of the two can be the one
                # this question is asking about.
                span = locate(answers) or locate(answers, between(q.get("paper_number")))
                if span:
                    recovered += 1
            if q.get("marker") and span is None:
                # A warning, not a problem. The marker was not found in the
                # audioscript, so this answer gets no "hear it again" -- which
                # is a degradation, not a broken question, and refusing the
                # whole section over it threw away nine good questions to
                # protect one replay button.
                warnings.append(
                    f"group {gi} q{q['number']}: marker {q['marker']} was not found in "
                    "the audioscript, so it gets no replay span")
            # A choice question is linked to the audio per OPTION, not per
            # question: a "choose TWO" has two answers at two moments, so
            # publishing asks where each chosen letter is said. The margin
            # marker gives the turn where the answer is given, and the answer
            # is the correct option -- so that turn is what every correct
            # letter points at. Where a "choose two" shares one marker both
            # letters get the same span, which is what the book itself says.
            # Applied last, over everything the marker and the words said.
            if (settled := by_hand.get(q.get("paper_number"))) is not None:
                span = settled
                by_hand_used += 1

            # What the answer's own words say about where it is, kept
            # beside what the marker says. Reconciled after the group is
            # whole -- see `in_order` below, which needs every question's
            # evidence before it can tell which of two disagreeing claims
            # is the one out of step.
            heard_at = None if lettered else locate(answers)

            option_replay = ({letter: [span[0], span[1]] for letter in answers}
                             if span and group["type"] == "multiple_choice" else {})
            questions.append({
                "number": q["number"],
                "paper_number": q.get("paper_number"),
                "key": q["key"],                    # kept: the printed form
                "correct_answers": answers,
                "replay_start_ms": span[0] if span else None,
                "replay_end_ms": span[1] if span else None,
                **({"_heard_at": heard_at} if heard_at else {}),
                **({"prompt": q["prompt"]} if q.get("prompt") else {}),
                **({"options": q["options"]} if q.get("options") else {}),
                **({"option_replay": option_replay} if option_replay else {}),
            })

        # The group is whole, so the claims about WHERE can be reconciled
        # against each other. Not per question, inside the loop: the
        # evidence that a span is the one out of step is what the questions
        # after it say, and inside the loop they have not been read yet.
        shifted_on, lost = in_order(questions)
        moved_back += shifted_on
        unplaced += lost

        # And last, the window has to actually contain the answer. Done after
        # `in_order` so it widens the span that survived rather than one about
        # to be dropped.
        if not lettered:
            for q in questions:
                if q["replay_start_ms"] is None:
                    continue
                wider = reaches(q["correct_answers"],
                                (q["replay_start_ms"], q["replay_end_ms"]))
                if wider is not None:
                    q["replay_start_ms"], q["replay_end_ms"] = wider
                    widened += 1
        for q in questions:
            if q.get("option_replay") and q["replay_start_ms"] is None:
                q.pop("option_replay")
            elif q.get("option_replay"):
                q["option_replay"] = {
                    letter: [q["replay_start_ms"], q["replay_end_ms"]]
                    for letter in q["option_replay"]
                }

        # `config` is what the group's own schema expects, and the three
        # kinds want three different things in it.
        if group["type"] == "multiple_choice":
            # How many letters the group asks for is COUNTED from its answers,
            # not taken from the reader. A "Choose TWO letters" printed as
            # "11&12  IN EITHER ORDER / A / C" came back with pick=1 and two
            # letters, which the schema rightly refused. The key is the
            # evidence; the instruction line is a description of it.
            picked = max((len(q["correct_answers"]) for q in questions), default=1)
            claimed = int(group.get("pick") or 1)
            if picked != claimed:
                print(f"note: group {gi}: the reader said pick={claimed}, the answer "
                      f"key says {picked}; using the key", file=sys.stderr)
            # `answers_per_question`, not `pick`: pydantic drops a key the
            # model does not declare without a word, so the group came out
            # asking for one answer while its question held two and the schema
            # refused it with a message about neither.
            config = {"answers_per_question": picked}
        elif group["type"] in MATCHING_TYPES:
            config = {"options": unlettered(group.get("options") or []),
                      "allow_reuse": bool(group.get("reuse"))}
            # Only where the box really is numbered that way. Sent as
            # "letters" on a headings group the server would label the box
            # A, B, C and then refuse every answer for naming an option that
            # does not exist.
            if group["type"] != "matching":
                config["label_style"] = ("roman" if labels is ROMAN
                                         else "letters")
        elif fixed:
            # Empty, and it stays empty. See CONFIG_KEYS above.
            config = {}
        else:
            drawn = 0
            # Only where the answers really are letters. A labelling task is
            # answered EITHER by picking a letter off the picture or by
            # writing words into blanks drawn on it, and the second kind has
            # no letters at all -- Cambridge 11's Falkirk Wheel diagram is
            # questions 8 to 13 written into the drawing. The fallback below
            # counts letters found in the answer key, which on a key of words
            # finds the letters inside them: "A-X", from an X in "axle".
            if lettered and group["type"] in ("map_labelling", "diagram_labelling"):
                span = LETTER_RANGE.search(group.get("instructions") or "")
                if span:
                    drawn = ord(span.group(2).upper()) - ord(span.group(1).upper()) + 1
                else:
                    # Fall back to the letters the answers actually use. Fewer
                    # than are drawn, but a labelling task that publishes with a
                    # short box beats one that does not publish at all.
                    used = {c.upper() for q in group["questions"]
                            for c in re.findall(r"[A-Z]", q["key"], re.I)}
                    drawn = (ord(max(used)) - ord("A") + 1) if used else 0
                    print(f"note: group {gi}: the instructions do not say which letters "
                          f"are on the picture; using A-{chr(ord('A') + drawn - 1)} "
                          "from the answer key", file=sys.stderr)
            # A labelling task is answered from ONE of two things, and the
            # server refuses a group that offers both. Which one it is shows
            # in what the options say. Bare letters -- ["A", "B", ... "I"] --
            # are the letters printed on the map itself, which "image_letters"
            # already draws; carried as options as well they would show the
            # learner a list reading "A, B, C". Words are a box beside the
            # map, and then the letters are in the box rather than on the
            # picture and the learner needs to read them.
            box = unlettered(from_a_box(group))
            drawn_on = group["type"] in ("map_labelling", "diagram_labelling")
            written = group.get("template") or laid_out(group)
            config = {"template": as_rows(written) if drawn_on else written,
                      "options": box,
                      "image_letters": 0 if box else drawn}
        allowed = CONFIG_KEYS.get(group["type"], DEFAULT_CONFIG_KEYS)
        unknown = set(config) - allowed
        if unknown:
            problems.append(
                f"group {gi}: config key(s) {sorted(unknown)} are not what a "
                f"{group['type']} group takes ({sorted(allowed)}) -- the server would "
                "drop them without a word")
        out_groups.append({
            # The SOURCE's picture first, then the one carried forward. Two
            # stages find a picture and they run on opposite sides of this
            # one: `extract_image.py` cuts a region out of a scanned page
            # AFTER the build and stamps it into questions.json, which is
            # what `pictures` above carries; `read_html_test.py` downloads a
            # file named by the page and has it BEFORE, so it puts it in the
            # source with everything else it read. Source wins, because a
            # re-read is the thing that would have corrected it.
            **({"picture": group["picture"] if group.get("picture")
                else pictures[gi]}
               if group.get("picture") or gi in pictures else {}),
            "type": group["type"],
            "instructions": group["instructions"],
            # Never on a lettered group: how long an answer may be is not a
            # question you can ask about a letter, and the schema refuses it.
            "word_limit": None if (lettered or fixed) else group.get("word_limit"),
            "config": config,
            "questions": questions,
        })

    if recovered:
        print(f"note: {recovered} replay span(s) found by searching the alignment for "
              "the answer's own words, the book having marked no margin number",
              file=sys.stderr)
    if moved:
        print(f"note: {moved} replay span(s) moved off their marker onto the answer's "
              "own words, which were said outside the turn the marker names",
              file=sys.stderr)
    if tightened:
        print(f"note: {tightened} replay span(s) longer than {LONG_SPAN // 1000}s "
              "narrowed to the answer's own words inside the turn", file=sys.stderr)
    if moved_back:
        print(f"note: {moved_back} replay span(s) moved onto the moment the "
              "answer is actually spoken, their marker being the claim that "
              "did not fit the order", file=sys.stderr)
    if widened:
        print(f"note: {widened} replay span(s) widened to take in an answer "
              "spoken just outside them", file=sys.stderr)
    if unplaced:
        print(f"note: {unplaced} replay span(s) dropped for not fitting the "
              "order the recording answers in; those answers get no replay "
              "button", file=sys.stderr)
    for w in warnings:
        print(f"note: {w}", file=sys.stderr)
    if problems:
        for p in problems:
            print(f"PROBLEM  {p}", file=sys.stderr)
        return 1

    (work / "questions.json").write_text(json.dumps(
        {"source": src.get("source", {}), "groups": out_groups}, indent=2, ensure_ascii=False))

    # Both stages in one go: the questions and their key come off the same
    # pages and are checked against each other above, so one succeeding
    # without the other is not a state this can reach.
    # A passage has no `stage` rows: `stage` is one row per SECTION per
    # stage, and a reading passage is a sibling of a section rather than one.
    # The UPDATE would match nothing and say nothing, which is the same
    # silence as a bug.
    conn = sqlite3.connect(SEED / "catalogue.db")
    if "-s" in section_id:
        done = (
            ("questions", {"groups": len(out_groups),
                           "questions": sum(len(g["questions"]) for g in out_groups)}),
            ("answer_key", {"accepted_answers": sum(
                len(q["correct_answers"]) for g in out_groups for q in g["questions"])}),
        )
        for name, meta in done:
            conn.execute(
                """UPDATE stage SET status = 'done', attempts = attempts + 1, error = NULL,
                       output_path = ?, meta = ?, updated_at = datetime('now')
                   WHERE section_id = ? AND name = ?""",
                (f"seed/work/{section_id}/questions.json", json.dumps(meta),
                 section_id, name))
    conn.commit()
    conn.close()

    for gi, group in enumerate(out_groups):
        total = sum(len(q["correct_answers"]) for q in group["questions"])
        replayed = sum(1 for q in group["questions"] if q["replay_start_ms"] is not None)
        print(f"group {gi} {group['type']}: {len(group['questions'])} questions, "
              f"{total} accepted answers, {replayed} with a replay span")
        for q in group["questions"]:
            when = (f"{q['replay_start_ms'] / 1000:6.1f}s"
                    if q["replay_start_ms"] is not None else "     -")
            print(f"  {q['number']:>3} {when}  {q['key']:<34} -> {q['correct_answers']}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("section_id")
    sys.exit(build(ap.parse_args().section_id))

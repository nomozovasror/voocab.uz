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
}
DEFAULT_CONFIG_KEYS = {"template", "options", "image_letters", "image", "image_adapt"}

#: The two that are answered by picking a letter rather than writing words.
#: They carry no template, so the gap checks below do not apply to them and
#: their answer key is a letter rather than a list of accepted phrasings.
LETTERED = {"multiple_choice", "matching"}
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
LETTER_RANGE = re.compile(r"letters?\s+([A-Z])\s*[-–—]\s*([A-Z])", re.I)
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

    # A section's questions are its own. The question pages of Section 1 and
    # Section 2 sit on the same sheets, so the reader hands back groups for
    # both -- and the answer key, asked only for this section's range, leaves
    # the other one's keys empty. Dropping them here rather than failing on an
    # empty key is the same rule the audioscript reader applies to a marker
    # outside its range: out of range is proof it belongs to the neighbour.
    section_no = int(section_id.split("-s")[1])
    lo, hi = (section_no - 1) * 10 + 1, section_no * 10
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
    covered = {n for g in kept for q in g["questions"]
               if (n := q.get("paper_number")) is not None}
    short = [n for n in range(lo, hi + 1) if n not in covered]
    if covered and short:
        raise SystemExit(
            f"PROBLEM  after dropping, questions {short} of {lo}-{hi} are "
            "missing; the page was misread")

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
        before = [spans[n][1] for n in spans if n < paper]
        after = [spans[n][0] for n in spans if n > paper]
        return (max(before) if before else 0,
                min(after) if after else 1 << 62)

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

    problems: list[str] = []
    warnings: list[str] = []
    recovered = 0
    out_groups = []
    for gi, group in enumerate(src["groups"]):
        lettered = group["type"] in LETTERED
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

        if not lettered:
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
            if lettered and not printed:
                # The key line was the note and nothing else, which means the
                # letters printed under it were not read. Better to say so than
                # to write a question with no answer.
                problems.append(
                    f"group {gi} q{q['number']}: the key line was {q['key']!r} with no "
                    "letters -- they are printed on the lines below it")
                continue
            if lettered:
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
            option_replay = ({letter: [span[0], span[1]] for letter in answers}
                             if span and group["type"] == "multiple_choice" else {})
            questions.append({
                "number": q["number"],
                "paper_number": q.get("paper_number"),
                "key": q["key"],                    # kept: the printed form
                "correct_answers": answers,
                "replay_start_ms": span[0] if span else None,
                "replay_end_ms": span[1] if span else None,
                **({"prompt": q["prompt"]} if q.get("prompt") else {}),
                **({"options": q["options"]} if q.get("options") else {}),
                **({"option_replay": option_replay} if option_replay else {}),
            })

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
        elif group["type"] == "matching":
            config = {"options": group.get("options") or [],
                      "allow_reuse": bool(group.get("reuse"))}
        else:
            drawn = 0
            if group["type"] in ("map_labelling", "diagram_labelling"):
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
            config = {"template": group.get("template") or "", "options": [],
                      "image_letters": drawn}
        allowed = CONFIG_KEYS.get(group["type"], DEFAULT_CONFIG_KEYS)
        unknown = set(config) - allowed
        if unknown:
            problems.append(
                f"group {gi}: config key(s) {sorted(unknown)} are not what a "
                f"{group['type']} group takes ({sorted(allowed)}) -- the server would "
                "drop them without a word")
        out_groups.append({
            "type": group["type"],
            "instructions": group["instructions"],
            # Never on a lettered group: how long an answer may be is not a
            # question you can ask about a letter, and the schema refuses it.
            "word_limit": None if lettered else group.get("word_limit"),
            "config": config,
            "questions": questions,
        })

    if recovered:
        print(f"note: {recovered} replay span(s) found by searching the alignment for "
              "the answer's own words, the book having marked no margin number",
              file=sys.stderr)
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
    conn = sqlite3.connect(SEED / "catalogue.db")
    for name, meta in (("questions", {"groups": len(out_groups),
                                      "questions": sum(len(g["questions"]) for g in out_groups)}),
                       ("answer_key", {"accepted_answers": sum(
                           len(q["correct_answers"]) for g in out_groups for q in g["questions"])})):
        conn.execute(
            """UPDATE stage SET status = 'done', attempts = attempts + 1, error = NULL,
                   output_path = ?, meta = ?, updated_at = datetime('now')
               WHERE section_id = ? AND name = ?""",
            (f"seed/work/{section_id}/questions.json", json.dumps(meta), section_id, name))
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

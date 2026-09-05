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

from answer_key import parse_answer

SEED = pathlib.Path(__file__).resolve().parent
WORK = SEED / "work"
GAP = re.compile(r"\{\{(\d+)\}\}")
#: The two that are answered by picking a letter rather than writing words.
#: They carry no template, so the gap checks below do not apply to them and
#: their answer key is a letter rather than a list of accepted phrasings.
LETTERED = {"multiple_choice", "matching"}
#: A letter, as the key prints it. "17-18.AE" is handled where the group is
#: built, not here: it is a statement about how two numbers share one question.
LETTERS = re.compile(r"^[A-H](?:\s*[,/&]?\s*[A-H])*$", re.I)
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


def build(section_id: str) -> int:
    work = WORK / section_id
    src = json.loads((work / "questions.src.json").read_text())

    aligned = turns = None
    if (work / "aligned.json").exists():
        aligned = json.loads((work / "aligned.json").read_text())
        turns = json.loads((work / "turns.json").read_text())

    #: marker -> the span of the turn it is printed against
    spans: dict[str, tuple[int, int]] = {}
    if aligned and turns:
        for index, turn in enumerate(turns):
            marker = turn.get("marker")
            if not marker:
                continue
            words = [w for w in aligned if w["turn"] == index]
            if words:
                spans[marker] = (words[0]["start_ms"], words[-1]["end_ms"])

    problems: list[str] = []
    warnings: list[str] = []
    out_groups = []
    for gi, group in enumerate(src["groups"]):
        lettered = group["type"] in LETTERED
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
            if lettered:
                # A lettered answer is the KEY, not a list of phrasings: the
                # letters must be picked exactly, and expanding "A" the way a
                # gap-fill answer is expanded would be nonsense.
                answers = [c.lower() for c in re.findall(r"[A-H]", printed, re.I)]
                if not LETTERS.match(printed):
                    problems.append(
                        f"group {gi} q{q['number']}: {printed!r} is not a letter, but "
                        f"this is a {group['type']} group")
            else:
                answers = parse_answer(printed)
            if not answers:
                problems.append(f"group {gi} q{q['number']}: key {q['key']!r} expands to nothing")
            span = spans.get(q.get("marker") or "")
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
            config = {"pick": int(group.get("pick") or 1)}
        elif group["type"] == "matching":
            config = {"options": group.get("options") or [],
                      "reuse": bool(group.get("reuse"))}
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
        out_groups.append({
            "type": group["type"],
            "instructions": group["instructions"],
            # Never on a lettered group: how long an answer may be is not a
            # question you can ask about a letter, and the schema refuses it.
            "word_limit": None if lettered else group.get("word_limit"),
            "config": config,
            "questions": questions,
        })

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

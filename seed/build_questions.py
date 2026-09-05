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
    out_groups = []
    for gi, group in enumerate(src["groups"]):
        gaps = [int(n) for n in GAP.findall(group["template"])]
        numbers = [q["number"] for q in group["questions"]]

        # The template and the questions are two readings of the same page, and
        # a disagreement between them means one of them was misread. The
        # backend refuses this too -- better to hear it here, by name.
        if sorted(gaps) != sorted(numbers):
            problems.append(
                f"group {gi}: template gaps {sorted(gaps)} != question numbers "
                f"{sorted(numbers)}")
        if len(gaps) != len(set(gaps)):
            problems.append(f"group {gi}: template repeats a gap number")

        rendered = gaps_that_render(group["template"])
        if rendered is None:
            print(f"note: could not run the layout check for group {gi} "
                  "(needs node and frontend/)", file=sys.stderr)
        elif set(gaps) - rendered:
            lost = sorted(set(gaps) - rendered)
            problems.append(
                f"group {gi}: gaps {lost} are in the template but the take page "
                f"would not draw them -- a line is colliding with the layout "
                f"grammar (a leading '+', '>', '#', or a '|')")

        questions = []
        for q in group["questions"]:
            answers = parse_answer(q["key"])
            if not answers:
                problems.append(f"group {gi} q{q['number']}: key {q['key']!r} expands to nothing")
            span = spans.get(q.get("marker") or "")
            if q.get("marker") and span is None:
                problems.append(
                    f"group {gi} q{q['number']}: marker {q['marker']} has no aligned turn")
            questions.append({
                "number": q["number"],
                "paper_number": q.get("paper_number"),
                "key": q["key"],                    # kept: the printed form
                "correct_answers": answers,
                "replay_start_ms": span[0] if span else None,
                "replay_end_ms": span[1] if span else None,
            })

        out_groups.append({
            "type": group["type"],
            "instructions": group["instructions"],
            "word_limit": group.get("word_limit"),
            "config": {"template": group["template"], "options": [], "image_letters": 0},
            "questions": questions,
        })

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

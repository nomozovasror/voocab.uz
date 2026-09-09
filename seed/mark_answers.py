"""Find where each answer is given, when the book printed no margin to read.

    seed/.venv/bin/python seed/mark_answers.py cam13-t3-s2

A margin marker is printed knowledge: the book says, against one line, that
this is where question 13 is answered. `read_audioscript.py` reads it, and
everything downstream depends on it.

Two kinds of section have none. One was heard rather than read
(`hear_audio.py`) and never had a margin. The other was read and the marker
was missed. `build_questions.py` covers most of what is left by searching the
alignment for the answer's own words -- but that only works when the answer IS
words. A "choose TWO letters" is answered by picking B and D, and neither
letter is spoken; the recording says the thing the letter stands for, in its
own phrasing.

So this asks the one question that remains: given the turns of this section and
what the answer to question N actually is, which turn is it given in? That is
a question about meaning, which is the one thing a model is better at here than
any matching rule.

**It is checked before it is believed.** A paper asks its questions in the
order the recording answers them, so placements must not go backwards. One that
does is dropped rather than written, on the same reasoning as everywhere else
in this pipeline: a marker on the wrong turn sends a learner to the wrong
second of a recording, and that is worse than no marker at all. Two questions
sharing a turn is allowed -- a "choose TWO" is answered in one breath, and the
book itself prints "17&18" against a single line.

Runs as part of the `questions` stage, between reading the page and building
from it, and does nothing at all when every question already has a marker.
"""

import argparse
import json
import pathlib
import sys

import vision

SEED = pathlib.Path(__file__).resolve().parent
WORK = SEED / "work"
#: Long enough to be worth placing, short enough that a model reading forty of
#: them is still reading rather than skimming.
QUOTE = 400

PROMPT = """Below are the numbered turns of one IELTS Listening section, and the
questions it asks with the CORRECT answer to each already given.

For each question, say which turn the answer is given in. The speaker does not
say the letter or read the gap aloud -- they say the thing itself, usually in
different words from the question. Judge by meaning.

The questions are answered in the order they are numbered, so the turns you
give must not go backwards. Two questions may share one turn.

If you cannot tell which turn answers a question, leave it out. A wrong turn is
worse than a missing one.

JSON only, no prose:

{"placements": [{"q": <question number>, "turn": <turn number>}]}

TURNS
{turns}

QUESTIONS
{questions}"""


def describe(group: dict, question: dict) -> str:
    """One question as the model needs to see it: what is asked, and what the
    right answer actually says. A letter alone tells it nothing -- the option
    the letter points at is the whole of the evidence."""
    number = question.get("paper_number") or question.get("number")
    asked = (question.get("prompt") or group.get("instructions") or "").strip()
    answers = question.get("correct_answers") or []
    options = question.get("options") or group.get("options") or []

    said = []
    for answer in answers:
        letter = answer.strip().lower()
        if len(letter) == 1 and "a" <= letter <= "z" and options:
            index = ord(letter) - ord("a")
            if index < len(options):
                text = options[index]
                said.append(f"{letter.upper()} = {text}")
                continue
        said.append(answer)
    return (f"Q{number}: {asked[:200]}\n"
            f"    correct: {'; '.join(said) or '(unknown)'}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("section_id")
    ap.add_argument("--model", default=vision.DEFAULT_MODEL)
    ap.add_argument("--all", action="store_true",
                    help="place every question, not only the unmarked ones")
    args = ap.parse_args()

    work = WORK / args.section_id
    turns_path, source = work / "turns.json", work / "questions.src.json"
    if not (turns_path.exists() and source.exists()):
        print(f"{args.section_id}: needs turns.json and questions.src.json",
              file=sys.stderr)
        return 0

    turns = json.loads(turns_path.read_text())
    groups = json.loads(source.read_text())["groups"]

    marked = {n for t in turns for n in _numbers(t.get("marker"))}
    wanted = []
    for group in groups:
        for question in group["questions"]:
            number = question.get("paper_number") or question.get("number")
            if args.all or number not in marked:
                wanted.append((number, describe(group, question)))
    if not wanted:
        print(f"  every question already carries a marker")
        return 0

    spoken = [(i, t) for i, t in enumerate(turns) if t.get("text")]
    said = vision.ask_json(
        PROMPT.replace("{turns}", "\n".join(
            f"[{i}] {t['speaker']}: {t['text'][:QUOTE]}" for i, t in spoken))
              .replace("{questions}", "\n".join(text for _, text in wanted)),
        [], model=args.model, max_tokens=2000)

    # Believed only where it does not contradict the numbering. `floor` is the
    # last turn accepted, so a placement earlier than one already taken by a
    # lower-numbered question is a placement in the wrong place.
    placements = sorted(
        ((int(p["turn"]), int(p["q"])) for p in said.get("placements", [])
         if isinstance(p, dict) and p.get("q") is not None and p.get("turn") is not None),
        key=lambda pair: pair[1])
    real = {i for i, _ in spoken}
    asked = dict(wanted)
    floor, placed, refused, done = -1, 0, [], set()
    for turn, number in placements:
        # `done` because the same question came back against two turns, and
        # writing both puts one question in two places in the recording --
        # which is the failure this whole file is written to avoid. The first
        # is kept: placements are walked in question order, so it is the one
        # the ordering check has already vouched for.
        if number in done:
            # The same question against a second turn. Not a disagreement to
            # report -- the first was accepted and this adds nothing.
            continue
        if turn not in real or turn < floor or number not in asked:
            refused.append(number)
            continue
        floor = turn
        done.add(number)
        existing = _numbers(turns[turn].get("marker"))
        if number not in existing:
            turns[turn]["marker"] = (f"{turns[turn]['marker']} Q{number}"
                                     if turns[turn].get("marker") else f"Q{number}")
            placed += 1

    turns_path.write_text(json.dumps(turns, indent=2, ensure_ascii=False))
    print(f"  placed {placed} of {len(wanted)} missing marker(s) by meaning")
    if placed and placed < len(wanted):
        print(f"  {len(wanted) - placed} still unplaced", file=sys.stderr)
    if refused:
        print(f"  refused {len(refused)}: Q{', Q'.join(str(n) for n in refused)} "
              "went backwards or named no turn", file=sys.stderr)
    return 0


def _numbers(marker: str | None) -> list[int]:
    import markers as marker_syntax
    return marker_syntax.numbers(marker) if marker else []


if __name__ == "__main__":
    sys.exit(main())

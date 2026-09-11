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
import re
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
    # `key` in questions.src.json, which is what this stage runs against;
    # `correct_answers` only exists after build_questions.py has expanded it.
    # Reading the built name off the source file gave every question
    # "correct: (unknown)", so the model was being asked where an answer it had
    # not been told is given -- and answered, reasonably, with nothing.
    answers = (question.get("correct_answers")
               or [a for a in [question.get("key")] if a])
    options = question.get("options") or group.get("options") or []

    said = []
    for answer in answers:
        letter = str(answer).strip().lower()
        if len(letter) == 1 and "a" <= letter <= "z" and options:
            index = ord(letter) - ord("a")
            if index < len(options):
                text = options[index]
                said.append(f"{letter.upper()} = {text}")
                continue
        said.append(answer)
    return (f"Q{number}: {asked[:200]}\n"
            f"    correct: {'; '.join(said) or '(unknown)'}")


def already_known(work: pathlib.Path, wanted: list[tuple[int, str]],
                  groups: list[dict]) -> dict[int, int]:
    """The turn each answer is in, for the answers that say so themselves.

    An answer whose words appear exactly once in the alignment needs no model
    to place it -- `build_questions.py` uses that to make a replay span. Here
    it is used for something else: as a set of answers whose turn is already
    known, to check the model's placements against. A reading that gets these
    wrong is a reading to throw away, and there is no reason to find that out
    only when a learner presses replay.
    """
    path = work / "aligned.json"
    if not path.exists():
        return {}
    aligned = json.loads(path.read_text())
    stream = [re.sub(r"[^a-z0-9]", "", w["word"].lower()) for w in aligned]
    keys = {q.get("paper_number") or q.get("number"): q.get("key")
            for g in groups for q in g["questions"]}
    known = {}
    for number, _ in wanted:
        for answer in str(keys.get(number) or "").split("/"):
            words = [w for w in (re.sub(r"[^a-z0-9]", "", x.lower())
                                 for x in answer.split()) if w]
            if not words or len("".join(words)) < 4:
                continue
            hits = [i for i in range(len(stream) - len(words) + 1)
                    if stream[i:i + len(words)] == words]
            if len(hits) == 1:
                known[number] = aligned[hits[0]]["turn"]
                break
    return known


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
    # EVERY question goes in the prompt, and only the unmarked ones come out of
    # it. Asking about the four a section is missing, out of ten, gives the
    # model four sentences and no sense of where in the recording it is; the
    # six it already knows are the anchors that place the four. Measured on
    # cam19-t2-s4: asked about four it put two in the wrong part of the
    # recording, asked about ten it got seven exactly right and none wrong.
    # The extra questions cost nothing -- it is the same one request -- and
    # they are what the check below has to work with.
    wanted, missing = [], set()
    for group in groups:
        for question in group["questions"]:
            number = question.get("paper_number") or question.get("number")
            wanted.append((number, describe(group, question)))
            if number not in marked:
                missing.add(number)
    if not missing:
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
    # Measured before anything is written. One turn either way is the answer
    # sitting across a boundary, which a replay span survives; further than
    # that is a placement in the wrong part of the recording, and if the model
    # does that to answers whose turn is knowable it is doing it to the others
    # too.
    known = already_known(work, wanted, groups)
    placed_by = {int(p["q"]): int(p["turn"]) for p in said.get("placements", [])
                 if isinstance(p, dict) and p.get("q") is not None
                 and p.get("turn") is not None}
    checked = {n: t for n, t in known.items() if n in placed_by}
    astray = [n for n, t in checked.items() if abs(placed_by[n] - t) > 1]
    if len(checked) >= 3:
        print(f"  checked against {len(checked)} answer(s) that name their own "
              f"turn: {len(checked) - len(astray)} within one turn")
    if astray and len(checked) >= 3 and len(astray) > len(checked) // 4:
        # Nothing is written, and that is the whole of the consequence. This
        # stage ADDS markers the book did not print; refusing to add them
        # leaves the section exactly as the book left it, with a replay span
        # for every question it marked and none for the rest -- which
        # build_questions.py already handles and reports by name. Returning
        # non-zero here instead failed the section outright and cost
        # trn-t1-s4, whose eight printed markers were never in doubt.
        print(f"  REFUSED the whole reading: Q{', Q'.join(str(n) for n in astray)} "
              f"of {len(checked)} checkable were placed more than one turn from "
              f"where their own words are. Nothing written; Q"
              f"{', Q'.join(str(n) for n in sorted(missing))} keep the book's "
              "silence and get no replay span", file=sys.stderr)
        return 0

    # Where the book's own markers already are. They bound a missing question
    # far better than a running floor does: Q39 sits between whatever turn
    # carries Q38 and whatever carries Q40, and that is true whether or not
    # the markers around it happen to run in order -- cam12-t3-s4 prints Q38
    # on one turn and Q37 on the next, and a floor that walked through the
    # context placements refused the one real answer because of it.
    at = {n: i for i, t in enumerate(turns) for n in _numbers(t.get("marker"))}

    def allowed(number: int) -> tuple[int, int]:
        """The turns a missing question can be in, from its NEAREST numbered
        neighbours either side.

        Nearest, not the extreme of all of them: a book's markers are not
        always in order -- cam12-t3-s4 prints Q38 on turn 7 and Q37 on turn 8
        -- and taking the furthest turn below made the window for Q39 a single
        turn that excluded the right one. Q38 and Q40 are what actually bound
        it.
        """
        below = max((n for n in at if n < number), default=None)
        above = min((n for n in at if n > number), default=None)
        low = at[below] if below is not None else 0
        high = at[above] if above is not None else len(turns) - 1
        return (low, high) if low <= high else (high, low)

    real = {i for i, _ in spoken}
    asked = dict(wanted)
    floor, placed, refused, done = -1, 0, [], set()
    for turn, number in placements:
        if number in missing and at:
            # Bounded by the book rather than by the walk.
            low, high = allowed(number)
            if not low <= turn <= high:
                refused.append(number)
                continue
            done.add(number)
            existing = _numbers(turns[turn].get("marker"))
            if turn in real and number not in existing:
                turns[turn]["marker"] = (f"{turns[turn]['marker']} Q{number}"
                                         if turns[turn].get("marker") else f"Q{number}")
                placed += 1
            continue
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
        if number not in missing:
            # Sent for context, not to be written. Its marker is the book's.
            continue
        existing = _numbers(turns[turn].get("marker"))
        if number not in existing:
            turns[turn]["marker"] = (f"{turns[turn]['marker']} Q{number}"
                                     if turns[turn].get("marker") else f"Q{number}")
            placed += 1

    turns_path.write_text(json.dumps(turns, indent=2, ensure_ascii=False))
    print(f"  placed {placed} of {len(missing)} missing marker(s) by meaning")
    if placed and placed < len(missing):
        print(f"  {len(missing) - placed} still unplaced", file=sys.stderr)
    if refused:
        print(f"  refused {len(refused)}: Q{', Q'.join(str(n) for n in refused)} "
              "went backwards or named no turn", file=sys.stderr)
    return 0


def _numbers(marker: str | None) -> list[int]:
    import markers as marker_syntax
    return marker_syntax.numbers(marker) if marker else []


if __name__ == "__main__":
    sys.exit(main())

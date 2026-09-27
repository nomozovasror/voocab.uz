"""Measure how often a listening answer's replay span is not evidence for its
answer, three ways -- see `seed/README.md` for the bug this was written to
chase down (`cam21-t4-s1`, Cambridge 21 Test 4 Section 1) and the fix in
`build_questions.py` it measures the corpus before and after.

    seed/.venv/bin/python seed/measure_evidence.py
    seed/.venv/bin/python seed/measure_evidence.py --before work-before

Three independent checks, over every word-answer (never a lettered one -- a
matching option is a paraphrase, and hunting a transcript for its wording
misses most answers that are perfectly correct, exactly as `build_questions.
in_order` already says):

(a) TURN      the span lies entirely inside a turn spoken by the section's
              questioner rather than the person the form is about.
(b) SPELLING  the answer is, somewhere in this section's own recording,
              spelled out letter by letter -- and the span does not reach
              the letters.
(c) TEXT      none of the answer's accepted phrasings are said inside the
              span at all.

A span can fail more than one check (Q1 in the report fails only (b); Q7 and
Q10 fail only (a) -- their span already contains the literal word, since
that IS where the interviewer says it). Reported separately because the
existing "does this span contain the answer" reasoning in `build_questions.
py` -- `reaches`, `in_order` -- already guards (c) for most of the corpus,
which is exactly why (a) and (b) went unnoticed: they are wrong in a way
(c)'s check does not see.
"""

import argparse
import json
import pathlib
import re
import sys

SEED = pathlib.Path(__file__).resolve().parent
WORK = SEED / "work"
sys.path.insert(0, str(SEED))

from build_questions import (LETTERED, LABELLING, FIXED_CHOICE, SPELLED_OUT,
                             dominant_speaker, spelled_word, from_a_box)


def normalize(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", word.lower())


def turn_of(aligned: list[dict], ms: int) -> int | None:
    """The turn whose words straddle this millisecond, nearest first."""
    best, best_gap = None, None
    for w in aligned:
        if w["start_ms"] <= ms <= w["end_ms"]:
            return w["turn"]
        gap = min(abs(w["start_ms"] - ms), abs(w["end_ms"] - ms))
        if best_gap is None or gap < best_gap:
            best, best_gap = w["turn"], gap
    return best


def contains_text(aligned: list[dict], answers: list[str],
                  lo: int, hi: int) -> bool:
    stream = [normalize(w["word"]) for w in aligned]
    for answer in answers:
        wanted = [normalize(w) for w in answer.split()]
        wanted = [w for w in wanted if w]
        if not wanted:
            continue
        for i in range(len(stream) - len(wanted) + 1):
            if (stream[i:i + len(wanted)] == wanted
                    and lo <= aligned[i]["start_ms"] <= hi):
                return True
    return False


def spelled_confirmation(aligned: list[dict], answers: list[str]
                         ) -> tuple[int, int] | None:
    """Where, ANYWHERE in the section, this answer is spelled out -- not
    bounded to a window, because this is the empirical test for "is this a
    spelling-type answer at all", not the corrected placement.
    """
    wanted = {spelled_word(a) for a in answers}
    for w in aligned:
        if SPELLED_OUT.match(w["word"]) and spelled_word(w["word"]) in wanted:
            return w["start_ms"], w["end_ms"]
    return None


def _final_speakers(built: dict, aligned: list[dict], paper_number: int,
                    turns: list[dict]) -> set[str]:
    """Every speaker this paper number's span FINALLY covers, after every
    existing correction in `build_questions.py` has run -- `locate`'s
    override, `reaches`'s widen, `in_order`'s drop. Empty if the question has
    no span, or is not this paper number at all.

    The whole SET and not just the turn the span starts in: `reaches` widens
    a marked turn forward to take in a word spoken just past it without
    moving the start, so `cam15-t4-s1`'s Q1 starts in the interviewer's turn
    and ends inside the reply that says "journalist" -- one span, two
    speakers, and asking only where it starts would call that turn the
    interviewer's alone.
    """
    for group in built["groups"]:
        for q in group["questions"]:
            if q.get("paper_number") != paper_number:
                continue
            lo, hi = q.get("replay_start_ms"), q.get("replay_end_ms")
            if lo is None:
                return set()
            start, end = turn_of(aligned, lo), turn_of(aligned, hi)
            if start is None or end is None:
                return set()
            return {turns[i].get("speaker") for i in range(start, end + 1)
                   if 0 <= i < len(turns)}
    return set()


def measure_section(section_id: str, questions_path: pathlib.Path
                    ) -> list[dict]:
    work = WORK / section_id
    turns_path, aligned_path = work / "turns.json", work / "aligned.json"
    if not (turns_path.exists() and aligned_path.exists()
            and questions_path.exists()):
        return []
    turns = json.loads(turns_path.read_text())
    aligned = json.loads(aligned_path.read_text())
    built = json.loads(questions_path.read_text())

    # Who the section is about, read off the markers `build_questions.py`
    # never had to second-guess. A marker the alignment's own unambiguous
    # words later moved away from is not a vote for the speaker it USED to
    # name -- `cam15-t4-s1` marks eight of its ten answers on the
    # interviewer, and `locate`'s "the words win" rule has already relocated
    # seven of those eight onto the respondent by the time this runs, which
    # would otherwise call the respondent's own, already-correct turn wrong a
    # second time. A marker the build left exactly where it was printed is
    # the trustworthy kind: either it was already right, or nothing could
    # prove it wasn't.
    #
    # This is still a majority vote over one section, and a vote is only
    # ever as good as the assumption that the section has ONE respondent.
    # `cam10-t1-s1` does not: an interviewee for the first half of the call
    # and the one asking the questions for the second, once the travel agent
    # starts pricing tours. The same 2x-majority guard that stops
    # `build_questions.py` from acting on a thin margin stops this from
    # claiming one -- five markers a side, unmoved, is silence rather than a
    # coin toss. Below that guard this section prints nothing, which is why
    # "worst sections" below is a list to read, not one to act on unread.
    import markers as marker_syntax
    marked_at = {n: i for i, t in enumerate(turns)
                for n in marker_syntax.numbers(t.get("marker"))}
    unmoved = {n: i for n, i in marked_at.items()
              if _final_speakers(built, aligned, n, turns)
              == {turns[i].get("speaker")}}
    dominant = dominant_speaker(turns, unmoved)

    rows = []
    for group in built["groups"]:
        lettered = (group["type"] in LETTERED
                   or (group["type"] in LABELLING
                       and bool(from_a_box(group) or group.get("options"))))
        if lettered or group["type"] in FIXED_CHOICE:
            continue
        for q in group["questions"]:
            lo, hi = q.get("replay_start_ms"), q.get("replay_end_ms")
            if lo is None:
                continue
            answers = q.get("correct_answers") or []
            # A single letter is a map or box reference that missed the
            # `lettered` test above -- a genuine, separate bug in reading
            # the picture, not in placing the evidence. A bare letter is
            # never spoken, so counting it here would measure that bug
            # under this one's name instead of its own.
            if answers and all(re.fullmatch(r"[A-Za-z]", a.strip())
                               for a in answers):
                continue
            start_turn, end_turn = turn_of(aligned, lo), turn_of(aligned, hi)

            turn_fail = False
            if dominant and start_turn is not None and end_turn is not None:
                speakers = {turns[i].get("speaker")
                           for i in range(start_turn, end_turn + 1)
                           if 0 <= i < len(turns)}
                turn_fail = bool(speakers) and dominant not in speakers

            spelled = spelled_confirmation(aligned, answers)
            spelling_fail = (spelled is not None
                             and not (lo <= spelled[0] and spelled[1] <= hi))

            text_fail = not contains_text(aligned, answers, lo, hi)

            if turn_fail or spelling_fail or text_fail:
                rows.append({
                    "section": section_id,
                    "number": q.get("paper_number") or q["number"],
                    "key": q.get("key"), "turn": turn_fail,
                    "spelling": spelling_fail, "text": text_fail,
                })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--questions-dir", default=None,
                    help="read questions.json from here instead of work/<id>/ "
                         "(e.g. work-before, for a snapshot taken pre-fix)")
    args = ap.parse_args()

    rows = []
    for d in sorted(WORK.iterdir()):
        if not d.is_dir() or not d.name.startswith("cam"):
            continue
        qpath = (pathlib.Path(args.questions_dir) / d.name / "questions.json"
                 if args.questions_dir else d / "questions.json")
        rows.extend(measure_section(d.name, qpath))

    by_section: dict[str, int] = {}
    turn_n = spelling_n = text_n = 0
    for r in rows:
        by_section[r["section"]] = by_section.get(r["section"], 0) + 1
        turn_n += r["turn"]
        spelling_n += r["spelling"]
        text_n += r["text"]

    print(f"{len(rows)} answer(s) flagged, across {len(by_section)} section(s)")
    print(f"  (a) turn belongs to the questioner, not the respondent: {turn_n}")
    print(f"  (b) a spelling exists and the span does not reach it:   {spelling_n}")
    print(f"  (c) span contains none of the accepted answers at all:  {text_n}")
    print()
    print("worst sections:")
    for section, n in sorted(by_section.items(), key=lambda p: -p[1])[:15]:
        detail = [f"Q{r['number']}" + "".join(
            c for c, flag in (("a", r["turn"]), ("b", r["spelling"]),
                              ("c", r["text"])) if flag)
                 for r in rows if r["section"] == section]
        print(f"  {section}: {n}  {' '.join(detail)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

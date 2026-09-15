"""Which seeded sections are wrong, measured rather than trusted.

    seed/.venv/bin/python seed/verify.py
    seed/.venv/bin/python seed/verify.py --below 0.7 --ids

Every other check in this pipeline asks whether a stage *ran*. A stage can run,
exit zero, and produce something wrong: the page that was read was the wrong
page. Nothing downstream notices, because each stage believes what the one
before it wrote.

Two things here are cross-checks -- they compare one stage's output against
another's, so a mistake has to be made twice in the same direction to survive.

**Alignment score.** `align.py` fits the audioscript to the recording. A
transcript that belongs to a different section still aligns, because forced
alignment always returns a path; it just returns a bad one. Across 160 sections
the median word score is 0.91, and the sections that were wrong scored 0.04 to
0.23 -- not a close call, and the gap is wide enough that a threshold anywhere
in the middle picks out the same set. This is what found five sections whose
`turns.json` was read before their audioscript pages were corrected and never
re-read: the catalogue said the right pages, the file on disk was from the
wrong ones, and every stage after it agreed with the file.

**Answers in the audioscript.** A gap-fill answer is a word the speaker says,
so it should appear in that section's own transcript. Only word answers can be
checked -- a letter picked off a box or a picture is not in the script at all,
and neither is a labelling group's -- so those are skipped rather than counted
as misses. This is the check that caught an entire test answered from the
reading paper's key.

**Answers inside the span they replay.** A replay span is a promise -- press
this and hear the answer again -- and the words between `replay_start_ms` and
`replay_end_ms` are exactly what gets played. Whether the answer is among them
is a sharper question than whether it is anywhere in the transcript, and it is
the only check that reaches a book printing no question numbers at all: the
Official Cambridge Guide underlines its answers and numbers none of them, so
which question a marker belongs to is an inference, and this measures that
inference against a key that came off a different page.

**Markers that run backwards.** A paper asks its questions in the order the
recording answers them, so the Q numbers down an audioscript page run up. A
number lower than one already passed means the page was read out of order --
two columns taken across rather than down -- and every replay span built from
those markers sends a learner to the wrong minute. This found the same three
sections of IELTS Trainer that the alignment score did, from a completely
different direction: `trn-t1-s3` came back marked 23, 24, 21, 22. Repeats are
not that; the books print "Q21/22" against the line and again over the
question, so 21, 22, 21, 22, 23 is what a pair looks like.

None of the three is proof. A low score is a section to look at, and looking
is cheap:
re-read the audioscript, re-align, and see whether the number moves.
"""

import argparse
import json
import pathlib
import re
import sqlite3
import statistics
import sys

import markers as marker_syntax

SEED = pathlib.Path(__file__).resolve().parent
WORK = SEED / "work"
#: Where a real disagreement sits, well below the 0.91 the corpus runs at and
#: well above the 0.23 of the worst genuine failure found so far.
FLOOR = 0.70
#: Below this fraction of a section's word answers appearing in its own
#: transcript, something is being read off the wrong page.
FOUND = 0.5
#: Below this fraction of a section's word answers falling inside the span
#: their own question replays, the markers are on the wrong turns.
ON_SPAN = 0.6


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", (text or "").lower())


def score(section: pathlib.Path) -> float | None:
    """The mean per-word alignment score, or None if it has not been aligned."""
    path = section / "aligned.json"
    if not path.exists():
        return None
    scores = [w["score"] for w in json.loads(path.read_text())
              if isinstance(w, dict) and w.get("score") is not None]
    return statistics.mean(scores) if scores else None


def heard(section: pathlib.Path) -> tuple[int, int] | None:
    """How many of this section's word answers appear in its own transcript."""
    questions, turns = section / "questions.json", section / "turns.json"
    if not (questions.exists() and turns.exists()):
        return None
    script = " " + " ".join(norm(" ".join(
        t.get("text", "") for t in json.loads(turns.read_text()))).split()) + " "
    found = total = 0
    for group in json.loads(questions.read_text())["groups"]:
        for question in group["questions"]:
            # Substring rather than word equality: the key prints "graphic(s)"
            # where the speaker says "graphics".
            words = [w for answer in (question.get("correct_answers") or [])
                     for w in norm(answer).split() if len(w) > 3]
            if not words:
                continue
            total += 1
            found += any(w in script for w in words)
    return (found, total) if total else None


def on_the_span(section: pathlib.Path) -> tuple[int, int] | None:
    """How many word answers are inside the span the learner is given.

    A sharper question than whether the answer is somewhere in the transcript.
    A replay span is a promise -- press this and hear the answer again -- and
    the words between `replay_start_ms` and `replay_end_ms` are exactly what
    is played. If the answer is not among them the promise is broken, whatever
    the alignment score says.

    It is also the only check that reaches a book which prints no question
    numbers. The Official Cambridge Guide underlines its answers and numbers
    none of them, so which question a marker belongs to is an inference; this
    measures the inference against the key, which came off a different page.
    """
    questions, aligned = section / "questions.json", section / "aligned.json"
    if not (questions.exists() and aligned.exists()):
        return None
    words = json.loads(aligned.read_text())
    inside = total = 0
    for group in json.loads(questions.read_text())["groups"]:
        for question in group["questions"]:
            start, end = question.get("replay_start_ms"), question.get("replay_end_ms")
            wanted = [w for answer in (question.get("correct_answers") or [])
                      for w in norm(answer).split() if len(w) > 3]
            if not wanted or start is None or end is None:
                continue
            said = " " + " ".join(norm(w["word"]) for w in words
                                  if start <= w["start_ms"] <= end) + " "
            total += 1
            inside += any(f" {w} " in said or w in said for w in wanted)
    return (inside, total) if total else None


def backwards(section: pathlib.Path) -> list[int]:
    """The markers that are lower than one earlier in the transcript."""
    path = section / "turns.json"
    if not path.exists():
        return []
    walked, seen, back = -1, set(), []
    for turn in json.loads(path.read_text()):
        if not turn.get("marker") or marker_syntax.is_example(turn["marker"]):
            continue
        for number in marker_syntax.numbers(turn["marker"]):
            # `not in seen`, because a number coming round AGAIN is a pair
            # printed twice -- "Q21/22" against the line answering both, and
            # again over the question -- which is how the books write it and
            # is not a page read out of order. A number that has never been
            # passed arriving below one that has is.
            if number < walked and number not in seen:
                back.append(number)
            seen.add(number)
            walked = max(walked, number)
    return back


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--below", type=float, default=FLOOR,
                    help=f"flag sections aligning below this (default {FLOOR})")
    ap.add_argument("--ids", action="store_true",
                    help="print just the flagged ids, for feeding to run_pipeline")
    args = ap.parse_args()

    rows = []
    for section in sorted(WORK.iterdir()):
        if not section.is_dir():
            continue
        fit = score(section)
        if fit is None:
            continue
        answers = heard(section)
        rows.append((fit, section.name, answers, backwards(section),
                     on_the_span(section)))

    if not rows:
        print("nothing aligned yet", file=sys.stderr)
        return 1

    flagged = [r for r in rows if r[0] < args.below
               or (r[2] and r[2][1] >= 5 and r[2][0] / r[2][1] < FOUND)
               or r[3]
               or (r[4] and r[4][1] >= 5 and r[4][0] / r[4][1] < ON_SPAN)]
    if args.ids:
        print(" ".join(name for _, name, *_ in sorted(flagged, key=lambda r: r[0])))
        return 0

    conn = sqlite3.connect(SEED / "catalogue.db")
    elsewhere = conn.execute(
        "SELECT id, question_source FROM section "
        "WHERE question_source IS NOT NULL ORDER BY id").fetchall()

    middle = statistics.median(fit for fit, *_ in rows)
    landed = [r[4] for r in rows if r[4]]
    if landed:
        print(f"{sum(a for a, _ in landed)}/{sum(b for _, b in landed)} word answers "
              f"fall inside the span their question replays")
    print(f"{len(rows)} aligned sections, median word score {middle:.3f}")
    if elsewhere:
        # Said every time rather than kept in a column nobody opens. The book
        # is the source of record; these are the sections whose question
        # wording came from a page on the internet because the PDF would not
        # read straight. Their ANSWERS still came off the book's key, so this
        # is a provenance note and not a doubt about correctness.
        where = sorted({url for _, url in elsewhere})
        print(f"{len(elsewhere)} section(s) had their questions read from "
              f"{len(where)} page(s) rather than the book:")
        for url in where:
            named = [sid for sid, u in elsewhere if u == url]
            print(f"  {url}\n    {', '.join(named)}")
    print()
    if not flagged:
        print(f"none below {args.below}")
        return 0

    # A section already known to be unfixable carries the reason in the
    # catalogue. Printing it here is what stops the same page being chased
    # twice: one of these is a sheet the scan never had, and no re-read of the
    # pages it does have will ever produce it.
    conn = sqlite3.connect(SEED / "catalogue.db")
    notes = dict(conn.execute("SELECT id, note FROM section WHERE note IS NOT NULL"))
    conn.close()

    print(f"{'section':<14}{'align':>7}  answers heard   on their span")
    for fit, name, answers, back, landed in sorted(flagged, key=lambda r: r[0]):
        told = f"{answers[0]}/{answers[1]}" if answers else "-"
        span = f"{landed[0]}/{landed[1]}" if landed else "-"
        print(f"{name:<14}{fit:>7.3f}  {told:<15} {span}")
        if back:
            print(f"{'':<14}         markers run backwards at "
                  f"Q{', Q'.join(str(n) for n in back)}")
        note = notes.get(name, "")
        if note and not note.startswith("trimmed:"):
            print(f"{'':<14}         {note[:96]}")
    print(f"\n{len(flagged)} to look at. Re-read and re-align one with\n"
          f"  seed/run_pipeline.py <id> --force audioscript,align,questions,import\n"
          "and see whether the score moves; that is the whole test.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

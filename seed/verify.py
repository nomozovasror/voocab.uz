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

Neither is proof. A low score is a section to look at, and looking is cheap:
re-read the audioscript, re-align, and see whether the number moves.
"""

import argparse
import json
import pathlib
import re
import sqlite3
import statistics
import sys

SEED = pathlib.Path(__file__).resolve().parent
WORK = SEED / "work"
#: Where a real disagreement sits, well below the 0.91 the corpus runs at and
#: well above the 0.23 of the worst genuine failure found so far.
FLOOR = 0.70
#: Below this fraction of a section's word answers appearing in its own
#: transcript, something is being read off the wrong page.
FOUND = 0.5


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
        rows.append((fit, section.name, answers))

    if not rows:
        print("nothing aligned yet", file=sys.stderr)
        return 1

    flagged = [r for r in rows if r[0] < args.below
               or (r[2] and r[2][1] >= 5 and r[2][0] / r[2][1] < FOUND)]
    if args.ids:
        print(" ".join(name for _, name, _ in sorted(flagged, key=lambda r: r[0])))
        return 0

    middle = statistics.median(fit for fit, _, _ in rows)
    print(f"{len(rows)} aligned sections, median word score {middle:.3f}\n")
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

    print(f"{'section':<14}{'align':>7}  answers heard")
    for fit, name, answers in sorted(flagged, key=lambda r: r[0]):
        told = f"{answers[0]}/{answers[1]}" if answers else "-"
        print(f"{name:<14}{fit:>7.3f}  {told}")
        note = notes.get(name, "")
        if note and not note.startswith("trimmed:"):
            print(f"{'':<14}         {note[:96]}")
    print(f"\n{len(flagged)} to look at. Re-read and re-align one with\n"
          f"  seed/run_pipeline.py <id> --force audioscript,align,questions,import\n"
          "and see whether the score moves; that is the whole test.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

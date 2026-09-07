"""Attach margin markers that were read by eye rather than by a model.

    seed/.venv/bin/python seed/place_markers.py cam17-t1-s1 \
        '{"7": "the price of the ticket", "8": "bring a waterproof jacket"}'

Nineteen sections came out of the automated readings still short of a marker or
two, and 75 markers is a smaller job to do by looking than to keep paying a
model to guess at. The quote is a few words of the line the marker sits
against; this finds the turn whose text carries them and writes the marker onto
it, using the same backing-off match the model's own second pass uses -- so a
quote that drifts by a word still lands.

Nothing here trusts the quote blindly. A marker that matches no turn is
reported and not written, because a marker on the wrong turn is worse than a
missing one: it sends a learner to the wrong second of the recording.
"""

import argparse
import json
import pathlib
import sys

import markers as marker_syntax

SEED = pathlib.Path(__file__).resolve().parent
WORK = SEED / "work"


def place(turns: list[dict], readings: dict[int, str]) -> tuple[int, list[int]]:
    import re

    def key(text: str) -> str:
        return re.sub(r"[^a-z0-9 ]", "", (text or "").lower())

    placed, lost = 0, []
    for number, quote in sorted(readings.items()):
        words = key(quote).split()
        hit = None
        for size in range(len(words), 2, -1):
            probe = " ".join(words[:size])
            hit = next((t for t in turns if probe in key(t["text"])), None)
            if hit:
                break
        if hit is None:
            lost.append(number)
            continue
        if number not in marker_syntax.numbers(hit.get("marker")):
            hit["marker"] = (f"{hit['marker']} Q{number}"
                             if hit.get("marker") else f"Q{number}")
            placed += 1
    return placed, lost


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("section_id")
    ap.add_argument("readings", help='JSON: {"7": "a few words of the line", ...}, '
                                     'or with --append a list of turn objects')
    ap.add_argument("--append", action="store_true",
                    help="add turns to the end of the transcript instead of "
                         "marking the ones already there")
    args = ap.parse_args()

    path = WORK / args.section_id / "turns.json"
    if not path.exists():
        raise SystemExit(f"no turns.json for {args.section_id}")
    turns = json.loads(path.read_text())

    if args.append:
        # Some transcripts stop at a page break -- the reader took the first
        # page and never came back for the second, so the turns themselves are
        # missing and there is nothing for a marker to attach to. These are
        # read off the page and appended whole.
        added = [{"speaker": t.get("speaker") or "SPEAKER",
                  "text": (t.get("text") or "").strip(),
                  "marker": t.get("marker") or None,
                  "answer": t.get("answer") or None}
                 for t in json.loads(args.readings)]
        turns.extend(t for t in added if t["text"] or t["speaker"] == "__BREAK__")
        path.write_text(json.dumps(turns, indent=2, ensure_ascii=False))
        print(f"{args.section_id}: appended {len(added)} turn(s)")
        section = int(args.section_id.split("-s")[1])
        first, last = (section - 1) * 10 + 1, section * 10
        seen = {n for t in turns for n in marker_syntax.numbers(t.get("marker"))
                if not marker_syntax.is_example(t.get("marker"))}
        print(f"  still missing: {[n for n in range(first, last+1) if n not in seen] or 'none'}")
        return 0

    readings = {int(k): v for k, v in json.loads(args.readings).items()}

    placed, lost = place(turns, readings)
    path.write_text(json.dumps(turns, indent=2, ensure_ascii=False))

    section = int(args.section_id.split("-s")[1])
    first, last = (section - 1) * 10 + 1, section * 10
    seen = {n for t in turns for n in marker_syntax.numbers(t.get("marker"))
            if not marker_syntax.is_example(t.get("marker"))}
    still = [n for n in range(first, last + 1) if n not in seen]

    print(f"{args.section_id}: placed {placed}")
    if lost:
        print(f"  no turn carries the quoted line for {lost} -- not written", file=sys.stderr)
    print(f"  still missing: {still or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

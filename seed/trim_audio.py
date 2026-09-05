"""Cut a section's recording down to the part the book actually prints.

    seed/.venv/bin/python seed/trim_audio.py cam11-t1-s1

A Cambridge recording opens with about three minutes that are not the test:
the general instructions, "now turn to Section 1", the half-minute to read the
questions, and the example played once as a demonstration before the section
starts over. It ends with another minute of "you now have half a minute to
check your answers" and silence. For cam11-t1-s1 that is 185 seconds at the
front and 46 at the back of a 578-second file.

**Where to cut is not guessed -- it is where the alignment starts.** Everything
before the first aligned word is audio the audioscript has no text for, which
is exactly the definition of "not the section". That makes this adapt on its
own to the difference the user noticed: Part 1 carries the long preamble
because it carries the example, and Parts 2 to 4 carry a much shorter one.

Nothing the book prints is lost. The Section 1 audioscript begins at "Hello?",
and the example is inside the conversation that follows it -- what goes is the
narration and the demonstration playing, not the exchange itself.

Writes `audio.mp3` and `trim.json` beside the alignment. The importer shifts
every timestamp by the offset recorded there, so the transcript and the replay
spans still point at the right moments in the shorter file.
"""

import argparse
import json
import pathlib
import sqlite3
import subprocess
import sys
import tempfile

import numpy as np
import soundfile as sf

SEED = pathlib.Path(__file__).resolve().parent
REPO = SEED.parent
MATERIALS = REPO / "Materials"
WORK = SEED / "work"

#: Enough that the first word is not clipped by the cut and the last is not
#: cut off mid-syllable, and little enough that the preamble does not survive.
LEAD_IN_MS = 1500
TAIL_MS = 1500

#: The cut is only as good as the alignment it reads, so it is checked before
#: it is trusted. Judged over a WINDOW rather than the first word alone: that
#: word sits directly against the star that swallowed three minutes of
#: narration and is systematically the least certain thing on the page. On
#: cam11-t1-s1 it scores 0.40 while the first ten words average 0.84, so a
#: threshold on the single word refuses the very cut it exists to approve.
OPENING_WINDOW = 10
MIN_OPENING_SCORE = 0.6
MAX_HEAD_FRACTION = 0.45
MAX_HEAD_MS = 300_000


def load(path: pathlib.Path) -> tuple[np.ndarray, int]:
    """Samples and rate, whatever container the file arrived in."""
    try:
        return sf.read(path, dtype="float32", always_2d=True)
    except sf.LibsndfileError:
        # libsndfile has no AAC, which is what Cambridge 14 is.
        with tempfile.TemporaryDirectory() as td:
            wav = pathlib.Path(td) / "decoded.wav"
            subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16", str(path), str(wav)],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return sf.read(wav, dtype="float32", always_2d=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("section_id")
    ap.add_argument("--keep-tail", action="store_true",
                    help="cut only the preamble, leaving the end as it is")
    ap.add_argument("--force", action="store_true",
                    help="cut anyway when the checks say the alignment cannot "
                         "be trusted to say where the section starts")
    args = ap.parse_args()

    work = WORK / args.section_id
    aligned = json.loads((work / "aligned.json").read_text())
    if not aligned:
        raise SystemExit(f"{args.section_id}: nothing aligned, so nothing to cut to")

    conn = sqlite3.connect(SEED / "catalogue.db")
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM section WHERE id = ?", (args.section_id,)).fetchone()
    conn.close()
    if row is None:
        raise SystemExit(f"{args.section_id} is not in the catalogue")

    audio, rate = load(MATERIALS / row["rel_path"])
    total_ms = int(len(audio) / rate * 1000)

    first = aligned[0]
    head_ms = first["start_ms"]
    opening = aligned[:OPENING_WINDOW]
    opening_score = sum(w.get("score", 1.0) for w in opening) / len(opening)
    refusals = []
    if opening_score < MIN_OPENING_SCORE:
        refusals.append(
            f"the first {len(opening)} words average {opening_score:.2f}, so the "
            "alignment is not sure where the section starts")
    if head_ms > MAX_HEAD_MS or head_ms > total_ms * MAX_HEAD_FRACTION:
        refusals.append(
            f"the preamble would be {head_ms / 1000:.0f}s of a "
            f"{total_ms / 1000:.0f}s file, which is more than any real one")
    if refusals and not args.force:
        for r in refusals:
            print(f"REFUSING  {r}", file=sys.stderr)
        print("Listen to the start, then re-run with --force if it is right.",
              file=sys.stderr)
        return 1

    start_ms = max(0, head_ms - LEAD_IN_MS)
    end_ms = (total_ms if args.keep_tail
              else min(total_ms, aligned[-1]["end_ms"] + TAIL_MS))
    if end_ms <= start_ms:
        raise SystemExit(f"{args.section_id}: the cut would be empty")

    cut = audio[int(start_ms / 1000 * rate):int(end_ms / 1000 * rate)]
    out = work / "audio.mp3"
    sf.write(out, cut, rate, format="MP3")

    (work / "trim.json").write_text(json.dumps({
        "source": row["rel_path"],
        "source_sha256": row["sha256"],
        "offset_ms": start_ms,
        "duration_ms": end_ms - start_ms,
        "cut_head_ms": start_ms,
        "cut_tail_ms": total_ms - end_ms,
    }, indent=2))

    print(f"{args.section_id}: {total_ms / 1000:.0f}s -> {(end_ms - start_ms) / 1000:.0f}s")
    print(f"  cut {start_ms / 1000:.0f}s of preamble and "
          f"{(total_ms - end_ms) / 1000:.0f}s of tail "
          f"(opening confidence {opening_score:.2f})")
    print(f"  {out.relative_to(REPO)} ({out.stat().st_size / 1e6:.1f} MB, "
          f"was {(MATERIALS / row['rel_path']).stat().st_size / 1e6:.1f} MB)")

    conn = sqlite3.connect(SEED / "catalogue.db")
    conn.execute("UPDATE section SET note = ? WHERE id = ?",
                 (f"trimmed: {start_ms // 1000}s preamble, "
                  f"{(total_ms - end_ms) // 1000}s tail", args.section_id))
    conn.commit()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

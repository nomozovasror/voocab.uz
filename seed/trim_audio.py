"""Cut a section's recording down to the part the book actually prints.

    seed/.venv/bin/python seed/trim_audio.py cam11-t1-s1

What goes is the book-level preamble that repeats on every recording -- "you
will hear a number of different recordings ... the test is in four sections".
What stays is the section itself, and a section starts before its first word:

    0 - 85s     general instructions, then "you will hear a conversation ...
                first you have some time to look at questions 1 to 10"
    85 - 116s   the pause to read them          <- part of the test
    116 - 181s  the example, played and explained  <- part of the test
    185s        the conversation begins

The first version of this cut at 185s and was wrong in a way worth recording:
it took the introduction and the reading pause with it, so the recording opened
mid-conversation with nothing telling the candidate what they were about to
hear or any time to read the questions. Sitting a paper is not only hearing
the words on it.

**The cut is anchored on the reading pause, not on the first word.** That pause
is the longest silence before the content and is unmistakable -- 30.7 seconds
where nothing else comes near it -- and the speech immediately before it is the
section introduction by construction. Cutting a fixed lead ahead of it keeps
the introduction and everything after, and drops the general instructions,
which say the same thing on all 176 recordings.

A section with no such pause is not trimmed at the front at all. Guessing where
a preamble ends is how the first version removed the test.

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

#: How much to keep ahead of the reading pause. The section introduction runs
#: ten to twenty seconds ("you will hear a conversation between ... first you
#: have some time to look at questions 1 to 10"), so thirty keeps all of it
#: with room to spare and still drops the general instructions before it.
INTRO_LEAD_MS = 30_000
#: What counts as the reading pause. Sentence gaps in the narration run two to
#: four seconds; the pause is half a minute, so there is no contest.
MIN_READING_PAUSE_MS = 15_000
#: Dead air at the end goes; speech at the end does not. "That is the end of
#: Section 1, you now have half a minute to check your answers" is the test
#: talking, the same as the introduction is.
TAIL_SILENCE_KEEP_MS = 2000

#: A cut bigger than this share of the preamble means the silence picked was
#: not the reading pause. Refuse rather than remove the test.
MAX_HEAD_FRACTION = 0.75
#: The gap between two narrated sentences. The cut is snapped back to one of
#: these so the recording opens on a sentence rather than halfway through a
#: word: thirty seconds before the pause lands mid-sentence more often than
#: not, because nothing made it line up with anything.
SENTENCE_GAP_MS = 1500


def silences(mono: np.ndarray, rate: int, min_ms: int) -> list[tuple[int, int]]:
    """Stretches of quiet, in milliseconds. Measured against the recording's
    own loudness rather than an absolute level, because these are transfers of
    varying age and gain."""
    win = max(1, int(0.1 * rate))
    frames = mono[:len(mono) // win * win].reshape(-1, win)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    quiet = rms < np.percentile(rms, 92) * 0.06

    runs, start = [], None
    for i, is_quiet in enumerate(quiet):
        if is_quiet and start is None:
            start = i
        elif not is_quiet and start is not None:
            if (i - start) * 100 >= min_ms:
                runs.append((start * 100, i * 100))
            start = None
    if start is not None and (len(quiet) - start) * 100 >= min_ms:
        runs.append((start * 100, len(quiet) * 100))
    return runs


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
    mono = audio.mean(axis=1)
    total_ms = int(len(mono) / rate * 1000)
    content_ms = aligned[0]["start_ms"]

    quiet = silences(mono, rate, MIN_READING_PAUSE_MS)
    before = [(a, b) for a, b in quiet if b <= content_ms]
    pause = max(before, key=lambda r: r[1] - r[0], default=None)

    if pause is None:
        print(f"  no reading pause found before {content_ms / 1000:.0f}s -- "
              "leaving the front alone rather than guessing where it ends")
        start_ms = 0
    else:
        target = max(0, pause[0] - INTRO_LEAD_MS)
        # Snap back to the last gap between sentences at or before the target,
        # so the recording opens on a whole sentence. Back rather than forward:
        # keeping a little too much of the introduction costs seconds, cutting
        # into it costs the sentence that says what the candidate will hear.
        gaps = [b for a, b in silences(mono, rate, SENTENCE_GAP_MS) if b <= target]
        start_ms = gaps[-1] if gaps else 0
        snapped = start_ms != target
        if start_ms > content_ms * MAX_HEAD_FRACTION and not args.force:
            print(f"REFUSING  the cut would drop {start_ms / 1000:.0f}s, more than "
                  f"{MAX_HEAD_FRACTION:.0%} of the {content_ms / 1000:.0f}s before "
                  "the content -- the pause found is probably not the reading pause",
                  file=sys.stderr)
            return 1

    # Trailing DEAD AIR, not the trailing narration: "that is the end of
    # Section 1" belongs to the test the same way the introduction does.
    tail = [(a, b) for a, b in silences(mono, rate, 3000) if b >= total_ms - 500]
    end_ms = total_ms
    if tail and not args.keep_tail:
        end_ms = min(total_ms, tail[-1][0] + TAIL_SILENCE_KEEP_MS)
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
    if pause:
        print(f"  reading pause at {pause[0] / 1000:.0f}-{pause[1] / 1000:.0f}s "
              f"({(pause[1] - pause[0]) / 1000:.0f}s); keeping from "
              f"{start_ms / 1000:.0f}s so the introduction survives"
              + (" (snapped to a sentence gap)" if snapped else ""))
    print(f"  cut {start_ms / 1000:.0f}s of general instructions and "
          f"{(total_ms - end_ms) / 1000:.0f}s of dead air")
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

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

**The preamble is transcribed, not guessed at.** Two earlier versions guessed
-- first at the alignment's first word, which cut the introduction and the
reading pause off with the branding, then at a fixed lead ahead of the reading
pause, which landed in the middle of "the test is in four sections". Silence
tells you where sentences end and nothing about which sentence is which.

So the first two minutes go through Groq's `whisper-large-v3` once, and the cut
lands on the first segment that announces the test:

       0.0 -   6.4   Cambridge English, IELTS 11, Tests 1-4.
       8.2 -  14.6   Published by Cambridge University Press ...
      16.2 -  18.0   This recording is copyright.
      19.8 -  20.9   CD 1.
      23.0 -  24.3   Test 1.                          <- the cut
      24.3 -  32.9   You will hear a number of different recordings ...
      61.2 -  77.5   Now turn to section one ... You will hear a telephone
                     conversation between an official at a village hall ...
      79.6 -  84.8   First, you have some time to look at questions one to six.

What goes is the publisher and copyright announcement, which is the same on
every disc. Everything the candidate is meant to hear stays, in order, with the
reading pause and the example where they belong.

Parts 2 to 4 open at "Now turn to section three" instead, with no branding in
front of it, so there is usually nothing to cut -- which is the difference the
user noticed, arrived at from what is actually said rather than from a rule
about which part it is.

A recording where no announcement is found is not trimmed at the front at all.

Writes `audio.mp3` and `trim.json` beside the alignment. The importer shifts
every timestamp by the offset recorded there, so the transcript and the replay
spans still point at the right moments in the shorter file.
"""

import argparse
import json
import pathlib
import re
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

#: How much of the front to transcribe looking for the announcement. Long
#: enough to reach it on a Part 1, short enough to stay cheap.
HEAD_PROBE_MS = 150_000
#: A breath before the announcement, so it does not open clipped.
ANNOUNCE_LEAD_MS = 400
#: What the test announcing itself sounds like. The first line matching any of
#: these is the start; everything before it is the disc talking about itself.
START_MARKERS = [
    re.compile(r"\bnow turn to (the )?section\b", re.I),
    re.compile(r"\byou will hear\b", re.I),
    re.compile(r"\bsection (one|two|three|four|\d)\b", re.I),
    re.compile(r"\btest (one|two|three|four|\d)\b", re.I),
]
#: "Test 1." on its own is a label, not the test speaking, and it is followed
#: by two seconds of silence before anything happens. Starting there gives a
#: recording that opens with a number and a pause. The start is the next line
#: that actually says something.
BARE_LABEL = re.compile(r"^(test|section|cd|part)\s*(one|two|three|four|\d+)\s*[.:]?$", re.I)
#: Dead air at the end goes; speech at the end does not. "That is the end of
#: Section 1, you now have half a minute to check your answers" is the test
#: talking, the same as the introduction is.
TAIL_SILENCE_KEEP_MS = 2000

#: A cut bigger than this share of the preamble means the silence picked was
#: not the reading pause. Refuse rather than remove the test.
MAX_HEAD_FRACTION = 0.75


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


def transcribe_head(samples: np.ndarray, rate: int, cache: pathlib.Path) -> list[dict]:
    """The narration at the front of the recording, with timings.

    Groq's whisper-large-v3, the same model the production worker uses, on the
    first couple of minutes only. Cached beside the alignment: the answer never
    changes for a given file, and re-running the trim while tuning it should
    not spend the quota again."""
    if cache.exists():
        return json.loads(cache.read_text())["segments"]

    import vision  # for the API key, which lives in one place

    with tempfile.TemporaryDirectory() as td:
        clip = pathlib.Path(td) / "head.mp3"
        sf.write(clip, samples, rate, format="MP3")
        out = subprocess.run(
            ["curl", "-sS", "-X", "POST",
             "https://api.groq.com/openai/v1/audio/transcriptions",
             "-H", f"Authorization: Bearer {vision.api_key()}",
             "-F", f"file=@{clip}", "-F", "model=whisper-large-v3",
             "-F", "language=en", "-F", "response_format=verbose_json",
             "-F", "timestamp_granularities[]=segment"],
            capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        raise SystemExit(f"transcription failed: {out.stderr[:300]}")
    reply = json.loads(out.stdout)
    if "segments" not in reply:
        raise SystemExit(f"transcription said: {json.dumps(reply)[:300]}")
    cache.write_text(json.dumps(reply, indent=2))
    return reply["segments"]


def announcement(segments: list[dict]) -> dict | None:
    """The first line where the test actually starts speaking, or None.

    A segment that is only "Test 1." is skipped: it is a label, it is a second
    long, and two seconds of silence follow it. Cutting there produces a
    recording that opens with a number and then a pause."""
    for segment in segments:
        text = segment.get("text", "").strip()
        if BARE_LABEL.match(text):
            continue
        if any(marker.search(text) for marker in START_MARKERS):
            return segment
    return None


def speech_onset(mono: np.ndarray, rate: int, anchor_ms: int) -> int:
    """Where the speech containing ``anchor_ms`` began.

    Whisper's segment boundaries absorb the silence in front of a sentence --
    it timed "You will hear a number of different recordings" from 24.3s when
    the words start at 26.45s -- so its start is a good pointer at WHICH
    sentence and a poor one at WHEN. The anchor is taken from inside the
    segment and walked back to the last silence before it, which is the real
    onset."""
    ends = [b for _, b in silences(mono, rate, 400) if b <= anchor_ms]
    return ends[-1] if ends else 0


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

    probe_ms = min(HEAD_PROBE_MS, content_ms)
    segments = transcribe_head(mono[:int(probe_ms / 1000 * rate)], rate,
                               work / "head-transcript.json")
    found = announcement(segments)

    if found is None:
        print(f"  nothing in the first {probe_ms / 1000:.0f}s announces the test -- "
              "leaving the front alone rather than guessing")
        start_ms = 0
    else:
        # Anchored INSIDE the segment rather than at its edge, so a boundary
        # that ran early or late does not decide the cut.
        anchor_ms = int((found["start"] + (found["end"] - found["start"]) * 0.4) * 1000)
        onset_ms = speech_onset(mono, rate, anchor_ms)
        start_ms = max(0, onset_ms - ANNOUNCE_LEAD_MS)
        print(f"  starts at {onset_ms / 1000:.1f}s: {found['text'].strip()[:58]!r}"
              f"  (whisper said {found['start']:.1f}s)")
        if start_ms > content_ms * MAX_HEAD_FRACTION and not args.force:
            print(f"REFUSING  that would drop {start_ms / 1000:.0f}s, more than "
                  f"{MAX_HEAD_FRACTION:.0%} of the {content_ms / 1000:.0f}s before the "
                  "content -- the line matched is probably not the announcement",
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
    # Cutting means re-encoding, and libsndfile's default lands around 85 kbps
    # against a 128 kbps source. 0.0 is its best quality, which comes back at
    # 113 -- close enough that a listening test is not being marked on a worse
    # recording than the one the book shipped.
    sf.write(out, cut, rate, format="MP3", compression_level=0.0)

    (work / "trim.json").write_text(json.dumps({
        "source": row["rel_path"],
        "source_sha256": row["sha256"],
        "offset_ms": start_ms,
        "duration_ms": end_ms - start_ms,
        "cut_head_ms": start_ms,
        "cut_tail_ms": total_ms - end_ms,
    }, indent=2))

    print(f"{args.section_id}: {total_ms / 1000:.0f}s -> {(end_ms - start_ms) / 1000:.0f}s")
    print(f"  cut {start_ms / 1000:.0f}s of disc announcement and "
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

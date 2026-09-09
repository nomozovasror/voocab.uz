"""Write a section's turns.json by listening to the recording, not reading the book.

    seed/.venv/bin/python seed/hear_audio.py cam20-t1-s1

`read_audioscript.py` is the normal path and the better one: the book prints
the words, who says them, and -- the thing that matters most -- a Q number down
the margin against the line each answer is spoken in. That margin is what gives
an answer its replay span.

This is for the sections where no such page exists. Cambridge 20 is a Chinese
re-typeset with no audioscript at all, and one section of book 13 lost its sheet
to the scanner. Sixteen and one sections that otherwise stop here.

**Only the words are taken from the transcriber.** The timings still come from
`align.py`, which was measured at a median 40ms against known timings; a
transcriber's own word timestamps are a second guess at something already
solved, and a worse one. So this writes exactly what `read_audioscript.py`
writes -- speaker turns, no timings -- and every stage after it is unchanged.

**What is lost is the markers, and they do not come back.** Nothing in the
recording says "this sentence answers question 13"; that is printed knowledge.
`build_questions.py` finds a span by searching the alignment for the answer's
own words instead, which works for a gap-fill and cannot work for a letter
picked from a box. So a section seeded this way will have replay spans for its
written answers and none for its lettered ones, and `publish_blockers()` will
say so by name.

Measured against the hand-checked transcription of `cam11-t1-s1`, which has a
real audioscript to be wrong about: 98.0% of the book's words come back in the
same order, and all ten of its answers are found in the result -- which is the
only property `build_questions.py` needs. It costs half a cent a section.
"""

import argparse
import json
import pathlib
import sqlite3
import sys
import tempfile

import soundfile as sf
import torch
import torchaudio

import vision

SEED = pathlib.Path(__file__).resolve().parent
WORK = SEED / "work"
MATERIALS = SEED.parent / "Materials"
#: Speech, not music. 16 kHz mono is what every ASR model resamples to anyway,
#: and it takes a 9 MB section down to 2.5 MB -- which is the difference
#: between a request that goes and one that times out.
RATE = 16000

PROMPT = """Transcribe this IELTS Listening recording verbatim, from the first word
spoken to the last. Every word: this is a transcription, not a summary, and
nothing may be shortened, skipped or paraphrased.

Break it into turns. A turn is one speaker talking, and a new turn starts
whenever the speaker changes. Label each speaker with a short name in capitals
for their role, used consistently throughout: MAN, WOMAN, TUTOR, STUDENT,
OFFICIAL, LECTURER.

The recording also carries announcements read over it that are not part of the
conversation -- "You will hear...", "First you have some time to look at
questions...", "Now turn to section...", "That is the end of...". Label every
one of those NARRATOR. Transcribe them too; do not leave them out.

Where the recording pauses for the candidate to read the questions, emit a turn
{"speaker": "__BREAK__", "text": ""} at that point.

JSON only, no prose and no code fence:

{"turns": [{"speaker": "<LABEL>", "text": "<all of it, verbatim>"}]}"""


def downsample(source: pathlib.Path, into: pathlib.Path) -> float:
    """A mono 16 kHz copy of the recording, and how long it runs."""
    data, rate = sf.read(source, dtype="float32", always_2d=True)
    mono = torch.from_numpy(data.mean(axis=1)).unsqueeze(0)
    if rate != RATE:
        mono = torchaudio.functional.resample(mono, rate, RATE)
    sf.write(into, mono.squeeze(0).numpy(), RATE, format="MP3")
    return len(data) / rate


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("section_id")
    ap.add_argument("--model", default=vision.DEFAULT_MODEL)
    args = ap.parse_args()

    conn = sqlite3.connect(SEED / "catalogue.db")
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT rel_path FROM section WHERE id = ?",
                       (args.section_id,)).fetchone()
    if row is None:
        raise SystemExit(f"{args.section_id}: not in the catalogue")

    work = WORK / args.section_id
    work.mkdir(parents=True, exist_ok=True)
    source = MATERIALS / row["rel_path"]

    with tempfile.TemporaryDirectory() as temp:
        small = pathlib.Path(temp) / "listen.mp3"
        seconds = downsample(source, small)
        size = small.stat().st_size / 1e6
        print(f"listening to {seconds:.0f}s of {source.name} ({size:.1f} MB at "
              f"{RATE} Hz) with {args.model}")
        said = vision.ask_json(PROMPT, [], recording=small, model=args.model)

    turns = [
        {"speaker": (t.get("speaker") or "").strip().rstrip(":").strip(),
         "text": (t.get("text") or "").strip(),
         # Nothing in a recording says which question a sentence answers. The
         # field is written empty rather than left out, so what reads this
         # cannot tell a section heard from a section read.
         "marker": None, "answer": None}
        for t in said.get("turns", [])
    ]
    turns = [t for t in turns if t["text"] or t["speaker"] == "__BREAK__"]
    if not turns:
        raise SystemExit(f"{args.section_id}: nothing came back")

    (work / "turns.json").write_text(json.dumps(turns, indent=2, ensure_ascii=False))
    spoken = [t for t in turns if t["speaker"] != "__BREAK__"]
    words = sum(len(t["text"].split()) for t in spoken)
    speakers = sorted({t["speaker"] for t in spoken})
    print(f"  {len(spoken)} turns, {words} words, {len(turns) - len(spoken)} break(s)")
    print(f"  speakers: {speakers}")
    print("  no markers: this section was heard, not read -- replay spans come "
          "from the answers' own words", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

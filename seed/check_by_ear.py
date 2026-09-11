"""Cut each answer's replay span to its own clip, so a person can check it.

    seed/.venv/bin/python seed/check_by_ear.py cam20-t1-s1
    seed/.venv/bin/python seed/check_by_ear.py --sample

`verify.py` measures two things that correlate with a section being right. It
cannot hear. Every span in this corpus is now either a margin number the book
printed, a phrase found in the alignment, or a turn a model picked by meaning,
and all three are arguments rather than evidence. The evidence is that the
answer is audible where the span says it is.

So this writes one clip per question, named for the question and the answer it
claims to contain:

    seed/work/cam20-t1-s1/answers/Q03-Spanish.wav

Play it. If the speaker says "Spanish" in those few seconds, that span is
right; if they do not, it is wrong and the section is worth re-reading. That is
the whole check, and it takes a minute a section.

`align.py --clips` cuts a different thing -- the TURN each margin marker sits
on -- which is what the alignment produced. This cuts what the learner will
actually be given, which for many questions no longer comes from a margin at
all.

`--sample` picks the sections worth hearing first: the ones whose spans rest on
the least evidence. Reading them all by ear is not the point; reading the ones
where a mistake would be invisible is.
"""

import argparse
import json
import pathlib
import re
import sqlite3
import sys

import soundfile as sf

SEED = pathlib.Path(__file__).resolve().parent
WORK = SEED / "work"
MATERIALS = SEED.parent / "Materials"
#: A second either side, so the answer is not clipped by a span that is tight
#: to the word. Generous on purpose: this is for a person to judge, and a word
#: cut in half is harder to judge than one with room around it.
PADDING_MS = 1000


def clips(section_id: str) -> int:
    work = WORK / section_id
    built = work / "questions.json"
    if not built.exists():
        print(f"{section_id}: no questions.json", file=sys.stderr)
        return 1

    conn = sqlite3.connect(SEED / "catalogue.db")
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT rel_path FROM section WHERE id = ?",
                       (section_id,)).fetchone()
    conn.close()
    if row is None:
        print(f"{section_id}: not in the catalogue", file=sys.stderr)
        return 1

    # The recording as the alignment saw it, untrimmed. questions.json holds
    # spans against that; the trim offset is applied at import, not here.
    audio, rate = sf.read(MATERIALS / row["rel_path"], dtype="float32", always_2d=True)
    out = work / "answers"
    out.mkdir(exist_ok=True)
    for old in out.glob("*.wav"):
        old.unlink()

    written, unspanned = 0, []
    for group in json.loads(built.read_text())["groups"]:
        for question in group["questions"]:
            number = question.get("paper_number") or question.get("number")
            start, end = question.get("replay_start_ms"), question.get("replay_end_ms")
            if start is None or end is None:
                unspanned.append(number)
                continue
            # A letter cannot be heard. "Q11-f.wav" tells a listener nothing
            # about whether the span is right, and the sections most in need
            # of an ear are exactly the lettered ones -- cam13-t3-s2's every
            # span was placed by meaning. So the letter is expanded to the
            # option it stands for, which IS a thing the speaker says
            # something about.
            answers = question.get("correct_answers") or []
            options = (question.get("options")
                       or group.get("config", {}).get("options") or [])
            said = []
            for answer in answers:
                letter = str(answer).strip().lower()
                index = ord(letter) - ord("a") if len(letter) == 1 else -1
                if 0 <= index < len(options):
                    said.append(f"{letter.upper()}-{options[index]}")
                else:
                    said.append(str(answer))
            label = re.sub(r"[^A-Za-z0-9]+", "-", " ".join(said)).strip("-")[:56] or "?"
            a = max(0, int((start - PADDING_MS) / 1000 * rate))
            b = min(len(audio), int((end + PADDING_MS) / 1000 * rate))
            sf.write(out / f"Q{number:02d}-{label}.wav", audio[a:b], rate)
            written += 1

    print(f"{section_id}: {written} clip(s) in {out.relative_to(SEED.parent)}"
          f"  ({(b - a) / rate:.0f}s each, roughly)")
    if unspanned:
        print(f"  no span, nothing to hear: Q{', Q'.join(str(n) for n in unspanned)}")
    return 0


def sample(conn) -> list[tuple[str, str]]:
    """The sections whose spans rest on the least evidence, and why.

    Ordered by how many ways a span could be wrong without anything noticing,
    which is not the same as how likely it is to be wrong."""
    picked: list[tuple[str, str]] = []
    heard = {r["id"] for r in conn.execute(
        "SELECT s.id FROM section s JOIN book b ON b.number = s.book_number "
        "WHERE b.has_audioscript = 0")}
    web = {r["id"] for r in conn.execute(
        "SELECT id FROM section WHERE question_source IS NOT NULL")}
    # A book can have an audioscript and one section still not: cam13-t3-s2's
    # sheet is missing from the scan, so it was heard like Cambridge 20's are
    # while its fifteen neighbours were read. The note is where that was
    # written down.
    noted = {r["id"]: r["note"] for r in conn.execute(
        "SELECT id, note FROM section WHERE note IS NOT NULL "
        "AND note NOT LIKE 'trimmed:%'")}

    for section in sorted(WORK.iterdir()):
        if not section.is_dir() or not (section / "questions.json").exists():
            continue
        sid = section.name
        turns = section / "turns.json"
        markers = 0
        if turns.exists():
            markers = sum(1 for t in json.loads(turns.read_text()) if t.get("marker"))
        why = []
        if sid in heard:
            why.append("heard, not read")
        if sid in web:
            why.append("questions from the web")
        if not markers:
            why.append("no margin markers at all")
        if sid in noted:
            why.append(noted[sid].split(":")[0][:48])
        if why:
            picked.append((sid, "; ".join(why)))
    return picked


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sections", nargs="*")
    ap.add_argument("--sample", action="store_true",
                    help="list the sections worth hearing first, and why")
    args = ap.parse_args()

    conn = sqlite3.connect(SEED / "catalogue.db")
    conn.row_factory = sqlite3.Row
    if args.sample:
        rows = sample(conn)
        print(f"{len(rows)} section(s) whose spans rest on less than a printed "
              f"margin number:\n")
        for sid, why in rows:
            print(f"  {sid:<14} {why}")
        return 0
    conn.close()

    if not args.sections:
        raise SystemExit("name some sections, or pass --sample")
    return max(clips(sid) for sid in args.sections)


if __name__ == "__main__":
    sys.exit(main())

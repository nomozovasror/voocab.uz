"""Name a listening section the book left unnamed, from what is said in it.

    seed/.venv/bin/python seed/name_sections.py            # every one that needs it
    seed/.venv/bin/python seed/name_sections.py cam10-t1-s3
    seed/.venv/bin/python seed/name_sections.py --report

A listening paper prints a heading over its first task -- "Oyster Bay Sailing
Club Courses" above the table, "SELF-DRIVE TOURS IN THE USA" above the notes
-- and `import_section.printed_name` reads it. 162 of the 272 sections have
one. The other 110 are Part 2s and Part 3s answered by multiple choice and
matching, which print questions and no heading at all, and they were left
carrying their reference as a name: a shelf where "C10 T1 P2" sits between
"Joining the leisure club" and "THE SPIRIT BEAR".

So this reads the recording instead and writes down what it is about.

**The name is OURS, and the pipeline keeps knowing that.** It goes to
`work/<id>/name.json` and never near `questions.json`, so `printed_name`
keeps meaning "what the book printed" and the importer reaches for this only
after that comes back empty. A reader who wants to know where a title came
from has the file, with the model that wrote it and the date.

**It describes, it does not summarise.** The named sections are short noun
phrases naming a subject, never sentences and never a verdict on it, so these
are asked for in that register and checked against it: a title that runs to a
clause, ends in a full stop or reaches for a word the transcript never used is
a title that has started telling the learner what to think about a recording
they have not heard yet.

It is also the cheapest stage in this pipeline by a distance -- one text
request per section over eight hundred words, no images, no audio.
"""

import argparse
import datetime
import json
import pathlib
import re
import sqlite3
import sys

import vision

SEED = pathlib.Path(__file__).resolve().parent
WORK = SEED / "work"

#: How long a title may be, in words.
#:
#: The printed ones run from two words ("Transport Survey") to six
#: ("'Self-regulatory focus theory' and leadership"), and eight is the point
#: past which a noun phrase has become a sentence about the recording.
WORDS = (2, 8)

#: And in characters, because a card truncates. "The Official Cambridge Guide
#: to IELTS" is 37 and reads as too long already.
CHARS = 60

#: Words that mean the model described the FORM rather than the subject.
#: "Part 3 discussion", "A conversation between two students" and "IELTS
#: listening practice" are all true of dozens of these and identify none of
#: them.
EMPTY = re.compile(
    r"\b(part\s*[1-4]|section\s*[1-4]|ielts|listening|transcript|recording|"
    r"conversation|discussion|dialogue|monologue|lecture|talk|interview)\b",
    re.I,
)

PROMPT = """This is the transcript of one part of an IELTS Listening paper.

Give it a title, the way the book titles the parts it does title. Real
examples from the same books:

  SELF-DRIVE TOURS IN THE USA
  Joining the leisure club
  Transport Survey
  Fiddy Working Heritage Farm
  'Self-regulatory focus theory' and leadership
  Tourist attractions in Manham
  Uses of Nanotechnology

Rules:
- Name the SUBJECT being talked about, not the form of the recording. Never
  "Part 3", "a conversation between two students", "an academic discussion".
- A short noun phrase. {low} to {high} words. No sentence, no verb phrase, no
  full stop at the end, no quotation marks around the whole thing.
- Use the transcript's own words for names, places and terms. Do not invent a
  detail, and do not judge or summarise what is said -- somebody is about to
  sit this paper and must not be told its content in advance beyond what it
  is about.
- If two things are discussed, name the one the questions are mostly about.

Reply with JSON only: {{"title": "..."}}

Transcript:
{transcript}
"""


def printed(section_id: str) -> str | None:
    """The heading the book printed, if it printed one.

    The same three lines `import_section.printed_name` runs, deliberately
    duplicated rather than imported: this script runs in the seed venv and
    that one lives in the backend's, and a shared module between the two
    would be the first thing either of them has ever borrowed from the other.
    """
    path = WORK / section_id / "questions.json"
    if not path.exists():
        return None
    for group in json.loads(path.read_text()).get("groups", []):
        template = (group.get("config") or {}).get("template") or ""
        for line in template.splitlines():
            if line.startswith("#") and line[1:].strip():
                return line[1:].strip()
    return None


def transcript(section_id: str) -> str | None:
    """What is said in the recording, as speakers and lines."""
    path = WORK / section_id / "turns.json"
    if not path.exists():
        return None
    lines = []
    for turn in json.loads(path.read_text()):
        said = (turn.get("text") or "").strip()
        # The aligner's own marker between the two halves of a part. It is
        # not speech and it is not a speaker.
        if not said or turn.get("speaker") == "__BREAK__":
            continue
        lines.append(f"{turn.get('speaker') or 'SPEAKER'}: {said}")
    return "\n".join(lines) or None


def usable(title: str) -> str | None:
    """The title if it is one, or nothing and a reason on stderr."""
    title = (title or "").strip().strip('"').rstrip(".").strip()
    if not title:
        return None
    words = title.split()
    if not (WORDS[0] <= len(words) <= WORDS[1]) or len(title) > CHARS:
        print(f"    refused, {len(words)} words / {len(title)} chars:"
              f" {title!r}", file=sys.stderr)
        return None
    if EMPTY.search(title):
        print(f"    refused, names the form not the subject: {title!r}",
              file=sys.stderr)
        return None
    return title


def name(section_id: str, *, model: str) -> str | None:
    said = transcript(section_id)
    if not said:
        print(f"{section_id:16} no transcript", file=sys.stderr)
        return None
    asked = PROMPT.format(low=WORDS[0], high=WORDS[1], transcript=said)
    reply = vision.ask_json(asked, [], model=model, max_tokens=300)
    return usable((reply or {}).get("title") or "")


def sections(conn: sqlite3.Connection, where: str, args: tuple) -> list[str]:
    return [row[0] for row in conn.execute(
        f"select id from section where {where} order by id", args)]


def report(ids: list[str]) -> None:
    printed_count = derived = left = 0
    for section_id in ids:
        if printed(section_id):
            printed_count += 1
        elif (WORK / section_id / "name.json").exists():
            derived += 1
        else:
            left += 1
    print(f"{len(ids)} sections | {printed_count} named by the book"
          f" | {derived} named from the transcript | {left} still unnamed")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("section_id", nargs="?", help="one section, like cam10-t1-s3")
    ap.add_argument("--book", type=int, help="every section of one book")
    ap.add_argument("--report", action="store_true",
                    help="what is named and by whom, then stop")
    ap.add_argument("--force", action="store_true",
                    help="name again a section already named here")
    ap.add_argument("--model", default=vision.DEFAULT_MODEL)
    args = ap.parse_args()

    conn = sqlite3.connect(SEED / "catalogue.db")
    if args.section_id:
        ids = sections(conn, "id = ?", (args.section_id,))
    elif args.book:
        ids = sections(conn, "book_number = ?", (args.book,))
    else:
        ids = sections(conn, "1=1", ())

    if args.report:
        report(ids)
        return 0

    done = skipped = failed = 0
    for section_id in ids:
        out = WORK / section_id / "name.json"
        # The book's own heading always wins, and a section that has one is
        # not this script's business at any point -- not even with --force.
        if printed(section_id) or (out.exists() and not args.force):
            skipped += 1
            continue
        title = name(section_id, model=args.model)
        if not title:
            failed += 1
            continue
        out.write_text(json.dumps({
            "title": title,
            # Written down because the title is not the book's, and six
            # months from now the only way to tell will be this line.
            "source": "transcript",
            "model": args.model,
            "at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        }, indent=2, ensure_ascii=False))
        print(f"{section_id:16} {title}")
        done += 1

    print(f"\n{done} named, {skipped} left alone, {failed} refused")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

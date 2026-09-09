"""Read one section's audioscript off the page.

    seed/.venv/bin/python seed/read_audioscript.py cam11-t1-s1

Writes `turns.json` -- the text forced alignment is aligned against, and the
last thing in the pipeline that was being typed by hand.

Three things are taken off the page, and only one of them is the words.

**The speaker labels**, because a change of speaker is the only boundary the
source marks and it is what the transcript lines are cut on.

**The margin markers.** The book prints `Q1`, `Q2` ... down the right-hand side
against the line where each answer is spoken. That is a far better route to
`replay_start_ms` than searching the aligned words for the answer text: the
marker names the turn, and a turn's start is the most accurate thing the
alignment produces, where hunting for a spelled-out phone number runs straight
into the one thing it is bad at.

**The dotted rule** across the page, which is not decoration: it is where the
recording pauses to let the candidate read the second half of the questions,
and the alignment needs a star there or it spends that half-minute on words.

What is NOT taken off the page is anything printed and unspoken -- the page
numbers, the running heads, the iyuce.com watermark. What IS spoken stays, and
the distinction matters more than it looks: the narrator's lines are not
printed in these audioscripts at all, so the recording holds three minutes the
text has no words for. That is the trimmer's problem, and it is why the
alignment runs with stars rather than assuming the text covers the audio.
"""

import argparse
import json
import pathlib
import re
import sqlite3
import sys

import markers as marker_syntax
import vision

SEED = pathlib.Path(__file__).resolve().parent
REPO = SEED.parent
MATERIALS = REPO / "Materials"
WORK = SEED / "work"

#: Three images a request is Groq's limit and it is a COUNT, not a size -- so
#: the way to fit more pages is not to shrink them further but to send fewer
#: bytes each and then make more than one request. As JPEG a page is half the
#: size it is as PNG (216 KB against 458 at 110 dpi), which buys the headroom
#: to read at 130 instead.
#:
#: Capping at two pages and stopping there was the previous fix and it cost
#: real answers: 60 sections have a script spanning more than two pages, and 30
#: of them lost their last margin marker with the tail. A span longer than the
#: cap is now read in overlapping windows and stitched.
PAGES_PER_CALL = 3
SCRIPT_DPI = 130

PROMPT = """These images are consecutive pages of the audioscripts at the back of a
Cambridge IELTS book. Read ONLY the audioscript for {label}.

It begins at the heading "SECTION {section}" or "PART {section}" (under "TEST
{test}") and ENDS at the next such heading, which belongs to the next section --
stop there even if it is halfway down a page.

The FIRST PAGE almost always opens partway through the PREVIOUS section, above
your heading. Everything above that heading belongs to the previous section:
skip it entirely, however much of the page it is.

The only margin markers in this section are Q{first} to Q{last}. If you find
yourself copying a turn marked with a number below Q{first}, you are still in
the previous section and have not reached your heading yet.

Return ONE JSON object, no prose and no code fence:

{{"turns": [
  {{"speaker": "<the LABEL in the left column, verbatim, e.g. OFFICIAL, WOMAN, TUTOR>",
    "text": "<everything that speaker says, as one line>",
    "marker": "<the Q number printed in the RIGHT MARGIN against this turn, like Q1, or Example, or null>",
    "answer": "<the words UNDERLINED in this turn, verbatim, or null>"}}
]}}

Rules that matter:

* One entry per speaker turn, in order. A turn that runs over several printed
  lines is ONE entry, unless a marker falls inside it.
* **Start a NEW entry at every margin marker, even when the speaker has not
  changed.** Sections 2 and 4 are usually one person talking without
  interruption, and putting the whole talk in a single entry makes it
  impossible to say where each answer falls. Break the text so that each
  marked line begins its own entry, carrying that marker. A talk with ten
  markers is therefore at least eleven entries, not one.
* **A lecture often has NO speaker labels at all** -- no left column, just
  paragraphs with markers down the right. That is normal for sections 2 and 4.
  Use "SPEAKER" as the speaker for every entry there and break the text at the
  markers exactly as above. Do not return one entry for the whole talk, and do
  not return nothing because there was no name to copy.
* Where the page has a horizontal dotted or dashed rule across it, emit
  {{"speaker": "__BREAK__", "text": "", "marker": null, "answer": null}} at that
  point. It marks a pause in the recording and it must not be dropped.
* Copy the words exactly as printed, including names spelled out letter by
  letter ("C-H-A-R L-T-O-N"). Do not correct, shorten or paraphrase anything.
* Ignore page numbers, the running head, and any watermark (iyuce.com, "Edit
  by:", Chinese text). None of it is spoken.
* "marker" and "answer" are usually null. Fill them only where the book really
  prints a Q number in the margin or really underlines words."""


#: Asked to transcribe AND mark at once, the model segments by paragraph and
#: attaches at most one marker to each -- a first paragraph carrying Q31 and
#: Q32 came back with neither. Three rounds of telling it to break at the
#: markers instead did not move it. So the markers are asked for on their own,
#: which is the one thing that has worked every time in this pipeline: a narrow
#: question gets a reliable answer.
MARKER_PROMPT = """These pages are the audioscript for {label} of a Cambridge IELTS book.

Down the RIGHT-HAND MARGIN it prints Q numbers, one against each line where an
answer is spoken. List EVERY one you can see for questions {first} to {last}.

JSON only, no prose:

{{"markers": [{{"q": <number>, "quote": "<8 to 15 words of the line it sits
against, copied exactly>"}}]}}

The quote must be text you can actually read on the page, copied word for word,
long enough to find again. Where two numbers share one line ("Q31" and "Q32"
against the same sentence), list them separately with the same quote.

Do not invent a marker you cannot see, and do not skip one because its line
looks like the paragraph above it."""


def attach_markers(turns: list[dict], found: list[dict]) -> int:
    """Put each marker on the turn whose text carries its quoted line."""
    def key(text: str) -> str:
        return re.sub(r"[^a-z0-9 ]", "", (text or "").lower())

    placed = 0
    for item in found:
        number, quote = item.get("q"), key(item.get("quote", ""))
        if not number or len(quote) < 12:
            continue
        # The longest run of the quote that any turn actually contains: the
        # model's copy drifts by a word or two, and an exact match would miss
        # most of them.
        words = quote.split()
        best = None
        for size in range(len(words), 3, -1):
            probe = " ".join(words[:size])
            best = next((t for t in turns if probe in key(t["text"])), None)
            if best:
                break
        if best is None:
            continue
        existing = marker_syntax.numbers(best.get("marker"))
        if number not in existing:
            best["marker"] = (f"{best['marker']} Q{number}"
                              if best.get("marker") else f"Q{number}")
            placed += 1
    return placed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("section_id")
    ap.add_argument("--pages", help="override the catalogue's script pages")
    ap.add_argument("--model", default=vision.DEFAULT_MODEL)
    args = ap.parse_args()

    conn = sqlite3.connect(SEED / "catalogue.db")
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT s.*, d.rel_path pdf FROM section s JOIN document d ON d.id = s.document_id "
        "WHERE s.id = ?", (args.section_id,)).fetchone()
    conn.close()
    if row is None:
        raise SystemExit(f"{args.section_id} is not in the catalogue")

    pages = ([int(p) for p in args.pages.split(",")] if args.pages
             else json.loads(row["script_pages"] or "null") or [])
    if not pages:
        raise SystemExit(
            f"{args.section_id}: no audioscript pages in the catalogue. Run "
            f"seed/locate_pages.py {row['book_number']} first, or pass --pages.")

    work = WORK / args.section_id
    label = f"Test {row['test_no']}, Section {row['section_no']}"
    first, last = (row["section_no"] - 1) * 10 + 1, row["section_no"] * 10
    prompt = PROMPT.format(label=label, test=row["test_no"],
                           section=row["section_no"], first=first, last=last)

    # Overlapping windows: each carries the last page of the one before it, so
    # a turn that straddles a page break is seen whole by at least one call.
    windows = [pages[i:i + PAGES_PER_CALL]
               for i in range(0, max(1, len(pages) - 1), PAGES_PER_CALL - 1)] or [pages]
    print(f"reading the audioscript for {label} from pages {pages}"
          + (f" in {len(windows)} windows" if len(windows) > 1 else ""))

    turns: list[dict] = []
    rendered: list[list[pathlib.Path]] = []
    for window in windows:
        shots = vision.render(MATERIALS / row["pdf"], window, work / "pages",
                              dpi=SCRIPT_DPI, jpeg=True)
        rendered.append(shots)
        read = vision.ask_json(prompt, shots, model=args.model, max_tokens=8000)
        got = [
            # The page prints "OFFICIAL:" and the prompt asks for the label
            # verbatim, so a model is right either way -- but this string is
            # the segment's speaker in the app, where the colon is the
            # renderer's business and not the book's. Some providers keep it,
            # some drop it; stripped here so the transcript reads the same
            # whichever one answered.
            {"speaker": (t.get("speaker") or "").strip().rstrip(":").strip(),
             "text": (t.get("text") or "").strip(),
             "marker": t.get("marker") or None, "answer": t.get("answer") or None}
            for t in read.get("turns", [])
        ]
        # Stitch on the overlap: a window repeats what the one before it
        # already said, so anything already present by its text is dropped.
        seen = {t["text"] for t in turns if t["text"]}
        turns.extend(t for t in got if t["text"] not in seen or not t["text"])
    # A turn with no words is either the break or a misread line; the break is
    # kept because it carries meaning, the rest go.
    turns = [t for t in turns if t["text"] or t["speaker"] == "__BREAK__"]

    # The prompt says to start at this section's heading and the model still
    # opens with the previous section's tail -- cam11-t1-s2 came back carrying
    # Q7 to Q10. A marker below this section's range is proof of where the text
    # actually is, so everything up to and including the last such turn goes.
    # A turn can carry more than one marker -- "Q21/22" is one line answering
    # two questions -- so these look at every number in the string, not at a
    # single one. Matching only "Q21" treated "Q21/22" as no marker at all.
    def nums(turn: dict) -> list[int]:
        return [] if marker_syntax.is_example(turn.get("marker")) \
            else marker_syntax.numbers(turn.get("marker"))

    strays = [i for i, t in enumerate(turns)
              if (ns := nums(t)) and max(ns) < first]
    if strays:
        cut = strays[-1] + 1
        print(f"  dropped {cut} turn(s) belonging to the section before this one")
        turns = turns[cut:]

    # And the same at the other end. Reading a long span in windows means the
    # last window runs into the NEXT section, which came back carrying Q31 to
    # Q39 on a section whose own range ends at Q30. Everything from the first
    # marker above this section's range belongs to the next one.
    ahead = next((i for i, t in enumerate(turns)
                  if (ns := nums(t)) and min(ns) > last), None)
    if ahead is not None:
        print(f"  dropped {len(turns) - ahead} turn(s) belonging to the next section")
        turns = turns[:ahead]
    (work / "turns.json").write_text(json.dumps(turns, indent=2, ensure_ascii=False))

    # A second, narrow pass for anything the transcription did not mark.
    seen_now = {n for t in turns for n in nums(t)}
    if set(range(first, last + 1)) - seen_now:
        # Every window, not just the last one that happens to still be in
        # scope: a marker missed on page one is not on page three.
        placed = 0
        for shots in rendered:
            marks = vision.ask_json(
                MARKER_PROMPT.format(label=label, first=first, last=last),
                shots, model=args.model, max_tokens=2000).get("markers", [])
            placed += attach_markers(turns, marks)
        if placed:
            print(f"  a second pass placed {placed} marker(s) the transcription missed")

    spoken = [t for t in turns if t["speaker"] != "__BREAK__"]
    words = sum(len(t["text"].split()) for t in spoken)
    seen_numbers = sorted({n for t in turns for n in nums(t)})
    markers = [f"Q{n}" for n in seen_numbers]
    breaks = sum(1 for t in turns if t["speaker"] == "__BREAK__")
    print(f"  {len(spoken)} turns, {words} words, {breaks} break(s)")
    print(f"  markers: {markers}")

    missing = [f"Q{n}" for n in range(first, last + 1) if n not in set(seen_numbers)]
    if missing:
        print(f"  MISSING markers: {missing} -- those answers get no replay span",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

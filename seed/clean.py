"""Split a book audioscript into the turns that were actually SPOKEN.

The distinction that matters (and that the brief got wrong): a speaker label
is printed but never said, while a narrator's "You will hear a conversation
between..." IS said and must stay in the alignment text -- drop it and the
aligner is handed twenty seconds of speech with nothing to match it to.

Speaker labels aren't discarded either: stripped from the text, kept as the
segment boundary. They are the best segmentation signal in the document.
"""

import re, json, sys

# Printed, never spoken.
NOISE = [
    re.compile(r"^\s*$"),
    re.compile(r"^\s*\[.*\]\s*$"),                    # [pause]
    re.compile(r"^\s*SECTION\s+\d+\s*$", re.I),       # section heading
    re.compile(r"page\s+\d+\s*$", re.I),              # running header / folio
    re.compile(r"^\s*Cambridge IELTS.*Audioscripts", re.I),
]
SPEAKER = re.compile(r"^([A-Z][A-Z '&-]{1,24}):\s*(.*)$")


def clean(path):
    turns, current = [], None
    for raw in open(path, encoding="utf-8"):
        line = raw.rstrip("\n")
        if any(p.search(line) for p in NOISE):
            continue
        m = SPEAKER.match(line)
        if m:
            if current:
                turns.append(current)
            current = {"speaker": m.group(1).strip(), "text": m.group(2).strip()}
        elif current:                                  # continuation of a turn
            current["text"] += " " + line.strip()
    if current:
        turns.append(current)
    for t in turns:
        t["text"] = re.sub(r"\s+", " ", t["text"]).strip()
    return [t for t in turns if t["text"]]


if __name__ == "__main__":
    turns = clean(sys.argv[1])
    json.dump(turns, open(sys.argv[2], "w"), indent=2)
    words = sum(len(t["text"].split()) for t in turns)
    print(f"{len(turns)} turns, {words} spoken words")
    for t in turns[:3]:
        print(f"  {t['speaker']}: {t['text'][:70]}...")

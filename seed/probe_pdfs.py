"""Does each book's PDF actually carry the three things the pipeline needs?

A section becomes a material out of three parts of its book: the question
pages, the audioscript at the back, and the answer key. A PDF missing any one
of them is a section that cannot be built, and it is far cheaper to learn that
now than at the end of a batch run.
"""

import json, pathlib, re, sys
import fitz  # PyMuPDF

REPO = pathlib.Path(__file__).resolve().parent.parent
MATERIALS = REPO / "Materials"

MARKERS = {
    "audioscript": re.compile(r"audioscript|transcript", re.I),
    "answer key":  re.compile(r"answer\s*key|listening\s+answers", re.I),
    "listening":   re.compile(r"\bLISTENING\b"),
}

rows = json.load(open(REPO / "seed" / "manifest.json"))
pdfs = sorted({r["pdf"] for r in rows if r["pdf"]})

print(f"{'pdf':<52}{'pages':>6}{'text?':>7}   markers (first page seen)")
for rel in pdfs:
    doc = fitz.open(MATERIALS / rel)
    found, chars = {}, 0
    for i, page in enumerate(doc):
        text = page.get_text()
        chars += len(text)
        for name, pattern in MARKERS.items():
            if name not in found and pattern.search(text):
                found[name] = i + 1
    # A scanned book has pages but almost no extractable text -- that would
    # push the answer key onto the vision model too, so it is worth knowing.
    per_page = chars // max(len(doc), 1)
    label = "yes" if per_page > 200 else f"THIN({per_page})"
    summary = ", ".join(f"{k} p{v}" for k, v in sorted(found.items(), key=lambda x: x[1])) or "NONE FOUND"
    print(f"{rel[:50]:<52}{len(doc):>6}{label:>7}   {summary}")
    doc.close()

"""Every Cambridge section file -> one canonical (book, test, section) id.

Ten books arrived under seven naming conventions, none of which the pipeline
should ever have to know about again. This is the only place that knows; from
here on a section is `cam{book}-t{test}-s{section}` and nothing else.

Nothing is renamed or moved. The manifest maps the canonical id to whatever
the file is actually called, so the originals stay exactly as they are and a
wrong guess here costs a re-run, not a restore.
"""

import hashlib, json, pathlib, re, subprocess
import soundfile as sf

ROOT = pathlib.Path(__file__).resolve().parent.parent / "Materials"

# Tried in order; the first that matches a filename wins. The book number
# comes from the top-level folder, never the filename -- "C 18 section3 part2"
# names the test where you would expect the book.
PATTERNS = [
    ("book.test.section", re.compile(r"IELTS\s*(\d+)\.(\d)\.(\d)", re.I)),
    ("test_audio",        re.compile(r"IELTS(\d+)_t(?:est)?(\d)_audio(\d)", re.I)),
    ("Test N Part N",     re.compile(r"\bTest\s*(\d)\s*Part\s*(\d)", re.I)),
    ("sectionN-partN",    re.compile(r"\bsection\s*(\d)\s*-?\s*part\s*(\d)", re.I)),
    ("TN PN",             re.compile(r"\bT(\d)\s*P(\d)\b", re.I)),
    ("TNSN",              re.compile(r"\bT(\d)S(\d)\b", re.I)),
]

#: Books 10-19 print one PDF for the whole book; Cambridge 20 arrived as four,
#: one per test. A section therefore has to name its own source document
#: rather than inheriting the book's, or the question-extraction stage would
#: have to rediscover this.
PER_TEST_PDF = re.compile(r"TEST\s*(\d)", re.I)


def pdf_for(book_dir, test):
    """The document carrying this section's questions, audioscript and key."""
    pdfs = sorted(book_dir.rglob("*.pdf"))
    per_test = [p for p in pdfs if (m := PER_TEST_PDF.search(p.stem)) and int(m.group(1)) == test]
    if per_test:
        return per_test[0]
    # A book with several PDFs but none named per test is the Academic/General
    # pair; Listening is common to both, and Academic is the one to read.
    whole = [p for p in pdfs if "general" not in p.stem.lower()] or pdfs
    return whole[0] if whole else None


def duration_and_format(path):
    """Header-only probe. libsndfile covers the mp3s; Cambridge 14 is really
    AAC behind a .mp3 extension, and CoreAudio trusts the extension -- hence
    the correctly-suffixed symlink."""
    try:
        info = sf.info(path)
        return round(info.duration, 1), info.samplerate, info.channels, info.format
    except Exception:
        pass
    # libsndfile has no AAC; CoreAudio does, and trusts the extension -- which
    # seed/fix_extensions.py has already made honest.
    out = subprocess.run(["afinfo", str(path)], capture_output=True, text=True).stdout
    secs = re.search(r"estimated duration: ([\d.]+)", out)
    fmt = re.search(r"(\d+) ch,\s+(\d+) Hz,\s+(\w+)", out)
    if not (secs and fmt):
        return None, None, None, "UNKNOWN"
    return round(float(secs.group(1)), 1), int(fmt.group(2)), int(fmt.group(1)), fmt.group(3).upper()


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


rows, unmatched = [], []
for book_dir in sorted(ROOT.glob("Cambridge *")):
    # Skip anything that isn't a numbered book directory: Finder and Spotlight
    # drop temporary entries into shared folders, and one of them matching the
    # glob is not a reason for the whole inventory to fall over.
    book_match = re.search(r"Cambridge\s*(\d+)", book_dir.name)
    if not (book_dir.is_dir() and book_match):
        continue
    book = int(book_match.group(1))
    for audio in sorted(p for ext in ("*.mp3", "*.m4a") for p in book_dir.rglob(ext)):
        name = audio.name
        for label, pattern in PATTERNS:
            m = pattern.search(name)
            if not m:
                continue
            groups = m.groups()
            test, section = (int(groups[1]), int(groups[2])) if len(groups) == 3 else (int(groups[0]), int(groups[1]))
            secs, sr, ch, fmt = duration_and_format(audio)
            rows.append({
                "id": f"cam{book}-t{test}-s{section}",
                "book": book, "test": test, "section": section,
                "path": str(audio.relative_to(ROOT)),
                "convention": label, "secs": secs, "sample_rate": sr,
                "channels": ch, "format": fmt, "sha256": sha256(audio),
                "pdf": (str(pdf.relative_to(ROOT)) if (pdf := pdf_for(book_dir, test)) else None),
            })
            break
        else:
            unmatched.append(str(audio.relative_to(ROOT)))

rows.sort(key=lambda r: (r["book"], r["test"], r["section"]))
json.dump(rows, open(pathlib.Path(__file__).parent / "manifest.json", "w"), indent=2)

print(f"{len(rows)} matched, {len(unmatched)} unmatched")
for u in unmatched:
    print("  UNMATCHED", u)

# --- the checks that make the manifest worth trusting ----------------------
seen, dupes = {}, []
for r in rows:
    dupes.append((r["id"], seen[r["id"]], r["path"])) if r["id"] in seen else None
    seen.setdefault(r["id"], r["path"])
by_hash = {}
for r in rows:
    by_hash.setdefault(r["sha256"], []).append(r["id"])

print(f"\nduplicate ids: {len(dupes)}")
for d in dupes:
    print("  ", d)
print("identical audio under different ids:",
      [v for v in by_hash.values() if len(v) > 1] or "none")

print(f"\n{'book':<7}{'files':>6}{'missing':>34}{'formats':>22}")
for book in sorted({r['book'] for r in rows}):
    rs = [r for r in rows if r["book"] == book]
    have = {(r["test"], r["section"]) for r in rs}
    missing = [f"t{t}s{s}" for t in range(1, 5) for s in range(1, 5) if (t, s) not in have]
    fmts = sorted({f"{r['format']}@{(r['sample_rate'] or 0)//1000}k/{r['channels']}ch" for r in rs})
    print(f"{book:<7}{len(rs):>6}{(', '.join(missing) or '-'):>34}{', '.join(fmts):>22}")

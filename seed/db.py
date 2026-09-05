"""Build and query the source-material catalogue.

    python seed/db.py init      # (re)build from manifest.json + the PDFs
    python seed/db.py status    # what is here and how far it has been taken

`init` is idempotent and safe to re-run: books, documents and sections are
upserted by their natural keys, so a re-inventory updates facts about files
without touching `stage` progress or `finding` notes. Those two tables are the
only things in here that cannot be rebuilt from `Materials/`, which is exactly
why they are kept apart from everything that can.
"""

import argparse
import hashlib
import json
import pathlib
import sqlite3
import sys

import pymupdf

SEED = pathlib.Path(__file__).resolve().parent
REPO = SEED.parent
MATERIALS = REPO / "Materials"
DB_PATH = SEED / "catalogue.db"
MANIFEST = SEED / "manifest.json"

#: What the files themselves cannot say. `kind` decides what the pipeline is
#: allowed to attempt: only a 'cambridge' book prints an audioscript, and only
#: an audioscript makes forced alignment possible.
BOOK_FACTS: dict[int, tuple[str, str, int | None, str | None]] = {
    **{n: (f"Cambridge IELTS {n}", "cambridge", None, None) for n in range(10, 20)},
    11: ("Cambridge IELTS 11", "cambridge", 1, "audioscripts confirmed from page 103"),
    17: ("Cambridge IELTS 17", "cambridge", 1,
         "has an OCR text layer, but a contaminated one -- read the pages visually instead"),
    20: ("Cambridge IELTS 20 Academic (Chinese re-typeset)", "retypeset", 0,
         "questions are cleanly re-typeset; no audioscript anywhere in the four PDFs"),
}

#: Knowledge that survives a rebuild because no rebuild would rediscover it.
FINDINGS: list[tuple[str, str, str, str]] = [
    ("20", "blocker",
     "Cambridge 20 has no audioscript",
     "Its listening section is four pages of questions and then the reading passages "
     "begin. Forced alignment is impossible for these 16 sections; they need ASR "
     "(whisper large-v3), which is the only job in this pipeline the office RTX 3060 "
     "is actually needed for."),
    ("corpus", "blocker",
     "The books are scans: plain text extraction is not available",
     "Zero extractable text in books 10-14, 16, 18 and all four Cambridge 20 PDFs; "
     "book 19 has text on 19 of 139 pages. The brief assumed the answer key could be "
     "read as text -- for nine of eleven books there is no text on the page at all, "
     "so the key goes through the same visual path as the questions."),
    ("17", "warning",
     "Cambridge 17's text layer is contaminated OCR",
     "3,864 Cyrillic homoglyphs (a e o c y p A B) sitting inside English words, plus "
     "digit-for-letter errors: 'T1M:' for 'TIM:', '1 heard' for 'I heard', 'lt's', "
     "'Hе said'. They look right and compare unequal. The layout is lost too -- the "
     "speaker column and the speech column are separate blocks, so extraction returns "
     "every label first and then every line of speech, with the turns gone."),
    ("corpus", "info",
     "Cambridge audioscripts mark where each answer is spoken",
     "Q1, Q2, Q3 ... down the right margin, with the answer phrase underlined in the "
     "body. A better route to replay_start_ms than searching the aligned word stream: "
     "the marker names the turn, and a turn's start was the most accurate thing the "
     "alignment measured (median ~40ms), where hunting for a spelled-out phone number "
     "runs straight into the one thing alignment is bad at."),
    ("20", "warning",
     "Cambridge 20's answer key uses its own conventions",
     "Alternatives separated by '|' rather than '/' (9-30|thirty), and '17-18.AE' for a "
     "'choose TWO letters' spanning two question numbers -- which maps onto "
     "question_marks(): one Question row, two letters, two marks."),
    ("20", "warning",
     "Cambridge 20's question pages have no instruction lines",
     "Test 1 Part 1 is a bare table with numbered gaps and no 'Complete the table "
     "below / NO MORE THAN TWO WORDS' above it, so `instructions` and `word_limit` "
     "have no source on the page."),
    ("corpus", "warning",
     "The scans carry watermarks, and one obscures text",
     "iyuce.com headers and footers and red 'Edit by:' lines are print-only noise the "
     "cleaner drops. A large PREDICTING watermark sits on top of the text on at least "
     "one page and hides part of it."),
    ("14", "resolved",
     "Cambridge 14 was AAC behind a .mp3 extension",
     "Sixteen files unreadable by libsndfile (no AAC) and by afinfo (trusts the "
     "extension). fix_extensions.py renamed fifteen by content sniff; the sixteenth had "
     "already been re-cut by hand."),
    ("cam14-t2-s4", "resolved",
     "cam14-t2-s4 had the next test appended",
     "17.3 minutes against a library range of 5.9-9.6. Re-cut by hand to 8.0 minutes."),
]

#: The stages a section passes through, in the order they block on each other.
STAGES = ("audioscript", "align", "questions", "answer_key", "import")


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


#: A page carrying fewer characters than this is a picture of text, not text.
TEXT_PAGE_CHARS = 200


def probe_pdf(path: pathlib.Path) -> tuple[int, int]:
    """Page count, and how many of those pages carry real extractable text.

    Counted per page rather than averaged over the document: book 19 has text
    on 19 pages of 139, and those few dense pages drag a mean over any
    threshold worth setting, which reports a scanned book as a readable one."""
    with pymupdf.open(path) as doc:
        return len(doc), sum(1 for page in doc if len(page.get_text()) >= TEXT_PAGE_CHARS)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def cmd_init() -> int:
    if not MANIFEST.exists():
        print(f"No manifest at {MANIFEST}. Run seed/manifest.py first.", file=sys.stderr)
        return 1
    rows = json.loads(MANIFEST.read_text())

    conn = connect()
    conn.executescript((SEED / "schema.sql").read_text())

    for number in sorted({r["book"] for r in rows}):
        title, kind, has_script, note = BOOK_FACTS.get(
            number, (f"Cambridge IELTS {number}", "cambridge", None, None))
        conn.execute(
            """INSERT INTO book (number, title, kind, has_audioscript, note)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(number) DO UPDATE SET
                   title = excluded.title, kind = excluded.kind,
                   has_audioscript = excluded.has_audioscript, note = excluded.note""",
            (number, title, kind, has_script, note))

    doc_ids: dict[str, int] = {}
    for rel in sorted({r["pdf"] for r in rows if r["pdf"]}):
        path = MATERIALS / rel
        pages, text_pages = probe_pdf(path)
        book = int(rel.split("/")[0].removeprefix("Cambridge ").split()[0])
        conn.execute(
            """INSERT INTO document (book_number, rel_path, sha256, pages,
                                     text_pages, has_text_layer)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(rel_path) DO UPDATE SET
                   sha256 = excluded.sha256, pages = excluded.pages,
                   text_pages = excluded.text_pages,
                   has_text_layer = excluded.has_text_layer""",
            # "Has a text layer" means most of the book is readable as text, not
            # that some of it is: a title page with a caption is not a text layer.
            (book, rel, sha256_file(path), pages, text_pages,
             int(text_pages > pages / 2)))
        doc_ids[rel] = conn.execute(
            "SELECT id FROM document WHERE rel_path = ?", (rel,)).fetchone()["id"]

    conn.execute("UPDATE document SET audioscript_page = 103 "
                 "WHERE rel_path LIKE 'Cambridge 11/%' AND audioscript_page IS NULL")

    for r in rows:
        conn.execute(
            """INSERT INTO section (id, book_number, test_no, section_no, document_id,
                                    rel_path, sha256, duration_ms, container,
                                    sample_rate, channels, convention)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   document_id = excluded.document_id, rel_path = excluded.rel_path,
                   sha256 = excluded.sha256, duration_ms = excluded.duration_ms,
                   container = excluded.container, sample_rate = excluded.sample_rate,
                   channels = excluded.channels, convention = excluded.convention""",
            (r["id"], r["book"], r["test"], r["section"], doc_ids.get(r["pdf"]),
             r["path"], r["sha256"], round(r["secs"] * 1000), r["format"],
             r["sample_rate"], r["channels"], r["convention"]))

    # A section of a book with no audioscript can never be aligned, so it starts
    # blocked rather than pending. A batch run that ignores the difference
    # spends an hour discovering it.
    for r in rows:
        blocked = BOOK_FACTS.get(r["book"], (None, None, None, None))[2] == 0
        for stage in STAGES:
            status = "blocked" if blocked and stage in ("audioscript", "align") else "pending"
            conn.execute(
                """INSERT INTO stage (section_id, name, status) VALUES (?, ?, ?)
                   ON CONFLICT(section_id, name) DO NOTHING""",
                (r["id"], stage, status))

    for subject, severity, summary, detail in FINDINGS:
        conn.execute(
            """INSERT INTO finding (subject, severity, summary, detail)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(summary) DO UPDATE SET
                   subject = excluded.subject, severity = excluded.severity,
                   detail = excluded.detail""",
            (subject, severity, summary, detail))

    conn.commit()
    print(f"{DB_PATH.relative_to(REPO)}: "
          f"{conn.execute('SELECT COUNT(*) c FROM book').fetchone()['c']} books, "
          f"{conn.execute('SELECT COUNT(*) c FROM document').fetchone()['c']} documents, "
          f"{conn.execute('SELECT COUNT(*) c FROM section').fetchone()['c']} sections, "
          f"{conn.execute('SELECT COUNT(*) c FROM finding').fetchone()['c']} findings")
    conn.close()
    return 0


def cmd_status() -> int:
    if not DB_PATH.exists():
        print("No catalogue yet. Run: python seed/db.py init", file=sys.stderr)
        return 1
    conn = connect()

    print(f"{'book':<6}{'kind':<12}{'script':>7}{'sections':>9}{'hours':>7}   documents")
    for b in conn.execute("""
            SELECT b.number, b.kind, b.has_audioscript,
                   (SELECT COUNT(*)          FROM section  s WHERE s.book_number = b.number) n,
                   (SELECT SUM(duration_ms)  FROM section  s WHERE s.book_number = b.number) ms,
                   (SELECT COUNT(*)          FROM document d WHERE d.book_number = b.number) docs,
                   (SELECT SUM(text_pages)   FROM document d WHERE d.book_number = b.number) tp,
                   (SELECT SUM(pages)        FROM document d WHERE d.book_number = b.number) pp
            FROM book b ORDER BY b.number"""):
        script = {1: "yes", 0: "NO", None: "?"}[b["has_audioscript"]]
        docs = f"{b['docs']} pdf, {b['tp']}/{b['pp']} pages with text"
        print(f"{b['number']:<6}{b['kind']:<12}{script:>7}{b['n']:>9}"
              f"{b['ms'] / 3600000:>7.1f}   {docs}")

    total = conn.execute("SELECT COUNT(*) n, SUM(duration_ms) ms FROM section").fetchone()
    print(f"\n{total['n']} sections, {total['ms'] / 3600000:.1f} hours")

    print(f"\n{'stage':<14}" + "".join(f"{s:>10}" for s in
                                       ("pending", "blocked", "running", "done", "failed")))
    for name in STAGES:
        counts = dict(conn.execute(
            "SELECT status, COUNT(*) c FROM stage WHERE name = ? GROUP BY status",
            (name,)).fetchall())
        print(f"{name:<14}" + "".join(f"{counts.get(s, 0):>10}" for s in
                                      ("pending", "blocked", "running", "done", "failed")))

    print()
    for f in conn.execute(
            "SELECT * FROM finding WHERE severity != 'resolved' "
            "ORDER BY CASE severity WHEN 'blocker' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END"):
        print(f"  [{f['severity']:<7}] {f['subject']:<12} {f['summary']}")
    conn.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("init", "status"))
    return {"init": cmd_init, "status": cmd_status}[ap.parse_args().command]()


if __name__ == "__main__":
    sys.exit(main())

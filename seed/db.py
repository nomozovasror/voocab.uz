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

#: What the files themselves cannot say. `has_audioscript` decides what the
#: pipeline is allowed to attempt -- only a printed audioscript makes forced
#: alignment possible -- and `kind` says how that book's pages are laid out,
#: which is a different question: the Trainer prints a transcript and marks the
#: answer inline, the Guide prints one and does not number the answer at all.
BOOK_FACTS: dict[int, tuple[str, str, int | None, str | None]] = {
    **{n: (f"Cambridge IELTS {n}", "cambridge", None, None) for n in range(10, 20)},
    101: ("Cambridge IELTS Trainer", "trainer", 1,
          "transcripts at printed page 173, interleaved with the key test by test; "
          "the answer is marked inline as '(31)' and underlined, not in the margin"),
    102: ("The Official Cambridge Guide to IELTS", "guide", 1,
          "eight practice tests; recording scripts head each section with its track "
          "number and underline the answers WITHOUT numbering them"),
    103: ("Cambridge IELTS Trainer 2", "trainer", 0,
          "questions and key are a clean text layer, but the audioscripts were never "
          "printed -- the book sends you to esource.cambridge.org for them"),
    11: ("Cambridge IELTS 11", "cambridge", 1, "audioscripts confirmed from page 103"),
    17: ("Cambridge IELTS 17", "cambridge", 1,
         "has an OCR text layer, but a contaminated one -- read the pages visually instead"),
    # The title is what a material is called on the site, and it is the key
    # import_section.py dedups on -- so it has to stay exactly what the old
    # f"Cambridge IELTS {number}" produced, or re-importing book 20 would
    # create sixteen second copies rather than update the first sixteen. What
    # the edition actually is belongs in the note.
    20: ("Cambridge IELTS 20", "retypeset", 0,
         "the Academic paper, Chinese re-typeset: questions are cleanly set and "
         "there is no audioscript anywhere in the four PDFs"),
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
    ("20", "blocker",
     "Cambridge 20's pages cannot be located the way the others' are",
     "It is four PDFs, one per test, with indices restarting in each, and its "
     "re-typeset packs several parts onto one page -- 'Test1-listening-part2' and "
     "'-part3' share a sheet. locate_pages.py assumes one heading per page and one "
     "document per book, so it finds nothing here. The sixteen sections are blocked "
     "on the missing audioscript anyway, so this waits for the ASR path rather than "
     "for a page-map special case."),
    ("corpus", "info",
     "Newer books say PART where older ones say SECTION",
     "IELTS renamed the listening sections to parts around 2020. Cambridge 10-14 print "
     "'SECTION 3  Questions 21-30' and 15 onwards print 'PART 3'. A heading regex that "
     "knows only the older word finds nothing in half the corpus -- five books came "
     "back 0/16 before it accepted both."),
    ("cam102-t6-p2", "blocker",
     "The Guide's test 6 is missing four sheets, and passage 2 with them",
     "Printed pages 255-258 are not in the PDF: pdf index 254 is printed page 254 and "
     "the next sheet is printed page 259. Those four hold the whole of Reading Passage "
     "2 of test 6 -- its text and questions 14 to 30 -- so the paper can be read as two "
     "passages or not at all. This is the one gap in 192 that locate_passages.py cannot "
     "close, and it is a gap in the source rather than in the pipeline."),
    ("12", "info",
     "Cambridge 12 numbers its tests 5 to 8",
     "It continues from Cambridge 11 rather than starting again, so a book's own test "
     "numbers say nothing about which of its four tests a page belongs to. Answer keys "
     "are matched to tests by ORDER for that reason."),
    ("14", "resolved",
     "Cambridge 14 was AAC behind a .mp3 extension",
     "Sixteen files unreadable by libsndfile (no AAC) and by afinfo (trusts the "
     "extension). fix_extensions.py renamed fifteen by content sniff; the sixteenth had "
     "already been re-cut by hand."),
    ("cam14-t2-s4", "resolved",
     "cam14-t2-s4 had the next test appended",
     "17.3 minutes against a library range of 5.9-9.6. Re-cut by hand to 8.0 minutes."),
    ("103", "blocker",
     "IELTS Trainer 2 prints no audioscripts",
     "The back of the book runs questions, answer sheets, then KEY Test 1-6 with "
     "explanations, and stops. Page 4 says why: 'use the audio files available to "
     "download with the audioscripts from esource.cambridge.org'. Its 24 sections "
     "take the Cambridge 20 route -- heard by ASR, markers placed by meaning."),
    ("102", "warning",
     "The Guide's recording scripts underline the answers but do not number them",
     "Cambridge and the Trainer both name the question: 'Q31' in the margin, '(31)' "
     "inline. The Guide only underlines the phrase. The numbering is recoverable -- "
     "the nth underline in a section is question n -- but that rule breaks on a "
     "'choose TWO letters', where one question takes two underlines, so it has to be "
     "checked against the count the key expects rather than trusted."),
    ("102", "info",
     "The Guide holds eight practice tests, not four",
     "Which is why section.test_no runs to 8. Its listening tracks are Cam39 to "
     "Cam70, four to a test in order, and the recording scripts confirm the mapping "
     "in print: Practice Test 2 Section 1 is headed track 43."),
    ("corpus", "blocker",
     "Both providers stopped mid-book, for two different reasons",
     "Groq returned 'Organization has blocked API access because a spend alert "
     "threshold was met' -- an alert set on the account, not an empty balance, "
     "and clearing it in the console brings it back. Gemini's free tier is 500 "
     "requests a DAY for gemini-flash-lite ('limit: 500, model: gemini-flash-"
     "lite'), which one 398-page book uses most of; it recovers on its own at "
     "the daily reset. Reading the Guide's remaining 106 pages, then both it "
     "and Trainer 2 through the pipeline, is roughly 800 more requests -- two "
     "days of free-tier Gemini, or a few minutes of Groq at about $0.0006 a "
     "page."),
    ("corpus", "warning",
     "A Google AI Pro subscription does not raise the API's limits, and may lower them",
     "Measured, because it was asked. Before: the 429 named the metric "
     "'generate_content_free_tier_requests, limit: 500' -- the free tier, 500 a "
     "day, counted separately PER MODEL, so gemini-flash-latest was a second "
     "day's work on a day gemini-3.1-flash-lite was spent. After the subscription "
     "was bought, BOTH models answer 'Your prepayment credits are depleted. Please "
     "go to AI Studio at https://ai.studio/projects to manage your project and "
     "billing' -- the project has left the free tier for a prepaid one with no "
     "balance, which for this work is worse than the free tier it replaced. AI Pro "
     "is a consumer subscription for the Gemini app; the API key's tier follows the "
     "Cloud project behind it. What is needed is credit on that project, and the "
     "amount is small: 499 requests went through today for a measured $0.35."),
    ("102", "warning",
     "A quarter of the Guide came back unread, and said so",
     "The first pass ran out of Gemini quota at index 286 and recorded pages 286 "
     "to 397 as unread rather than as 'other' -- which is exactly why classify() "
     "was changed to do that after Cambridge 20 lost 34 pages to the opposite. "
     "`locate_pages.py 102 --unread` re-reads only those and keeps the 292 pages "
     "that were read."),
    ("corpus", "blocker",
     "Complete IELTS Bands 6.5-7.5 cannot be seeded from what arrived",
     "The Student's Book is a coursebook, not a test book: its 55 tracks are unit "
     "exercises with only eight running long enough to be a section. 153 of its 189 "
     "pages carry no extractable text, it prints no audioscript, and no answer key "
     "was found in it -- both live in the Teacher's Book. Registered nowhere and "
     "counted in nothing; it needs a different source file, not a pipeline change."),
]

#: Sections that must be HEARD whatever their book does. A book-level flag
#: cannot say this: Cambridge 13 prints audioscripts, and printed page 108 --
#: the one carrying test 3 section 2 -- is missing from the scan, so the pages
#: the catalogue names for it hold the wrong section's words.
HEARD_SECTIONS = ("cam13-t3-s2",)

#: The stages a section passes through, in the order they block on each other.
STAGES = ("audioscript", "questions", "answer_key", "align", "picture", "trim", "import")


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


def widen(conn: sqlite3.Connection) -> None:
    """Rebuild the catalogue in place when schema.sql has outgrown it.

    SQLite cannot ALTER a CHECK constraint, and `CREATE TABLE IF NOT EXISTS`
    does nothing to a table that already exists -- so a catalogue built before
    the Guide arrived would still refuse its test 5, and one built before the
    Trainer would refuse kind='trainer'. Deleting the file and starting again
    is not an option: `stage` and `finding` are the only things in here that no
    rebuild could reproduce.

    Every table is renamed aside, recreated from schema.sql, and refilled by
    the columns the two definitions have in common -- all of them, not only
    the two whose constraints moved, because renaming one table rewrites the
    references to it held by the others. Doing it to a single table leaves
    `stage` pointing at `section_old`, and `section_old` is about to be
    dropped; that is not a hypothetical, it is what this did on its first
    run.
    """
    marks = {  # what the OUTGROWN definition of each table still contains
        "book": "CHECK (kind IN ('cambridge', 'retypeset'))",
        "section": "CHECK (test_no    BETWEEN 1 AND 4)",
    }
    written = {r["name"]: r["sql"] or "" for r in conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'table'")}
    if not any(mark in written.get(table, "") for table, mark in marks.items()):
        return

    tables = [t for t in written if not t.startswith("sqlite_")]
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    # The view names the tables it reads, so a rename would rewrite it and
    # then CREATE VIEW IF NOT EXISTS would leave the rewrite in place.
    conn.execute("DROP VIEW IF EXISTS work_remaining")
    for table in tables:
        conn.execute(f'ALTER TABLE "{table}" RENAME TO "{table}__old"')
    conn.executescript((SEED / "schema.sql").read_text())
    # schema.sql opens with `PRAGMA foreign_keys = ON`, and executescript
    # commits first -- so running it turns the constraint back on midway
    # through the one operation that needs it off. Off again, and checked
    # rather than assumed, because the failure it causes lands eight
    # statements later on a DROP with nothing to say about why.
    conn.execute("PRAGMA foreign_keys = OFF")
    if conn.execute("PRAGMA foreign_keys").fetchone()[0]:
        raise SystemExit("PROBLEM  foreign keys would not turn off; "
                         "the rebuild cannot proceed safely")
    for table in tables:
        fresh = {r["name"] for r in conn.execute(f'PRAGMA table_info("{table}")')}
        kept = [r["name"] for r in conn.execute(f'PRAGMA table_info("{table}__old")')
                if r["name"] in fresh]
        columns = ", ".join(f'"{c}"' for c in kept)
        conn.execute(f'INSERT INTO "{table}" ({columns}) '
                     f'SELECT {columns} FROM "{table}__old"')
        moved = conn.execute(f'SELECT COUNT(*) c FROM "{table}"').fetchone()["c"]
        print(f"rebuilt {table}, {moved} row(s) carried over")
    for table in tables:
        conn.execute(f'DROP TABLE "{table}__old"')
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    dangling = conn.execute("PRAGMA foreign_key_check").fetchall()
    if dangling:
        raise SystemExit(f"PROBLEM  the rebuild left {len(dangling)} dangling "
                         f"reference(s); the catalogue is not safe to use")


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
    widen(conn)

    # CREATE TABLE IF NOT EXISTS does nothing to a table that already exists,
    # so a column added to schema.sql never reaches an existing catalogue.
    # Adding the missing ones here keeps `init` the single way to bring a
    # catalogue up to date, without dropping the stage progress to do it.
    for table, column, decl in (
        ("section", "question_pages", "TEXT"),
        ("section", "has_audioscript", "INTEGER"),
        ("section", "key_page", "INTEGER"),
        ("section", "script_pages", "TEXT"),
        ("document", "audioscript_page", "INTEGER"),
    ):
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            print(f"added {table}.{column}")

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
        # From the manifest rather than from the folder name: three of the
        # books are not called "Cambridge N" at all, and the row that names
        # the PDF already knows which book it belongs to.
        book = next(r["book"] for r in rows if r["pdf"] == rel)
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

    # Left to locate_pages.py, which finds it by reading the book. The hand
    # value here was 103 -- the PRINTED page -- while every other page number
    # in the catalogue is a zero-based index. The audioscripts start at 102.

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

    # A book with no printed audioscript is HEARD rather than read -- that is
    # what hear_audio.py is -- so its sections start pending like any other.
    # They used to start 'blocked', which was true before there was a way to
    # hear one and is a lie now: it stopped IELTS Trainer 2 dead, and
    # run_pipeline's --force cannot override a blocked stage by design.
    # Existing rows are corrected, because 'blocked' is a judgement the
    # catalogue made and judgements go stale.
    for r in rows:
        for stage in STAGES:
            conn.execute(
                """INSERT INTO stage (section_id, name, status) VALUES (?, ?, 'pending')
                   ON CONFLICT(section_id, name) DO NOTHING""",
                (r["id"], stage))
    freed = conn.execute(
        """UPDATE stage SET status = 'pending', updated_at = datetime('now')
           WHERE status = 'blocked' AND name IN ('audioscript', 'align')""").rowcount
    if freed:
        print(f"unblocked {freed} stage(s): a book with no audioscript is heard, "
              "not stuck")

    # The one section whose own pages cannot be read, in a book whose others
    # can. Set here rather than left to a person to remember, because
    # forgetting it is silent: the pages exist, they are just somebody else's.
    for section_id in HEARD_SECTIONS:
        conn.execute("UPDATE section SET has_audioscript = 0 WHERE id = ?",
                     (section_id,))

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

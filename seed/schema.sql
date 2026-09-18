-- Catalogue of the source material, and how far each section has been taken.
--
-- SQLite, and deliberately not the app's Postgres: this is the pipeline's own
-- bookkeeping, not product data. Putting it in the app database would mean an
-- Alembic migration every time a pipeline stage changed its mind, and would
-- mix "what we know about a scanned book" with "what a learner can practise".
-- One file, no server, and it travels to the office machine by being copied.
--
-- Everything here is rebuildable from Materials/ except `stage` and `finding`,
-- which record work and judgement rather than facts about files.

PRAGMA foreign_keys = ON;


-- One row per book that arrived. `kind` says which family the book belongs to
-- and therefore how its pages are laid out; `has_audioscript` is the flag that
-- actually decides what the pipeline may attempt, because only a printed
-- audioscript makes forced alignment possible.
--
-- 'cambridge'  the numbered editions, audioscript at the back with Q numbers
--              down the margin
-- 'retypeset'  Cambridge 20, cleanly typeset questions and no script at all
-- 'trainer'    IELTS Trainer 1 and 2. Six tests, and the transcript (where
--              there is one) marks the answer inline as "(31)" rather than in
--              the margin
-- 'guide'      the Official Cambridge Guide. EIGHT tests, and its recording
--              scripts underline the answer without numbering it
CREATE TABLE IF NOT EXISTS book (
    number           INTEGER PRIMARY KEY,
    title            TEXT    NOT NULL,
    kind             TEXT    NOT NULL CHECK (kind IN ('cambridge', 'retypeset',
                                                      'trainer', 'guide')),
    -- NULL until somebody has actually looked. Not a default of "yes":
    -- assuming an audioscript exists is how a batch run discovers at the end
    -- that a sixth of it was never alignable.
    has_audioscript  INTEGER CHECK (has_audioscript IN (0, 1)),
    note             TEXT
);


-- The PDFs. Books 10-19 shipped one for the whole book; Cambridge 20 shipped
-- four, one per test -- which is why a section names its document rather than
-- inheriting its book's.
CREATE TABLE IF NOT EXISTS document (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    book_number      INTEGER NOT NULL REFERENCES book(number),
    rel_path         TEXT    NOT NULL UNIQUE,   -- relative to Materials/
    sha256           TEXT    NOT NULL,
    pages            INTEGER NOT NULL,
    -- How many pages carry real extractable text, against how many there are.
    -- A MEAN over the document was the first attempt and it lies: book 19 has
    -- text on 19 pages of 139, and those few dense pages pull the average over
    -- any threshold you pick. The fraction is what says "this is a scan".
    text_pages       INTEGER NOT NULL,
    has_text_layer   INTEGER NOT NULL CHECK (has_text_layer IN (0, 1)),
    -- Where the audioscripts start, once found. NULL until located.
    audioscript_page INTEGER,
    note             TEXT
);


-- The unit of work. One recording, one test section, one future Material.
CREATE TABLE IF NOT EXISTS section (
    id            TEXT    PRIMARY KEY,          -- cam11-t1-s1
    book_number   INTEGER NOT NULL REFERENCES book(number),
    -- Up to eight because the Official Cambridge Guide prints eight practice
    -- tests in one volume. Every other book here stops at four.
    test_no       INTEGER NOT NULL CHECK (test_no    BETWEEN 1 AND 8),
    section_no    INTEGER NOT NULL CHECK (section_no BETWEEN 1 AND 4),
    document_id   INTEGER          REFERENCES document(id),
    rel_path      TEXT    NOT NULL UNIQUE,
    -- The same content hash the backend dedups on, so a section already
    -- ingested is recognisable without re-reading the file.
    sha256        TEXT    NOT NULL,
    duration_ms   INTEGER NOT NULL,
    container     TEXT    NOT NULL,             -- MP3 | AAC | WAV
    sample_rate   INTEGER NOT NULL,
    channels      INTEGER NOT NULL,
    -- Which naming convention this file arrived under. Kept so a re-inventory
    -- that suddenly parses a file differently is visible rather than silent.
    convention    TEXT    NOT NULL,
    -- Where this section's questions and its answer key are, as ZERO-BASED pdf
    -- indices. Filled in by locate_pages.py, which reads every page and asks
    -- what it is; NULL until it has run. Indices rather than printed page
    -- numbers because they are not the same: Cambridge 11's printed page 10 is
    -- index 7, and assuming otherwise reads Section 2's questions as Section 1's.
    question_pages TEXT,                        -- JSON array of ints
    key_page       INTEGER,
    -- The pages of the audioscript for THIS section, same indexing. What
    -- forced alignment reads its text from.
    script_pages   TEXT,                        -- JSON array of ints
    -- NULL where the questions were read off the book's own pages, which is
    -- the normal case and the one to prefer. Otherwise the URL they were read
    -- from instead: five of Cambridge 20's tables would not come off the PDF
    -- straight, and a text of the same paper had no columns to guess at. The
    -- ANSWERS are never taken from there -- they come off the book's key page
    -- whatever this says -- but where a question's wording came from is not
    -- something to have to work out later from a commit message.
    question_source TEXT,
    -- NULL means "whatever the book does". 0 means THIS section must be heard
    -- however the rest of its book is read: cam13-t3-s2's audioscript page is
    -- missing from the scan, so the pages the catalogue names for it carry
    -- somebody else's words. Without it, a book-level flag is the only thing
    -- the runner looks at, and a re-run silently replaced a good heard
    -- transcript with a reading of the wrong pages.
    has_audioscript INTEGER CHECK (has_audioscript IN (0, 1)),
    note          TEXT,
    UNIQUE (book_number, test_no, section_no)
);


-- How far a section has been taken, one row per stage. A table rather than a
-- column per stage on purpose: adding 'answer_key' or 'replay_spans' later is
-- an INSERT, not a migration. `meta` carries whatever that stage wants to
-- remember -- word counts, alignment scores, the confidence flags that decide
-- which sections get looked at by hand.
CREATE TABLE IF NOT EXISTS stage (
    section_id   TEXT    NOT NULL REFERENCES section(id) ON DELETE CASCADE,
    name         TEXT    NOT NULL,              -- audioscript | align | questions | answer_key | import
    status       TEXT    NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'running', 'done', 'failed', 'blocked', 'skipped')),
    attempts     INTEGER NOT NULL DEFAULT 0,
    -- Where this stage left its intermediate JSON, so the next stage can be
    -- re-run without redoing this one.
    output_path  TEXT,
    error        TEXT,
    meta         TEXT,                          -- JSON
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (section_id, name)
);

CREATE INDEX IF NOT EXISTS ix_stage_status ON stage(name, status);


-- Things learned that no amount of re-running will rediscover: that a book has
-- no audioscript, that a text layer is poisoned, that a recording had the next
-- test appended to it. `subject` is a book number, a section id, or 'corpus'.
CREATE TABLE IF NOT EXISTS finding (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    subject     TEXT    NOT NULL,
    severity    TEXT    NOT NULL CHECK (severity IN ('blocker', 'warning', 'info', 'resolved')),
    summary     TEXT    NOT NULL UNIQUE,
    detail      TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_finding_subject ON finding(subject);


-- A reading passage: the text, its questions, and where both are printed.
--
-- Its OWN table rather than a column on `section`, and the reason is what
-- `section` is: facts about an audio FILE -- a path, a sha256, a duration, a
-- sample rate, all NOT NULL and none of them true of a passage. Bending them
-- to nullable would leave one table where half the columns are about the
-- other half of the corpus, and the row would no longer say what it is.
--
-- The two are siblings, not parent and child: one book holds sixteen
-- listening sections and twelve reading passages, and neither is part of the
-- other.
CREATE TABLE IF NOT EXISTS passage (
    id            TEXT    PRIMARY KEY,          -- cam11-t1-p2
    book_number   INTEGER NOT NULL REFERENCES book(number),
    -- Up to eight, like a section: the Official Guide prints eight tests.
    test_no       INTEGER NOT NULL CHECK (test_no    BETWEEN 1 AND 8),
    -- Three to an Academic paper, always. A fourth is a misread.
    passage_no    INTEGER NOT NULL CHECK (passage_no BETWEEN 1 AND 3),
    document_id   INTEGER          REFERENCES document(id),
    -- Every page this passage runs across, questions included, as ZERO-BASED
    -- pdf indices -- the same indexing `section.question_pages` uses, and for
    -- the same reason: a printed page number is not a pdf index.
    pages         TEXT,                          -- JSON array of ints
    -- Where its answers are printed. Separate from the listening key, which
    -- these books print on the facing page and which cost a whole test of
    -- wrong answers the one time the two were confused.
    key_page      INTEGER,
    -- The passage's own title, once read off the page. NULL until then.
    title         TEXT,
    -- How the pages were grouped. `heading` where the book prints "READING
    -- PASSAGE 2" and the grouping fell out of the page map for free; `read`
    -- where that came back empty and a narrowed re-read settled it. Kept so a
    -- grouping that later looks wrong can be told apart from one that was
    -- never in doubt.
    located_by    TEXT    CHECK (located_by IN ('heading', 'read')),
    note          TEXT,
    UNIQUE (book_number, test_no, passage_no)
);

CREATE INDEX IF NOT EXISTS ix_passage_book ON passage(book_number);


-- What is left to do, in the order it blocks on. A section with no audioscript
-- cannot be aligned, so it shows here as blocked rather than pending, and a
-- batch run that ignores the difference wastes an hour finding out.
CREATE VIEW IF NOT EXISTS work_remaining AS
SELECT s.id,
       s.book_number,
       b.kind,
       b.has_audioscript,
       ROUND(s.duration_ms / 60000.0, 1) AS minutes,
       COALESCE(st.name, '-')            AS stage,
       COALESCE(st.status, 'pending')    AS status
FROM section s
JOIN book b ON b.number = s.book_number
LEFT JOIN stage st ON st.section_id = s.id
ORDER BY s.book_number, s.test_no, s.section_no;

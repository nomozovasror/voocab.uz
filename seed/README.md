# Seed pipeline — source material

Offline tooling that turns the books and recordings in `Materials/` into
listening materials. It is deliberately **outside** `backend/`: it needs
torch, it needs no database, and it must never be installed into the API or
worker image.

`Materials/` is gitignored — copyrighted source, 2.6GB of it. `manifest.json`
is the part worth keeping: it records what was found, so a re-run that gets a
different answer is a change somebody can see.

## Its own environment

```bash
uv venv --python 3.14 seed/.venv
uv pip install --python seed/.venv/bin/python torch torchaudio soundfile
```

Python 3.14 works — torch 2.14 and torchaudio 2.11 both ship `cp314` macOS
arm64 wheels. WhisperX does not, which is one of the reasons the aligner here
is torchaudio's own `MMS_FA` rather than WhisperX: the other is that WhisperX
drags in `faster-whisper`/`ctranslate2` for an ASR step this pipeline does not
perform.

**Load audio with `soundfile`, never `torchaudio.load`.** torchaudio 2.11
routes loading through `torchcodec`, which needs a working ffmpeg; libsndfile
reads mp3 directly and the pipeline then needs no ffmpeg at all.

## What is in `Materials/`

`manifest.py` builds `manifest.json`: every Cambridge section file mapped to a
canonical `cam{book}-t{test}-s{section}` id, with duration, format and SHA-256.
Nothing is renamed or moved — the manifest points at the files where they are,
so a wrong guess costs a re-run rather than a restore.

Eleven books arrived under **six** naming conventions and the manifest is the
only place that knows about them:

| Books | Filename shape |
|---|---|
| 10–14 | `Cambridge IELTS 12.3.2 [...].mp3` — book.test.section |
| 15, 17 | `IELTS15_test3_audio2`, `IELTS17_t3_audio2` |
| 16 | `Test 3 Part 2[...]` |
| 18 | `C 18 section3-part2` — "section" is the TEST, "part" is the section |
| 19 | `T3 P2 [...]` |
| 20 | `T3S2` |

176 files, 176 matched, no gaps and no duplicate ids: eleven books × four
tests × four sections, 22.0 hours.

Each row also names the PDF carrying its questions, audioscript and key.
Books 10–19 print one document for the whole book; Cambridge 20 arrived as
four, one per test, so a section has to name its own source rather than
inherit the book's.

### What the inventory turned up

* **Cambridge 14 was not mp3** — sixteen AAC/M4A files behind a `.mp3`
  extension, unreadable by libsndfile (no AAC) and by `afinfo` (trusts the
  extension). `fix_extensions.py` renamed fifteen of them by content sniff;
  the sixteenth had already been re-cut by hand. Fixed. They still run at
  22 kHz against everyone else's 44.1, which costs nothing: alignment
  resamples to 16 kHz mono regardless.
* **`cam14-t2-s4` was 17.3 minutes** — the next test was appended to it. Re-cut
  by hand to 8.0 minutes. No duration outliers remain anywhere in the library.
* **Cambridge 16's PDF arrived**, and Cambridge 20 with it. Eleven books now.

Note for the backend, from the same bug: `app/services/storage.py` maps
extension → MIME type for audio, while images have their type read from their
own header ("the bytes said what they are"). Audio trusts the filename where
images do not, so a mislabelled upload is stored claiming a type it isn't.

The other four collections in `Materials/` — IELTS Guide, IELTS trainer,
IELTS trainer 2, Complete IELTS — are **not** in the manifest. They are
course-book CDs numbered by track (`Track No07.mp3`), and a track maps to a
page of a coursebook rather than to a test section; the mapping exists only
inside the book. They are a separate problem from the eleven Cambridge books and
should stay one, and are being left until the Cambridge books are done.

## The books are scans, and that changes the plan

`probe_pdfs.py` reports, per PDF, how much text can be extracted and where the
audioscript and answer key sit. The answer is that **there is almost no text
to extract**:

| | |
|---|---|
| Zero extractable text | 10, 11, 12, 13, 14, 16, 18, and all four of 20 |
| Real text layer | 17 only |
| Mostly scan, a few text pages | 19 (19 of 139) |

Two consequences, both of which contradict the original brief.

**The answer key cannot be read with plain text extraction.** The brief put
the key down as the easy stage — "vision kerak emas". For nine of eleven books
there is no text on the page at all, so the key goes through the same visual
path as the questions.

**Cambridge 17's text layer is worse than no text.** It is OCR output, and it
is contaminated: 3,864 Cyrillic homoglyphs (`а е о с у р А В`) sitting inside
English words, plus digit-for-letter errors — `т1м:` for `TIM:`, `1 heard` for
`I heard`, `lt's`, `аге`, `Не said`, `Ьееп`. The characters look right and
compare unequal, so this text would poison an answer key silently and break
alignment loudly (MMS_FA knows `a-z`; a Cyrillic `а` is stripped and the word
collapses). Its layout is lost too — the speaker column and the speech column
are separate blocks, so `get_text()` returns every label first and then every
line of speech, with the turns gone.

So: re-read the pages visually rather than repairing the text layer. Whatever
reads the question pages should read the audioscript and the key as well.

### The scans themselves are good, and they carry a gift

Cambridge 11's audioscripts start on page 103 at roughly 300 DPI, clean and
high-contrast. And the printed audioscript **already marks where every answer
is spoken**: `Q1`, `Q2`, `Q3` … down the right margin, with the answer phrase
underlined in the body text.

That is a much better route to `replay_start_ms` than searching the aligned
word stream for the answer text. The marker names the turn, and a turn's start
was the most accurate thing the alignment measured (median ~40ms) — where
hunting for a spelled-out phone number runs straight into the one thing
alignment is bad at. It also means the answer key can be cross-checked against
the audioscript before either is trusted.

The scans carry watermarks that the cleaner has to drop — `iyuce.com` headers
and footers, red "Edit by:" lines — and on at least one page a large
`PREDICTING` watermark sits on top of the text and obscures it. Print-only
noise mostly, but not always harmless.

### Cambridge 20 is a different book

It is a Chinese-market re-typeset (剑桥雅思官方真题集), not the Cambridge
original, and it behaves differently in three ways:

* **No audioscript at all.** Its listening section is four pages of questions
  and then the reading passages start. Forced alignment is therefore
  impossible for these sixteen sections; they would need ASR, which is the one
  job the office GPU would actually be useful for.
* **The answer key uses its own conventions**: `9、30|thirty` — alternatives
  separated by `|`, not the `/` the brief expected — and `17-18.AE`, a "choose
  TWO letters" spanning two question numbers. That second shape maps exactly
  onto `question_marks()`: one `Question` row, two letters, two marks.
* **Instruction lines are missing.** Test 1 Part 1 is a bare table with
  numbered gaps and no "Complete the table below / NO MORE THAN TWO WORDS"
  above it, so `instructions` and `word_limit` have no source on the page.

Its questions are, on the other hand, the cleanest input in the whole corpus:
digitally re-typeset and rendered as images, not photographed paper.

## Forced alignment, measured

`clean.py` splits a book audioscript into spoken turns. `align.py` aligns a
known transcript against its recording and reports throughput.

The measurements below are from a synthetic multi-voice recording built by
`say` with known timings, on an M2 Air. They settle cost, not quality —
alignment compute is a fixed forward pass over the waveform, so the throughput
carries over to real recordings; accuracy does not, and has to be re-measured
on a real section.

| | |
|---|---|
| Model | `MMS_FA`, 315M params |
| Throughput, MPS | **29.7× realtime** |
| Throughput, CPU | 10.5× realtime |
| Throughput, unchunked | **0.8×** |
| Turn-start error | median ~40ms, nearly all under 200ms |

**Chunking is not an optimisation.** wav2vec2's attention is quadratic in
sequence length, so one pass over a whole section runs slower than realtime
while 30-second windows run at 11× on the same machine. Emissions are
frame-wise logits and concatenate cleanly; `emit_chunked()` trims a small
overlap at each seam.

At 29.7× the whole 22.0-hour Cambridge library aligns in about 45 minutes.
The office GPU is not needed for any of this.

### The weak spot, and why it matters here

Runs of short, acoustically similar monosyllables — spoken digits, spelled-out
names — get compressed, and the audio left over is absorbed by whichever word
follows. In the test recording a phone number finished four seconds early, and
the same digits in the next turn left `seven` holding for 2.4 seconds.

Those are exactly what a Section 1 answer is made of. So the alignment cannot
be trusted blindly where it matters most — but the failure is **visible**:
80ms for a spoken digit and 2.4s for one word are both outliers against any
plausible band. A per-word duration check is the cheapest confidence signal
available, and it is what tells you which of 176 sections to look at by hand.

Synthetic speech reads digit strings faster and flatter than a real speaker
does, so this may well be better on real recordings. Re-measure before
believing either version.

## The catalogue

`manifest.json` says what the files are. `catalogue.db` — SQLite, built by
`db.py init` — says that plus how far each section has been taken, and it is
what the pipeline reads and writes from here on.

```bash
seed/.venv/bin/python seed/manifest.py    # inventory Materials/ -> manifest.json
seed/.venv/bin/python seed/db.py init     # manifest + PDFs -> catalogue.db
seed/.venv/bin/python seed/db.py status   # books, hours, stage progress, findings
```

Not the app's Postgres, deliberately. This is the pipeline's bookkeeping rather
than product data: putting it in the app database would mean an Alembic
migration every time a stage changed its mind, and would mix "what we know
about a scanned book" with "what a learner can practise". One file, no server,
and it reaches the office machine by being copied.

Five tables, and the split between them is the point:

| | |
|---|---|
| `book`, `document`, `section` | facts about files — **rebuildable** from `Materials/` |
| `stage`, `finding` | work done and judgement formed — **not** rebuildable |

`init` upserts the first three by their natural keys, so re-running it after
new material arrives updates the facts and leaves the progress alone.

`stage` is a row per section per stage rather than a column per stage, so
adding `replay_spans` later is an INSERT and not a migration. Its `meta` column
carries whatever that stage wants to remember — alignment scores, word-duration
outliers, the confidence flags that decide which sections get read by hand.

Sections of a book with no audioscript start `blocked` rather than `pending`,
so Cambridge 20's sixteen are visibly waiting on ASR rather than quietly
queued behind an alignment that can never run.

## One real section, end to end

`cam11-t1-s1`, its audioscript transcribed by hand from pages 103-104 and
aligned against the actual recording:

| | |
|---|---|
| Throughput | **35.9x realtime** (MPS) — better than the synthetic 29.7x |
| Median word confidence | **0.99** |
| Words below 0.35 | 15 of 704 (2.1%) |
| Answer-span confidence | 0.75 – 0.97 across all ten questions |

It works. Four things the real recording taught that the synthetic one could
not.

**The printed audioscript is half the recording.** It begins at the first line
of dialogue: no narrator introduction, no example replay, none of the
half-minute pauses for reading the questions. 722 words against 9.6 minutes —
230 seconds of the audio has no text at all. Star tokens absorb it, and the
alignment then lands the first word at 184.7s rather than at zero.

**Stars are safe at the edges and dangerous inside.** Numbers are the problem:
the book prints "115" and `[^a-z'\- ]` deletes it, so the word vanished from
the alignment entirely — 704 words aligned out of 722, and the missing ones
were the answers. Filling those holes with stars scored well and broke the
transcript: the star standing in for "200" swallowed the example's entire
second playing and gave that turn a 71-second span. `say()` spells numbers out
instead, which leaves no hole for a star to grow in.

**A dotted line in the book is a pause in the recording.** The alignment put a
61-second gap between Q6 and Q7 with no prompting, exactly where the book
prints its mid-section rule — which is a free check that the alignment has not
drifted.

**The confidence score is the instrument; duration heuristics are not.**
Per-word confidence found the five genuinely uncertain places, one of which is
a real defect in the source: the book prints "September 1st?" and the speaker
says "September the first", and the aligner scored it 0.07. The duration checks
were noisier and wrong in a specific way — "C-H-A-R" held for 2.3 seconds is
correct, because it is spoken letter by letter, and a words-per-second check
flags every one-word turn ("Yeah.", "OK.", "Sure.") as impossible. Judge
duration per token, and only on turns of four words or more; of eight turns
that check flagged, seven were one-word answers and one was real.

## Getting a section onto the site

The catalogue is bookkeeping. Nothing in `seed/` is ever read by the app --
what a learner can practise lives in Postgres, and `backend/scripts/
import_section.py` is the one thing that crosses between them:

```
Materials/ ──► seed/catalogue.db ──► import_section.py ──► Postgres ──► the site
   mp3+pdf      what is left to do        the crossing        Material     :5173
```

That script lives in `backend/` rather than here for the same reason the rest
of this lives here: it needs the database and no torch, where extraction needs
torch and no database. It writes through the same services the API uses --
content-addressed blob, dedup on SHA-256, `persist_transcript_result` -- so a
seeded recording and an uploaded one produce identical rows.

```bash
cd backend
DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/app" \
  uv run --no-sync python -m scripts.import_section cam11-t1-s1 --owner <user-uuid>
```

**The DATABASE_URL override is not optional.** `backend/.env` points at the
test database on 5433; the dev app the site talks to is on 5432. Importing
without it puts the material somewhere the site will never look.

One `AudioSegment` per **speaker turn**, because that is the only boundary the
source actually marks and the one the review page's transcript lines want.
Materials are created **private** and the script has no switch to change that:
this is copyrighted source, in the database to prove the pipeline works rather
than to be practised. Re-running is safe -- the blob dedups on its hash and the
material is looked up by the title the script generates.

## Questions and the answer key

`questions.src.json` is what comes off the page: the template with its
``{{N}}`` gaps, the instruction lines, and each answer **exactly as the key
prints it**. `build_questions.py` expands that into `questions.json`, and
`import_section.py` writes it.

Keeping the printed form rather than only the expansion is what makes the
result auditable. When a learner reports a right answer marked wrong, the line
to check is the one the book actually prints.

### Reading the key is a parser, not a transcription

`answer_key.py` exists because `normalize_answer` is deliberately dumb -- trim,
collapse whitespace, lowercase, and nothing else. Every phrasing a candidate
might write has to be in `correct_answers` as its own string, so the key's
shorthand has to be expanded rather than stored. Two marks, and they compose:

| Printed | Accepted |
|---|---|
| `floor/floors` | floor, floors |
| `(£)115 / a hundred (and) fifteen` | 115, £115, a hundred fifteen, a hundred and fifteen |

Ten questions in Cambridge 11 Test 1 Section 1 become **fifteen** accepted
answers. Too few marks correct answers wrong; too many marks wrong ones right.

The subtlety that a first attempt gets wrong: **a separator with space around
it alternates whole phrases; one without space alternates a single word.**
`urban centres/centers` is "urban centres" or "urban centers", never "centers"
on its own. Splitting on the separator regardless of spacing silently drops the
"urban". `answer_key.py` runs its own cases -- `python seed/answer_key.py`.

### Page numbers are not PDF pages

Cambridge 11's printed page 10 is PDF index 7. Two pages of front matter sit
outside the printed numbering, and reading the offset off the contact sheet
rather than assuming it is the difference between the Section 1 questions and
the Section 2 questions. `questions.src.json` records the offset it used.

### What the build step is for

It refuses rather than writes when the template's gaps and the question numbers
disagree, when a key expands to nothing, or when a margin marker names a turn
the alignment never placed. All three are a page misread, and all three would
otherwise reach a learner as a broken question. The importer then validates
again through `FormCompletionGroupIn` -- the schema is where "gaps must match
question numbers" actually lives, and a seed script writing behind it would be
the one caller able to produce a material the editor never could.

## Reading the page with a model

`read_questions.py` does by machine what the section above describes doing by
hand, and writes the same `questions.src.json` -- so `build_questions.py`
checks its work exactly as it checks a person's. That split is the design: this
stage is allowed to be wrong, and the next stage is where being wrong is
caught.

```bash
seed/.venv/bin/python seed/read_questions.py cam11-t1-s1 --questions 7,8 --key 123
```

Groq has two models that can see: `qwen/qwen3.8-27b`, which answers directly,
and `qwen/qwen3.6-27b`, a reasoning model that puts a `<think>` block in front
of its answer. The first is the default. Requests go through `curl`, because
the endpoint sits behind Cloudflare and answers urllib's default User-Agent
with a 403 that says nothing about why.

**Two calls, not one.** The questions come off the question pages and the key
off the key page, and they are independent readings of the same ten answers.
When the gaps and the key lines disagree, a page was misread. One call would
buy one fewer request and throw that check away.

### On the one section measured, it reads better than a person

Against the version transcribed by hand from the same pages: the template came
back **identical**, and the answer key came back **more accurate**. The key
prints `(£)115 / a/one hundred (and) fifteen`; reading it off a contact sheet,
a person read `a hundred` and lost two accepted answers. Fifteen accepted
answers by hand, seventeen by machine, and the two extra ones are right.

### What it gets wrong is what a rule fixes

Two mistakes survived a prompt that had a worked example for each, because the
model transcribes what it sees line by line and "merge this into the line
above" is not what the page looks like. Both are unambiguous, so `repair()`
fixes them rather than asking again:

* **A lone `+` line is prose, not a table.** A table needs a header row and a
  body row, so a `+` line with no `+` neighbour cannot be one -- and as a
  one-row table it is all header, where gaps are not drawn at all. This is the
  exact mistake that cost question 3, made independently by a person and by a
  model, which is why the check for it is not optional.
* **The printed question number is not part of the template.** Removed only
  where the digits match that gap's own paper number, so "seats 100" is never
  touched.

### The rate limit is the bulk constraint, not the model

A page at 170 dpi costs about 3,400 input tokens and the free tier allows
7,000 a minute -- two pages. `vision.py` waits and retries on the limit
(the error says how long), so a batch survives it, but at roughly three pages
a minute the 176 sections are hours of waiting rather than hours of work. That
is a billing decision, not an engineering one.

## Cutting the preamble

What goes is the disc announcing itself. What stays is everything the candidate
is meant to hear, in order.

```bash
seed/.venv/bin/python seed/trim_audio.py cam11-t1-s1
```

**The preamble is transcribed, not guessed at.** Two earlier versions guessed
and both were wrong in ways that only listening would catch:

* cutting at the alignment's first word took the section introduction and the
  half-minute reading pause away with the branding, so the recording opened
  mid-conversation with nothing saying what was coming;
* cutting a fixed lead ahead of the reading pause landed in the middle of "the
  test is in four sections", because silence says where sentences end and
  nothing about which sentence is which.

So the first couple of minutes go through Groq's `whisper-large-v3` -- the same
model the production worker uses -- and the cut lands on the first line where
the test actually starts speaking:

```
   0.0 -   6.4   Cambridge English, IELTS 11, Tests 1-4.
   8.2 -  14.6   Published by Cambridge University Press ...
  16.2 -  18.0   This recording is copyright.
  19.8 -  20.9   CD 1.
  23.5 -  24.4   Test 1.                    <- skipped: a label, then 2s of silence
  26.4 -  33.0   You will hear a number of different recordings ...   <- the cut
  61.2 -  77.5   Now turn to section one ... You will hear a telephone
                 conversation between an official at a village hall ...
  79.6 -  84.8   First, you have some time to look at questions one to six.
  85   - 116     the pause to read them
  116  - 181     the example, played and explained
```

Two details that only listening turned up. **"Test 1." is a label, not the
test speaking** -- it lasts under a second and two seconds of silence follow
it, so cutting there gives a recording that opens with a number and a pause;
segments that are only a label are skipped. And **whisper's segment boundaries
absorb the silence in front of a sentence** -- it timed "You will hear a number
of different recordings" from 24.3s when the words start at 26.45s -- so its
start says WHICH sentence reliably and WHEN badly. The cut is anchored inside
the matched segment and walked back to the last silence, which is the real
onset.

The transcript is cached beside the alignment, so tuning the cut does not spend
the quota again. Parts 2 to 4 open at "Now turn to section three" with no
branding in front of it, so there is usually nothing to cut -- which is the
difference between the parts, arrived at from what is actually said rather than
from a rule about which part it is.

A recording where no announcement is found is not trimmed at the front at all,
and a cut taking more than three quarters of the preamble is refused. At the
end, dead air goes and speech does not: "you now have half a minute to check
your answers" is the test talking too.

Cutting means re-encoding, and libsndfile's default lands near 85 kbps against
a 128 kbps source. `compression_level=0.0` comes back at 113, so a listening
test is not marked on a worse recording than the book shipped.

`Part.audio_start_ms` looked like the answer and is not: the field exists, the
Studio editor writes it, and the take page reads it only to draw part
boundaries on the waveform -- for a single-part material it is ignored outright
(`ListeningTakePage.tsx`, `i === 0 ||`).

The importer shifts every timestamp by the recorded offset, transcript and
replay spans together. cam11-t1-s1: 578s becomes 555s.

## Where this stops

Stage 0 is done: 176 sections catalogued, every file's extension honest, every
duration plausible, and what the PDFs can and cannot give us written down.
Alignment is a measured prototype against synthetic audio, not yet wired to
anything. Nothing here writes to the app database.

`cam11-t1-s1` is aligned and its ten answer spans are cut to
`seed/work/cam11-t1-s1/clips/` — a confident alignment and a correct one are
different claims, and only listening settles the second.

`cam11-t1-s1` is now in the dev database as a private draft: audio, 39
transcript lines with word timings, one part, no questions. `publish_blockers()`
says it is not publishable, which is correct -- questions come from a stage
that does not exist yet.

`cam11-t1-s1` is complete: audio, 39 transcript lines, one `note_completion`
group, ten questions, fifteen accepted answers, and a replay span on every one
of them. `publish_blockers()` returns nothing, and it stays private anyway.

The reading is automated and measured on one section. What is not automated is
finding the pages: `--questions 7,8 --key 123` are still passed in by hand, and
a contact-sheet pass over each book -- about twelve vision calls -- is what
would replace that.

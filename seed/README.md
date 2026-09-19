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
uv pip install --python seed/.venv/bin/python torch torchaudio soundfile pymupdf
```

The whole run, once a book's pages are located:

```bash
seed/.venv/bin/python seed/locate_pages.py 11      # once per book
seed/.venv/bin/python seed/run_pipeline.py --book 11
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

## Reading the audioscript

`read_audioscript.py` writes `turns.json` -- the text the alignment is aligned
against, and the last thing in the pipeline that was typed by hand.

```bash
seed/.venv/bin/python seed/read_audioscript.py cam11-t1-s1
```

Three things come off the page and only one of them is the words: the speaker
labels, because a change of speaker is the only boundary the source marks; the
`Q1`, `Q2` markers down the right margin, which say which turn each answer is
spoken in; and the dotted rule, which is where the recording pauses for the
candidate to read the second half of the questions and where the alignment
needs a star.

### Against the hand transcription

| | by hand | by model |
|---|---|---|
| Turns | 41 | **41** |
| Break position | index 23 | **index 23** |
| Markers found | 11 | **11, every one on the same turn** |
| Text | — | **40 of 41 identical** |

The one difference is the model being righter: the book prints `£115` and the
hand copy had expanded it to "115 pounds". Its underlined answers are tighter
too -- "stage door" where the hand copy took the whole sentence around it. The
alignment run from the model's text produces the same replay spans to a tenth
of a second.

That did surface a real gap, though: dropping `£` drops a spoken word, since
the speaker says "a hundred and fifteen **pounds**". `say()` now renders the
symbol, so "£115" aligns as "one hundred and fifteen pounds".

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

Six tables, and the split between them is the point:

| | |
|---|---|
| `book`, `document`, `section` | facts about files — **rebuildable** from `Materials/` |
| `passage` | where a reading passage is printed — rebuildable, at a price |
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

`Part.audio_start_ms` looked like the answer to the trimming and is not: the
take page reads it only to draw part boundaries on the waveform, and for a
single-part material ignores it outright (`ListeningTakePage.tsx`, `i === 0 ||`).

It is not inert, though. The Studio editor DOES bound playback to it, and a
part left marked `0 - 6105` plays six seconds and stops -- which reads exactly
like a broken audio file and sent a long hunt through encoders, Xing headers,
CORS and the HTTP cache before the editor showed the marks on screen. A seeded
part is the whole recording by construction, so the importer clears both bounds
on **every** import rather than only when it creates the part.

The importer shifts every timestamp by the recorded offset, transcript and
replay spans together. cam11-t1-s1: 578s becomes 555s.

## Finding the pages

The last thing that was done by hand. `read_questions.py` needs to know which
pages hold the questions and which holds the key; `locate_pages.py` reads every
page of a book and writes that into the catalogue, so the flags become an
override rather than the interface.

```bash
seed/.venv/bin/python seed/locate_pages.py 11
seed/.venv/bin/python seed/read_questions.py cam11-t1-s1   # pages from the catalogue
```

On Cambridge 11 it finds all sixteen sections, the four answer-key pages and
the start of the audioscripts, and its answer for `cam11-t1-s1` -- pages 7 and
8, key on 123 -- is the one that was found by hand.

### One page per request, not a contact sheet

A twelve-up sheet was the obvious saving and does not work. The model spends a
fixed token budget on an image whatever it holds -- 1,488 tokens for a sheet of
twelve against 1,813 for a single page -- so each thumbnail gets a twelfth of
the detail. On twelve pages it classified five correctly, invented an answer
key and two audioscripts that were not there, and drifted a section out of step
in the middle. Page by page, the same twelve came back twelve out of twelve.

The same measurement settles the dpi question: 90, 120 and 170 dpi all cost
**1,813 tokens**. Rendering smaller saves nothing and only loses detail.

### Transcribe, then interpret -- twice over

Asked for the test number, the model returns the first question number:
"Questions 15-20" comes back as test 15. Asked to copy the running header, it
copies it correctly -- but these books print the header alternately, "Test 2"
on one side and "Listening" on the other, so a page carries one or the other
and never both. Filtering on "Listening" threw away every odd page and left
nine sections of sixteen.

What is actually reliable is the thing printed in large type: `SECTION 3
Questions 21-30`. Sections run 1,2,3,4 and start over, so a test is one such
run, and the page after a heading belongs to it if it carries no heading of its
own. Nothing is inferred that is not printed.

The audioscripts are found the same way: the **start of the longest run** of
audioscript pages, not the first page anywhere that resembles one. A single
misread page in the middle of the book made that answer 21 against a true 102.

## Running a whole test

`run_pipeline.py` calls the stages in order and records how far each section
got. It does not absorb them -- every stage stays a program you can run on its
own, and a stage that fails costs one section rather than a book.

```bash
seed/.venv/bin/python seed/run_pipeline.py --book 11 --test 1
seed/.venv/bin/python seed/run_pipeline.py --book 11        # all sixteen
```

Cambridge 11 Test 1, all four sections, about 50 seconds each:

| | group | questions | with a replay span |
|---|---|---|---|
| Part 1 | note completion | 10 | 10 |
| Part 2 | map labelling + note completion | 6 + 4 | 10 |
| Part 3 | multiple choice | 10 | 10 |
| Part 4 | note completion | 10 | 7 |

Part 2 splitting itself into two groups is the reader getting it right: the
page really is "Questions 11-16, label the map" followed by "Questions 17-20,
complete the notes".

### The order is not the interesting order

`align` has to run before `questions`, because `build_questions.py` resolves
each answer's replay span out of `aligned.json`. Run the other way round it
reports every margin marker as having no turn -- and the first two sections
passed anyway, because an earlier run had left an alignment on disk. A
dependency that only shows up on a section nobody has touched is the kind a
batch finds and a demo does not.

### Three kinds of task, not one

The pipeline was built and measured on a gap-fill and quietly assumed every
section was one. The first multiple-choice section failed at the import with a
pydantic literal error, because the importer validated everything as a
completion group. The reader now emits three shapes -- gap-fill with a
template, multiple choice with a stem and options per question, matching with a
lettered box -- the builder keeps letters as an answer KEY rather than
expanding them as phrasings, and the importer validates through the schema's
own discriminated union.

### The picture, and where each option is said

Two things a section needed before it could publish, and neither could come
from the reader.

**A labelling task is answered on a picture**, and a vision model returns text.
`extract_image.py` finds it by its **border**: the picture is printed inside a
drawn box, and a scanned page renders that box as long runs of dark pixels --
two horizontal rules across most of the width, two vertical down most of the
height. On Cambridge 11's map they land at 20% and 79% down and 7% and 75%
across, which is the box to the pixel. A bounding box asked of a model would
have been a guess in the same place. The copier's black bars at the top and
bottom of every scan are excluded first, being the outermost runs on the sheet.

How many letters are drawn on it is read off the instruction line -- "Write the
correct letter **A-I**" is nine -- rather than counted from the answer key,
which only names the ones that happen to be right.

**A choice question is linked to the audio per OPTION**, not per question: a
"choose TWO" has two answers at two moments, so publishing asks where each
chosen letter is said. The margin marker gives the turn where the answer is
given and the answer is the correct option, so that turn is what every correct
letter points at.

`picture` runs after `questions` rather than before, because
`build_questions.py` rewrites `questions.json` and would erase the picture it
had just been handed.

With both in, Cambridge 11 Test 1 publishes complete on Parts 1, 2 and 3. Part
4 is three questions short of it, because the audioscript reader did not find
three of its margin markers -- a warning rather than a failure, since refusing
the section would throw away nine good questions to protect one replay button.

## What a hundred and sixty sections found that four did not

The first full batch put 56 of 160 through every stage. The other 104 named
four faults, and every one of them is a thing a single worked example cannot
show.

**Two size limits, 58 failures.** Groq takes three images a request and refuses
a body much over a megabyte; an audioscript span can be four pages at 400 KB
each. Capped at two and rendered at 110 dpi -- audioscripts are dense text
rather than fine line-work and read fine small.

**Paired answer keys, 18 failures.** The key prints "11&12 IN EITHER ORDER"
against a question taking two of the paper's numbers. The parsing was the
smaller half of it: a "Choose TWO letters" is ONE question worth two marks, not
two questions with one letter each, so the second number is dropped rather than
given a question of its own.

**A variable shadowed, 19 failures.** Unpacking a paired label as `first,
second` overwrote the section's own first paper number, so after reading
"29&30" the coverage check expected a whole section to cover 29-30. The model
had read every one of those pages correctly.

**Audioscript headings, 19 sections.** Asked to classify a page, the model
answers the audioscript pages of some books with their running title --
"Audioscripts" -- rather than the PART heading below it. `--scripts` asks the
one thing needed rather than a general question, and recovered all but two.

That last one is the shape of nearly every failure in this pipeline: a general
question gets a general answer, and the fix is to ask a narrower one and do the
arithmetic here.

## Where the corpus stands

**All 176** sections of Cambridge 10 to 20 are in the database as private
drafts, and **all 176 are content-complete**: 1,680 questions, every one of
them carrying a replay span. Everything since the ledger started has cost
**$0.57**.

### The windowing fix worked, and less than it looked like it would

Reading a long audioscript in overlapping windows was aimed at a clear signal:
markers were missed far more often at the end of a section than the start, and
that slope is what truncation looks like.

```
position    1    2    3    4    5    6    7    8    9   10
before     32   39   36   28   24   26   33   39   50   54
after      29   37   31   29   14   21   27   35   36   41
```

The tail did come down -- position 10 from 54 misses to 41, position 9 from 50
to 36 -- and 15 sections stopped missing markers altogether. But the slope did
not flatten, and positions 1 to 4 barely moved. So truncation was *a* cause and
not *the* cause: something else loses markers evenly across a section, and it
is still losing about one in five.

Worth saying plainly because the measurement invited the wrong conclusion. A
signal that points at one explanation can be real and still be partial.

### What is left, and it is a long tail

The borderless-picture search closed the largest item on this list: nine
labelling groups that had come back "no bordered picture found" now have their
crop, and all nine sections are content-complete.

Six more were recovered without a single API call, off readings already on
disk, and the two causes are worth naming because neither is a misreading:

* **A group numbered off the paper.** A group's `number` runs 1..N within the
  group; the paper's numbering lives in `paper_number`. The reading gets that
  right for a section's first group -- the two agree there -- and hands back
  5..10 for the second. Sometimes only the template slips, sometimes only the
  questions, so `build_questions.py` now shifts each on its own evidence and
  they meet in the same place. A run with a hole in it is still refused: that
  is a misreading, and renumbering would hide it.
* **A line colliding with the layout grammar**, in the two shapes it takes.
  A form's fields read as `##` headings, where a gap is given rather than
  answered and so never drawn; and a table cell that wrapped onto its own line,
  which broke a run of `+` rows in two and made the next row a header -- where
  a gap is never drawn either. Both are corrections to the reading, made in
  `questions.src.json`.

What remains is **8 questions across 7 materials**, each one a phrase the
alignment cannot place unambiguously, plus `cam13-t3-s2` and Cambridge 20's
sixteen -- both waiting on audio nobody has a script for.

### The catalogue is not self-repairing, and `--force` is why

`--force` redoes a stage from the start, and a stage that then fails on the API
is recorded as failed -- even though its output is still on disk and its
material still in the database. Fourteen sections read that way: catalogued as
barely started, actually seeded with ten questions each. The stage table is a
record of what ran, not of what exists, and the two drift the moment a forced
run is interrupted. They were reconciled against the evidence -- the files in
`work/` and the materials in the database -- and the numbers above are the
reconciled ones.

## What it costs, and why the first estimate was eight times under

The estimate was $2.50 and the bill was $20, with books left. The estimate was
made by reading the code: a page image is about 3,400 input tokens, Groq asks
$0.29 a million for them, there are about 240 page reads in a book. All three
of those numbers are right, and their product is not the answer, because the
question is not what a page costs. It is **how many times a page is read**.

A rate is a thing you can look up. A multiplier is a thing you have to measure,
and nothing here was measuring it. So `vision.py` now appends every request's
token counts to `work/usage.jsonl` and `spend.py` adds them up:

```
seed/.venv/bin/python seed/spend.py            # by program
seed/.venv/bin/python seed/spend.py --by for   # by section
```

The column to watch is `out/call`, not the total.

### Switching provider does not fix this

Checked 2026-09-08, per million tokens:

| | in | out |
|---|---|---|
| Groq `qwen3-32b` | **$0.29** | **$0.59** |
| Gemini 3.5 Flash-Lite | $0.30 | $2.50 |
| Gemini 3.1 Flash-Lite | $0.25 | $1.50 |
| Gemini 3.8 / 3.7 / 3.6 Flash | $0.75 | $3.75 |

Groq is already among the cheapest inputs available and is four times cheaper
on output than the nearest Gemini. A `gemini` provider is in the table because
a free tier and a second account are worth having when one is spend-blocked,
not because it is cheaper per token. It is not.

### The suspect is reasoning, and it is not yet a finding

`qwen3-32b` thinks before it answers, `<think>` is billed as output at twice
the rate of the page that prompted it, and `read_json` throws it away. The
audioscript stage allows 8,000 output tokens a request. That is the shape of a
bill nobody expected, and it is a hypothesis until the ledger has a day in it.

`SEED_VISION_EFFORT` passes Groq a reasoning effort. It defaults to unset --
the provider's own default -- because what the thinking is worth here has not
been measured, and the last thing this pipeline needs is a second number
adopted on a guess. Measure it the way NVIDIA was measured: against the hand
transcription of `cam11-t1-s1`, on the margin markers, before anything else is
re-read with it.

### The cheapest run is the one that reads nothing

Six sections were recovered today without a single request, off readings
already on disk. That is the real lever, and `--force` was working against it:
bare, it redid every stage from the page reads down, so a fix in
`build_questions.py` was paid for twice. It now takes the stages to redo --

```
seed/run_pipeline.py cam18-t3-s1 --force questions,import
```

-- and `questions` reuses `questions.src.json` when it is there, so that run
costs nothing. Fourteen sections had also been recorded as barely started while
sitting complete in the database: a bare `--force` that died on the API had
overwritten their stage rows.

## Gemini measured, and adopted

Groq blocked on a spend alert with eleven sections to go, so the provider
switch got used for the first time. `gemini-3.1-flash-lite` was measured the
way NVIDIA was -- against the hand transcription of `cam11-t1-s1`, on the
margin markers, before anything was re-read with it:

| | Groq 27B | Gemini 3.1 Flash-Lite |
|---|---|---|
| Turns | 41 | **41** |
| Margin markers found | 11 of 11 | **11 of 11, on the same turns** |
| Turns identical | — | 32 of 41, the rest 0.97+ |
| One section's audioscript | — | **12s, $0.01** |

The differences are punctuation and where an underline stops. It reads pages
as well as the model it replaced, at a price the ledger can now show: eleven
sections, three whole-book page maps, four re-read audioscripts and a dozen
repairs came to twelve cents.

One defect, and not the model's: it returns the speaker label with the colon
the page prints. That is right, and the app then shows "OFFICIAL:" as a
speaker. `read_audioscript.py` strips it, so a transcript reads the same
whichever provider answered.

**`run_pipeline.py` was swallowing the choice.** It builds a clean environment
for each stage rather than inheriting one, which is right, and `SEED_VISION`
was not in it -- so a batch launched with `SEED_VISION=gemini` ran every stage
on Groq and said nothing. Six sections failed on a spend limit they had been
told to route around.

## Two ways a stage exits zero and is wrong

Everything else here asks whether a stage *ran*. These two ask whether it was
*right*, by comparing one stage's output against another's, and each found
sections that every existing check had passed.

### An entire test answered from the reading paper

Cambridge 14's test 2 was seeded with answers like TRUE, NOT GIVEN and roman
numerals -- a reading paper's answer shapes, in a listening material. These
books print the listening key and the reading key on facing pages and they look
alike: forty numbered answers under a heading a classifier cannot always see.
Test 2's listening key has no test number printed on it, so it was skipped, and
the reading key on the next page claimed test 2. Four sections took their
answers from it. Nothing failed.

`--keys` asks the one question that separates them -- "does this page say
LISTENING or READING?" -- and marks the reading keys as what they are. The
claim then runs on order alone, which this file has always said was the thing
to trust, and no longer needs a printed number to do it.

The tell was arithmetic, and worth keeping: **the four listening keys of a book
sit at a regular stride.** Every book runs 2 apart. Book 14 read 118, 121, 122,
124, and the 3 and the 1 are the whole of the bug.

### A transcript from pages that were later corrected

`verify.py` scores each section by how well its audioscript aligned to its own
recording. Forced alignment always returns a path, so a transcript belonging to
another section still aligns -- it just aligns badly. The corpus median word
score is **0.915**; twelve sections sat between 0.04 and 0.67.

Five of them were book 15, and the cause was ordinary and invisible: their
`turns.json` was read before `locate_pages` had corrected their audioscript
pages, and nothing re-read it. The catalogue said the right pages; the file on
disk came from the wrong ones; every stage after it believed the file.

Re-reading one moved it from **0.043 to 0.958**, which is the whole test. All
twelve were re-read, and one page added to book 13's last audioscript, whose
span stopped a page short of the end of the book.

```
seed/.venv/bin/python seed/verify.py
seed/.venv/bin/python seed/verify.py --ids   # feed straight to run_pipeline
```

One section still sits at 0.509 with all nine of its answers heard in its own
transcript, which is the reason this is written as two checks and not one: a
low score is a section to look at, not a verdict.

## The last forty replay spans, and what they were actually waiting for

Fourteen materials held 48 questions with no replay span, nine of them Part 4 --
a monologue, which is broken into turns only at its markers, so a missed marker
loses the boundary as well as the span. The obvious reading was that the
transcription runs out of steam near the end, and the missing numbers do
cluster at 37 to 40.

It was not that. Of the 40, **34 had the answer's own words sitting in their
own transcript already** -- the text was there and only the margin number was
missing. And `build_questions.py` has searched the alignment for exactly that
since the commit before this one. Those sections were simply built before it
did, and nothing rebuilds a section whose stage says done.

So the fix cost nothing: rebuild thirteen sections from readings already on
disk, and 30 spans appeared. Which is the same lesson as the stale `turns.json`
in book 15, from the other direction: **the pipeline has no way to know that a
stage's output is older than the code that would produce it.** Both times the
data was fine and the file was old.

### Bracketing, which narrows the search rather than relaxing the rule

`locate()` takes only an unambiguous match, because a replay at the wrong
moment is worse than none. Four answers were said two or three times in their
recording and were refused.

The paper asks its questions in the order the recording answers them, so a gap
with no marker is bracketed by the nearest markers either side of it. Searching
inside that stretch is not a guess about where the answer is -- it is what the
numbering already says, built from markers the book itself printed. The
uniqueness rule then applies unchanged, to a shorter recording. Two of the four
came back.

### A sheet the scan never had

`cam13-t3-s2` came out with no audioscript at all, and re-reading its pages
produced a transcript that aligned at 0.292 against a corpus median of 0.915 --
uniformly low, not a tail, which is what a *plausible transcript of the wrong
audio* looks like.

Reading the margins of book 13's audioscript pages settles it. Every test runs
1 to 40 continuously across five or six sheets; test 3 has four, and its
margins jump from Q9 to Q21. The printed folios say the rest: pdf 106 is
printed page 108 and pdf 108 is printed page 111, so one of 109 and 110 -- the
sheet carrying SECTION 2 -- was never scanned.

No re-read fixes that, so it is written into the section's `note` and
`verify.py` prints it beside the score. Its questions and answers are sound;
they come off the question paper and the answer key, which are both in the
book. What it cannot have is a transcript, and therefore replay spans, until
either a complete scan turns up or the recording is transcribed by ASR -- which
is the same path Cambridge 20 is waiting on.

This one is worth stating plainly because of how it presented: after the
re-read the section **passed** `publish_blockers()`. Ten markers, ten spans,
nothing missing. It was wrong in the one way that function cannot see, and only
the alignment score said so.

## Hearing a section there is no page to read

Two things in this corpus have audio and no audioscript: Cambridge 20, which
prints none, and `cam13-t3-s2`, whose sheet the scanner missed. Seventeen
sections that stop at the first stage.

`hear_audio.py` writes the same `turns.json` that `read_audioscript.py` writes,
from the recording instead of the page. `run_pipeline.py` picks between them
off `book.has_audioscript`, and nothing downstream changes -- which is the
point of the two writing one file.

**Only the words come from the transcriber.** `align.py` still supplies the
timings: it was measured at a median 40ms against known timings, and a
transcriber's own word timestamps are a second, worse guess at something
already solved. Measured against `cam11-t1-s1`, which has a real audioscript to
be wrong about:

| | |
|---|---|
| The book's words, in order, in the transcript | **98.0%** |
| Its ten answers found in the transcript | **10 of 10** |
| Turns, with speakers | 49, MAN / WOMAN / NARRATOR |
| Time and cost for one section | **12s, $0.005** |

The extra turns over the book's 41 are the narrator announcements, which the
audioscript does not print and the recording does contain. Having them is
better than not: they are eight more anchors for the alignment.

### The markers do not come with them

Nothing in a recording says "this sentence answers question 13". That is
printed knowledge, and it is what gives an answer its replay span.
`build_questions.py` covers the gap-fills by searching the alignment for the
answer's own words, and cannot cover a letter: "choose TWO letters" is answered
by picking B and D, and neither letter is ever spoken.

`mark_answers.py` asks the question that is left -- here are the turns, here is
what the answer to Q13 actually says, which turn is it given in? It is a
question about meaning, which is the one thing worth spending a model on, and
it runs inside the `questions` stage between reading the page and building from
it. It does nothing when every question already carries a marker.

**Checked before believed**, on the same reasoning as everywhere else here: a
paper asks its questions in the order the recording answers them, so a
placement that goes backwards is dropped rather than written. Two questions
sharing one turn is allowed -- the book itself prints "17&18" against a single
line -- and the same question named twice keeps the first.

`cam13-t3-s2` end to end: alignment **0.292 to 0.914** against a corpus median
of 0.915, and all eight of its lettered answers placed, at 65s, 90s, 124s,
143s, 164s, 192s, 275s and 304s of a 381-second recording. That ordering is
most of the evidence that they are right.

### One universe of page numbers, or four

Cambridge 20 is four PDFs of one test each, so "page 2" names four different
pages and the test number is a property of the FILE rather than of anything
printed on the sheet. `locate_pages.py` had one index space and one set of four
tests in it.

It now settles one **universe** at a time -- a run of page indices that mean
something together, with the tests it covers. Nine books are one universe of
four tests; book 20 is four universes of one. Inside a single-test universe a
page needs no printed test number to belong: being in that file is the
evidence. The `--keys` and `--recheck` passes work per universe unchanged.

### Where Cambridge 20 stands

Its listening pages are found. `--numbers` asks each page which paper it is
from and which question numbers are printed on it, and takes the part from
those: 1-10 is part 1, 11-20 part 2. Both papers number 1 to 40, so the
numbers alone put reading questions into listening sections until the page was
asked which paper it belonged to -- a reading page carries prose to read, a
listening page carries a form or a map. A sheet can hold two parts, which is
why a page now claims a list of them and `read_questions.py` keeps its half.

Its key page indexing was wrong in a way only this book could show:
`settle()` numbered the four answer keys by their POSITION in the universe,
which for a whole-book universe is 1, 2, 3, 4 and for a one-test file is
always 1. Tests 2 to 4 looked up their own number and found nothing.

Fifteen of sixteen sections have their question pages. The key is the thing
still open, and the reason is worth writing down.

`--keys` asked whether a page said LISTENING or READING and was told neither,
because **this book prints its key under 答案 and names no paper at all.** The
prompt is language-agnostic now and reports each list it finds with the heading
verbatim; a list under a heading that names no paper is recorded as
`answer_list` rather than guessed at, since guessing from the answers is
exactly what put a test of reading answers into book 14.

The lists are found -- doc 11 pages 20 (1-10) and 21 (11-40), doc 12 page 23,
doc 13 page 21, doc 14 page 20 -- and which of them is the listening one cannot
be read off the page.

**The recording settles it.** A listening answer is a word the speaker says, so
a key belongs to the listening paper if its answers turn up in that section's
own transcript, and `hear_audio.py` now produces one for every section of this
book. That is the same cross-check `verify.py` already runs over the corpus,
pointed at a different question, and it is the next thing to write.

## An error recorded as a fact

Cambridge 20 would not classify. Test 2 came back as 34 pages of "other" out of
35, and the same pages read one at a time came back correctly every time.

`classify()` ended with

```python
    except SystemExit:
        out = {"kind": "other"}
```

so a request that failed and a page that really is something else were the same
fact. The pass reported a fully classified book, every stage downstream
believed it, and the only symptom was that a book with sixteen sections located
none.

They are separate facts now -- a page nobody could read is `unread`, with what
went wrong kept beside it -- and writing that down is what showed the cause in
one line:

```
gemini answered with a list: [{"error": {"code": 429, "message": "You exceeded ...
gemini answered with a list: [{"error": {"code": 503, "message": "This model is ...
```

**Gemini returns its errors as a one-element JSON array and its successes as an
object.** The retry checked `reply.get("error")` on something that has no keys,
so every 429 and every 503 read as an unrecognised reply and was raised instead
of waited out. Unwrapping first, and treating an overloaded model as the same
category as a rate limit -- the request was fine, the moment was not -- took
the unread count from 97 pages to zero.

Worth the space because of how it hid. Nothing crashed, nothing was logged, and
the cost was a whole book. The fix that mattered was not the retry; it was
refusing to write down a failure as if it were an observation.

## Cambridge 20, and where its listening key actually is

The book prints its answers under 答案 with no paper named, so the question was
which of the lists is the listening one. Reading the page cannot say. **The
recording can**: a listening answer is a word the speaker says, so a key
belongs to the listening paper if its answers turn up in that section's own
transcript, and `hear_audio.py` produces one.

The first four lists found -- the ones near the writing section -- scored
**0/10** against their recordings. They are the reading keys, and the answers
say so once you look: `potatoes, butter, meat` against a reading passage called
Frozen Food.

Scanning a whole file found the real one, and it is not at the back at all:

| test | file | page | answers heard in its own recording |
|---|---|---|---|
| 1 | TEST 1.pdf | 4 | **9 of 10** |
| 2 | TEST 2.pdf | 6 | **9 of 10** |
| 3 | TEST 3.pdf | 5 | **8 of 10** |
| 4 | TEST 4.pdf | 5 | — |

(The three misses are a number and a three-letter word, which the check skips,
and one word the speaker inflects differently.)

**The listening key sits immediately after the listening questions**, before
the reading passages start -- and on three of the four files it shares a sheet
with part 4's questions, printed above it. A page in this pipeline had one
`kind`, so calling that sheet the key lost the questions and calling it
questions lost the key. It keeps its kind and carries `has_key` for the other
role.

### What went through, and what did not

Eleven of sixteen, first pass. Two more faults came out of it:

* **A matching group can answer "I".** `LETTERS` was `A-H`, which is what a
  multiple choice offers; a box of options can hold more. The key expanded to
  nothing and took the section down without naming the letter it refused.
* **A section can be left short by its own repairs.** `build_questions.py`
  drops a group belonging to the neighbouring part, which is right, and
  nothing checked that what remained still covered the section. Two sections
  went into the database with two and four questions of ten -- and were counted
  content-complete, because `publish_blockers()` asks whether the questions
  present are sound, not whether they are all of them. It now refuses a section
  the drops have left short.

The last five were pages no vision model would read straight: a four-column
table came back as one run-on line, question numbers as 7-10 for a section
asking 11-20, JSON breaking mid-string. Re-reading gave the same answer every
time, so it was the model and not the weather.

### Reading the page as text, when a text of it exists

`read_questions.py --web URL` takes the questions from a page's text instead of
the PDF's images. A vision model reading a re-typeset table is inferring where
the columns are; the same table as characters leaves nothing to infer.

The answers still come off the book's own key page. A third party's page is
used for the SHAPE of the questions and never for what the answers are, so the
worst a wrong page can do is fail the coverage check.

**Which is also how the page is identified.** These sites number their tests
their own way, and nothing on the page says which Cambridge book it is. What
says it is the answer key we already read out of the PDF and checked against
the recordings: `fish, roof, Spanish, vegetarian, Audley, hotel, reviews,
local, 30, average` on one side and `Fish, Roof, Spanish, Vegetarians, Audley,
Hotel, Reviews, Local, Thirty, Average` on the other is not a coincidence.
Tests 201, 203 and 204 matched Cambridge 20's tests 1, 3 and 4 that way before
a word of them was used.

The page is fetched with its `<script>` blocks intact and unescaped first --
these sites render the paper from JavaScript string literals, so stripping
scripts the obvious way throws the questions away and leaves the navigation.

**And it is written down.** `section.question_source` is NULL where the
questions came off the book's own pages, which is 169 of the 176, and holds the
URL for the seven where they did not. `verify.py` prints them every run rather
than leaving it in a column nobody opens:

```
7 section(s) had their questions read from 3 page(s) rather than the book:
  https://practicepteonline.com/ielts-listening-test-201/
    cam20-t1-s1, cam20-t1-s3
```

The book stays the source of record. This says which sections have a second
provenance for their wording, so that a question that later reads oddly can be
checked against the page it actually came from.

### Four repairs a table needs, and one a pair does

Text removed the transcription errors and left the structural ones, which are
the same on any source:

* **A note under a table row is part of that row.** The page prints a company,
  two lines of notes, then the next company. Read as plain lines they end the
  run of `+` rows, and the row after them becomes a new table's header -- where
  a gap is never drawn. Cambridge 20 lost seven of ten that way. They fill the
  rightmost cells: which column a note belongs to is printed nowhere, and the
  right-hand one is where these books put them.
* **A `+` mid-line starts a row there**, where one row's last cell runs into
  the next row's first.
* **A table's header row written as a heading.** `# Name | Location | ...`
  above a run of `+` rows is the column names, read as the block's title
  because that is how the page prints them. Converted only when the cell
  counts agree.
* **The second half of a "choose TWO" that the key listed singly.** `paired`
  handles a key line labelled "23&24"; where the key instead lists 23 and
  leaves 24 blank, the reading gives two questions and the second has no
  answer. Folded into the question it shares a mark with.

And two checks that were counting a pair wrong in opposite directions: the
coverage check in `build_questions.py` counted only the number a pick-2
question starts at, so a correct section looked as though it were missing every
second question; and the key check counted a paired second number as a missing
answer. A `paired` map read off a whole key page also carries the pairs of
every part on it, and "33&34" from part 4 made a part 3 section look as though
it covered question 34.

## The last eleven answers, and the two rules that were quietly wrong

Eleven questions still had no replay span. None of them needed a better model.

**`mark_answers.py` was asking where an answer it had not been told is given.**
It read the answer from `correct_answers`, which only exists after
`build_questions.py` has expanded the key -- and it runs BEFORE that, against
`questions.src.json`, where the answer is `key`. Every question reached the
model as "correct: (unknown)", and the model answered, reasonably, with
nothing. Reading the right field turned "placed 0 of 10" into "placed 10 of 10".

**It was also asking about too few.** Only the unmarked questions went into the
prompt -- four out of ten, with no sense of where in the recording they sat.
Sending all ten and writing only the four costs the same one request and gives
the model the six the book already placed as anchors. On `cam19-t2-s4`: asked
about four it put two in the wrong part of the recording; asked about ten it
got seven exactly right and none wrong.

### Checking a placement against an answer that names its own turn

An answer whose words appear exactly once in the alignment needs no model to
place it. `mark_answers.py` now works those out first and uses them as a
control: if the model puts them more than one turn from where their own words
are, the whole reading is refused rather than written.

It earned its place on the first run. `cam19-t2-s4` came back with two of four
checkable placements in the wrong part of the recording and was refused; the
same section, asked with all ten questions, agreed with nine of nine.

On `cam20-t1-s1`, where nothing was checked before it went in: 4 placements
exactly right, 3 one turn out, 0 wrong, against seven answers that name their
own turn. One turn out is the answer sitting across a boundary, which a replay
span survives.

### The same mistake in two places: nearest, not furthest

The last question, `cam12-t3-s4`'s Q39, took both.

A missing question is bounded by the markers around it -- Q39 lies between
whatever turn carries Q38 and whatever carries Q40. Both `mark_answers.py` and
`build_questions.py` took the FURTHEST marker below rather than the nearest,
and **a book's markers are not always in order**: this section prints Q38 on
turn 7 and Q37 on turn 8. Taking the furthest start below Q39 began its window
at 398.0s, and the word it was looking for is at 388.7s.

`build_questions.py` also bounded the window at the previous marker's turn
END. Two questions can share a turn -- the book prints "17&18" against one
line -- so an answer with no marker of its own often lies inside the turn the
marker before it names; bounding at that turn's end puts the window in the
silence between two turns.

Nearest neighbour, from where its turn starts: "food" appears three times in
that recording and exactly once inside the window the book allows.

### A section that had been missing two questions all along

Rebuilding all 176 to check the change refused one that had been counted
complete since it was seeded. `cam12-t3-s2` covers 11&12, then 15 to 20:
questions 13 and 14 are not there. The page has them -- "Questions 11 and 12:
Choose TWO letters, A-E" is followed by "Questions 13 and 14: Choose TWO
letters, A-E" -- and the reading collapsed the two into one, because what
separates them is the numbers and not a word of the wording. The prompt says so
now.

That is the third section this year found to have gone in short, and all three
were found by the same check rather than by anyone looking.

## One page misread, and a section transcribed from somewhere else

`cam17-t3-s4` was the last thing the verifier flagged: 0.509 against a corpus
median of 0.914, with all nine of its word answers present in its own
transcript. Two signals disagreeing, which is the interesting kind.

The score across the section says what happened:

```
0.92   0.76   0.70   0.54   0.08   0.06
```

Not a bad section -- a section that starts right and comes apart. Its markers
finish the story: Q31 to Q38, and then **Q31 again**, then Q37, Q38, Q39, Q40.
The transcript holds this section's audioscript followed by another one.

Its span in the catalogue was six pages where its neighbours have two, and it
carried the `script span guessed, heading not found` flag it has carried since
it was located. Reading the margins settles where the audioscript actually is:
page 104 is PART 4 with Q31-38 down the side, page 105 carries Q39-40.

**Page 104 had been classified `reading`.** One page, in the middle of the
audioscript block. The block is found as the longest run of consecutive
audioscript pages, so it stopped at 103 -- and every section after that got a
guessed span, and one of them was transcribed from the wrong pages.

Two rules now, and the second is narrower than the first attempt:

* **A one-page gap inside the run is bridged.** A single page that came back
  as something else, with audioscript either side of it, is a misreading and
  not a boundary.
* **One page past the end of the run, where an answer key follows it.** The
  audioscripts run until the keys begin, so a single sheet between them belongs
  to the block. Book 13's last page of PART 4 came back as `reading` too, and
  its section had been transcribed from one page instead of two.

The first version of the second rule was "anything between the first
audioscript page and the first key", which is the same idea and far too much of
it: one page misread as an audioscript early in a book made the whole of it the
block, and twenty-eight sections had their spans rewritten to the question
papers. The README already said why -- *the start of the longest run, not the
first page anywhere that looks like one* -- and the rule now says it too.

Re-read against pages 104 to 106: **0.509 to 0.933**, ten markers of ten.

## NVIDIA measured, and not adopted

`vision.py` takes `SEED_VISION=groq|nvidia` because the cost of this pipeline
is dominated by iteration rather than by one clean pass, and a free tier
removes that variable instead of predicting it better. The switch was then
measured against the hand transcription of `cam11-t1-s1` before anything was
re-read with it, and the measurement said no.

Of the six vision entries in NVIDIA's catalogue visible to this account, one
serves: `meta/llama-3.2-11b-vision-instruct`. `phi-3-vision` and `nvidia/vila`
return 404 for the account; `llama-3.2-90b-vision-instruct` is listed and times
out after five minutes on a **text-only** request, so it is not serving either.

On the same page, against Groq's `qwen/qwen3.8-27b`:

| | Groq 27B | NVIDIA 11B |
|---|---|---|
| Images per request | 3 | **1** |
| Turns read | 41 | 24 |
| Margin markers found | **11 of 11** | **1 of 11** |
| Answers the narrow marker question | yes | returns prose, not JSON |

The transcription itself is passable. The margin markers are not, and they are
the whole point: they are what gives an answer its replay span, and a material
is not publishable without them. A narrow question -- the one framing that has
rescued every other stage here -- came back as an essay about the page.

The provider switch stays in, because it costs nothing to keep and the
catalogue changes. The default does not move.

### Measured again, on a different question, with the same answer

Asked about it a second time -- with Gemini's daily quota spent and Groq
spend-blocked, so a free provider was worth another look -- on the work that
was actually blocked. Three pages of Cambridge 20, against readings already
verified:

| asked | true | `llama-3.2-11b-vision-instruct` |
|---|---|---|
| which paper is this page from | listening | **listening** |
| which paper is this page from | reading | **reading** |
| question numbers on a listening page | 1-15 | 1-16 |
| question numbers on a reading page | 6-13 of them | **all forty** |
| first three printed answers on a key page | potatoes, butter, meat | `"NG 9.T"`, `"10.F 11.T"` |

The pattern is the same one the markers showed. **The coarse judgement is
sound and the exact reading is not.** Which paper a page belongs to, it gets
right every time. What is printed on the page, it fills in: forty numbers on a
sheet that carries a dozen, and answers with the question numbers glued into
them.

It also needs `response_format` to produce JSON at all, and then writes a
paragraph before it -- which `read_json`'s brace-hunting rescue happens to
survive, so that part is not the objection.

Not adopted, and for a sharper reason than last time: what is left to do needs
exactly the reading it cannot do. Cambridge 20's four answer lists are printed
under 答案 with no paper named, and telling the listening one from the reading
one means reading the answers themselves correctly.

### `moonshotai/kimi-k3`, and why quality was not the problem

Tried next, on the same pages. It is not in the same class as the llama:

| asked | true | kimi-k3 | llama-3.2-11b |
|---|---|---|---|
| paper and question numbers on a listening sheet | listening, 1-15 | **listening, 1-15** | listening, 1-16 |
| first three answers on the 答案 page | potatoes, butter, meat | **potatoes, butter, meat** | `"NG 9.T"`, `"10.F 11.T"` |

Two for two, matching Gemini exactly, on the reading the llama filled in. So
the objection is not accuracy. It is that this is not a batch tool:

* **The rate limit is per MODEL and it is hard.** After about four requests it
  answers 429 and stops recovering: three single pages in a row, each waiting
  100 seconds across five retries, all failed. On the same key at the same
  minute `llama-3.2-11b` answers normally, so it is kimi's quota that is spent,
  not the account's.
* **One page a request.** Two audioscript pages in one call did not answer
  within 300 seconds.
* **It reasons first, and the thinking is billed as output** in a separate
  `reasoning_content`. A budget that fits the answer does not fit the thinking,
  and the request then costs a full answer and returns nothing.

A pass over one book is roughly two hundred requests and the cost of this
pipeline is measured in passes, so four before a wall is not a candidate for
the sweep.

**It may still be right for the last mile.** What is left of Cambridge 20 is
not a sweep: it is five answer-list pages that have to be read exactly --
`potatoes, butter, meat` and not `"NG 9.T"` -- and five is a number kimi's
limit does not reach. Gemini reads them just as well and the choice may never
have to be made; it is worth knowing there is a second reader for the one job
where being right matters more than being quick.

### Three faults it found on the way through

None of them are about the model, and all three were live in every provider.

**A rate limit that did not look like one.** NVIDIA answers with a bare
`{"status": 429, "title": "Too Many Requests"}` and no `error` object, so the
check written for Groq's shape and widened for Gemini's still missed it and
raised instead of waiting. It reads the whole reply now rather than an object
inside it, which is the third shape and the last time this should need doing.

**The key was in argv.** `_post` passed `Authorization: Bearer ...` as a curl
argument, readable by anything that can list processes -- and it appeared
verbatim in a `TimeoutExpired` traceback, which is how it was noticed. It goes
in a 0600 config file now, and a timeout is reported as a timeout rather than
by printing the command.

**A reasoning model that spends the budget thinking** returned
`content: null`, which was handed back as `None` and became a `TypeError`
several frames from the cause. Said plainly now, with how many words it thought
and what the budget was.

**The entry was broken and silent.** `nvidia/llama-3.1-nemotron-nano-vl-8b-v1`,
named here since the first measurement, is no longer served to this account, so
`SEED_VISION=nvidia` had not worked for some time and nothing said so. It now
names a model the catalogue still has, at one image a request rather than four.

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

Every stage runs from the catalogue. 78 materials are seeded and private;
Cambridge 20's sixteen sections are blocked on their missing audioscript and
wait for an ASR path.

Every stage now runs from the catalogue without a page number passed by hand.
What has not been done is the other ten books, and the batch runner that would
take a book from `locate_pages` through to `import_section` without a person
between the steps.

## Three books that are not "Cambridge N"

Eleven numbered editions is not the whole shelf. `Materials/` also holds
**IELTS Trainer** (six tests), **IELTS Trainer 2** (six) and **The Official
Cambridge Guide to IELTS** (eight) — eighty more sections, ten more hours, a
45% larger corpus — and a fourth folder, **Complete IELTS Bands 6.5–7.5**,
which is not seedable at all and is recorded as a finding rather than a book:
it is a coursebook whose answer key and audioscript both live in a Teacher's
Book that did not arrive, 153 of its 189 pages carry no text, and only eight
of its 55 tracks run long enough to be a section.

### The filename says nothing, so duration does

Every Cambridge file names its test and section somewhere — seven conventions,
all parsed in `manifest.py`. These three name a CD track and nothing else:
`Track No08.mp3`, `Cam43.mp3`, `TRACK 30.mp3`. No pattern reaches that.

What does reach it is length. A listening section runs six to ten minutes and
the exercise snippets scattered among them run under four, and across all
three books there is **nothing in the gap between** — longest snippet 3.7
minutes, shortest section 6.0. Take the long tracks in disc-and-track order
and they are the tests in order.

That is an inference, so it is checked twice. The count has to come out at
exactly four a test — 24, 32, 24 — and the books say the mapping themselves in
print: IELTS Trainer 2 heads Test 6 Listening Part 1 with track 30 and gets
`TRACK 30`; the Guide heads Practice Test 2 Listening Section 1 with track 43
and gets `Cam43`. Both land.

### What the catalogue had to give up

`section.test_no` was `CHECK (test_no BETWEEN 1 AND 4)`. The Guide prints
eight practice tests in one volume. `book.kind` was `('cambridge',
'retypeset')`; neither is a Trainer or a Guide.

SQLite cannot ALTER a CHECK, and `CREATE TABLE IF NOT EXISTS` does nothing to
a table that already exists — so `db.py init` rebuilds the catalogue in place
when `schema.sql` has outgrown it. Every table, not only the two whose
constraints moved: renaming one rewrites the references the others hold to it,
and doing `section` alone left `stage` pointing at `section_old` one statement
before `section_old` was dropped. 1,232 stage rows and twelve findings carried
over.

Two smaller couplings went with it. `locate_pages.py` built section ids as
`f"cam{book}-t{test}-s{section}"`, which UPDATEd nothing for a book whose
sections are called `trn-t1-s1` and reported the row as written; and
`import_section.py` built the material title as `f"Cambridge IELTS {book}"`,
which would have named the Trainer "Cambridge IELTS 101". Both take the string
from the catalogue now. For the eleven numbered books the title is
byte-identical to what it always built, which matters more than it reads:
the title is the key the import dedups on, so a changed one seeds a second
copy rather than updating the first. Book 20's catalogue title lost its
"(Chinese re-typeset)" for exactly that reason.

### The address is in the running line, not the heading

`resolve()` reads the section number off the task heading. IELTS Trainer puts
the whole address in the running line instead — "Test 2 Exam practice |
Listening Section 3" — and leaves the heading to say "Questions 26–30". The
first run located **2 sections of 24**.

Reading the running line where the heading carries no section number fixes it,
and costs the existing corpus nothing: not one of the 176 Cambridge sections
has a section number in its running line, and re-running all eleven books
against their cached page maps returns byte-identical rows. It needs one extra
rule, though — where the section comes from the running line, *every* page of a
section carries it, not just the first, so a repeated number is the rest of
that section rather than the next test starting at it.

The result agrees with the printed contents page: Test 3 Listening at 97, Test
4 at 116, Test 5 at 135, Test 6 at 154.

### A book that prints each test twice

The Trainer's first two tests appear as "Test 1 Training", which teaches the
task with worked examples, and again as "Test 1 Exam practice", which is the
paper. Only the paper has a recording — the training exercises are the short
tracks the manifest already leaves behind — so a training page swept into a
section would put questions in front of a learner that nothing in their audio
answers. Skipped by name. Cambridge 10 prints eighteen pages saying "General
Training" and every one of them is Reading, so the rule excludes that phrase.

### The transcripts are not one block

Cambridge prints forty-odd audioscript pages in one run at the back. The
Trainer interleaves: each test's key, then that test's four transcript pages,
then the next test's key. A span from Test 1 Section 4 to Test 2 Section 1
therefore covered thirteen pages of answer key that would have been read as if
somebody had spoken them, and the rule that absorbs one stray page at the end
of the block was swallowing a key page. Both now stop at the first page that
is not an audioscript.

A transcript page can also *begin two sections* — one ends partway down and
the next starts below it — which the reader could only report one of. It
reported the second, and four sections lost their span to a guess. It lists
them now.

### Two columns, read across

This is the one that would have shipped quietly.

`verify.py` put three of the four worst-aligned sections in the corpus in this
book. A walk over the markers — a paper asks its questions in the order the
recording answers them, so the numbers down a page run up — found the same
three going backwards: `trn-t1-s3` came back marked **23, 24, 21, 22**. The
pages are two columns and were being read across rather than down, so two
parts of the recording minutes apart were interleaved, and every replay span
built from those markers sent a learner to the wrong minute.

Told to finish the left column before starting the right, all four came back
in order and their median alignment went from 0.62 to 0.93. The backwards walk
now runs after every reading and says so by name.

The same fault, in the same shape, was losing answers on the key pages: Test
6's questions 11–16 sit at the bottom of one column and 17–20 at the top of
the other, and a reading that stopped at the fold lost the tail of a section
while looking complete. Telling the prompt about the columns helped and did
not fix it. What fixed it was asking the same page again naming the four
numbers that were missing — the narrow question, which is the one thing that
has worked every time here.

### The marker is inline, and the words after it are spoken

Cambridge prints `Q31` down the right margin. The Trainer prints `(31)` in the
text, immediately before the underlined answer. Told to read either, it read
both — and then, told that a printed number is not a spoken word, it dropped
the underlined phrase along with the number. `trn-t6-s4` had **2 of its 10
answer words anywhere in its transcript**, which is a section whose replay
spans could not have been right and whose alignment score was 0.95. Saying
explicitly that the number goes and the words after it stay took it to 10 of
10.

Inline markers are, incidentally, better than margin ones: they sit on the
sentence rather than the turn.

### What the key prints that is not the answer

Three things, none of which Cambridge does.

The Trainer writes editorial asides into the key line itself: `route
[alterations = changes]` explains how the question paraphrased the recording,
and `ballantyne (you can write this in small or capital letters)` is advice to
the candidate. Expanded as notation, the first gives exactly one accepted
answer — the whole line — so a learner writing "route" is marked **wrong**.
Square brackets are dropped, and so is a parenthesis of more than four words;
every real optional group in this corpus is one to three, and no line in the
176 sections read before this book has either shape.

It prints the answers to its teaching exercises on the same page, under
"Useful language: dates" — a numbered list of ten that is not the key.

And a section's answers can be three sheets past the page the catalogue names:
Test 5's questions 38 to 40 sit in the corner of a page headed "READING
PASSAGE 1", where a reader asked for Section 4's listening key answers, quite
reasonably, that there is none. The spill walks forward up to three pages,
asking only for the numbers still missing, and stops as soon as none are.

### A blank with no number is not a gap

"help is needed with **4** .......... and .........." is one number, two
blanks and one mark. Read as two gaps it shifted every answer after it by one,
and the build caught it as eleven gaps against ten questions. The Example's
answer line is a blank with no number too, for the same reason.

### A map is not a matching task

A map task with a lettered box above it looks exactly like a matching task,
and two of the Trainer's four came back named that way. The difference is that
a matching task can be published and **a map task without its picture cannot
be answered at all**.

So a group whose instructions say "Label the map/plan/diagram below" is named
by that, whatever the reader called it — and applying the rule to the 176
sections already read found **two Cambridge 11 sections that had been in the
database as letter-matching tasks with no map since the day they were seeded**.
`publish_blockers()` had been saying so; nothing had asked it about them,
because `seed_status.py` matched titles beginning "Cambridge IELTS &lt;number&gt;"
and so could not see the Trainer either. It matches the tail now.

Three things followed from getting the type right. A labelling group is
answered *either* from blanks on the picture *or* from a box beside it and the
server refuses one that offers both — so bare letters in `options` (`["A",
"B", ... "I"]`, which is the alphabet, not a list to read) become
`image_letters`, and words stay a box. A group read as matching carries its
item names on the questions rather than in a template, and an empty template
is refused, so the list is built from the names already there. And the gap
checks do not apply to a labelling group answered with letters.

### Where the Trainer stands

24 sections, **234 of 234 replay spans**, nothing below 0.7 in `verify.py`, and
all 24 in the database as private drafts. The corpus is **200 materials, 1,914
of 1,914 replay spans, 200 of 200 content-complete**.

Its `trim` stage failed on all 24 and was skipped: trimming transcribes the
first two minutes through Groq's `whisper-large-v3`, and Groq blocked this
account partway through the book on a spend-alert threshold. Nothing is lost
by it here — these tracks are one section each and open with the test's own
introduction, which belongs to the test.

## A span that does not contain its answer

`verify.py` asked two questions of every section: does the transcript fit the
recording, and does each answer appear in that transcript. Both were passing
everywhere. Neither asks the question a learner actually cares about.

**Is the answer inside the span its own question replays?** Not somewhere in
the transcript — in the seconds that get played when they press the button.
The answer was **766 of 987**. One replay span in five was a button that did
not do what it said.

And it was not random. Thirteen Part 4 sections across seven books had *every*
marker landing on the paragraph **after** the one that answers the question, by
a median of 7 to 64 seconds:

```
Q32  logic          span    171-   209s   word spoken at    149s
Q34  meditation     span    252-   282s   word spoken at    204s
Q36  coins          span    316-   365s   word spoken at    239s
Q39  paper          span    393-   395s   word spoken at    343s
```

That is `cam17-t1-s4`: nine of its ten answers outside their own span, in a
section that aligns at 0.95 with every marker present and in order. Nothing
else in this pipeline could see it, because every other check was satisfied.

The fix is the same cross-check used everywhere else here. A marker is a
reading of where a printed symbol sits beside a line; the answer's own words in
the aligned recording are evidence. Where the two do not overlap **at all**,
the words win. Where they agree — about nine times in ten — nothing moves.
**922 of 987**, and the median section is now at 100%.

### And rebuilding all of them detached eighteen maps

Applying that meant rebuilding every section's `questions.json` from its
`questions.src.json`, which is free and is meant to be. But the source file has
never heard of the picture: `extract_image.py` writes the cut map into
`questions.json` *after* the build, so a rebuild dropped it, and eighteen map
groups quietly lost the image they are answered on. 200 content-complete became
182, and `publish_blockers()` was the only thing that noticed.

The cut file was still on disk and still right. The build carries it forward
now, so a rebuild is what it claims to be.

## The Guide: eight tests, and a coursebook in front of them

Three assumptions that held for eleven Cambridge editions fail here at once.

**Its answer keys are consecutive.** One test to a page, 383 and 385–391 — so
the rule that consecutive key pages are one test's spilling over merged seven
of eight into a single run. Worse, two other listening keys sit in the same
back matter, one for the teaching units and one for the General Training test,
which order cannot tell from a practice test's. Order came back with four pages
for eight tests, and the four were wrong.

The Guide prints the test number on seven of its eight. That is used only where
order has already come back short, so every Cambridge book — including the two
the order rule was written for — is untouched, which re-running all twelve
against their cached page maps confirms byte for byte. The eighth, which the
book numbers nowhere, is the sheet immediately before test 2's.

**Its recording scripts open with the coursebook's.** Counting runs of 1, 2, 3,
4 through the block put Practice Test 2 Section 1 — printed plainly as such,
with its track number 43 — into test 4. The page says which practice test it
is, once, over Section 1; Sections 2 to 4 carry the section heading alone. So a
named start sets the test and the unnamed ones after it follow, which also
drops the unit material: it is the only thing before the first named start.

**It numbers no answers at all.** Cambridge prints `Q31` in the margin and the
Trainer prints `(31)` inline. The Guide underlines the answer and prints
nothing beside it. The order is still evidence — the nth underline in a section
is question n — and `read_audioscript.py` will use it, but only while the count
comes out exactly right, because a "choose TWO letters" is two underlines
against one question and one of those puts every number after it out by one.

Which makes the on-span check above not a nicety but the only thing that can
audit this book: the numbering is an inference, and the key it is measured
against came off a different page.

### A quarter of it had never been read

The first pass over its 398 sheets ran out of Gemini's free tier — 500 requests
a day — at index 286 and recorded the remaining 106 as **unread**. That is
exactly why `classify()` was changed to say `unread` rather than `other` after
Cambridge 20 lost 34 pages to the opposite; `locate_pages.py 102 --unread`
recovered them without paying for the 292 that were fine.

### Does numbering by order actually work?

It is a rule applied to a book that prints no numbers, so the only honest
answer is a measurement. The on-span check is the measurement, and it is
independent of the rule: the spans come from the underlines' order in the
recording scripts, and the answers they are checked against come off the
answer key, which is a different page read by a different pass.

On the eighteen sections built so far: **121 of 137 word answers fall inside
the span their own question replays**, and the median section is at 100%. One
section is below 60%.

That is the same figure the Cambridge corpus reaches with printed margin
numbers. The order is enough.

### The free tier is the wall, not the money

Gemini's free tier allows **500 requests a day** for `gemini-flash-lite`. The
whole Cambridge corpus — eleven books, 176 sections, every page of every PDF —
cost **$0.57**. Money has never been the constraint. A day's quota is: the
Guide alone spends 398 of it on page location before a single section is read,
and the book has been stopped twice by the daily cap with ten sections left.

Groq has no such cap and is cheaper per token, which is why it was the default.
It is blocked on this account by a spend-alert threshold, which is a setting,
not a balance.

## What the provider limits actually are

Worth stating plainly, because it has now stopped the work three times and
never once for the reason it looks like.

**Groq** is blocked on this account by a *spend alert threshold* — a setting,
not a balance. Clearing it in the console brings it back. It has no daily cap
and is the cheapest per token, which is why it is the default.

**Gemini's free tier** is 500 requests a day, counted **per model**. So
`SEED_VISION_MODEL=gemini-flash-latest` is a second day's work on a day
`gemini-3.1-flash-lite` is spent — at four times the price, which `BY_MODEL` in
`vision.py` knows so the ledger stays honest.

**A Google AI Pro subscription does not raise either.** Measured, because it
was asked. Before: `generate_content_free_tier_requests, limit: 500`. After:
both models answer `Your prepayment credits are depleted. Please go to AI
Studio at https://ai.studio/projects to manage your project and billing`. The
project has left the free tier for a prepaid one with no balance, which for
this work is *worse* than the free tier it replaced. AI Pro is a consumer
subscription for the Gemini app; an API key's tier follows the Cloud project
behind it.

The amount of money involved has never been the issue. 499 requests went
through on the day this was measured, for **$0.35**. The whole Cambridge corpus
— eleven books, 176 sections, every page of every PDF — cost **$0.57**.

## Where the three books stand

| | sections | in the database | what is left |
|---|---|---|---|
| IELTS Trainer | 24 | **24** | — |
| Official Cambridge Guide | 32 | **22** | ten sections' questions; seventeen answers unlinked in six more |
| IELTS Trainer 2 | 24 | 0 | pages located free from the text layer; every section still to be heard |

**222 materials, 2,114 of 2,131 replay spans, 216 of 222 content-complete.**

Trainer 2 is the Cambridge 20 shape: no audioscript printed anywhere, so its
24 sections are heard rather than read, and their markers placed by meaning.
Its page map cost nothing, because 229 of its 232 sheets carry real text.

## Ten answers the book never printed

The worst thing found in this corpus, and it was found by a rule rather than
by reading.

`trn2-t2-s4` came back with a clean, correctly formatted answer key: *forest,
soil, roots, insects, fungi, light, temperature, wind, water, nutrients*. Ten
plausible one-word answers for a Part 4. The recording is a student's
presentation about Sarah Guppy, a 19th-century engineer, and the real answers
are *academic, doctors, floods, models, investor, ships, erosion, breakfast,
gym, graduated*. **Not one of the ten words appears anywhere in the book.**

The cause was a truncation. Reading a key from the page's text sends the pages
of that test; a test's key can run to twelve pages, so the text was cut at
12,000 characters — and Test 2's "Questions 31–40" begins at 14,540. Asked for
answers it had not been shown, the model produced ten anyway.

Two things changed. The window is **aimed** at the section's own range rather
than cut from the start: find `Questions 31–40` in the text and send from
there. And, because this is the one route where it can be checked, **an answer
that does not appear in the text it was read from is dropped** — the source is
right there. Re-reading all 24 of Trainer 2's keys afterwards changed nothing
else, so this was the only section it happened to.

It is worth being clear about what nearly shipped. Every stage exited zero.
The alignment was 0.92. The template matched the questions. `publish_blockers`
was satisfied. The only visible symptom was that the ten answers had no replay
span — because `locate()` could not find *forest* in the recording, which is
exactly right and was the only thing objecting.

## Breaking a monologue that nothing else breaks

A book that prints no question numbers gives the reader nothing to break a
monologue at — no speaker change and no marker — so three of the Guide's Part 2
sections came back as **three turns for eight minutes of speech**, and a
section heard rather than read came back as one. Every span built from such a
turn plays two minutes, and a model asked which turn answers question 18 is
choosing between three options that are all "most of the recording".

So an over-long turn that **no marker names** is broken at its sentences.
Only unmarked turns, because a marker names a line inside the turn and nothing
here knows which line — which leaves every book that numbers its answers
untouched and helps exactly the books with nothing to lose.

| | before | after |
|---|---|---|
| Trainer 2 spans over 60s | 42% | **0%** |
| unlinked questions | 22 | **2** |
| corpus median span | 14s | 14s |

## Where the corpus stands

**256 materials. 2,455 of 2,457 replay spans. 255 of 256 content-complete.**
Median alignment 0.916; 1,214 of 1,302 word answers fall inside the span their
own question replays; 2% of spans run over a minute, all of them Part 4 turns
in books that mark by paragraph.

Fourteen books: Cambridge 10–20, IELTS Trainer, IELTS Trainer 2, and the
Official Cambridge Guide. Total measured spend, every pass over every page
since the first: **$2.71**.

## Closing the last of it

Three things stood between 254 of 256 and 255, and each was a different kind
of wrong.

### A book that numbers nothing still reports numbers

The Guide underlines its answers and prints no question number anywhere, and
the transcription pass returned `Q1` to `Q10` anyway — numbers it had worked
out for itself from the underlines. That is precisely the job the underline
pass does properly, in order, having first checked that the count comes out
right. Worse, those invented markers **blocked the sentence split**, because
the split only touches a turn no marker names: `gd-t6-s4` stayed at six turns
for eight minutes of speech and two of its questions could not be placed at
all.

Dropping them where the book's kind says it numbers nothing took that section
from 6 turns to 16, and the Guide's spans over a minute from 13 to **none**.

### A span that is right and too long

The marker names a turn, and a Part 4 turn is a paragraph. Where the answer's
own words fall *inside* the span and the span runs over a minute, the span is
narrowed to them — which is also where `locate()` is most likely to come back
unambiguous, since it is searching one paragraph rather than eight minutes.

| | before | after |
|---|---|---|
| spans over 60s | 52 (2.1%) | **21 (0.9%)** |
| longest | 367s | 118s |

### `3000/3,000/three thousand`

The module docstring predicted this one and asked for a real line before
guessing at a rule. Fifteen turned up. An unspaced `/` alternates a single
word — `urban centres/centers` — and these are not that: they alternate the
whole phrase, and expanded word by word they produced answers nobody would
write. `13th May/13 May/thirteenth May/May 13/May 13th/May thirteenth` became
sixteen strings beginning "13th May May May". `3000/3,000/three thousand`
became "3000 thousand", so the one thing a candidate actually writes was
marked **wrong**.

Two rules tell them apart, and both had to be right or a working key would
break:

* **Several branches are more than one word.** Six ways of writing a date are
  six phrases. `5/five km/kilometres/kilometers` is *not* that — only one of
  its four branches has a space, and its two alternations really are
  independent.
* **Two branches of one token are the same number.** 3000 and 3,000 are one
  amount written twice, so the trailing word belongs to the third branch
  alone. 7 and 7th are not, so `7/7th April` stays two answers.

Ten keys changed and every one was nonsense before. `answer_key.py` carries
all four shapes as cases.

### Where it ends

**256 materials. 2,456 of 2,457 replay spans. 255 of 256 content-complete.**

The one question without a span is `gd-t3-s1` Q4, whose answer is *swimming*
and whose recording says "swimming" twice, 23 seconds apart, with no marker to
say which. `locate()` refuses an ambiguous match on purpose: a replay at the
wrong moment teaches a learner they misheard something they never heard. One
question of 2,457 is the right price for that rule.

## Reading: finding the passages

The reading corpus comes out of the same fourteen books and the same scans,
and three of the listening stages simply do not exist for it — no audio, no
forced alignment, no replay spans. What is left starts where listening
started: which pages is it printed on.

```bash
seed/.venv/bin/python seed/locate_passages.py --book 11
seed/.venv/bin/python seed/locate_passages.py --book 11 --read   # ask the pages
seed/.venv/bin/python seed/locate_passages.py --report
```

**191 of 192 passages located.** Every one is three to six sheets, no sheet is
claimed by two passages, and no test's passages are out of page order. The
192nd is not a failure of the pipeline — see below.

`locate_pages.py` had already classified all 829 reading pages during the
listening run, so the first pass spends nothing: it reads the page maps in
`work/` and groups them on the `READING PASSAGE 2` headings the books print.
That got 134 for free. The other 58 are in books that print no such heading,
and they went to a narrowed re-read — one request a page, the same lesson
every stage here learned. The whole locate pass cost **$0.56**.

### Grouping is backwards from listening

A listening section is questions and nothing else. A reading passage is TEXT
first and questions after, so a page with no question numbers on it belongs
to the passage whose questions come **next**. Read the other way — the way
the audioscript grouper works — every passage took the following one's text
and passage 1 lost its own.

### Six rules, each bought with a specific wrong answer

The first version of this found "191 of 192" too, and most of them were
wrong. What made the number honest was a run for a book **replacing** that
book rather than upserting into it: rows from earlier, buggier runs were
surviving, so the report improved as the code got worse. The honest number
was 183, and these closed the gap.

**A passage ends; it does not run until the next one begins.** "No heading
continues the last passage" is right inside a paper and wrong at the end of
it — after passage 3 comes the writing task, and the next `READING PASSAGE 1`
may be forty pages away. Left unbounded, every third passage swallowed the
rest of the book; one came out at 61 pages. Each passage keeps its leading
contiguous run and no more.

**A book has as many tests as it has.** Two books print a General Training
paper beside the Academic one — a different exam, laid out identically — and
it arrived as tests 5 and 6. The Guide prints eighty pages of short exercises
before its eight tests, each numbered from 1, and they all claimed passage 1;
one came out at 40 pages. Both are refused by the same line, because both
claim a test the book does not have. `test_count` is the book's listening
sections ÷ 4, which is a fact already inventoried from the files.

**General Training is judged by the run; a lesson is judged by the page.**
These were one rule for a while and it cost four whole tests. Only half of a
GT paper's sheets carry the name, so dropping them one at a time left the
silent half looking like academic reading and the Guide's test 8 came out
eighteen sheets long with the GT paper inside it — it has to be condemned as
a run. But a Trainer's lesson is a single sheet printed *between* the
passages of the test beside it, always named ("Training Test 1" against "Exam
Practice Test 1"), and book 103's test 1 is twenty sheets of which six are
lessons. Condemning that run left the book showing four tests of six.

**A misread sheet is bridged; the writing task is not.** Cambridge 17 prints
its third passage over five sheets and the page map called three of them
`listening_questions` and `other` — two of them back to back — so the passage
was located as the single sheet that still said `READING PASSAGE 3`, and the
questions to 40 with it. A run of up to three non-reading sheets with reading
either side is a misreading, and at the *edge* of a paper, where there is no
reading on the far side, the same reach outward applies with a narrower stop:
anything that could be confused for a reading sheet is asked, and an answer
key — which carries the numbers 1 to 40 and is about reading — is not.

**The printed test number is a position in a series, not a number in a
book.** Cambridge 12 carries on from Cambridge 11 and heads its four tests
"Test 5" to "Test 8" — the same fact that makes answer keys match by order.
Believed literally, all twelve of its passages claimed a test the book does
not have and all twelve were refused. The heads are shifted to start at one,
and only when they have to be; a series still too long for the book after
shifting is a misreading and the refusals stand.

**Numbers that go down start the next paper.** Reaching outward at the edges
admitted the *previous* paper's last sheet at the front of the next block —
Cambridge 20 prints one test per PDF and each file opens on the back of the
previous test's last reading sheet. Those pages are genuinely reading, and
read as part of this paper their questions 34-40 opened a passage 3 that the
real passage 3 was then appended to. Eleven passages came out one page long.
A paper runs 1 to 40 once, so a number lower than the one before it is the
next paper starting.

**A passage does not resume after its last question.** The lowest number on a
sheet settles which passage it is in — unless that passage has already
printed question 13, or 26, or 40, in which case the low number is the
misreading and the high one is the page. Cambridge 11's test 4 has a sheet of
passage 2's questions 14-18 that came back "7-16"; believing the 7 gave
passage 1 seven pages, three of them passage 2's, and left passage 2 as what
was over. Four more across Cambridge 20 had the same shape.

### The one that is missing is missing from the book

The Official Guide's test 6 is four sheets short in the scan: pdf index 254
is printed page 254, and the next sheet is printed page **259**. Pages 255 to
258 hold the whole of its Reading Passage 2 — the text and questions 14 to 30
— and they are not in the file. It is recorded as a `finding` against
`cam102-t6-p2` and the report prints it beside the gap rather than
subtracting it from the count, because a report that quietly stops counting
what it has an excuse for is a report agreeing with itself.

## Reading: the rest of the pipeline

Four stages after the pages are found, and three of listening's are simply
absent — there is no recording, so nothing to align, nothing to trim and no
replay span to find.

```bash
seed/.venv/bin/python seed/run_reading.py --book 11 --owner <uuid>
seed/.venv/bin/python seed/run_reading.py --report
```

| stage | program | leaves |
|---|---|---|
| text | `read_passages.py` | `passage.json` |
| questions | `read_passage_questions.py` | `questions.src.json` |
| build | `build_questions.py` | `questions.json` |
| picture | `extract_image.py` | `image-group<N>.png` |
| import | `scripts.import_passage` | a private Material |

`run_reading.py` is its own runner rather than an arm of `run_pipeline.py`,
because `run_pipeline` is a loop over the `stage` table and that table holds
one row per SECTION. A passage is a sibling of a section, not one of them.
This carries no bookkeeping at all: what a passage has done is what is on
disk beside it, which is also what makes it resumable.

`build_questions.py` and `extract_image.py` are the same programs listening
uses. Both took a section id and did arithmetic on it; both now ask the id
which it is. A passage has no `aligned.json`, so every question comes out
with no replay span, which is what a paper you read rather than hear should
have.

### The letters are part of the answer key

Two of Reading's own tasks are answered BY a paragraph's letter — "which
paragraph contains the following information" has options A to G — so the
lettering is not layout. A passage stored as prose and re-split later, one
paragraph out, would mark every one of those answers wrong. The letters are
read off the page with the paragraphs, and a passage that comes back
half-lettered or lettered A, B, C, E is read again.

### Three answer shapes where listening has two

Matching is one task under five names, exactly as the nine completion types
are one document under nine. Matching headings is numbered **i, ii, iii**
because its items are the passage's lettered paragraphs — an answer of "C"
naming both a heading and a paragraph would be two questions at once — and
the key prints the pair together, "B vii" against question 15, of which only
the numeral is the answer. Scanned for `[A-K]` the way a lettered answer is,
"vii" yields nothing at all.

A **true/false set is neither lettered nor a gap-fill**. Its answer is a word
the candidate writes, so grading compares it as one; it has no template, so
the gap checks cannot apply; and its config is empty and stays empty, because
the three words are the TYPE. A key that abbreviates them — "T", "NG" — is
expanded to what the page offers, since a stored "T" is an answer nobody can
submit.

### What the pages refused

**`content_filter: RECITATION`.** Gemini recognises a published page and
returns an empty message with zero completion tokens. It arrived as "returned
no content", which is also what a reasoning model that spent its budget
thinking returns — two failures with opposite answers under one message.

The answer depends on which page. For an **answer key**, ask narrower: all
forty answers of Cambridge 11's page 124 were refused four times out of four,
and each band of thirteen was answered at once. For a **passage**, narrowing
does nothing — three paragraphs, one column, and the sheet cropped in half
were all refused, because the filter is on the image rather than on the
question — so it goes to a second provider, and nvidia's free tier reads the
same sheet immediately.

**A reply that will not parse.** A trailing comma before a closing brace is
legal in every language a model learned from and illegal in JSON; it is
repaired. Mismatched brackets are not: a repair that parses is one that has
quietly dropped the groups after the fault, and a partial read with no error
is the one failure this pipeline is built not to have. Those get a narrower
question instead — the window is halved, and halved again — because context
is what makes a group read correctly. A task printed across two sheets, asked
one sheet at a time, came back as a true/false set whose answers were letters.

And a **retry at temperature 0 is not a retry**. Everything here asks at 0.0,
which is right — a page has one correct reading and sampling from it is a way
to be wrong — but it meant three attempts at a malformed reply were three
copies of it, failing at the same character offset every time.

### The key is evidence; the reading is an interpretation

A true/false set whose answers are letters is not a hard question — it is a
group the page named something else. So a reading the key contradicts is made
once more and the better of the two kept. Twice, not until the check goes
quiet: sampling until nothing objects is a different thing from being right.

Finding the keys themselves took four corrections, and every one was the
window rather than the page:

* **The bound is the next TEST's key, not the next key sheet.** Cambridge
  prints a test's key across a spread — listening on one sheet, reading on
  the facing one — and both are classified as key pages, so the window was
  cut in half exactly where the reading answers begin. Tests 1 to 3 survived
  because the next test's key happened to be two pages on.
* **Where the sheets say which test they are, they decide.** IELTS Trainer
  heads every one "Test 4 Key" and prints three of them.
* **A page called the reading key only wins in a one-test document.** That
  branch was written for Cambridge 20, one PDF per test; applied to a
  four-test volume it answered Cambridge 13's test 2 from test 1's key.
* **In a one-test document the window opens on the last READING sheet.**
  Cambridge 20 packs several things onto one sheet, and its key starts at the
  foot of the page the last reading questions end on.

**64 of 64 tests have a complete reading key**, forty answers each.

## Where the reading corpus stands

**189 of 191 located passages are in the database and public**, beside the
256 listening materials — 2,511 reading questions across fourteen question
types, in fourteen courses of one book each. **64 of 64 tests have a complete
reading key**, forty answers apiece, and none of them is the listening key.

The reading half cost **$5.56**: $0.56 to find the pages, $1.14 to read the
passages, $3.86 to read the questions and the keys. Most of that last figure
is re-reads — the corpus was read through four times as the checks found
things, which is the same shape the listening half had and the reason this
file keeps a ledger at all.

### Two passages are refused, and each says why

`cam11-t4-p2` — **the scan's key disagrees with its own question pages.**
The paper is unambiguous across three sheets (14-18 multiple choice, 19-23
TRUE/FALSE/NOT GIVEN, 24-26) and the key page prints 14-19 as letters, 20-24
as TRUE/FALSE/NOT GIVEN, 25-26 as letters: one number apart from question 19
on. Both were read repeatedly and both come back the same, so it is the book
rather than the reading, and publishing half the answers against the wrong
questions is worse than publishing none.

`cam15-t3-p2` — **one sheet no provider will read.** Gemini answers
`content_filter: RECITATION` for it whole, in halves and in three
overlapping bands, every framing and every time; nvidia, the fallback, reads
a question page too poorly to use. Questions 14-20 come off the other sheet
correctly and 21-26 are on this one.

### What the checks caught that nothing else would have

Every one of these produced a material that looked complete:

* **A reading key that was the listening key.** Both papers number 1 to 40
  under one "Test 1 Key", and eleven of IELTS Trainer test 1's forty answers
  came from the wrong half — four of them consecutive words where the page
  prints multiple choice. Caught by the shape rule: a true/false set whose
  answers are words is not a hard question, it is the wrong key.
* **An answer taken from a "Distraction" line.** The Trainers explain each
  answer and then name the wrong options under it. "37 C: Austin is
  mentioned in both paragraph three and ... *Distraction* A: This makes
  grammatical sense, but ..." was read as 37 A — the one letter the book has
  just said is wrong. Caught by publishing, which refused a matching group
  where two questions shared a letter.
* **A summary with a box of words above it.** Twenty-seven passages had
  their template thrown away because the group carried options, and reached
  the build as "template gaps [] != question numbers".
* **A gap in a table's first row.** The layout grammar reads that row as the
  header and draws no gap in it — and `check_template.mjs` had been importing
  `form-syntax.ts` from a directory it left in a refactor, so the one check
  that runs the grammar rather than guessing at it had been silently off
  since.

# Vocabulary stage 3 — agreed decisions and contract

Companion to `brief-vocabulary-stage3.md`. The brief's own decisions are not
repeated here; this file records what the brief left open and was agreed with
the owner on 2026-10-04 (all 21 points accepted as recommended), plus the API
contract the backend and frontend build against.

## Findings behind the decisions (§0 of the brief)

- **Word timings** live in `audio_segment.words` (JSON
  `[{word, start_ms, end_ms}]`), one row per ASR segment of an `audio_blob`.
  317 blobs, all `ready`; 9,229 segments; 230,800 words. An owner's
  correction (`audio_asset.transcript_overrides`) rewrites a segment's TEXT
  only — its word timings no longer describe it, so a corrected segment is
  never a clip source.
- **Storage keys** are content-addressed (`app.services.storage`):
  `audio/{sha256}.ext`, `images/{sha256}.ext`. R2 in production, local disk
  (`media/`, served at `/media`) in dev. New prefixes: `tts/` and `clips/`.
- **Worker jobs** are not a generic queue: each kind of work is its own loop
  in `app/worker.py` and its own table is the queue (`audio_blob
  .transcript_status` + `SELECT … FOR UPDATE SKIP LOCKED`). TTS is one more
  loop over one more table — no broker, no new infrastructure.
- **Listening materials have no vocabulary.** `material_vocabulary` has rows
  for reading only; lookup exists only in reading. Rule 1 of the brief's clip
  choice ("saved from a listening material") is built but cannot fire today.
- **Coverage:** 4,857 of 11,855 single-word lexemes (41%) occur in a
  transcript in exactly their own form, not first/last in a segment. The rest
  are TTS.
- **Volume** is far below the brief's estimate: ~111K characters of lemmas
  (brief: 0.75M), 17,492 senses / ~923K characters of definitions (brief: 5M).
- **Kokoro on Python 3.14** works (verified in a `python:3.14-slim`
  container, CPU: 6.5 s of audio in ~5 s) with three conditions:
  - pin `transformers>=4.40`, or uv resolves transformers 4.12 whose
    tokenizers needs a Rust build;
  - take `torch` from the CPU index
    (`https://download.pytorch.org/whl/cpu`), or PyPI pulls GBs of CUDA
    libraries;
  - on macOS the `espeakng-loader` wheel is broken (the C library `exit(1)`s
    on a hard-coded data path) — Kokoro runs in Docker (Linux) in dev, never
    on the Mac host.
  misaki also needs `en_core_web_sm`; it tries to download it at runtime —
  install it as a pinned wheel URL instead.
- **No ffmpeg** anywhere in the stack. Cutting and encoding use **PyAV**
  (`av`, binary wheels bundle FFmpeg; cp314 wheels exist).

## Agreed decisions

### Audio source
1. **Exact form only.** A clip is taken only where the transcript has the word
   in exactly the saved form (case- and punctuation-insensitive): `played` is
   not a clip of `play` — in `listen` the learner types what they hear. A
   phrase matches consecutive words.
2. **Heteronyms never take a material clip.** The transcript has no part of
   speech, so a `record` clip may be the verb. Every heteronym lemma (see 6)
   is always TTS with the sense's own pronunciation.
3. **Clips are verified before use.** Each candidate clip is transcribed once
   with faster-whisper (seed run, on the 3060) and kept only if the word is
   heard. Candidates from materials added after a seed run stay unused until
   the next verification run — TTS serves them meanwhile.
4. **The server cuts.** Each clip is cut once into a small file, stored
   content-addressed; the browser never seeks inside a 30-minute recording.
   Padding ±150 ms (brief). Context clip: 2 words before + the word + 2 words
   after, within the same segment.

### TTS
5. **Voice: `bf_emma`** (Kokoro `lang_code='b'`). Model `hexgrad/Kokoro-82M`.
6. **Heteronyms from misaki's British gold lexicon** (`gb_gold.json`; 788
   entries keyed by part of speech, 199 of them in our lexicon), not a
   hand-written list. Words that differ WITHIN one part of speech (`lead` the
   metal /lɛd/, `tear` a rip, `bass`, `row`, `sow`, `bow`, `wound`, …) are not
   in it: for every sense of a heteronym lemma Gemini picks one of the
   candidate pronunciations once (misaki's variants ∪ a small extras table),
   and the decisions are written to the repo (like
   `backend/app/data/word_lists/decisions.jsonl`), replayable, reviewable.
7. **Seed script** `scripts/seed_tts.py`, same pattern as `seed_audio.py`,
   run by the owner on the 3060: every lexicon word (proper nouns excluded),
   every definition, and the clip verification of (3). Writes through the
   configured storage and DB. Production's worker generates only what is new
   or changed.
8. **Kokoro only in the worker image** via a `tts` extra; the API image does
   not change.

### `listen`
9. **Ladder** `recognise → recall → listen`; `recall` becomes a middle rung:
   2 consecutive correct at `recall` → `listen` (1 if the word has been at
   `listen` before); Again at `recall` → `recognise`; Again at `listen` →
   `recall`; Hard never demotes. Words already at `recall` with a streak
   promote on their next correct answer.
10. **"Can't listen now"** — a small link on the listen card. Pressed, every
    `listen` item for the rest of THIS session is served as its `recall`
    fallback, without penalty (same fallback pattern as no-audio).

### On the go
11. **The word inside its own definition** (recall shows `___`) is replaced in
    audio by a short silence.
12. **Sequence:** definition → 3 s pause → word → 1.5 s → next. The list is
    played once and stops at the end.
13. **Locked screen:** the server renders ONE file per item (definition +
    3 s silence + word + 1.5 s), content-addressed. The client plays items
    back to back on one `<audio>` with the Media Session API (play / pause /
    next / previous from headphones and the lock screen). Lock-screen
    metadata is `On the go · 3 / 40` — never the word, or the answer is on
    the lock screen during the pause. Real-iPhone test is the owner's.
14. **Exposure log:** new table; one row when the WORD part of an item
    actually played. Never touches FSRS.

### `speak`
15. **Not on a ladder.** `speak` is manual-only (settings exercise type, or
    `mode=speak`) and open to words whose passive level is `recall` or
    `listen`. Its answer is written to the passive FSRS card — accepted →
    Good, "I don't know" → Again — but never moves the rung, and ladder logic
    neither counts nor is broken by speak rows.
16. **Screen:** the (masked) definition is shown and read aloud once. The
    microphone opens only on the button or Space — never listening all the
    time.
17. **Uzbek substitutions** are applied to spelling, since STT returns English
    text, not phonemes: th→t/s, th→d/z, w→v, a≈e, a vowel prefixed to an
    initial consonant cluster (`istop` → `stop`). Applied to all 5
    alternatives. No other tolerance (no inflections, no edit distance).
18. **Three misses:** the word and its pronunciation are shown, nothing is
    written to FSRS or the review log, the miss is logged. Not requeued in
    this session; it comes back next session.
19. **Unsupported** (no `SpeechRecognition`, microphone refused, iOS
    failing): the speak card becomes a typing card (the recall prompt); the
    session never breaks. (Chrome's recognition sends audio to Google — not
    our server, but not "no server" either.)

### Settings
20. **Pronunciation toggle** = when on, the word's audio plays automatically
    when an answer is revealed. The speaker button is always there either
    way. Default ON; existing rows are set to true (nobody ever chose false —
    the control did not exist).
21. **Speaker button** on the practice answer reveal and the word page. The
    reading popover is out of scope.

### Small calls taken in building (not owner decisions — flagged in the report)
- The listen card plays the word once on its own when it appears; it never
  repeats by itself. Replay = button or Tab; presses alternate word → context
  → word … when a context clip exists.
- `0.75×` is a toggle that stays for the session (`playbackRate`,
  `preservesPitch`).

## API contract

All audio is `AudioOut = { url: string, context_url: string | null,
source: "clip" | "tts" }`. `null` where an audio field is allowed means "not
ready yet" — the server has already queued it.

### Practice
- `Level` (exercise_type / planned_exercise) gains `"listen"` and `"speak"`;
  `Mode` and settings `exercise_types` accept both.
- New prompt kinds on `PracticeItemOut.prompt`:
  - `{ kind: "listen", audio: AudioOut, fallback: PracticePromptOut }` —
    `fallback` is the item's ordinary recall gap prompt, used for "Can't
    listen now". Served only when audio is ready; otherwise the item is
    served as `exercise_type: "recall"`, `planned_exercise: "listen"` with an
    ordinary recall prompt.
  - `{ kind: "speak", definition: string, definition_audio_url: string |
    null, fallback: PracticePromptOut }` — `fallback` for unsupported
    browsers.
- `POST /vocabulary/practice/answer`:
  - listen: `exercise_type: "listen"`, `given` = typed. Graded exactly as
    recall (exact → Good, edit distance 1–2 → Hard, else Again).
  - Can't-listen / unsupported-speak fallback: `exercise_type: "recall"`,
    `planned_exercise: "listen"` (or `"speak"`), graded as recall.
  - speak accepted: `exercise_type: "speak"`, `given` = the matched
    alternative; the server re-runs the matcher on `given` (422 if it does
    not match). → Good.
  - speak "I don't know": `exercise_type: "speak"`, `gave_up: true`,
    `given: ""` → Again.
- `POST /vocabulary/practice/speak-check` `{ word_id, alternatives: string[]
  (1..5, each ≤ 200), attempt: 1..3 }` → `{ caught: boolean, matched: string
  | null, answer: string | null, audio: AudioOut | null }`. Writes nothing
  to FSRS or the review log; a miss is logged. `answer`/`audio` are filled
  only on attempt 3 with `caught: false` (the reveal).
- `PracticeAnswerOut.word.audio: AudioOut | null` — for the reveal's speaker
  button and the pronunciation autoplay.

### Word page and settings
- `GET /vocabulary/words/{id}` gains `audio: AudioOut | null`.
- `PUT /vocabulary/settings` accepts `pronunciation: boolean` (optional;
  absent = unchanged).

### On the go
- `GET /vocabulary/on-the-go` → `{ items: [{ word_id, url, duration_ms,
  word_offset_ms }], preparing: number }` — words in rotation (`learning` +
  `review`), newest first, independent of the daily queue. Only items whose
  render is ready are listed; `preparing` counts the rest (already queued).
  `word_offset_ms` is where the word starts inside the item file.
- `POST /vocabulary/on-the-go/exposures` `{ word_id }` → 204. Sent once per
  item, when playback passes `word_offset_ms`.

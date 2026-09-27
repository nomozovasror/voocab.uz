import type { QuestionResult, TranscriptLine, TranscriptWord } from "@/features/paper/types";

/**
 * The sentence either side of an answer — dimmer than the answer itself, and
 * there for the same reason the answer's own quote is: half of why somebody
 * missed a question is what led them to it. A candidate is far more often
 * pulled off course by the QUESTION than by the answer's own sentence, and
 * that question is very often a different speaker's turn entirely — an
 * interviewer's line before a candidate's answer in a Part 1 dialogue.
 *
 * This module is pure and untested by any runner: `frontend/package.json`
 * has no test runner configured (no vitest, no jest — only `tsc` and
 * `oxlint`). Kept dependency-free and exported function-by-function so it
 * can still be exercised by hand or from a future harness without changing
 * its shape.
 *
 * ## Where the data comes from
 *
 * `grading.transcript_with_context` (backend) sends every line the question's
 * own marked range touches, ROLE `"answer"`, plus the one line immediately
 * before and the one immediately after that touching set, roles `"before"`/
 * `"after"`. Word-level timings ride on every line. This module never asks
 * the server anything further — everything below is arithmetic over what one
 * `QuestionResult.transcript` array already carries, plus the other
 * questions' own marked ranges (`answerSpansOf`), which are already on every
 * other `QuestionResult` in the same attempt.
 */

// ── Named constants — each is a decision, not a magic number ────────────────

/** A gap this long between two words is a breath, not a stumble. Long enough
 *  that ordinary word-to-word timing in fluent speech never trips it, short
 *  enough that a genuine pause for breath or emphasis always does — picked
 *  for spoken English, not reused from the audio engine's own timing (that
 *  one governs playback UI, this one reads a transcript). */
export const PAUSE_MS = 350;

/** How long a neighbour sentence is allowed to run before it is cut. Past
 *  this a "neighbour" reads as a paragraph, and the whole point of showing
 *  one is a glance at what led into the answer, not a second transcript. */
export const MAX_NEIGHBOUR_WORDS = 20;

/** The hard fallback once neither a pause nor a clause boundary can be found
 *  within the limit — enough words either side of the cut to still read as
 *  English, short enough to still be a neighbour rather than a second answer
 *  line. Marked with "…" because, unlike the other two stages, this cut does
 *  not land on anything a reader would recognise as a natural stop. */
export const FALLBACK_WORDS = 12;

/** Clause-ending punctuation a stage-2 cut may land on, immediately after the
 *  word carrying it: comma, semicolon, colon, or an em/en dash standing in
 *  for one. Not sentence-enders — those are `SENTENCE_END` below, and a
 *  cut that landed on a full stop would just be a shorter sentence, not a
 *  clause boundary. */
const CLAUSE_END = /[,;:–—]$/;

/** Sentence-ending punctuation, optionally followed by a closing quote or
 *  bracket — the same shape `review.ts`'s own `SENTENCE` regex tests for,
 *  applied here per WORD rather than to a joined string, since sentences are
 *  built directly from timed words. */
const SENTENCE_END = /[.!?]["'’”)\]]*$/;

// ── Tokens: a word, or a word-shaped piece of plain text ─────────────────────

/** One token of a neighbour line, either a timed word (`start_ms`/`end_ms`
 *  present on the wire) or a plain-text piece of one with no timing at all.
 *  `startMs`/`endMs` are `null` in the second case, which is what turns off
 *  the pause stage everywhere below — never a sentinel like `-1`, which a
 *  gap calculation could silently treat as a real timestamp. */
interface Token {
  text: string;
  startMs: number | null;
  endMs: number | null;
}

function tokensOf(line: TranscriptLine): Token[] {
  if (line.words.length) {
    return line.words.map((w: TranscriptWord) => ({
      text: w.word,
      startMs: w.start_ms,
      endMs: w.end_ms,
    }));
  }
  // No word timings on this line's segment at all — `role`-aware callers
  // never partially trim a line in this state (see `neighbourFor`): there is
  // no time boundary to trim AT. Split on whitespace purely so sentence
  // splitting and the word-count limit still work off plain text.
  return line.text
    .split(/\s+/)
    .filter(Boolean)
    .map((text) => ({ text, startMs: null, endMs: null }));
}

/** Whether every token in a line carries real timing. Mixed timed/untimed
 *  tokens never occur on the wire — a line's words are all-or-nothing — but
 *  the check is written over the tokens rather than assumed, so a future
 *  partially-timed line degrades to "no timing" rather than crashing on a
 *  null half-way through a gap calculation. */
function isTimed(tokens: Token[]): boolean {
  return tokens.every((t) => t.startMs != null && t.endMs != null);
}

// ── Splitting a line into sentences ──────────────────────────────────────────

/** A line cut into its sentences, each a run of tokens. Falls back to the
 *  whole line as one sentence where no sentence-ending punctuation is found
 *  at all — the same trade `lineAround` (`review.ts`) makes, and for the
 *  same reason: a segment with no full stop in it is one sentence by
 *  definition, not zero. */
function sentencesOf(tokens: Token[]): Token[][] {
  const out: Token[][] = [];
  let current: Token[] = [];
  for (const token of tokens) {
    current.push(token);
    if (SENTENCE_END.test(token.text)) {
      out.push(current);
      current = [];
    }
  }
  if (current.length) out.push(current);
  return out;
}

// ── The three-stage cut ──────────────────────────────────────────────────────

export type CutStage = "none" | "pause" | "clause" | "fallback";

/**
 * A sentence's tokens, ADJACENT-END FIRST — `tokens[0]` is the word right
 * next to the answer, `tokens[length - 1]` is the word furthest from it —
 * cut down to `MAX_NEIGHBOUR_WORDS` from that end if it runs longer.
 *
 * Normalising direction this way lets one function serve both a "before"
 * sentence (cut its FRONT, keep its tail) and an "after" sentence (cut its
 * BACK, keep its head): the caller reverses the array going in for "before"
 * and reverses the kept prefix back on the way out.
 *
 * Three stages, tried in order, each searched from the natural 20-word
 * point OUTWARD (fewer words kept) — never inward, which would keep more
 * than the limit allows:
 *
 * 1. **A pause** (`PAUSE_MS`) between two consecutive words — most speech has
 *    one within a sentence's first twenty words, and a cut there is
 *    inaudible as a cut.
 * 2. **A clause boundary** (`CLAUSE_END`) — comma, semicolon, colon, dash —
 *    where the sentence has no pause long enough but does have a clause
 *    somewhere in range.
 * 3. **`FALLBACK_WORDS` words, marked "…"** — an arbitrary cut, so it is the
 *    only stage that leaves a mark saying so.
 */
function cutFromAdjacentEnd(tokens: Token[]): { tokens: Token[]; stage: CutStage } {
  if (tokens.length <= MAX_NEIGHBOUR_WORDS) return { tokens, stage: "none" };

  if (isTimed(tokens)) {
    for (let k = MAX_NEIGHBOUR_WORDS; k >= 1; k--) {
      // `tokens[k - 1]` and `tokens[k]` are adjacent in the ORIGINAL
      // sentence either way, but which one is spoken first flips with the
      // direction: for "after" (no reversal) array order already matches
      // speech order, while for "before" (reversed on the way in) index
      // k - 1 is spoken AFTER index k. Sorting the pair by its own
      // `startMs` rather than assuming array order is what makes one
      // function correct for both — computing `tokens[k].startMs -
      // tokens[k - 1].endMs` unconditionally gave a negative "gap" on
      // every "before" sentence, since it read the pair backwards.
      const [earlier, later] =
        tokens[k - 1].startMs! <= tokens[k].startMs!
          ? [tokens[k - 1], tokens[k]]
          : [tokens[k], tokens[k - 1]];
      const gap = later.startMs! - earlier.endMs!;
      if (gap >= PAUSE_MS) return { tokens: tokens.slice(0, k), stage: "pause" };
    }
  }

  for (let k = MAX_NEIGHBOUR_WORDS; k >= 1; k--) {
    if (CLAUSE_END.test(tokens[k - 1].text)) {
      return { tokens: tokens.slice(0, k), stage: "clause" };
    }
  }

  return { tokens: tokens.slice(0, FALLBACK_WORDS), stage: "fallback" };
}

// ── Never crossing into another question's evidence span ────────────────────

/** Strictly overlapping, the same test the server's own `_touches` uses for
 *  "does this moment touch this line" — so a span that merely ENDS where
 *  another begins is not treated as a collision. */
function overlaps(a: readonly [number, number], b: readonly [number, number]): boolean {
  return a[0] < b[1] && a[1] > b[0];
}

/**
 * Every stretch of audio ANOTHER question is answered from — the moments the
 * no-crossing rule has to stay clear of. Mirrors the backend's own
 * `question_ranges`: the question's single `replay_start_ms`/`replay_end_ms`
 * where set, plus one span per `option_replay` entry (a "choose TWO" is
 * answered in two places).
 */
export function answerSpansOf(result: QuestionResult): [number, number][] {
  const spans: [number, number][] = [];
  if (result.replay_start_ms != null && result.replay_end_ms != null) {
    spans.push([result.replay_start_ms, result.replay_end_ms]);
  }
  for (const span of Object.values(result.option_replay ?? {})) {
    spans.push([span[0], span[1]]);
  }
  return spans;
}

/**
 * A sentence's tokens (adjacent-end first, see `cutFromAdjacentEnd`),
 * trimmed so none of them reach into another question's marked span.
 *
 * Scans from the adjacent end OUTWARD — the direction is deliberately the
 * same one the length cut searches in — and stops at the first token that
 * collides, keeping everything closer to the answer. A collision at token
 * zero drops the whole neighbour, which is correct: the line immediately
 * beside this question's own evidence was, in that case, entirely another
 * question's.
 *
 * **Untimed tokens are clipped as a whole line, never partially.** With no
 * per-word timing there is no time boundary to trim AT, so the ONE check
 * available is whether the whole line's own `[start_ms, end_ms]` collides at
 * all — the same reduced precision the pause stage already accepts for a
 * line with no word timings, extended to this rule for the same reason.
 */
function clipToOtherSpans(
  tokens: Token[],
  line: TranscriptLine,
  otherSpans: readonly [number, number][],
): Token[] {
  if (!otherSpans.length) return tokens;
  if (!isTimed(tokens)) {
    const whole: [number, number] = [line.start_ms, line.end_ms];
    return otherSpans.some((s) => overlaps(whole, s)) ? [] : tokens;
  }
  const kept: Token[] = [];
  for (const token of tokens) {
    const span: [number, number] = [token.startMs!, token.endMs!];
    if (otherSpans.some((s) => overlaps(span, s))) break;
    kept.push(token);
  }
  return kept;
}

// ── One neighbour, assembled ─────────────────────────────────────────────────

export interface NeighbourContext {
  text: string;
  startMs: number;
  endMs: number;
  /** The printed text is not the whole neighbour sentence — either another
   *  question's evidence crowded it, or the cut fell back to a hard word
   *  limit (`CutStage: "fallback"`). A pause or a clause boundary both land
   *  on a stop a reader recognises and read fine with no mark; this is why
   *  only those two cases leave `truncated` false. */
  truncated: boolean;
}

/**
 * The sentence adjacent to the answer, cut and clipped, for one side.
 *
 * `side: "before"` reads the LAST sentence of the "before" line — the one
 * that actually touches the answer, where the line holds more than one —
 * and cuts its FRONT if it runs long. `side: "after"` reads the FIRST
 * sentence of the "after" line and cuts its BACK. Both directions share one
 * cutting function by normalising to "adjacent end first" going in and
 * restoring reading order on the way out.
 *
 * Returns `null` when there is no such line at all (the start or end of the
 * recording), or when the no-crossing clip removes every token — a
 * neighbour entirely inside another question's evidence is not shown
 * partially, it is not shown.
 *
 * A multi-run question (a "choose TWO letters" answered a minute apart) can
 * carry more than one `"before"`/`"after"` line, one per run. This reads the
 * OUTERMOST of each — the earliest `"before"` and the latest `"after"` — so
 * the shown context is "what led into the first answer" and "what followed
 * the last", never a gap between two runs that belongs to neither.
 */
export function neighbourFor(
  lines: TranscriptLine[],
  side: "before" | "after",
  otherSpans: readonly [number, number][],
): NeighbourContext | null {
  const candidates = lines.filter((l) => l.role === side);
  if (!candidates.length) return null;
  const line =
    side === "before"
      ? candidates.reduce((a, b) => (a.start_ms < b.start_ms ? a : b))
      : candidates.reduce((a, b) => (a.end_ms > b.end_ms ? a : b));

  const sentences = sentencesOf(tokensOf(line));
  const sentence = side === "before" ? sentences[sentences.length - 1] : sentences[0];
  if (!sentence?.length) return null;

  // Normalise to "adjacent end first" for both the crossing clip and the
  // length cut, then undo it once on the way out.
  const ordered = side === "before" ? [...sentence].reverse() : sentence;

  const clipped = clipToOtherSpans(ordered, line, otherSpans);
  if (!clipped.length) return null;

  const { tokens: cut, stage } = cutFromAdjacentEnd(clipped);
  const truncated = clipped.length < ordered.length || stage === "fallback";

  const kept = side === "before" ? [...cut].reverse() : cut;
  const text = kept.map((t) => t.text).join(" ");
  const timed = kept.filter((t) => t.startMs != null);
  // Falls back to the whole LINE's own bounds where nothing kept is timed —
  // there is then no finer time range to play than the line it came from.
  const startMs = timed.length ? timed[0].startMs! : line.start_ms;
  const endMs = timed.length ? timed[timed.length - 1].endMs! : line.end_ms;

  return {
    text: truncated ? (side === "before" ? `…${text}` : `${text}…`) : text,
    startMs,
    endMs,
    truncated,
  };
}

/** The line(s) marked `"answer"`, reduced to the span they actually cover —
 *  the same widening `review.ts`'s `spoken()` computes, now read straight
 *  off the roles the server already assigned rather than re-deriving them
 *  from a second overlap test against `replay_start_ms`/`replay_end_ms`. */
export function answerSpanOf(
  lines: TranscriptLine[],
): { startMs: number; endMs: number } | null {
  const answer = lines.filter((l) => l.role === "answer");
  if (!answer.length) return null;
  return {
    startMs: Math.min(...answer.map((l) => l.start_ms)),
    endMs: Math.max(...answer.map((l) => l.end_ms)),
  };
}

/** Both neighbours and the answer's own span, for one question. `otherSpans`
 *  is every OTHER question's own answer spans in the same attempt — see
 *  `answerSpansOf` — so the no-crossing rule has something to stay clear of.
 *
 *  Named `TranscriptContext` rather than `QuestionContext` — `review.ts`
 *  already uses that name for a question's place on the FORM (a field's
 *  label and the line it sat in), a different fact about the same row. */
export interface TranscriptContext {
  before: NeighbourContext | null;
  after: NeighbourContext | null;
  answer: { startMs: number; endMs: number } | null;
}

export function questionContext(
  lines: TranscriptLine[],
  otherSpans: readonly [number, number][],
): TranscriptContext {
  return {
    before: neighbourFor(lines, "before", otherSpans),
    after: neighbourFor(lines, "after", otherSpans),
    answer: answerSpanOf(lines),
  };
}

/** The whole shown passage's own play range — the smaller "Play with
 *  context" button's span: the before-sentence's start where there is one,
 *  through the after-sentence's end where there is one, else the answer's
 *  own bounds. Null only where the answer itself has no span (no transcript
 *  at all), which is also when neither button can be drawn. */
export function contextSpanOf(
  context: TranscriptContext,
): { startMs: number; endMs: number } | null {
  if (!context.answer) return null;
  return {
    startMs: context.before?.startMs ?? context.answer.startMs,
    endMs: context.after?.endMs ?? context.answer.endMs,
  };
}

import {
  parseTemplateLayout,
  type FormBlock,
  type FormLine,
} from "@/features/paper/form-syntax";
import { matchIndex } from "@/features/paper/matching";
import { sorted } from "@/features/paper/numbering";
import { paperParts } from "@/features/paper/take-paper";
import type {
  LabelStyle,
  MaterialTake,
  MistakeKind,
  QuestionResult,
  TakeQuestionGroup,
  TranscriptLine,
} from "@/features/paper/types";

/**
 * Turning a marked attempt into something a candidate can work from.
 *
 * The review is not the paper again. Sitting a paper, the question is the
 * form — the labels, the columns, the sentence the gap is inside — and that
 * whole document has to be on screen because the candidate is filling it in.
 * Afterwards none of it is being filled in, and printing it again buries the
 * four things they got wrong somewhere inside forty rows of correct ones.
 *
 * So a review row carries just enough of the form to be recognised: the
 * field's name and the line it sat in, with the gap written `___`. That is
 * the difference between "junction of Mill Street and ___ Avenue" and a
 * table redrawn to say the same thing.
 *
 * **Nothing here decides right from wrong, and nothing here classifies.**
 * Both of those came back with the attempt, from the server, because the
 * practice page's "Where you lose marks" is counted from the same
 * classifier — see `backend/app/services/mistakes.py`. What this module does
 * is presentation: which words of the form to quote, and which words of the
 * transcript to mark.
 */

// ── The line a gap sat in ────────────────────────────────────────────────

/**
 * Where one question was on the paper, said in as few words as possible.
 *
 * `label` is the field's name — a form row's label, a table row's stub, a
 * column heading — and `line` is the text it sat in. Either can be missing:
 * a bare gap on a form row has a label and nothing else worth quoting
 * ("Policy number"), and a note with no label has only its line.
 */
export interface QuestionContext {
  label: string | null;
  line: string | null;
}

/** What a gap is printed as once it is not a field any more. */
const GAP = "___";

/** A gap, while the line is being measured. One character, so the offsets
 *  either side of it are the text's own, and one nothing else in a passage
 *  or a template will contain. */
const MARKER = "\uFFFC";

function lineText(line: FormLine): string {
  return line.parts
    .map((part) => (part.kind === "text" ? part.text : GAP))
    .join("")
    .replace(/\s+/g, " ")
    .trim();
}

/** Where one sentence ends and the next begins — a full stop, question mark
 *  or exclamation, any closing quote or bracket after it, then a space.
 *
 *  The same rule and the same trade as `seed/read_vocabulary.py`'s: it gets
 *  `Dr. Ito` and `e.g.` wrong, and splitting too early gives a fragment
 *  where not splitting at all gives a paragraph. The first is occasionally
 *  ugly; the second is what this exists to stop. */
const SENTENCE = /(?<=[.!?]["'’”)\]])\s+|(?<=[.!?])\s+/;

/**
 * The line a gap sits in, cut down to that gap's own SENTENCE.
 *
 * A sentence completion is one sentence a line and this changes nothing for
 * it. A summary completion is a paragraph of prose holding three or four
 * gaps on ONE line, and without this every one of those questions quoted
 * the whole paragraph: three rows of the review, identical to each other,
 * each a hundred and twenty words long, with the answer to one of them
 * somewhere inside. The question the row exists to ask — "what were you
 * being asked here" — was answered three times with the same wall of text.
 *
 * So the sentence, and the sentence only. The row's own gap is `___` and
 * any other gap sharing that sentence is `___ (33)` — named, because a
 * second bare `___` would make two rows look alike again at the one place
 * they most need telling apart, and because the gap is not missing from the
 * sentence, it belongs to the row above or below.
 *
 * It was an ellipsis before the number, and a sentence ending in a gap then
 * read `…and a large proportion of them have ….` — four dots, which is a
 * typo rather than a blank. The number says whose blank it is and cannot
 * collide with the punctuation beside it.
 *
 * Falls back to the whole line where the split finds nothing — a template
 * with no full stop in it is one sentence by definition.
 */
function lineAround(
  line: FormLine,
  gap: number,
  /** What the paper calls another gap in the same sentence. */
  printed: (gap: number) => number | null,
): string {
  let text = "";
  const at: number[] = [];
  for (const part of line.parts) {
    if (part.kind === "text") {
      text += part.text;
    } else {
      at.push(text.length);
      text += MARKER;
    }
  }
  const which = line.parts
    .filter((part) => part.kind === "gap")
    .findIndex((part) => part.kind === "gap" && part.number === gap);
  if (which < 0) return lineText(line);

  let from = 0;
  let to = text.length;
  for (const piece of text.split(SENTENCE)) {
    const end = from + piece.length;
    if (at[which] < end) {
      to = end;
      break;
    }
    // Past this sentence and over the whitespace the split consumed. The
    // separator is not a fixed width — one space, two, a newline — so it is
    // stepped over rather than assumed, or every later sentence would be
    // measured from one character out.
    from = end;
    while (from < text.length && /\s/.test(text[from])) from += 1;
  }

  const gaps = line.parts.filter((part) => part.kind === "gap");
  const cut = text.slice(from, to);
  const mine = at[which] - from;
  let seen = at.filter((one) => one < from).length;
  return cut
    .split("")
    .map((ch, i) => {
      if (ch !== MARKER) return ch;
      const part = gaps[seen++];
      if (i === mine) return GAP;
      const number = part?.kind === "gap" ? printed(part.number) : null;
      return number == null ? GAP : `${GAP} (${number})`;
    })
    .join("")
    .replace(/\s+/g, " ")
    .trim();
}

function holds(line: FormLine, gap: number): boolean {
  return line.parts.some((part) => part.kind === "gap" && part.number === gap);
}

/**
 * Which line of a completion document one gap sits in, and what names it.
 *
 * The label is taken from whichever of the four shapes the gap is in, because
 * "what is this field called" has a different answer in each: a form row has
 * a label column, a table row has a stub and a column heading, a flow chart
 * has only its step, and notes have nothing at all.
 *
 * A line that is *only* the gap is dropped rather than quoted as "___" — on a
 * form row the label already said everything ("Policy number"), and printing
 * the blank back adds a row of punctuation to the page.
 */
function contextInTemplate(
  blocks: FormBlock[],
  gap: number,
  printed: (gap: number) => number | null,
): QuestionContext | null {
  for (const block of blocks) {
    if (block.kind === "row") {
      const line = block.lines.find((l) => holds(l, gap));
      if (line) {
        const text = lineAround(line, gap, printed);
        return {
          label: block.label.trim() || null,
          line: text === GAP ? null : text,
        };
      }
    }
    if (block.kind === "table") {
      for (const row of block.rows) {
        const column = row.findIndex((cell) => holds(cell, gap));
        if (column < 0) continue;
        const text = lineText(row[column]);
        // The row's stub names it where there is one — "Basic cover" — and
        // the column heading where the gap IS the first cell, since a stub
        // cannot name itself.
        const stub = column > 0 ? lineText(row[0]) : "";
        const head = (block.head[column] ?? "").trim();
        return {
          label: stub || head || null,
          line: text === GAP ? (stub ? head || null : null) : text,
        };
      }
    }
    if (block.kind === "flow") {
      const step = block.steps.find((l) => holds(l, gap));
      if (step) return { label: null, line: lineAround(step, gap, printed) };
    }
  }
  return null;
}

/**
 * Every question on the paper, by id, said in a phrase.
 *
 * Built off `paperParts`, which is the walk the take page and the navigator
 * already make — so the review cannot end up quoting question 24's line
 * beside question 23's number.
 *
 * Returns an empty map for a material that could not be fetched. That is an
 * ordinary state: an attempt outlives the material's visibility, and a review
 * of a paper unpublished since still has answers, mistakes and a transcript
 * to show. It just cannot say where on the form each gap was.
 */
export function questionContexts(
  material: MaterialTake | undefined,
): Map<string, QuestionContext> {
  const out = new Map<string, QuestionContext>();
  if (!material) return out;

  // What the PAPER calls each question, so a sentence holding two gaps can
  // name the one that is not this row's. The same walk everything else here
  // numbers by — a second way of counting to 32 is a second chance to
  // disagree about which question that is.
  const printedOf = new Map(
    paperParts(material).flatMap((part) =>
      part.rows.map((row) => [row.id, row.number] as const),
    ),
  );

  for (const part of sorted(material.parts)) {
    for (const group of sorted(part.question_groups)) {
      const blocks = group.config.template
        ? parseTemplateLayout(group.config.template)
        : null;
      const printed = (gap: number) =>
        printedOf.get(
          group.questions.find((one) => one.number === gap)?.id ?? "",
        ) ?? null;
      for (const question of group.questions) {
        // A question with its own text — multiple choice, matching — already
        // carries its context and needs no template read.
        if (question.prompt?.trim()) {
          out.set(question.id, { label: null, line: question.prompt.trim() });
          continue;
        }
        const found = blocks
          ? contextInTemplate(blocks, question.number, printed)
          : null;
        if (found) out.set(question.id, found);
      }
    }
  }
  return out;
}

/** What a letter answer was picked FROM, by question id.
 *
 *  Two places, because the two tasks answered by letter hold their options in
 *  two places: multiple choice gives each question its own list, and matching
 *  prints one box above the whole group. A review that only read the group
 *  would print "C" for every multiple-choice answer, which is the storage
 *  format rather than the answer. */
export function questionOptions(
  material: MaterialTake | undefined,
): Map<string, { group: TakeQuestionGroup; options: string[] }> {
  const out = new Map<
    string,
    { group: TakeQuestionGroup; options: string[] }
  >();
  for (const part of material?.parts ?? []) {
    for (const group of part.question_groups) {
      for (const question of group.questions) {
        out.set(question.id, {
          group,
          options: question.options ?? group.config.options ?? [],
        });
      }
    }
  }
  return out;
}

// ── Marking the answer inside the transcript ─────────────────────────────

export interface MarkedRun {
  text: string;
  /** Whether this run is the answer being said. */
  hit: boolean;
}

const WORDISH = /[\p{L}\p{N}]/u;

function boundedAt(haystack: string, at: number, length: number): boolean {
  const before = haystack[at - 1];
  const after = haystack[at + length];
  return (
    (before === undefined || !WORDISH.test(before)) &&
    (after === undefined || !WORDISH.test(after))
  );
}

/**
 * The transcript with the answer marked in it.
 *
 * This is the most valuable line on the page and the reason the transcript is
 * quoted at all. A candidate who wrote "windscreen" where the answer was
 * "wing mirror" did not mishear — they were pulled by a distractor, and the
 * only thing that shows them so is reading *"The windscreen was fine,
 * luckily — but the wing mirror is broken"*. Marking the answer inside it is
 * what makes that readable at a glance rather than a sentence to search.
 *
 * **Found by matching the text, and left unmarked when it cannot be found.**
 * The author's marked range is snapped to segment boundaries almost every
 * time, so highlighting by timing would light the whole sentence and claim
 * the entire line was the answer. Text matching is exact where it works and
 * silent where it doesn't: a number said as "A C four four seven one" and
 * written `AC4471` simply comes back unmarked, which is honest. A mark in
 * the wrong place would be worse than no mark, because a learner uses it to
 * decide what they missed.
 *
 * Whole words only, and the longest accepted phrasing first, so "wing mirror"
 * is marked as one answer rather than "mirror" being found inside it.
 *
 * **One occurrence, or none.** An answer said twice in the same line cannot be
 * marked, because nothing here knows which of the two the question is asking
 * about — and marking both says they are two answers, which is what a reader
 * saw when a line about a five-kilometre walk mentioned "kilometres" three
 * times and every one of them lit up. The rule above already says a mark in
 * the wrong place is worse than no mark; two marks are two chances to be in
 * the wrong place. A phrasing that appears more than once is skipped and the
 * next one tried, so "5 kilometres" being repeated does not stop "5 km" from
 * being marked if that is what the line says.
 */
export function markAnswer(text: string, answers: string[]): MarkedRun[] {
  const wanted = answers
    .map((a) => a.trim())
    .filter((a) => a.length > 1)
    .sort((a, b) => b.length - a.length);
  if (!wanted.length) return [{ text, hit: false }];

  const hay = text.toLowerCase();
  for (const answer of wanted) {
    const needle = answer.toLowerCase();
    const found: number[] = [];
    for (
      let at = hay.indexOf(needle);
      at >= 0;
      at = hay.indexOf(needle, at + 1)
    ) {
      if (boundedAt(hay, at, needle.length)) found.push(at);
    }
    if (found.length !== 1) continue;
    const [at] = found;
    const runs: MarkedRun[] = [];
    if (at > 0) runs.push({ text: text.slice(0, at), hit: false });
    runs.push({ text: text.slice(at, at + needle.length), hit: true });
    const rest = text.slice(at + needle.length);
    if (rest) runs.push({ text: rest, hit: false });
    return runs;
  }
  return [{ text, hit: false }];
}

/** The transcript across one answer's moment, as one line of prose. Several
 *  segments are joined rather than listed: they are consecutive sentences of
 *  the same speech, and stacking them turns a quotation into a transcript
 *  viewer. */
export function transcriptText(lines: TranscriptLine[] | undefined): string {
  return (lines ?? [])
    .map((line) => line.text.trim())
    .filter(Boolean)
    .join(" ");
}

/**
 * The stretch the play button covers: the SENTENCE, not the marked moment.
 *
 * These are two different spans and the difference is audible. The author
 * marks where the answer is said — often just the phrase — while the server
 * quotes every transcript LINE that moment touches, because half a sentence
 * is not a quotation. Playing the marked range under the quoted line meant
 * the recording stopped partway through the last word on screen, every time
 * the author's mark ended before the segment did.
 *
 * A row whose text and whose audio disagree is the same fault as a waveform
 * coloured by something other than the playhead: the reader is not going to
 * work out which of the two is the honest one, they are going to stop
 * trusting the row.
 *
 * Widened to the lines the range touches, never to every line present. A
 * "choose TWO letters" is answered in two places a minute apart and both
 * moments' lines come back together; taking the outer bounds of all of them
 * would play the minute of unrelated speech between.
 */
function spoken(
  startMs: number | null,
  endMs: number | null,
  lines: TranscriptLine[] | undefined,
): [number | null, number | null] {
  if (startMs == null || endMs == null || !lines?.length)
    return [startMs, endMs];
  let from = startMs;
  let to = endMs;
  for (const line of lines) {
    // Strictly overlapping, the same test the server used to pick these
    // lines — so a line that merely ends where the mark begins is not
    // dragged in here either.
    if (line.start_ms >= endMs || line.end_ms <= startMs) continue;
    from = Math.min(from, line.start_ms);
    to = Math.max(to, line.end_ms);
  }
  return [from, to];
}

// ── The rows the page draws ──────────────────────────────────────────────

export interface ReviewRow {
  result: QuestionResult;
  /** The first number this question carries, and how many it takes. */
  number: number;
  span: number;
  /** Zero-based; `partIndex + 1` is what the reader sees. */
  partIndex: number;
  context: QuestionContext | null;
  /** Answered by picking a letter rather than by writing words. */
  byLetter: boolean;
  /** The box a letter answer is picked from, so a review can print what "C"
   *  actually said rather than the storage format. */
  options: string[];
  /** Which alphabet that box is lettered in — matching headings is numbered
   *  i to viii, everything else is A to H. Carried because the answer is
   *  stored as its label and has to be looked back up. */
  labels: LabelStyle;
  transcript: string;
  /** Which paragraph the quote was taken from, where the paper has lettered
   *  paragraphs and the quote was found in one. Null for listening, whose
   *  quote is placed by a clock instead, and null for a passage the book
   *  does not letter. */
  where: QuoteSource | null;
  startMs: number | null;
  endMs: number | null;
}

/**
 * Every result, in the order the paper printed it, with what it takes to draw
 * one row.
 *
 * Ordered off `paperParts` where the material could be fetched, and off the
 * server's own `number` where it could not — the two agree, since the server
 * walks the tree the same way, but only one of them exists in both cases.
 */
/** A quoted line, and — where the page letters its paragraphs — which one it
 *  came from, so the review can offer to go and look at it. */
export interface Quote {
  text: string;
  where: QuoteSource | null;
}

/** A paragraph, named the way the passage pane's anchors name it. */
export interface QuoteSource {
  partId: string;
  label: string;
}

/**
 * Where an answer is found in the material, as a line to quote.
 *
 * Listening's answer is a moment in a recording, and the server sends the
 * transcript across it. Reading's is a sentence on the page, and nothing is
 * sent: the passage came down with the paper, so the quote is found in it
 * here — by the same text match the transcript's own highlight uses, and
 * under the same rule. An answer that appears twice in a passage is not
 * quoted at all: a quote pointing at the wrong occurrence teaches a candidate
 * they missed something they never read.
 */
export function passageQuote(
  material: MaterialTake | undefined,
  result: QuestionResult,
): Quote {
  const wanted = result.correct_answers
    .map((a) => a.trim())
    .filter((a) => a.length > 1);
  if (!wanted.length) return NOTHING;

  // The paragraph is carried with the part it belongs to, not flattened away
  // with it. Which paragraph an answer was in is half of what the reader
  // wants to know — "paragraph C" is where they go to check whether NOT
  // GIVEN really was not given — and a passage's letters only mean anything
  // beside the passage they were printed in: three passages each letter from
  // A, so a bare "C" names three paragraphs.
  const paragraphs = (material?.parts ?? []).flatMap((part) =>
    (part.passage?.paragraphs ?? []).map((one) => ({
      partId: part.id,
      label: one.label,
      text: one.text,
    })),
  );
  for (const answer of wanted) {
    const needle = answer.toLowerCase();
    const hits = paragraphs.filter((p) =>
      p.text.toLowerCase().includes(needle),
    );
    if (hits.length !== 1) continue;
    const [hit] = hits;
    // The SENTENCE, not the paragraph. A paragraph is eighty words and the
    // point of the quote is to put the reader back in front of the line they
    // misread — the same argument `spoken` makes about widening a marked
    // moment to its sentence rather than quoting the whole turn.
    const sentences = hit.text.split(/(?<=[.!?])\s+/);
    const line = sentences.find((one) => one.toLowerCase().includes(needle));
    return {
      text: (line ?? hit.text).trim(),
      where: hit.label ? { partId: hit.partId, label: hit.label } : null,
    };
  }
  return NOTHING;
}

/** No line worth quoting. One value rather than a fresh object each time it
 *  fails, because a row is drawn from this and a new object every render is a
 *  row that re-renders for no reason. */
const NOTHING: Quote = { text: "", where: null };

export function reviewRows(
  results: QuestionResult[],
  material: MaterialTake | undefined,
  /** Where to find the line to quote. Absent means the recording's
   *  transcript, which is what the server sends with a listening attempt. */
  quote?: (result: QuestionResult) => Quote,
): ReviewRow[] {
  const context = questionContexts(material);
  const groups = questionOptions(material);
  const walk = material ? paperParts(material) : [];
  const place = new Map(
    walk.flatMap((part) => part.rows.map((row) => [row.id, row] as const)),
  );

  return results
    .map((result) => {
      const at = place.get(result.question_id);
      const found = groups.get(result.question_id);
      // The play button covers the sentence on screen, not the phrase the
      // author marked inside it — see `spoken`.
      const [startMs, endMs] = spoken(
        result.replay_start_ms,
        result.replay_end_ms,
        result.transcript,
      );
      const options = found?.options ?? [];
      const labels = found?.group.config.label_style ?? "letters";
      const quoted = quote
        ? quote(result)
        : { text: transcriptText(result.transcript), where: null };
      // The server already knows which it is and says so; the group is only
      // consulted where the material came back at all.
      const byLetter =
        result.answered_by === "letters" ||
        found?.group.type === "multiple_choice" ||
        found?.group.type === "matching";
      return {
        result,
        number: at?.number ?? result.number,
        span: at?.span ?? result.marks ?? 1,
        partIndex: at?.partIndex ?? 0,
        context: context.get(result.question_id) ?? null,
        byLetter,
        options,
        labels,
        transcript: quoted.text,
        where: quoted.where,
        startMs,
        endMs,
      };
    })
    .sort((a, b) => a.number - b.number);
}

/**
 * The mistakes on this paper, by kind, biggest first.
 *
 * Counted from the kinds the server sent rather than worked out here, so this
 * panel and the practice page's "Where you lose marks" are the same
 * arithmetic over the same classifier. Ties break on the kind's own name so
 * two equal counts don't reshuffle between renders.
 */
export function tallyMistakes(
  results: QuestionResult[],
): { kind: MistakeKind; count: number }[] {
  const counts = new Map<MistakeKind, number>();
  for (const result of results) {
    if (!result.mistake) continue;
    counts.set(result.mistake, (counts.get(result.mistake) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([kind, count]) => ({ kind, count }))
    .sort((a, b) => b.count - a.count || a.kind.localeCompare(b.kind));
}

/** How an answer reads once it is not in a field any more. A letter answer is
 *  stored as "a,c" and means nothing printed that way, so it becomes "A and
 *  C" — and, where the box came back with the material, the option's own
 *  words.
 *
 *  **In the box's own alphabet**, which is why `labels` is here. Matching
 *  headings is numbered i to viii and everything else is lettered A to H,
 *  and `matchIndex` knows the difference; the arithmetic this used to do on
 *  the first character does not. It read `i` and `iii` as the same option,
 *  so a review printed one heading beside two answers and told a candidate
 *  they had chosen something they never chose. */
export function sayAnswer(
  value: string,
  byLetter: boolean,
  options: string[] = [],
  labels: LabelStyle = "letters",
): string {
  if (!byLetter) return value.trim();
  return value
    .split(",")
    .map((letter) => letter.trim().toLowerCase())
    .filter(Boolean)
    .map((letter) => {
      const text = options[matchIndex(letter, labels)];
      // A roman numeral stays lowercase where it is printed on its own —
      // "vii" is how the paper prints it — and a letter is capitalised.
      const shown = labels === "roman" ? letter : letter.toUpperCase();
      return text ? `${shown} — ${text}` : shown.toUpperCase();
    })
    .join(", ");
}

/**
 * What the reader marked in the passage, and where it is kept.
 *
 * The real computer-delivered test lets a candidate highlight the text, and
 * they use it constantly: the sentence an answer came from gets marked, and
 * the marks are how they find their way back through nine hundred words at
 * the end. Listening had no use for it — there is nothing on screen to mark
 * — and reading has little that matters more.
 *
 * ## Offsets, not ranges
 *
 * A mark is a paragraph and two character offsets into that paragraph's
 * PLAIN text. Not a DOM range, which stops meaning anything the moment React
 * re-renders, and not a copy of the marked words, which would match the
 * wrong occurrence the second time a word appears in a paragraph.
 *
 * Offsets survive everything the page does to the prose — a re-render, a
 * font-size change, another mark laid over the top — and they are the same
 * coordinates the review can redraw from, because both pages are rendering
 * the same passage text from the same material.
 *
 * ## In the browser, on purpose
 *
 * A highlight is a note somebody made to themselves while reading one
 * passage on one machine. It is worth surviving a reload and the walk to the
 * review page, which is what this gives it. It is not worth a column, a
 * migration and a round trip per stroke — and unlike the answers, nothing
 * else in the app ever has to read it.
 *
 * Kept separately from the take session rather than inside it, because it
 * outlives one: the session is cleared the moment the paper is submitted,
 * and the marks have to still be there on the review page the submit
 * navigates to.
 */

/**
 * What a mark MEANS, which is the point of having three of them.
 *
 * A candidate working a forty-question paper marks for different reasons and
 * needs them apart at a glance twenty minutes later: the word the question
 * turns on, the place the answer was found, and the line they are not sure
 * about and mean to come back to. One colour makes all three the same
 * decision, which is the same as making none of them.
 *
 * Never green and never red. Those two mean "right" and "wrong" on the
 * review page, and the marks are shown there — a line a candidate
 * highlighted green while reading would come back as a verdict they never
 * made.
 */
export type MarkColour = "key" | "found" | "doubt";

export const MARK_COLOURS: MarkColour[] = ["key", "found", "doubt"];

/** What each is for, in the reader's own words — the popover and the tool
 *  row both label them, because a row of three swatches is a puzzle. */
export const MARK_MEANING: Record<MarkColour, string> = {
  key: "Keyword in the question",
  found: "Answer found here",
  doubt: "Come back to this",
};

export interface Highlight {
  /** Which part's passage. A paper can hold three. */
  partId: string;
  /** Which paragraph within it, by index — the letter is null on most
   *  passages, so position is the only thing every paragraph has. */
  index: number;
  /** Character offsets into the paragraph's text, half-open. */
  start: number;
  end: number;
  /** Absent in a mark made before there was a choice, which reads as the
   *  amber it was drawn in. */
  colour?: MarkColour;
  /** What the reader wrote about this stretch, where they wrote anything.
   *
   *  A note IS a mark with words attached rather than a second kind of
   *  object beside it: it has the same anchor, the same persistence and the
   *  same click-to-remove, and every one of those would otherwise be written
   *  twice. */
  note?: string;
}

const key = (materialId: string) => `voocab.highlights.${materialId}`;

export function loadHighlights(materialId: string): Highlight[] {
  try {
    const raw = localStorage.getItem(key(materialId));
    const said = raw ? JSON.parse(raw) : null;
    return Array.isArray(said) ? (said as Highlight[]) : [];
  } catch {
    // A private window, storage switched off, or something written by an
    // older shape. An unmarked passage is a correct passage.
    return [];
  }
}

export function saveHighlights(materialId: string, marks: Highlight[]): void {
  try {
    if (marks.length === 0) localStorage.removeItem(key(materialId));
    else localStorage.setItem(key(materialId), JSON.stringify(marks));
  } catch {
    /* nothing to do about it, and nothing depends on it */
  }
}

/**
 * The marks for one paragraph, merged and in order.
 *
 * Merged because two marks that touch are one mark: a reader who highlights
 * a sentence and then the clause after it means one stretch, and drawing it
 * as two leaves a hairline seam where the rounded corners meet. Overlapping
 * is the same case — highlighting over something already highlighted has to
 * be idempotent or the second pass darkens the first.
 */
export function marksIn(
  all: Highlight[],
  partId: string,
  index: number,
): Highlight[] {
  const mine = all
    .filter((m) => m.partId === partId && m.index === index && m.end > m.start)
    .sort((a, b) => a.start - b.start);

  const out: Highlight[] = [];
  for (const mark of mine) {
    const last = out[out.length - 1];
    // Merged only where they agree. Two marks of one colour that touch are
    // one mark; two of DIFFERENT colours that touch are two things the
    // reader said, and running them together would turn "the keyword" and
    // "where the answer is" into one stripe of whichever came first.
    if (last && mark.start <= last.end && sameKind(last, mark)) {
      last.end = Math.max(last.end, mark.end);
    } else {
      out.push({ ...mark });
    }
  }
  return out;
}

function sameKind(a: Highlight, b: Highlight): boolean {
  return (a.colour ?? "key") === (b.colour ?? "key") && !a.note && !b.note;
}

export interface Run {
  text: string;
  at: number;
  /** Null where this run is plain text. */
  mark: Highlight | null;
}

/** The text of one paragraph, cut into marked and unmarked runs. */
export function runsOf(text: string, marks: Highlight[]): Run[] {
  const out: Run[] = [];
  let at = 0;
  for (const mark of marks) {
    const from = Math.max(at, Math.min(mark.start, text.length));
    const to = Math.max(from, Math.min(mark.end, text.length));
    if (from > at) out.push({ text: text.slice(at, from), at, mark: null });
    if (to > from) out.push({ text: text.slice(from, to), at: from, mark });
    at = to;
  }
  if (at < text.length) out.push({ text: text.slice(at), at, mark: null });
  return out;
}

/**
 * The same list with whatever covers `offset` taken out of it.
 *
 * Removing the WHOLE stretch the reader clicked, not the one original mark
 * that happens to hold that character. By the time it is on screen two
 * touching marks are one yellow shape, and clicking a shape has to remove
 * the shape — taking away half of it and leaving the rest looks like a bug
 * whatever the data says.
 */
export function withoutAt(
  all: Highlight[],
  partId: string,
  index: number,
  offset: number,
): Highlight[] {
  const hit = marksIn(all, partId, index).find(
    (m) => offset >= m.start && offset < m.end,
  );
  if (!hit) return all;
  const { start, end } = hit;
  return all.filter(
    (m) =>
      m.partId !== partId ||
      m.index !== index ||
      m.end <= start ||
      m.start >= end,
  );
}

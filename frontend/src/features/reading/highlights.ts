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

export interface Highlight {
  /** Which part's passage. A paper can hold three. */
  partId: string;
  /** Which paragraph within it, by index — the letter is null on most
   *  passages, so position is the only thing every paragraph has. */
  index: number;
  /** Character offsets into the paragraph's text, half-open. */
  start: number;
  end: number;
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
): Array<[number, number]> {
  const mine = all
    .filter((m) => m.partId === partId && m.index === index && m.end > m.start)
    .map((m) => [m.start, m.end] as [number, number])
    .sort((a, b) => a[0] - b[0]);

  const out: Array<[number, number]> = [];
  for (const [start, end] of mine) {
    const last = out[out.length - 1];
    if (last && start <= last[1]) last[1] = Math.max(last[1], end);
    else out.push([start, end]);
  }
  return out;
}

/** The text of one paragraph, cut into marked and unmarked runs. */
export function runsOf(
  text: string,
  marks: Array<[number, number]>,
): Array<{ text: string; marked: boolean; at: number }> {
  const out: Array<{ text: string; marked: boolean; at: number }> = [];
  let at = 0;
  for (const [start, end] of marks) {
    const from = Math.max(at, Math.min(start, text.length));
    const to = Math.max(from, Math.min(end, text.length));
    if (from > at) out.push({ text: text.slice(at, from), marked: false, at });
    if (to > from) out.push({ text: text.slice(from, to), marked: true, at: from });
    at = to;
  }
  if (at < text.length) out.push({ text: text.slice(at), marked: false, at });
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
    ([start, end]) => offset >= start && offset < end,
  );
  if (!hit) return all;
  const [start, end] = hit;
  return all.filter(
    (m) =>
      m.partId !== partId ||
      m.index !== index ||
      m.end <= start ||
      m.start >= end,
  );
}

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
 * What a mark MEANS — and why there are two of them rather than three.
 *
 * A candidate working a forty-question paper marks for two different
 * reasons and needs them apart at a glance twenty minutes later: *this is
 * the thing* and *I am not sure about this*. One mark makes both the same
 * decision, which is the same as making neither.
 *
 * ## It was three, in three colours
 *
 * Amber for the keyword, blue for where the answer was found, violet for
 * the line to come back to. The blue was `#5b9bd5` — which is exactly the
 * B1 colour on the CEFR scale — and the violet was a shade off B2. On the
 * review page those two systems land on the same passage one layer apart,
 * so blue meant "the answer was here" while the reader was working and
 * "this word is B1" ten minutes later. A colour that means two things is
 * not a colour system.
 *
 * The scale won, on reach: CEFR is printed on four screens and is a ladder
 * learners already have a feel for, where the pen is one reader's private
 * annotation on one screen. So the pen kept the amber — the app's own
 * accent, already saying "this is the thing" everywhere else — and
 * separates by STYLE instead of hue.
 *
 * ## What that cost, said plainly
 *
 * Two styles carry two meanings, so "the keyword in the question" and
 * "where the answer was" are now one mark between them. That is a real
 * loss and it is the right one of the three to take: both were always the
 * same gesture — *this matters, here* — differing only in which end of the
 * page the reader was looking at. "I am not sure" is the one that was
 * never like the other two, so it is the one that kept a channel.
 *
 * A fill and a line, and not two tints of amber: two strengths of one
 * colour is a thing to compare, and a reader scanning back through nine
 * hundred words has to RECOGNISE a mark, not measure it.
 *
 * Never green and never red. Those two mean "right" and "wrong" on the
 * review page, and the marks are shown there — a line a candidate
 * highlighted green while reading would come back as a verdict they never
 * made.
 */
export type MarkStyle = "fill" | "line";

export const MARK_STYLES: MarkStyle[] = ["fill", "line"];

/** What each is for, in the reader's own words — the popover and the tool
 *  row both label them, because two unlabelled swatches is a puzzle. */
export const MARK_MEANING: Record<MarkStyle, string> = {
  fill: "Something that matters here",
  line: "Not sure — come back to this",
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
   *  fill it was drawn as. */
  style?: MarkStyle;
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
    return Array.isArray(said) ? (said as unknown[]).map(restyle) : [];
  } catch {
    // A private window, storage switched off, or something written by an
    // older shape. An unmarked passage is a correct passage.
    return [];
  }
}

/**
 * One stored mark, in today's shape.
 *
 * These live in the browser and nowhere else, so there is no migration to
 * run and no moment at which the old ones are all gone: somebody who
 * marked up a passage last week and comes back to it next month arrives
 * here with `colour: "doubt"` on every mark, and a page that dropped them
 * would have thrown away an hour of their reading.
 *
 * The two that meant *this matters* — the keyword and where the answer was
 * — become the fill; the one that meant *I am not sure* becomes the line.
 * That is the same collapse the pen itself made, applied to what the pen
 * already wrote.
 */
function restyle(said: unknown): Highlight {
  const mark = said as Highlight & { colour?: string };
  if (mark.style || !mark.colour) return mark;
  const { colour, ...rest } = mark;
  return { ...rest, style: colour === "doubt" ? "line" : "fill" };
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
    // Merged only where they agree. Two marks of one style that touch are
    // one mark; a fill and a line that touch are two things the reader
    // said, and running them together would turn "this matters" and "I am
    // not sure" into one stripe of whichever came first.
    if (last && mark.start <= last.end && sameKind(last, mark)) {
      last.end = Math.max(last.end, mark.end);
    } else {
      out.push({ ...mark });
    }
  }
  return out;
}

function sameKind(a: Highlight, b: Highlight): boolean {
  return (a.style ?? "fill") === (b.style ?? "fill") && !a.note && !b.note;
}

export interface Run<T = Highlight> {
  text: string;
  at: number;
  /** Null where this run is plain text. */
  mark: T | null;
}

/**
 * The text of one paragraph, cut into marked and unmarked runs.
 *
 * Generic over what a mark IS, because the review page lays a second kind
 * over the same prose — where the answer was, which words are worth
 * learning, which of them this reader has already saved — and every one of
 * those is a paragraph and two offsets with something else hanging off it.
 * The cutting is identical; only what the caller does with `mark` differs.
 *
 * The marks must arrive sorted and non-overlapping. Both callers see to that
 * themselves, for different reasons: `marksIn` merges the reader's touching
 * marks, and `features/reading/layers.ts` drops an overlay swallowed by a
 * longer one.
 */
export function runsOf<T extends { start: number; end: number }>(
  text: string,
  marks: T[],
): Run<T>[] {
  const out: Run<T>[] = [];
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

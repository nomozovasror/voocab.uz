/**
 * What a candidate sees beside a question.
 *
 * A question's stored `number` is its place inside its own group, always
 * 1..N. The number on the page runs across the whole material: Part 1 might
 * be "Questions 1–6" of form completion followed by "Questions 7–10" of
 * multiple choice, and adding, deleting or moving a group renumbers
 * everything after it.
 *
 * Keeping that as a view rather than as stored data is what makes the
 * renumbering free — and what stops a group edit from having to rewrite every
 * row of every later group to stay consistent. Both sides of the app walk
 * their own ordered tree and accumulate the offset as they go; this module
 * only says how the result is worded.
 *
 * One question is not always one number. A "Choose TWO letters" question is
 * printed as *Questions 23 and 24* and carries two marks — that is how the
 * real paper does it, and it is why a 40-mark test can be fewer than 40 rows.
 * `questionSpan` is that rule, and everything that walks the tree accumulates
 * spans rather than counting questions.
 */

/** How many of the numbers on the paper one question in a group takes.
 *
 *  Its group's `answers_per_question` for multiple choice, and one for
 *  everything else — a form gap is one gap, one number, one mark. Anything
 *  that doesn't say means one, which covers every group written before the
 *  setting existed. */
export function questionSpan(answersPerQuestion?: number | null): number {
  return Math.max(1, answersPerQuestion ?? 1);
}

/** How a group's run of questions is titled: "Questions 7–10", or
 *  "Question 7" for a run of one. `span` is how many NUMBERS the group
 *  covers, not how many questions it holds — the two differ the moment it
 *  asks for more than one answer. Empty for a group with nothing in it yet:
 *  there is no run to name, and "Questions 7–6" is worse than nothing. */
export function questionRangeLabel(offset: number, span: number): string {
  if (span <= 0) return "";
  const first = offset + 1;
  const last = offset + span;
  return first === last ? `Question ${first}` : `Questions ${first}–${last}`;
}

/** The numbers one question occupies, written out: "23", "23 and 24", or
 *  "23–25". Two are joined by "and" rather than a dash, which is how
 *  Cambridge prints a pair and how anyone reads one aloud. For prose — a
 *  warning that names the question, a heading above it. */
export function questionNumbers(start: number, span: number): string {
  if (span <= 1) return String(start);
  const last = start + span - 1;
  return span === 2 ? `${start} and ${last}` : `${start}–${last}`;
}

/** The same numbers in the margin beside a question: "23", "23–24". A dash
 *  throughout, because this one is read as a label rather than as a
 *  sentence, and "23 and 24." in a gutter costs half again the width to say
 *  the same thing. */
export function questionNumbersShort(start: number, span: number): string {
  if (span <= 1) return String(start);
  return `${start}–${start + span - 1}`;
}

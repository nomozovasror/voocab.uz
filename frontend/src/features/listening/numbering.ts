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
 */

/** How a group's run of questions is titled: "Questions 7–10", or
 *  "Question 7" for a group of one. Empty for a group with no questions yet —
 *  there is no run to name, and "Questions 7–6" is worse than nothing. */
export function questionRangeLabel(offset: number, count: number): string {
  if (count <= 0) return "";
  const first = offset + 1;
  const last = offset + count;
  return first === last ? `Question ${first}` : `Questions ${first}–${last}`;
}

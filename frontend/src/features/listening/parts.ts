import type { QuestionGroupType } from "@/features/listening/types";

/**
 * What each part of an IELTS Listening test asks, and what we can build of
 * it.
 *
 * The four parts are not interchangeable. Part 1 is a transactional
 * conversation and is a completion task almost every time. Part 4 is an
 * academic monologue, dominated by note and summary completion. Multiple
 * choice belongs mostly to the middle two, and map/plan labelling only ever
 * to Part 2. Offering every type everywhere would be offering authors a way
 * to write a test that isn't one.
 *
 * So this is editorial, not structural: the server stores any type under any
 * part, and nothing here is enforced there. It is the difference between a
 * tool that knows the exam and a tool that makes you know it.
 *
 * The lists below are what a part can be given TODAY — the intersection of
 * what the exam uses there and what is built. `missingTypeNote` names the
 * rest, so a short list reads as "not yet" rather than "not allowed".
 */

/** One name per type, so the header, the menu and the chooser can't drift
 *  into calling the same thing three things. */
export const QUESTION_TYPE_LABEL: Record<QuestionGroupType, string> = {
  form_completion: "Form completion",
  multiple_choice: "Multiple choice",
};

/** What each type is, for the moment of choosing between them. */
export const QUESTION_TYPE_BLURB: Record<QuestionGroupType, string> = {
  form_completion: "Gaps in a form the candidate fills in",
  multiple_choice: "Lettered options, one or several right",
};

// Listed with the part's dominant type first, since that is the order they
// are offered in and the one the author reaches for most.
const PART_TYPES: QuestionGroupType[][] = [
  // Part 1 — form completion almost every time; short answer (not built).
  // Never multiple choice.
  ["form_completion"],
  // Part 2 — map/plan labelling (not built), matching (not built), multiple
  // choice, note/sentence/table completion.
  ["multiple_choice", "form_completion"],
  // Part 3 — multiple choice most of all, matching (not built),
  // note/sentence/summary/table completion.
  ["multiple_choice", "form_completion"],
  // Part 4 — note/summary/sentence completion dominates, then multiple
  // choice; diagram labelling (not built).
  ["form_completion", "multiple_choice"],
];

/** Every type this part may be given, in the order they're offered. A part
 *  beyond the fourth — which the editor has no way to make — falls back to
 *  everything rather than to nothing. */
export function questionTypesForPart(orderIndex: number): QuestionGroupType[] {
  return PART_TYPES[orderIndex] ?? ["form_completion", "multiple_choice"];
}

//: What each part asks that we can't author yet. Every one of them is
//: missing something, so every one of them says so — a list of two choices
//: should read as "these are the ones built", not "these are the ones
//: allowed".
const MISSING_TYPES: string[] = [
  "short answer",
  "map/plan labelling and matching",
  "matching",
  "diagram labelling",
];

/** What this part characteristically asks that we can't author yet, phrased
 *  for the author. */
export function missingTypeNote(orderIndex: number): string | undefined {
  const missing = MISSING_TYPES[orderIndex];
  if (!missing) return undefined;
  const types = questionTypesForPart(orderIndex);
  const available = types
    .map((type) => QUESTION_TYPE_LABEL[type].toLowerCase())
    .join(" and ");
  return (
    `${missing} ${missing.includes(" and ") ? "aren't" : "isn't"} built yet — ` +
    `${available} ${types.length > 1 ? "are" : "is"} what's available here.`
  );
}

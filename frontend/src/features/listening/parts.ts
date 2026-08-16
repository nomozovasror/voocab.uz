import { ArrowLeftRight, ListChecks, Rows3 } from "lucide-react";
import type { LucideIcon } from "lucide-react";
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
  matching: "Matching",
};

/** What each type is, for the moment of choosing between them. */
export const QUESTION_TYPE_BLURB: Record<QuestionGroupType, string> = {
  form_completion: "Gaps in a form the candidate fills in",
  multiple_choice: "Lettered options, one or several right",
  matching: "One box of options, answering a list of items",
};

/** And one mark per type, for the same reason: a type is recognised by its
 *  icon in the chooser, in the opening sequence and on a settled part, and
 *  those have to be the same icon. */
export const QUESTION_TYPE_ICON: Record<QuestionGroupType, LucideIcon> = {
  form_completion: Rows3,
  multiple_choice: ListChecks,
  matching: ArrowLeftRight,
};

// Listed with the part's dominant type first, since that is the order they
// are offered in and the one the author reaches for most.
const PART_TYPES: QuestionGroupType[][] = [
  // Part 1 — form completion almost every time; short answer (not built).
  // Never multiple choice, never matching.
  ["form_completion"],
  // Part 2 — map/plan labelling (not built), matching, multiple choice,
  // note/sentence/table completion.
  ["multiple_choice", "matching", "form_completion"],
  // Part 3 — multiple choice most of all, then matching,
  // note/sentence/summary/table completion.
  ["multiple_choice", "matching", "form_completion"],
  // Part 4 — note/summary/sentence completion dominates, then multiple
  // choice; diagram labelling (not built). Matching is rare enough here that
  // offering it would be offering a way to write an unusual paper.
  ["form_completion", "multiple_choice"],
];

/** Every type this part may be given, in the order they're offered. A part
 *  beyond the fourth — which the editor has no way to make — falls back to
 *  everything rather than to nothing. */
export function questionTypesForPart(orderIndex: number): QuestionGroupType[] {
  return (
    PART_TYPES[orderIndex] ?? ["form_completion", "multiple_choice", "matching"]
  );
}

//: What each part asks that we can't author yet. Every one of them is
//: missing something, so every one of them says so — a list of choices should
//: read as "these are the ones built", not "these are the ones allowed".
//: Part 3 is the exception now that matching is here: everything the exam
//: characteristically asks there can be authored, so nothing is said.
const MISSING_TYPES: (string | null)[] = [
  "short answer",
  "map/plan labelling",
  null,
  "diagram labelling",
];

/** "a, b and c" — the last pair joined by "and" rather than a comma, because
 *  this is read as a sentence. */
function listed(names: string[]): string {
  if (names.length <= 2) return names.join(" and ");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/** What this part characteristically asks that we can't author yet, phrased
 *  for the author. Undefined where there is nothing missing — a note saying
 *  so would be a note about nothing. */
export function missingTypeNote(orderIndex: number): string | undefined {
  const missing = MISSING_TYPES[orderIndex];
  if (!missing) return undefined;
  const types = questionTypesForPart(orderIndex);
  const available = listed(
    types.map((type) => QUESTION_TYPE_LABEL[type].toLowerCase()),
  );
  return (
    `${missing} ${missing.includes(" and ") ? "aren't" : "isn't"} built yet — ` +
    `${available} ${types.length > 1 ? "are" : "is"} what's available here.`
  );
}

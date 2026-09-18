import type { QuestionGroupType } from "@/features/paper/types";

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
 * The names, blurbs and icons of the types themselves are shared with every
 * other paper and live in `@/features/paper/question-types`. What lives here
 * is only which of them belong where, which is the one thing that is
 * genuinely about Listening.
 */

// Listed with the part's dominant type first, since that is the order they
// are offered in and the one the author reaches for most.
const PART_TYPES: QuestionGroupType[][] = [
  // Part 1 — a transactional conversation: the form, the notes taken from it,
  // and the short answers that sometimes follow. Never multiple choice, never
  // matching.
  ["form_completion", "note_completion", "table_completion", "short_answer"],
  // Part 2 — a monologue about a place, so map/plan labelling first: it is
  // the one type this part has that no other does. Then matching, multiple
  // choice, and the completion tasks.
  [
    "map_labelling",
    "multiple_choice",
    "matching",
    "note_completion",
    "sentence_completion",
    "table_completion",
  ],
  // Part 3 — multiple choice most of all, then matching, then the completion
  // tasks a discussion lends itself to.
  [
    "multiple_choice",
    "matching",
    "sentence_completion",
    "note_completion",
    "summary_completion",
  ],
  // Part 4 — an academic monologue: note and summary completion dominate,
  // then sentence completion, the diagram a process lecture labels, and
  // multiple choice. Matching is rare enough here that offering it would be
  // offering a way to write an unusual paper.
  [
    "note_completion",
    "summary_completion",
    "sentence_completion",
    "table_completion",
    "flow_chart_completion",
    "diagram_labelling",
    "multiple_choice",
  ],
];

/** Every type this part may be given, in the order they're offered. A part
 *  beyond the fourth — which the editor has no way to make — falls back to
 *  everything rather than to nothing. */
export function questionTypesForPart(orderIndex: number): QuestionGroupType[] {
  return (
    PART_TYPES[orderIndex] ?? [
      "note_completion",
      "sentence_completion",
      "multiple_choice",
      "matching",
    ]
  );
}

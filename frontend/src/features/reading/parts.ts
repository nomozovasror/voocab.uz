import type { QuestionGroupType } from "@/features/paper/types";

/**
 * What each passage of an IELTS Reading test asks, and in what order to
 * offer it.
 *
 * Editorial, not structural — the server stores any type under any part, and
 * nothing here is enforced there. It is the difference between a tool that
 * knows the exam and a tool that makes you know it.
 *
 * The three passages are far less specialised than Listening's four parts,
 * where a map only ever appears in Part 2 and a form almost only in Part 1.
 * A reading passage can carry nearly anything, and the real pattern is about
 * DIFFICULTY rather than about task: Passage 1 is the most factual and leans
 * on true/false and completion, Passage 3 is argument and leans on the
 * writer's own views — yes/no/not given, which is the one type that only
 * belongs where there is an opinion to agree with.
 *
 * So every passage is offered most of the set, in the order that passage
 * reaches for them. What is genuinely absent is map labelling: there is no
 * map in a reading paper.
 */

const PASSAGE_TYPES: QuestionGroupType[][] = [
  // Passage 1 — descriptive and factual. The candidate's first encounter is
  // usually a set of statements to check against the text, then gaps.
  [
    "true_false_not_given",
    "note_completion",
    "sentence_completion",
    "table_completion",
    "matching_information",
    "short_answer",
    "multiple_choice",
    "summary_completion",
    "matching_features",
  ],
  // Passage 2 — longer, and the one that most often has lettered paragraphs,
  // so headings and information-matching lead.
  [
    "matching_headings",
    "matching_information",
    "summary_completion",
    "true_false_not_given",
    "sentence_completion",
    "matching_features",
    "multiple_choice",
    "matching_sentence_endings",
    "table_completion",
    "flow_chart_completion",
    "diagram_labelling",
  ],
  // Passage 3 — argument and opinion. Yes/No/Not Given belongs here and
  // essentially nowhere else: it asks whether a statement agrees with the
  // WRITER, which needs a writer with a view.
  [
    "yes_no_not_given",
    "multiple_choice",
    "matching_features",
    "matching_sentence_endings",
    "summary_completion",
    "matching_headings",
    "sentence_completion",
    "matching_information",
    "true_false_not_given",
  ],
];

/** Everything offered on a passage beyond the third — which the editor has no
 *  way to make, a reading paper having three. Falls back to the commonest
 *  handful rather than to nothing. */
const ANY_PASSAGE: QuestionGroupType[] = [
  "true_false_not_given",
  "matching_headings",
  "summary_completion",
  "sentence_completion",
  "multiple_choice",
  "matching_information",
];

export function questionTypesForPassage(
  orderIndex: number,
): QuestionGroupType[] {
  return PASSAGE_TYPES[orderIndex] ?? ANY_PASSAGE;
}

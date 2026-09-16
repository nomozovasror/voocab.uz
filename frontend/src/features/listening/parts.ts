import {
  AlignLeft,
  ArrowLeftRight,
  CircleQuestionMark,
  Cog,
  List,
  ListChecks,
  Map,
  Pilcrow,
  Rows3,
  Table,
  Workflow,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type {
  CompletionType,
  QuestionGroupType,
} from "@/features/listening/types";

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
 * The lists below were once an intersection — what the exam uses there, and
 * what was built — with a note beside them naming the types that weren't. Both
 * halves of that are gone: every type the exam uses is built, so a part's list
 * is simply what belongs in it.
 */

/** One name per type, so the header, the menu and the chooser can't drift
 *  into calling the same thing three things. */
export const QUESTION_TYPE_LABEL: Record<QuestionGroupType, string> = {
  form_completion: "Form completion",
  note_completion: "Note completion",
  sentence_completion: "Sentence completion",
  summary_completion: "Summary completion",
  short_answer: "Short answer",
  table_completion: "Table completion",
  flow_chart_completion: "Flow-chart completion",
  map_labelling: "Map labelling",
  diagram_labelling: "Diagram labelling",
  multiple_choice: "Multiple choice",
  matching: "Matching",
};

/** What each type is, for the moment of choosing between them. The six
 *  completion tasks are one document underneath, so what these say is what
 *  actually tells them apart: the shape of the sheet. */
export const QUESTION_TYPE_BLURB: Record<QuestionGroupType, string> = {
  form_completion: "A form with its labels down the side",
  note_completion: "Headed notes, in bullet points",
  sentence_completion: "Separate sentences, each with a gap",
  summary_completion: "A paragraph with gaps in it",
  short_answer: "Questions answered in a few words",
  table_completion: "A grid with gaps in its cells",
  flow_chart_completion: "A process, as boxes with arrows between them",
  map_labelling: "Places named on a map or plan",
  diagram_labelling: "Parts named on a drawing of a thing",
  multiple_choice: "Lettered options, one or several right",
  matching: "One box of options, answering a list of items",
};

/** The instruction line each task is printed under. Offered as the
 *  placeholder, so an author who types nothing still sees what belongs
 *  there — and one who types their own is not fighting a default. */
export const QUESTION_TYPE_RUBRIC: Record<CompletionType, string> = {
  form_completion: "Complete the form below.",
  note_completion: "Complete the notes below.",
  sentence_completion: "Complete the sentences below.",
  summary_completion: "Complete the summary below.",
  short_answer: "Answer the questions below.",
  table_completion: "Complete the table below.",
  flow_chart_completion: "Complete the flow chart below.",
  map_labelling: "Label the map below.",
  diagram_labelling: "Label the diagram below.",
};

/** The same eleven as a short noun, for a sentence.
 *
 *  "Next map" is an invitation; "Next Map labelling" reads like a filename,
 *  and "Next drill" names the machinery rather than the thing. Written out
 *  rather than sliced off the label, because the useful short form is not a
 *  prefix of the long one — "flow chart" out of "Flow-chart completion" has
 *  a hyphen in the wrong place. */
export const QUESTION_TYPE_SHORT: Record<QuestionGroupType, string> = {
  form_completion: "form",
  note_completion: "set of notes",
  sentence_completion: "set of sentences",
  summary_completion: "summary",
  short_answer: "set of questions",
  table_completion: "table",
  flow_chart_completion: "flow chart",
  map_labelling: "map",
  diagram_labelling: "diagram",
  multiple_choice: "set of choices",
  matching: "matching task",
};

/** And one mark per type, for the same reason: a type is recognised by its
 *  icon in the chooser, in the opening sequence and on a settled part, and
 *  those have to be the same icon. */
export const QUESTION_TYPE_ICON: Record<QuestionGroupType, LucideIcon> = {
  form_completion: Rows3,
  note_completion: List,
  sentence_completion: AlignLeft,
  // A paragraph mark, because that is the whole of what makes a summary
  // different from the sentences above it: it is one block of prose.
  summary_completion: Pilcrow,
  short_answer: CircleQuestionMark,
  table_completion: Table,
  flow_chart_completion: Workflow,
  map_labelling: Map,
  // A machine part rather than a picture frame: what a diagram task labels is
  // the thing drawn, and the frame around it is the one thing every one of
  // these types would have in common.
  diagram_labelling: Cog,
  multiple_choice: ListChecks,
  matching: ArrowLeftRight,
};

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

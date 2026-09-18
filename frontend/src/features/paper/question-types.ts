import {
  AlignLeft,
  ArrowLeftRight,
  CircleQuestionMark,
  Cog,
  List,
  ListChecks,
  Map,
  Pilcrow,
  Heading,
  Rows3,
  Scale,
  Table,
  Workflow,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type {
  CompletionType,
  FixedChoiceType,
  QuestionGroupType,
} from "@/features/paper/types";

/**
 * Every question type the app knows, named once.
 *
 * One label, one blurb, one short noun and one icon per type — so the
 * header, the menu and the chooser cannot drift into calling the same thing
 * three things, and so a type added here reaches every surface at once.
 *
 * WHICH types belong on which part of which paper is a different question,
 * and an editorial one: it lives beside each skill (`listening/parts.ts`,
 * `reading/parts.ts`), because a form belongs in Listening Part 1 and
 * matching headings belongs to a reading passage, and nothing here should
 * have to know that.
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
  matching_headings: "Matching headings",
  matching_information: "Matching information",
  matching_features: "Matching features",
  matching_sentence_endings: "Matching sentence endings",
  true_false_not_given: "True / False / Not Given",
  yes_no_not_given: "Yes / No / Not Given",
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
  matching_headings: "A list of headings, one per paragraph",
  matching_information: "Which paragraph says each thing",
  matching_features: "Statements matched to who or what they describe",
  matching_sentence_endings: "Sentence halves, joined back together",
  true_false_not_given: "Statements judged against the facts in the text",
  yes_no_not_given: "Statements judged against the writer's own views",
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
  matching_headings: "set of headings",
  matching_information: "set of statements",
  matching_features: "set of features",
  matching_sentence_endings: "set of sentences",
  true_false_not_given: "set of statements",
  yes_no_not_given: "set of statements",
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
  // The four Reading matching tasks are one task under four names, so they
  // share the mark that says so — except headings, which is the one whose
  // items are the paragraphs themselves.
  matching_headings: Heading,
  matching_information: ArrowLeftRight,
  matching_features: ArrowLeftRight,
  matching_sentence_endings: ArrowLeftRight,
  // A judgement rather than a choice: the three words are the same three
  // every time, so what the reader does is weigh a statement, not pick from
  // a list somebody wrote.
  true_false_not_given: Scale,
  yes_no_not_given: Scale,
};

/** The three words each fixed-choice task is answered in.
 *
 *  The mirror of ``FIXED_CHOICE_OPTIONS`` in
 *  ``backend/app/models/question_group.py``, and mirrored rather than fetched
 *  for the same reason the question types themselves are: this is the exam's
 *  vocabulary, not the platform's data. The server still sends them on the
 *  group for the take page, so what a candidate answers from always comes
 *  from the one place that also grades it; this table is for the EDITOR,
 *  which is drawing the choice before any group exists to send. */
export const FIXED_CHOICE_OPTIONS: Record<FixedChoiceType, string[]> = {
  true_false_not_given: ["TRUE", "FALSE", "NOT GIVEN"],
  yes_no_not_given: ["YES", "NO", "NOT GIVEN"],
};

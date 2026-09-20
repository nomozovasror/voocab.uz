import type { QuestionGroupType } from "@/features/paper/types";

/**
 * What to do with the task in front of you, for the task in front of you.
 *
 * A reading paper asks eight or nine different things and each has its own
 * trap, and the traps are what candidates lose marks to rather than
 * vocabulary: answering TRUE where the passage never said it, writing three
 * words where the rubric allows two, reading the headings before the
 * paragraph instead of after. None of that is on the page — the printed
 * rubric says what form the answer takes and nothing about how to arrive at
 * one.
 *
 * Three lines per type, and never more. This is a panel somebody opens
 * mid-paper with the clock running; a page of advice is a page they will
 * close unread, and the one sentence they needed will have been in it.
 *
 * - **do** — the move, in the imperative.
 * - **rule** — the thing that is marked wrong most often.
 * - **tip** — one piece of technique, specific to this task and no other.
 *
 * It changes with the group the reader is in, because advice about matching
 * headings while somebody is filling a summary is worse than no advice: they
 * asked the page a question and it answered a different one.
 */

export interface Help {
  do: string;
  rule: string;
  tip: string;
}

const COMPLETION: Help = {
  do: "Fill each gap with words taken straight from the passage.",
  rule: "Never more words than the instruction allows, and copy the spelling exactly — a word spelt wrong is marked wrong even where the meaning is right.",
  tip: "Read what is either side of the gap first and decide what KIND of word is missing: a number, a noun, a date. Then look for that in the passage rather than re-reading for meaning.",
};

const HELP: Partial<Record<QuestionGroupType, Help>> = {
  matching_headings: {
    do: "Give each paragraph the heading that covers the whole of it.",
    rule: "There are more headings than paragraphs, and every one of the extras is written to sound like a line you have just read.",
    tip: "Read the paragraph first, decide in your own words what it is about, and only then look at the list. Reading the headings first makes you hunt for them in the text, which is how the distractors catch people.",
  },
  matching_information: {
    do: "Find the paragraph that contains each piece of information.",
    rule: "A letter may be used more than once where the instruction says so — and where it does not, each paragraph is used once.",
    tip: "These are not in passage order, unlike almost everything else on the paper. Work from the statement: pick the one thing in it that is hardest to paraphrase — a name, a number, a place — and scan for that.",
  },
  matching_features: {
    do: "Match each statement to the person, study or thing in the box.",
    rule: "The box is not in the passage's order, and some of its entries are never used.",
    tip: "Underline every name in the passage before you start. The task is really about finding where each name is spoken about, and doing that once is faster than doing it per statement.",
  },
  matching_sentence_endings: {
    do: "Complete each sentence with one of the endings given.",
    rule: "The finished sentence has to be grammatical AND true to the passage. Half the wrong endings are true of the passage but do not fit the sentence.",
    tip: "Read the beginning and predict how it ends before looking at the list — then find the ending nearest your own.",
  },
  matching: {
    do: "Match each item to one of the options in the box.",
    rule: "Check whether the instruction allows an option to be used more than once; where it does not, each is used exactly once.",
    tip: "Do the ones you are sure of first. Every certain answer removes an option from the box and makes the rest easier.",
  },
  true_false_not_given: {
    do: "Decide whether each statement agrees with the INFORMATION in the passage.",
    rule: "NOT GIVEN means the passage does not say — it is not a way of saying you could not find it. FALSE means the passage says the opposite.",
    tip: "The hardest choice is between FALSE and NOT GIVEN. Ask: could I point at a line that CONTRADICTS this? If yes it is FALSE; if you are only failing to find support, it is NOT GIVEN.",
  },
  yes_no_not_given: {
    do: "Decide whether each statement agrees with the writer's VIEWS.",
    rule: "This is about what the writer thinks, not about what is true. A statement can be correct in the world and still be NO.",
    tip: "Look for the writer's own language — 'surprisingly', 'it is clear that', 'only'. Opinions live in those words, and that is where the answers are.",
  },
  multiple_choice: {
    do: "Choose the option the passage supports.",
    rule: "Three of the four are written from the passage's own words. The right one is usually the one that says it differently.",
    tip: "Find the place in the passage first, read it, answer in your head — then go to the options. Reading the options first makes all four look plausible.",
  },
};

/** The guidance for a group, or the completion family's where the type is
 *  one of its nine names. */
export function helpFor(type: QuestionGroupType | null | undefined): Help | null {
  if (!type) return null;
  return HELP[type] ?? COMPLETION;
}

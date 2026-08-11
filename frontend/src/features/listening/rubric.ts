import type { AnswerRubric } from "@/features/listening/types";

/**
 * The rubric printed above a completion task.
 *
 * IELTS uses a small closed set of these. Two things vary — how many words are
 * allowed, and whether a number counts on its own — and they don't combine
 * into anything an author should be typing by hand, so they're offered as
 * choices and written out from one table here. The editor and the take page
 * both read it, which is what keeps the author's preview honest.
 */
export const ANSWER_RUBRICS: {
  value: AnswerRubric;
  /** What the candidate reads. */
  sentence: string;
  /** The short form the author picks from. */
  label: string;
  /** Kept in sync with the old numeric field. */
  words: number;
}[] = [
  {
    value: "one_word",
    label: "one word only",
    sentence: "Write ONE WORD ONLY for each answer.",
    words: 1,
  },
  {
    value: "one_word_number",
    label: "one word and/or a number",
    sentence: "Write ONE WORD AND/OR A NUMBER for each answer.",
    words: 1,
  },
  {
    value: "two_words",
    label: "up to two words",
    sentence: "Write NO MORE THAN TWO WORDS for each answer.",
    words: 2,
  },
  {
    value: "two_words_number",
    label: "up to two words and/or a number",
    sentence: "Write NO MORE THAN TWO WORDS AND/OR A NUMBER for each answer.",
    words: 2,
  },
  {
    value: "three_words",
    label: "up to three words",
    sentence: "Write NO MORE THAN THREE WORDS for each answer.",
    words: 3,
  },
  {
    value: "three_words_number",
    label: "up to three words and/or a number",
    sentence: "Write NO MORE THAN THREE WORDS AND/OR A NUMBER for each answer.",
    words: 3,
  },
];

export function rubricSentence(
  rubric: AnswerRubric | null | undefined,
  wordLimit: number | null,
): string | null {
  const match = ANSWER_RUBRICS.find((r) => r.value === rubric);
  if (match) return match.sentence;
  // Older groups stored only a number. Say what that meant rather than
  // dropping the line entirely.
  if (wordLimit != null) {
    return `Write no more than ${wordLimit} ${wordLimit === 1 ? "word" : "words"} for each answer.`;
  }
  return null;
}

import { docGaps, type DocBlock } from "@/features/listening/form-syntax";
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


/** A token that is only digits and the punctuation that goes with them — a
 *  date, a price, a room number. The rubric counts these separately from
 *  words, which is what "AND/OR A NUMBER" means. */
function isNumeric(token: string): boolean {
  return /\d/.test(token) && !/[a-z]/i.test(token);
}

/**
 * The rubric the answers themselves imply: the longest answer decides how
 * many words are allowed, and any digit anywhere decides whether a number is
 * allowed on top of them.
 *
 * Offered as the default, never forced. The rubric is a limit on what the
 * candidate may write, not a description of the answer key — a real paper
 * often says "NO MORE THAN TWO WORDS" where every answer happens to be one —
 * so an author reproducing that paper has to be able to say so.
 */
export function deriveRubric(doc: DocBlock[]): AnswerRubric | null {
  const answers = docGaps(doc)
    .flatMap((gap) => gap.answers)
    .map((a) => a.trim())
    .filter(Boolean);
  if (answers.length === 0) return null;

  let words = 1;
  let hasNumber = false;

  for (const answer of answers) {
    const tokens = answer.split(/\s+/).filter(Boolean);
    const numeric = tokens.filter(isNumeric);
    if (numeric.length > 0) hasNumber = true;
    // Numbers don't count against the word allowance — that is the whole
    // point of the "and/or a number" wording.
    words = Math.max(words, Math.min(3, tokens.length - numeric.length || 1));
  }

  const key = ["", "one_word", "two_words", "three_words"][words];
  return (hasNumber ? `${key}_number` : key) as AnswerRubric;
}

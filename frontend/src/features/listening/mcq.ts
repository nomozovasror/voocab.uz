import { newId } from "@/features/listening/form-syntax";
import { questionNumbers } from "@/features/listening/numbering";
import type {
  ChoiceQuestionIn,
  ListeningQuestion,
} from "@/features/listening/types";

/**
 * The multiple-choice document: what the builder edits, and how it becomes
 * what the API stores.
 *
 * Unlike a form, there is no shared resource here — no template, no layout to
 * write down. A multiple-choice group is a list of self-contained questions,
 * so this module is smaller than its form-completion counterpart and does
 * only three things: hold the editable shape, convert it in both directions,
 * and say what is still missing.
 *
 * Two decisions run through all of it:
 *
 * **Options are identified by id, letters are a view.** The letter beside an
 * option is its position, so it changes whenever one is inserted or deleted
 * above it. Anything remembering which option is right by letter — including
 * the answer key while it is being edited — would silently reattach to the
 * wrong option the moment the list moved. Letters appear only at the edges:
 * on the page, and in what gets sent.
 *
 * **How many answers belongs to the group, not the question.** The
 * instruction line above the set is what states it — "Choose the correct
 * letter, A, B or C" against "Choose TWO letters, A–E" — and that line is the
 * group's. Asked per question, a group could be built whose instructions and
 * questions disagreed. It is a count rather than a "several" flag for the
 * same reason: "several" doesn't tell the candidate what to do, and it let
 * one question ask for two while the next asked for three under one heading.
 * So the count lives on the group state and is passed in wherever a question
 * has to be judged against it.
 */

//: The option labels, in order. Twenty-six is where single letters run out;
//: a real question has three or five options.
const OPTION_LETTERS = "abcdefghijklmnopqrstuvwxyz";
export const MAX_OPTIONS = OPTION_LETTERS.length;

export function optionLetter(index: number): string {
  return OPTION_LETTERS[index] ?? "?";
}

// ── The editable document ────────────────────────────────────────────────

export interface ChoiceOption {
  id: string;
  text: string;
}

export interface ChoiceQuestion {
  id: string;
  prompt: string;
  options: ChoiceOption[];
  /** Which options are right, by option id. How many there should be is the
   *  group's `answersPerQuestion`, not anything held here. */
  correct: string[];
}

/** What a group asks for when it hasn't said. One is the ordinary
 *  single-answer question, and every group written before this was a group
 *  setting means it. */
export const DEFAULT_ANSWERS_PER_QUESTION = 1;

/** The counts worth offering. IELTS asks for two, occasionally three; beyond
 *  that it stops being a multiple-choice question. */
export const ANSWER_COUNTS = [1, 2, 3] as const;

/** How many options a new question starts with. Three is the common IELTS
 *  case, and starting with the shape of the answer is quicker to fill in
 *  than starting with nothing and pressing "add" three times. */
const STARTING_OPTIONS = 3;

export function newOption(text = ""): ChoiceOption {
  return { id: newId(), text };
}

export function newChoiceQuestion(): ChoiceQuestion {
  return {
    id: newId(),
    prompt: "",
    options: Array.from({ length: STARTING_OPTIONS }, () => newOption()),
    correct: [],
  };
}

/** A brand-new group: one empty question, ready to type into. */
export function newChoiceQuestions(): ChoiceQuestion[] {
  return [newChoiceQuestion()];
}

// ── Editing ──────────────────────────────────────────────────────────────

/** Mark or unmark an option, against a group that asks for `wanted` answers.
 *
 *  Clicking a marked option always clears it — the only way back out of a
 *  wrong click. Clicking an unmarked one when the question is already full
 *  drops the oldest mark to make room, rather than refusing: in a group
 *  asking for one that is the familiar radio-button behaviour, and in a
 *  "choose two" it means correcting the second of two answers is one click
 *  rather than two. */
export function toggleCorrect(
  question: ChoiceQuestion,
  optionId: string,
  wanted = DEFAULT_ANSWERS_PER_QUESTION,
): ChoiceQuestion {
  if (question.correct.includes(optionId)) {
    return {
      ...question,
      correct: question.correct.filter((id) => id !== optionId),
    };
  }
  const keep = question.correct.slice(Math.max(0, question.correct.length - wanted + 1));
  const next = new Set([...keep, optionId]);
  return {
    ...question,
    // Kept in the options' own order, so "answers: a, c" reads the way the
    // question does however they were clicked.
    correct: question.options.filter((o) => next.has(o.id)).map((o) => o.id),
  };
}

/** Trim every question's key down to what the group now asks for. Called when
 *  the count is lowered: a "choose two" turned back into a single-answer
 *  group would otherwise keep two marks that can never both be submitted, and
 *  the server refuses the payload outright. The earliest marks are kept —
 *  they are the ones the author was surest of. */
export function fitAnswerKeys(
  questions: ChoiceQuestion[],
  wanted: number,
): ChoiceQuestion[] {
  if (questions.every((q) => q.correct.length <= wanted)) return questions;
  return questions.map((q) =>
    q.correct.length <= wanted ? q : { ...q, correct: q.correct.slice(0, wanted) },
  );
}

/** Add an option. The caller may pass one it has already made, which is how
 *  the builder knows what to put the caret in: the edit itself runs against
 *  whatever the latest question is and reports nothing back. */
export function addOption(
  question: ChoiceQuestion,
  option: ChoiceOption = newOption(),
): ChoiceQuestion {
  if (question.options.length >= MAX_OPTIONS) return question;
  return { ...question, options: [...question.options, option] };
}

/** Remove an option, and with it any claim that it was the answer. The
 *  letters after it move up on their own — they are positions. */
export function removeOption(
  question: ChoiceQuestion,
  optionId: string,
): ChoiceQuestion {
  return {
    ...question,
    options: question.options.filter((o) => o.id !== optionId),
    correct: question.correct.filter((id) => id !== optionId),
  };
}

export function patchOption(
  question: ChoiceQuestion,
  optionId: string,
  text: string,
): ChoiceQuestion {
  return {
    ...question,
    options: question.options.map((o) =>
      o.id === optionId ? { ...o, text } : o,
    ),
  };
}

// ── Document <-> API ─────────────────────────────────────────────────────

/** What the API stores. Numbering is positional, so it is always contiguous
 *  from 1 — the same rule the form builder follows, and the same rule the
 *  server checks. */
export function choiceQuestionsToApi(
  questions: ChoiceQuestion[],
): ChoiceQuestionIn[] {
  return questions.map((question, index) => {
    const letterOf = new Map(
      question.options.map((option, i) => [option.id, optionLetter(i)]),
    );
    return {
      number: index + 1,
      prompt: question.prompt.trim(),
      options: question.options.map((o) => o.text),
      correct_answers: question.options
        .filter((o) => question.correct.includes(o.id))
        .map((o) => letterOf.get(o.id) as string),
    };
  });
}

/** The inverse, for reopening a saved group. Letters are resolved back to the
 *  options they stand for by position — which is what they were written from,
 *  and why the two are only ever saved together. */
export function choiceQuestionsFromApi(
  questions: ListeningQuestion[],
): ChoiceQuestion[] {
  const restored = questions
    .slice()
    .sort((a, b) => a.number - b.number)
    .map((question) => {
      const options = (question.options ?? []).map((text) => newOption(text));
      const key = new Set(
        (question.correct_answers ?? []).map((letter) =>
          letter.trim().toLowerCase(),
        ),
      );
      return {
        id: newId(),
        prompt: question.prompt ?? "",
        options,
        correct: options
          .filter((_option, index) => key.has(optionLetter(index)))
          .map((option) => option.id),
      };
    });
  return restored.length > 0 ? restored : newChoiceQuestions();
}

// ── Validation ───────────────────────────────────────────────────────────

/** Something a question still needs before it can be published, attached to
 *  the question it is about so the block itself can be marked rather than
 *  only listed underneath. */
export interface ChoiceIssue {
  questionId: string;
  /** The first of the numbers this question occupies, as the candidate will
   *  read it. A "choose two" takes two of them. */
  number: number;
  /** Which half of the work is missing — writing the question, or deciding
   *  the answer. The publish checklist counts them separately, since they
   *  are two different things to go and do. */
  kind: "prompt" | "options" | "answer";
  message: string;
}

/** What is missing, phrased for the author. `offset` is how many questions
 *  come before this group in the material, so the numbers quoted are the ones
 *  on the page.
 *
 * The order matters: the first thing wrong with a question is the first thing
 * to fix, and only that one is reported per question — a block listing four
 * complaints about one unfinished question reads as a much bigger problem
 * than it is. */
export function choiceIssues(
  questions: ChoiceQuestion[],
  offset = 0,
  wanted = DEFAULT_ANSWERS_PER_QUESTION,
): ChoiceIssue[] {
  const issues: ChoiceIssue[] = [];

  questions.forEach((question, index) => {
    const number = offset + index * wanted + 1;
    // "Question 23", or "Questions 23 and 24" — named the way it is printed,
    // so the author can find it by the number beside it on the page.
    const named =
      wanted > 1
        ? `Questions ${questionNumbers(number, wanted)}`
        : `Question ${number}`;
    // "Questions 23 and 24 have…", "Question 23 has…". The subject is the
    // numbers the question occupies, so the verb follows `named` rather than
    // the count of whatever is being complained about.
    const has = wanted > 1 ? "have" : "has";
    const needs = wanted > 1 ? "need" : "needs";
    const add = (kind: ChoiceIssue["kind"], message: string) =>
      issues.push({ questionId: question.id, number, kind, message });

    if (!question.prompt.trim()) {
      add("prompt", `${named} ${has} no question text yet.`);
      return;
    }
    // Always more options than answers: "choose two of these two" is not a
    // question, and the same rule the server publishes by.
    const minimum = Math.max(2, wanted + 1);
    if (question.options.length < minimum) {
      add("options", `${named} ${needs} at least ${minimum} options.`);
      return;
    }
    if (question.options.some((option) => !option.text.trim())) {
      add("options", `${named} ${has} an option with nothing in it.`);
      return;
    }
    if (question.correct.length !== wanted) {
      add(
        "answer",
        wanted === 1
          ? `${named} has no correct answer marked.`
          : `${named} ${has} ${question.correct.length} of ${wanted} ` +
            "answers marked.",
      );
    }
  });

  return issues;
}

/** Whether the author has put anything of their own in yet. An untouched
 *  group is still worth keeping — they added it on purpose — but nothing here
 *  should count as work in the publish checklist. */
export function isChoiceGroupEmpty(questions: ChoiceQuestion[]): boolean {
  return questions.every(
    (question) =>
      !question.prompt.trim() &&
      question.correct.length === 0 &&
      question.options.every((option) => !option.text.trim()),
  );
}

/** The answer as it reads, for the line under a question.
 *
 *  Where the group asks for more than one, an unfinished key says how far
 *  off it is rather than what it has so far: "1 of 2 marked" is the thing
 *  the author needs to act on, and "answer: a" beside a question that wants
 *  two reads as finished. Once it is finished, the letters are what matter
 *  again. Both live on this one line — the count used to have a row of its
 *  own above the options, which said the same thing twice in two places. */
export function answerSummary(
  question: ChoiceQuestion,
  wanted = DEFAULT_ANSWERS_PER_QUESTION,
): string {
  const letters = question.options
    .map((option, index) => (question.correct.includes(option.id) ? optionLetter(index) : null))
    .filter((letter): letter is string => letter !== null);
  if (letters.length !== wanted) {
    return wanted === 1
      ? "no answer marked"
      : `${letters.length} of ${wanted} marked`;
  }
  return letters.length === 1
    ? `answer: ${letters[0]}`
    : `answers: ${letters.join(", ")}`;
}

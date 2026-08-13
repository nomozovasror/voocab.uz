import { newId } from "@/features/listening/form-syntax";
import type {
  ChoiceMode,
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
 * **`mode` is stored, not counted.** "One answer" and "several answers" are
 * the author's intent, and an author who chose "several" and has marked only
 * the first of them has an unfinished question. Deriving the mode from how
 * many answers are marked would quietly turn that into a finished
 * single-answer one, on the next reload, with no way to tell.
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
  /** Which options are right, by option id. */
  correct: string[];
  mode: ChoiceMode;
}

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
    mode: "one",
  };
}

/** A brand-new group: one empty question, ready to type into. */
export function newChoiceQuestions(): ChoiceQuestion[] {
  return [newChoiceQuestion()];
}

// ── Editing ──────────────────────────────────────────────────────────────

/** Mark or unmark an option. In single-answer mode picking another option
 *  replaces the answer rather than adding to it, and picking the marked one
 *  again clears it — which is the only way back out of a wrong click. */
export function toggleCorrect(
  question: ChoiceQuestion,
  optionId: string,
): ChoiceQuestion {
  const marked = question.correct.includes(optionId);
  if (question.mode === "one") {
    return { ...question, correct: marked ? [] : [optionId] };
  }
  return {
    ...question,
    correct: marked
      ? question.correct.filter((id) => id !== optionId)
      : // Kept in the options' own order, so "answers: a, c" reads the way
        // the question does however they were clicked.
        question.options
          .filter((o) => o.id === optionId || question.correct.includes(o.id))
          .map((o) => o.id),
  };
}

/** Switch a question between one answer and several. Going back to one keeps
 *  the first marked option rather than clearing the lot: the author has just
 *  said the question has a single answer, and the first one they marked is
 *  the best guess at which. */
export function setChoiceMode(
  question: ChoiceQuestion,
  mode: ChoiceMode,
): ChoiceQuestion {
  if (mode === question.mode) return question;
  const correct =
    mode === "one" ? question.correct.slice(0, 1) : question.correct;
  return { ...question, mode, correct };
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
      mode: question.mode,
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
        mode: question.mode ?? "one",
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
  /** The number as the candidate will read it. */
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
): ChoiceIssue[] {
  const issues: ChoiceIssue[] = [];

  questions.forEach((question, index) => {
    const number = offset + index + 1;
    const add = (kind: ChoiceIssue["kind"], message: string) =>
      issues.push({ questionId: question.id, number, kind, message });

    if (!question.prompt.trim()) {
      add("prompt", `Question ${number} has no question text yet.`);
      return;
    }
    if (question.options.length < 2) {
      add("options", `Question ${number} needs at least two options.`);
      return;
    }
    if (question.options.some((option) => !option.text.trim())) {
      add("options", `Question ${number} has an option with nothing in it.`);
      return;
    }
    if (question.correct.length === 0) {
      add("answer", `Question ${number} has no correct answer marked.`);
      return;
    }
    if (question.mode === "multiple" && question.correct.length < 2) {
      add(
        "answer",
        `Question ${number} takes several answers but only one is marked — ` +
          "mark another, or set it back to one answer.",
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

/** The answer as it reads, for the line under a question. */
export function answerSummary(question: ChoiceQuestion): string {
  const letters = question.options
    .map((option, index) => (question.correct.includes(option.id) ? optionLetter(index) : null))
    .filter((letter): letter is string => letter !== null);
  if (letters.length === 0) return "no answer marked";
  return letters.length === 1
    ? `answer: ${letters[0]}`
    : `answers: ${letters.join(", ")}`;
}

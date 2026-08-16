import { newId } from "@/features/listening/form-syntax";
import type {
  ListeningQuestion,
  ListeningQuestionGroup,
  MatchingQuestionIn,
} from "@/features/listening/types";

/**
 * The matching document: what the builder edits, and how it becomes what the
 * API stores.
 *
 * A matching group is one box of lettered options and a list of items
 * answered from it — *A a holiday cottage, B a hotel, C a campsite*, and
 * under it the places the speaker talks about. That shape is the whole of
 * what makes this its own type rather than multiple choice with fewer words.
 *
 * Three decisions run through all of it:
 *
 * **The box belongs to the group.** The paper prints it once above the whole
 * set, and every item points at the same five lines. Held per item, as
 * multiple choice holds its options, the same box would be stored once per
 * question and could be edited into five different boxes under one heading.
 *
 * **Options are identified by id, letters are a view.** The letter beside an
 * option is its position, so it moves the moment one is inserted or deleted
 * above it. An answer remembering "c" would silently reattach to whatever
 * ended up third. Letters appear only at the edges: on the page, and in what
 * gets sent.
 *
 * **Where the answer is said belongs to the item, not to the option.** One
 * item is one answer at one moment — the form's shape, not multiple choice's.
 * An option answering three items is not three copies of one moment; it is
 * three items each said in their own place.
 */

//: The option labels, in order. The same alphabet the server letters by, and
//: the same one mcq.ts uses — a matching box rarely runs past H.
const OPTION_LETTERS = "abcdefghijklmnopqrstuvwxyz";
export const MAX_MATCH_OPTIONS = OPTION_LETTERS.length;

export function matchLetter(index: number): string {
  return OPTION_LETTERS[index] ?? "?";
}

// ── The editable document ────────────────────────────────────────────────

/** One line of the box the whole group is answered from. */
export interface MatchOption {
  id: string;
  text: string;
}

/** One thing to be matched: a place, a person, a year. */
export interface MatchItem {
  id: string;
  prompt: string;
  /** The option this is matched to, by option ID — never by letter, which is
   *  only where the option currently sits. Null until the author says. */
  answer: string | null;
  /** Where in the recording this item is answered.
   *
   *  Kept when the answer is cleared rather than cleared with it: the moment
   *  is about this item — "here is where the speaker talks about Trelawney" —
   *  and stays true whichever option turns out to be right. An author
   *  changing their mind should not have to find it again. */
  replayStartMs: number | null;
  replayEndMs: number | null;
}

/** How many options a new box starts with. Three is the smallest number that
 *  reads as a box rather than as a pair, and matches the commonest Part 3
 *  set. */
const STARTING_OPTIONS = 3;

/** And how many items. Two, because one item is not a matching task and
 *  showing a list of one invites the author to write one. */
const STARTING_ITEMS = 2;

export function newMatchOption(text = ""): MatchOption {
  return { id: newId(), text };
}

export function newMatchItem(): MatchItem {
  return {
    id: newId(),
    prompt: "",
    answer: null,
    replayStartMs: null,
    replayEndMs: null,
  };
}

export function newMatchOptions(): MatchOption[] {
  return Array.from({ length: STARTING_OPTIONS }, () => newMatchOption());
}

export function newMatchItems(): MatchItem[] {
  return Array.from({ length: STARTING_ITEMS }, () => newMatchItem());
}

// ── Editing ──────────────────────────────────────────────────────────────

/** Match an item to an option, or unmatch it.
 *
 *  Pressing the letter an item already has takes it back — the only way out
 *  of a wrong press.
 *
 *  Where a letter may only answer one item, pressing one that another item
 *  holds MOVES it: the letter leaves the item that had it and arrives here.
 *  That is what the gesture means on paper — there is one A and it goes in
 *  one box — and it is the alternative to refusing the press, which would
 *  leave the author to go and find the other item first. The one it leaves
 *  keeps everything else it had, including where its answer is said: the
 *  moment is about the item, not about the letter. */
export function matchTo(
  items: MatchItem[],
  itemId: string,
  optionId: string,
  allowReuse: boolean,
): MatchItem[] {
  const item = items.find((i) => i.id === itemId);
  if (!item) return items;
  const next = item.answer === optionId ? null : optionId;
  return items.map((current) => {
    if (current.id === itemId) return { ...current, answer: next };
    if (allowReuse || next === null || current.answer !== next) return current;
    return { ...current, answer: null };
  });
}

/** Where an item's answer is said. Set by the same press that chooses the
 *  letter — see the builder — so this is only ever called alongside
 *  `matchTo`. */
export function markItem(
  items: MatchItem[],
  itemId: string,
  range: { startMs: number; endMs: number },
): MatchItem[] {
  return items.map((item) =>
    item.id === itemId
      ? { ...item, replayStartMs: range.startMs, replayEndMs: range.endMs }
      : item,
  );
}

export function patchItem(
  items: MatchItem[],
  itemId: string,
  edit: (item: MatchItem) => MatchItem,
): MatchItem[] {
  return items.map((item) => (item.id === itemId ? edit(item) : item));
}

/** Drop an option, and with it every answer that pointed at it. The letters
 *  after it move up on their own — they are positions.
 *
 *  Both halves come back together because they have to change together: an
 *  answer naming an option that no longer exists is a payload the server
 *  refuses outright, so the group would stop saving from here on. */
export function removeMatchOption(
  options: MatchOption[],
  items: MatchItem[],
  optionId: string,
): { options: MatchOption[]; items: MatchItem[] } {
  return {
    options: options.filter((option) => option.id !== optionId),
    items: items.map((item) =>
      item.answer === optionId ? { ...item, answer: null } : item,
    ),
  };
}

/** Every letter that is spoken for, by option id — so the builder can show
 *  which of the box is already used up. Only meaningful where a letter
 *  answers one item; with reuse allowed nothing is ever spent. */
export function takenOptions(items: MatchItem[]): Set<string> {
  return new Set(
    items
      .map((item) => item.answer)
      .filter((answer): answer is string => answer !== null),
  );
}

// ── Document <-> API ─────────────────────────────────────────────────────

/** What the API stores. Numbering is positional, so it is always contiguous
 *  from 1 — the same rule the other two builders follow, and the same rule
 *  the server checks. */
export function matchingToApi(
  options: MatchOption[],
  items: MatchItem[],
): MatchingQuestionIn[] {
  const letterOf = new Map(
    options.map((option, index) => [option.id, matchLetter(index)]),
  );
  return items.map((item, index) => {
    const letter = item.answer ? letterOf.get(item.answer) : undefined;
    return {
      number: index + 1,
      prompt: item.prompt.trim(),
      // An answer pointing at an option that has since gone is simply no
      // answer. It cannot normally happen — `removeMatchOption` clears them
      // — but sending a letter the box hasn't got fails the whole save, and
      // a group that has stopped saving is a much worse outcome than an
      // answer the author has to set again.
      correct_answers: letter ? [letter] : [],
      replay_start_ms: item.replayStartMs,
      replay_end_ms: item.replayEndMs,
    };
  });
}

export function matchingOptionsToApi(options: MatchOption[]): string[] {
  return options.map((option) => option.text);
}

/** The inverse, for reopening a saved group. Letters are resolved back to
 *  the options they stand for by position — which is what they were written
 *  from, and why the box and the answers are only ever saved together. */
export function matchingFromApi(group: ListeningQuestionGroup): {
  options: MatchOption[];
  items: MatchItem[];
  allowReuse: boolean;
} {
  const options = (group.config.options ?? []).map((text) =>
    newMatchOption(text),
  );
  const byLetter = new Map(
    options.map((option, index) => [matchLetter(index), option.id]),
  );
  const items = group.questions
    .slice()
    .sort((a: ListeningQuestion, b: ListeningQuestion) => a.number - b.number)
    .map((question: ListeningQuestion) => {
      const letter = (question.correct_answers ?? [])[0]?.trim().toLowerCase();
      return {
        ...newMatchItem(),
        prompt: question.prompt ?? "",
        answer: (letter && byLetter.get(letter)) || null,
        replayStartMs: question.replay_start_ms ?? null,
        replayEndMs: question.replay_end_ms ?? null,
      };
    });
  return {
    options: options.length > 0 ? options : newMatchOptions(),
    items: items.length > 0 ? items : newMatchItems(),
    allowReuse: group.config.allow_reuse ?? false,
  };
}

// ── Validation ───────────────────────────────────────────────────────────

/** Something the group still needs before it can be published. */
export interface MatchingIssue {
  /** The item it is about, or null where it is about the box — which belongs
   *  to the group, so its problems are the group's and are said once rather
   *  than on every row. */
  itemId: string | null;
  /** The number this item carries on the page. Null for the box, which
   *  carries none. */
  number: number | null;
  kind: "options" | "prompt" | "answer" | "link";
  /** Named and complete: "Question 14 has no answer." For anywhere the item
   *  isn't in front of the reader — the publish refusal, a count in the
   *  checklist. */
  message: string;
  /** The same thing said on the item itself, where naming it would be
   *  telling the author which row they are looking at. */
  detail: string;
  /** Whether the row already shows this without being told. An empty field
   *  is an empty field; an unlit row of letters is an item with no answer.
   *  What is not self-evident is a rule about the box as a whole. */
  selfEvident: boolean;
}

/** What is missing, phrased for the author. `offset` is how many questions
 *  come before this group in the material, so the numbers quoted are the ones
 *  on the page.
 *
 *  The box is checked first and only once — with nothing to match to, every
 *  item is unanswerable and reporting each of them would be reporting one
 *  problem eight times. Past that, one complaint per item: the first thing
 *  wrong with it is the first thing to fix. */
export function matchingIssues(
  options: MatchOption[],
  items: MatchItem[],
  offset = 0,
  allowReuse = false,
): MatchingIssue[] {
  const issues: MatchingIssue[] = [];
  const box = (kind: MatchingIssue["kind"], said: string, selfEvident = false) =>
    issues.push({
      itemId: null,
      number: null,
      kind,
      message: said,
      detail: said,
      selfEvident,
    });

  if (options.length < 2) {
    box("options", "There have to be at least two options to match from.");
  } else if (options.some((option) => !option.text.trim())) {
    box("options", "An option to match from has nothing in it.", true);
  } else if (!allowReuse && options.length < items.length) {
    // Without reuse each option answers one item, so a box shorter than the
    // list can never be completed however long the author works at it. With
    // reuse it is ordinary: three options and eight items is a common set.
    box(
      "options",
      `${items.length} questions and only ${options.length} options to match ` +
        "them to — add more options, or allow a letter to be used more than once.",
    );
  }
  if (issues.length > 0) return issues;

  items.forEach((item, index) => {
    const number = offset + index + 1;
    const add = (
      kind: MatchingIssue["kind"],
      said: string,
      detail: string,
      selfEvident = true,
    ) =>
      issues.push({
        itemId: item.id,
        number,
        kind,
        detail,
        selfEvident,
        message: `Question ${number} ${said}`,
      });

    if (!item.prompt.trim()) {
      add("prompt", "has nothing to match yet.", "Nothing to match yet.");
      return;
    }
    if (!item.answer) {
      add("answer", "has no answer.", "No answer chosen.");
    }
  });

  return issues;
}

/** What has to be true to publish, over and above being finished: every item
 *  must also be linked to the moment it is answered.
 *
 *  Kept apart from `matchingIssues` for the same reason the other two
 *  builders keep theirs apart — an author shouldn't be nagged about marking
 *  the audio before they have written the question. */
export function matchingPublishIssues(
  options: MatchOption[],
  items: MatchItem[],
  offset = 0,
  allowReuse = false,
): MatchingIssue[] {
  const issues = matchingIssues(options, items, offset, allowReuse);
  if (issues.length > 0) return issues;

  return items.flatMap((item, index) => {
    if (item.replayStartMs != null) return [];
    const number = offset + index + 1;
    return [
      {
        itemId: item.id,
        number,
        kind: "link" as const,
        detail: "Not linked to the audio yet.",
        selfEvident: true,
        message: `Question ${number} isn't linked to the audio yet.`,
      },
    ];
  });
}

/** Every item the author has marked, in the shape the transcript pane
 *  highlights from. What the mark is checked against is the item's own words
 *  — the place or the name — rather than the option's: an option like "a
 *  hotel" answers three items and would light up all three. */
export function matchingMarks(
  items: MatchItem[],
): { startMs: number; endMs: number; answers: string[] }[] {
  return items.flatMap((item) =>
    item.replayStartMs != null && item.replayEndMs != null && item.prompt.trim()
      ? [
          {
            startMs: item.replayStartMs,
            endMs: item.replayEndMs,
            answers: [item.prompt.trim()],
          },
        ]
      : [],
  );
}

/** Whether the author has put anything of their own in yet. An untouched
 *  group is still worth keeping — they added it on purpose — but nothing here
 *  should count as work in the publish checklist. */
export function isMatchingGroupEmpty(
  options: MatchOption[],
  items: MatchItem[],
): boolean {
  return (
    options.every((option) => !option.text.trim()) &&
    items.every((item) => !item.prompt.trim() && item.answer === null)
  );
}

/** How far through the group is, for the line under the box: "3 of 5
 *  matched". The count the author acts on, in the one place both numbers are
 *  known. */
export function matchedSummary(items: MatchItem[]): string {
  const matched = items.filter((item) => item.answer !== null).length;
  return `${matched} of ${items.length} matched`;
}

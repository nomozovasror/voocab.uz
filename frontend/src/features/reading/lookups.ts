/**
 * The dictionary budget: three words a passage, and which three they were.
 *
 * A reader who can look anything up is reading with a dictionary, and the
 * exam does not have one — a passage worked through that way measures
 * comprehension-with-help, which is not the skill being practised and not
 * the one being scored. But a reader who can look up NOTHING stalls on a
 * word and stops, and stalling teaches nothing either.
 *
 * Three is the compromise, and the number is the feature: it makes the
 * lookup a decision. Somebody with three left spends them on the words the
 * questions turn on rather than on the first unfamiliar noun in paragraph A.
 *
 * ## What counts
 *
 * Unique words, not openings. Looking the same word up again is free — the
 * budget is there to make somebody CHOOSE which words matter, and charging
 * twice for one choice would instead teach them not to check their memory.
 *
 * Sitting the paper again resets the count, but the words already opened
 * stay opened: a second attempt is a fresh three, and a word this reader has
 * already been told the meaning of is not a lookup any more.
 *
 * The list is kept, not just the number, because the result page says what
 * was looked up. "You looked up three words" with the words under it is a
 * vocabulary list somebody can act on; a bare count is a score for something
 * nobody was being scored on.
 */

export interface Lookups {
  /** Every word opened for this passage, lower-cased, in the order opened. */
  words: string[];
  /** How many of them were charged to the CURRENT attempt. Reset by sitting
   *  it again; `words` is not. */
  spent: number;
}

/** How many a reader gets per passage. */
export const LOOKUP_BUDGET = 3;

/**
 * The longest selection worth looking up, in words.
 *
 * A word or a short phrase — `give rise to`, `at the expense of`. Past that
 * somebody is selecting a sentence to read it, not asking what it means,
 * and the control steps out of the way rather than greying out: absence
 * reads as "not this", disabled reads as "not you".
 *
 * It is NOT a claim about what the server can answer. Anything sent is
 * answered, from the extracted table where a row exists and from a model
 * where it does not. This is about what a reader plausibly meant.
 */
export const LOOKUP_WORDS = 5;

const key = (materialId: string) => `voocab.lookups.${materialId}`;

const EMPTY: Lookups = { words: [], spent: 0 };

export function loadLookups(materialId: string): Lookups {
  try {
    const raw = localStorage.getItem(key(materialId));
    const said = raw ? JSON.parse(raw) : null;
    if (!said || !Array.isArray(said.words)) return EMPTY;
    return {
      words: said.words.filter((w: unknown) => typeof w === "string"),
      spent: Number.isFinite(said.spent) ? Math.max(0, said.spent) : 0,
    };
  } catch {
    return EMPTY;
  }
}

export function saveLookups(materialId: string, state: Lookups): void {
  try {
    if (state.words.length === 0 && state.spent === 0) {
      localStorage.removeItem(key(materialId));
    } else {
      localStorage.setItem(key(materialId), JSON.stringify(state));
    }
  } catch {
    /* nothing depends on it */
  }
}

/** How many are left to spend. */
export function left(state: Lookups): number {
  return Math.max(0, LOOKUP_BUDGET - state.spent);
}

/** Whether this word can be opened — either it is already known, or there
 *  is budget for it. */
export function canOpen(state: Lookups, word: string): boolean {
  return known(state, word) || left(state) > 0;
}

export function known(state: Lookups, word: string): boolean {
  return state.words.includes(normalise(word));
}

/** The state after opening `word`, charged only if it is new. */
export function opened(state: Lookups, word: string): Lookups {
  const w = normalise(word);
  if (!w || state.words.includes(w)) return state;
  return { words: [...state.words, w], spent: state.spent + 1 };
}

/** A fresh attempt: the budget comes back, the words stay known. */
export function resetSpend(state: Lookups): Lookups {
  return { ...state, spent: 0 };
}

/** What two spellings of one word have in common. Lower-cased and stripped
 *  of the punctuation a selection drags in with it — a reader who
 *  double-clicks "languages," has looked up "languages". */
export function normalise(word: string): string {
  return word
    .toLowerCase()
    .replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "")
    .trim();
}

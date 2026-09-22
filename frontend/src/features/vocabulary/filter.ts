import { asLevel, type CefrLevel } from "@/features/vocabulary/cefr";
import type { VocabularyEntry } from "@/features/vocabulary/types";

/**
 * Which of a passage's words are being looked at — and the reason it is one
 * object passed around rather than three pieces of state.
 *
 * The filter governs BOTH halves of the review: press `C1` and the list
 * shows the C1 words while the passage keeps only their marks. That is the
 * whole point of it. A reader asking *which words here are above me?* gets
 * the answer as a shape on the text — three orange marks in paragraph A and
 * none after it is a different passage from one flecked orange throughout —
 * and a list filtered under a passage that was not would be the page
 * answering half the question.
 *
 * Two halves reading one predicate is the only way that stays true. The
 * first version filtered the list inside the panel and the marks inside the
 * page, which is two implementations of one rule and therefore one rule and
 * a bug waiting for the first entry that disagrees.
 */
export interface WordFilter {
  /** Empty means EVERY level, not none. A filter that starts by hiding
   *  everything is a page that looks broken until it is understood, and
   *  "nothing chosen" is what a reader means by "show me the lot". */
  levels: CefrLevel[];
  /** Only the words this reader spent one of their three look-ups on. */
  lookedUp: boolean;
  /** Only the words this passage uses in a sense that is not their usual
   *  one. Named `unusual` because that is what the toggle says and what the
   *  tag on the row says; what it reads is `sense_differs`. */
  unusual: boolean;
}

export const NO_FILTER: WordFilter = {
  levels: [],
  lookedUp: false,
  unusual: false,
};

/** Whether anything is being hidden — which is what decides whether the
 *  save button says "all of them" or "these". */
export function isFiltering(filter: WordFilter): boolean {
  return filter.levels.length > 0 || filter.lookedUp || filter.unusual;
}

/** One level on or off, leaving the rest alone. Several may be on at once:
 *  B2 and C1 together is "what is above me", which is the commonest thing
 *  anybody wants from this control and would be two presses of a radio. */
export function toggleLevel(filter: WordFilter, level: CefrLevel): WordFilter {
  return {
    ...filter,
    levels: filter.levels.includes(level)
      ? filter.levels.filter((one) => one !== level)
      : [...filter.levels, level],
  };
}

/**
 * Whether one entry survives the filter.
 *
 * The three clauses are ANDed, which is the reading a learner expects from
 * pressing two controls: *C1* and *looked up* means the hard words that
 * beat me, not the union of two lists neither of which they asked for.
 *
 * An UNRATED word fails any level clause, and that is right rather than
 * unfortunate: nobody said what level it is, so it cannot be claimed as an
 * answer to "show me the C1 words". With no level chosen it is shown like
 * everything else.
 */
export function keeps(
  filter: WordFilter,
  entry: VocabularyEntry,
  lookedUp: (lemma: string) => boolean,
): boolean {
  if (filter.levels.length) {
    const level = asLevel(entry.cefr_level);
    if (!level || !filter.levels.includes(level)) return false;
  }
  if (filter.lookedUp && !lookedUp(entry.lemma)) return false;
  if (filter.unusual && !entry.sense_differs) return false;
  return true;
}

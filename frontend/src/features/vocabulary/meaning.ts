/**
 * Which meanings of a word to print, and in which order.
 *
 * Three screens ask this question — the lookup popover mid-paper, the
 * review's word list, the saved-words page — and they have to answer it the
 * same way, so they ask here instead of each writing the rule out.
 *
 * ## The rule, and the gloss that made it necessary
 *
 * An entry carries two meanings: what the word USUALLY means, and what it
 * means in the passage it was met in. The usual one leads.
 *
 * That ordering is the whole point and it is worth saying why, because the
 * opposite one is what shipped first and it was defensible. A word's sense
 * in THIS passage is what a reader stuck on THIS sentence needs, and a
 * dictionary answering with five senses is precisely the thing a band 5
 * reader cannot use. All of that is still true.
 *
 * What it could not do is teach the language. A passage about artificial
 * intelligence glossed `learn` as "a computer process of finding patterns in
 * data" — a correct reading of `machine learning`, a false statement about
 * the verb, and the only thing a learner who saved that word would ever see.
 * They would then use it wrongly in the next sentence they wrote, with no
 * way of knowing where they got it from.
 *
 * So: the sense to carry away first, the sense that is true here underneath
 * — and underneath only where the two are genuinely different. A word used
 * ordinarily, which is the great majority of them, shows one meaning,
 * because the same sentence printed twice is not a second fact.
 *
 * ## Falling back rather than showing nothing
 *
 * `meaning_core_en` is empty on an entry written before the field existed,
 * and on one whose model would not answer for it. The contextual meaning
 * then stands alone and is printed as though it were the word's own: a
 * missing usual sense is narrower help, and refusing to print anything
 * would turn it into no help at all.
 */

/** Enough of an entry to be printed. Both the review's rows and a saved
 *  word's contexts satisfy it, which is the point — they are the same fact
 *  stored in two tables. */
export interface Glossed {
  meaning_core_en: string;
  meaning_core_uz: string;
  meaning_en: string;
  meaning_uz: string;
  sense_differs: boolean;
}

export interface Meanings {
  /** What the word usually means. Always present. */
  en: string;
  uz: string;
  /** What it means in this passage, when that is not the same thing.
   *  `null` for a word used ordinarily, which is most of them. */
  here: { en: string; uz: string } | null;
}

export function meanings(entry: Glossed): Meanings {
  const en = entry.meaning_core_en || entry.meaning_en;
  const uz = entry.meaning_core_uz || entry.meaning_uz;
  // `sense_differs` is the server's answer and is trusted; the string test
  // beside it is not a second opinion but a guard against the one case it
  // cannot cover — an entry with no usual meaning at all, where "the sense
  // here is different" has nothing to be different from.
  const differs =
    entry.sense_differs &&
    Boolean(entry.meaning_core_en) &&
    entry.meaning_en !== en;
  return {
    en,
    uz,
    here: differs ? { en: entry.meaning_en, uz: entry.meaning_uz } : null,
  };
}

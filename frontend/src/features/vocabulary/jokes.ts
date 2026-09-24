/**
 * The end screen's one joke.
 *
 * "Hech qachon talaba ustidan kulinmasin — faqat so'zlar ustidan yoki o'z
 * ustimizdan" (the brief): the target of the joke is always the words
 * themselves, or the app, and never the learner who just spent ten minutes
 * on them. That rule is why this is a small pool keyed off what actually
 * happened in the session rather than one line printed regardless — a
 * generic "well done!" would be safe and say nothing, and a joke that
 * picked on the READER for getting `burgeoning` wrong would break the one
 * rule that matters here.
 *
 * Picked at random from whichever bucket applies, so the same session shape
 * doesn't always land on the same line — a screen seen once a day, forever,
 * is worth more than one line of variety.
 */

export interface SessionStats {
  /** Distinct words answered at least once. Requeues of the same word don't
   *  add to this — it is asking "how many words", not "how many answers". */
  total: number;
  /** Distinct words that took at least one Again along the way. */
  struggled: number;
  /** The lemma with the most Again ratings, ties broken by whoever hit that
   *  count first. Null when nobody stumbled on anything. */
  hardest: string | null;
}

function pick(pool: string[]): string {
  return pool[Math.floor(Math.random() * pool.length)];
}

/** Nothing went wrong. Rare enough to deserve its own bucket — a joke about
 *  "wrestling words into submission" when every answer was Good undersells
 *  what actually happened, which is nothing dramatic at all. */
const CLEAN: string[] = [
  "Clean sweep. Suspiciously clean.",
  "Nothing put up a fight. Nothing ever does, until it does.",
  "Done. The words are in your head now, whether they like it or not.",
];

/** One word gave the session its shape. Interpolated rather than generic —
 *  the brief's own example is exactly this shape (`burgeoning` put up a
 *  fight. It won.), and naming the actual word is what makes the joke land
 *  on the word and not on the reader. */
function hardestPool(hardest: string): string[] {
  return [
    `\`${hardest}\` put up a fight. It won.`,
    `\`${hardest}\` again. It's not going to be easy about this.`,
    `Everything behaved except \`${hardest}\`, which has opinions.`,
  ];
}

/** The general case — some resistance, no single word carrying all of it. */
function generalPool(total: number, struggled: number): string[] {
  return [
    `${total} words wrestled into submission.`,
    `${total} words. ${struggled} of them will betray you tomorrow.`,
    `A session. Some casualties, mostly on our side.`,
  ];
}

export function pickJoke(stats: SessionStats): string {
  if (stats.struggled === 0) return pick(CLEAN);
  if (stats.hardest) return pick(hardestPool(stats.hardest));
  return pick(generalPool(stats.total, stats.struggled));
}

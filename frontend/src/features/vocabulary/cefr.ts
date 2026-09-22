/**
 * The CEFR scale as a colour, and the one rule that makes it safe to use.
 *
 * ## Why a level gets a colour at all
 *
 * A passage's word list is a hundred entries long and a learner reads it
 * with one question: *which of these do I actually have to learn?* The
 * answer is the level, and until now the level was a grey chip the same
 * size and weight as the part of speech beside it — a fact printed, not a
 * fact usable. Coloured, the same list sorts itself on the way past the
 * eye: the orange is the top of the list, and the passage on the left
 * shows at a glance whether this text is pitched above the reader or below
 * them, before a single entry is read.
 *
 * ## Blue → violet → orange
 *
 * Cool to warm, which is the one ordering people read as a scale without
 * being told. Three hues rather than three shades of one, because three
 * shades of blue is a thing to compare rather than a thing to recognise,
 * and the level has to be legible from one chip with nothing beside it.
 *
 * **Never green and never red.** They are the verdict on the review page —
 * right and wrong — and the vocabulary list sits on that same page, three
 * inches from a passage striped in both. A learner shown their C1 words in
 * red reads the hardest words in the text as forty mistakes.
 *
 * **And never blue as a reader's mark.** This scale took the blue and the
 * violet that the highlight tool used to own; see
 * `features/reading/highlights.ts` for what happened to the pen, and
 * `globals.css` for why a colour with two meanings is not a colour system.
 *
 * ## The colour never travels alone
 *
 * Every use prints the LETTERS — `C1` — beside or inside the colour. About
 * one man in twelve cannot separate the violet from the orange, and a
 * scale he cannot read is worse than no scale: it is a page that looks
 * organised and is not. The colour is the fast path for everybody who can
 * use it and decoration for everybody who cannot, and the letters are the
 * fact in both cases.
 *
 * That rule is why this module exports tones and not a `<span>` painter
 * that could be pointed at an empty string.
 */

/** In the order they get harder, which is also the order they are drawn.
 *  Named rather than taken from `Object.keys` of the counts, which would
 *  print whatever order the JSON arrived in — and `B1 · C1 · B2` reads as
 *  a bug. */
export const CEFR_LEVELS = ["B1", "B2", "C1"] as const;

export type CefrLevel = (typeof CEFR_LEVELS)[number];

/**
 * The level of one entry, or null.
 *
 * Null is an ordinary answer, not a failure: the seed pipeline leaves the
 * level empty where the model would not commit to one, and the wire type
 * is a plain string because a future scale (A2, C2) must not crash a page
 * built before it. Everything that draws a level has to handle the null —
 * an UNRATED word is not an easy one, and painting it B1 would be the page
 * making a claim it has no basis for.
 */
export function asLevel(raw: string | null | undefined): CefrLevel | null {
  const said = (raw ?? "").toUpperCase();
  return (CEFR_LEVELS as readonly string[]).includes(said)
    ? (said as CefrLevel)
    : null;
}

/** Sorts hardest last, with the unrated at the end rather than the start.
 *  See `asLevel`: unrated is not easy, so it does not sit with the easy
 *  ones — but it is also not a claim, so it does not head the list. */
export function levelRank(raw: string | null | undefined): number {
  const level = asLevel(raw);
  return level ? CEFR_LEVELS.indexOf(level) : CEFR_LEVELS.length;
}

/**
 * What each level looks like, in the four places it appears.
 *
 * One table rather than four, because the whole value of a colour system is
 * that the orange in the lookup popover mid-paper and the orange in the
 * review an hour later are the same claim. Two tables drift on the first
 * afternoon somebody adjusts one of them.
 *
 * - `chip` — the badge: wash behind, ink on top. What a level looks like
 *   standing on its own beside a word.
 * - `wash` — over the passage itself.
 * - `line` — the underline a looked-up word wears ON TOP of its wash. In
 *   the level's own colour, not the foreground: left to `currentColor` it
 *   came out white, which reads as a third thing happening to the word
 *   rather than as one more thing said about the same mark.
 * - `lit` — the ring the mark wears while its entry is under the pointer
 *   on the other side. A RING rather than a stronger wash on purpose: a
 *   stronger wash of the same hue reads as a harder word, and pointing at
 *   a row must not appear to change what the level is.
 * - `ink` — the level's name as text with nothing behind it, for the one
 *   line that prints all three.
 */
export const CEFR_TONE: Record<
  CefrLevel,
  { chip: string; wash: string; line: string; lit: string; ink: string }
> = {
  B1: {
    chip: "bg-cefr-b1-wash text-cefr-b1-ink",
    wash: "bg-cefr-b1-wash",
    line: "decoration-cefr-b1",
    lit: "ring-2 ring-cefr-b1",
    ink: "text-cefr-b1-ink",
  },
  B2: {
    chip: "bg-cefr-b2-wash text-cefr-b2-ink",
    wash: "bg-cefr-b2-wash",
    line: "decoration-cefr-b2",
    lit: "ring-2 ring-cefr-b2",
    ink: "text-cefr-b2-ink",
  },
  C1: {
    chip: "bg-cefr-c1-wash text-cefr-c1-ink",
    wash: "bg-cefr-c1-wash",
    line: "decoration-cefr-c1",
    lit: "ring-2 ring-cefr-c1",
    ink: "text-cefr-c1-ink",
  },
};

/** What an UNRATED word wears, everywhere the table above is read. The
 *  border the rest of the app's quiet chips wear, so it reads as "no
 *  level recorded" rather than as a fourth level. */
export const CEFR_NONE = {
  chip: "border border-border text-muted-foreground",
  wash: "bg-foreground/10",
  line: "decoration-foreground/50",
  lit: "ring-2 ring-foreground/40",
  ink: "text-muted-foreground",
} as const;

/** The tone for whatever the wire said, unrated included. */
export function toneOf(raw: string | null | undefined) {
  const level = asLevel(raw);
  return level ? CEFR_TONE[level] : CEFR_NONE;
}

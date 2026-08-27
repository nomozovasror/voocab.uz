/**
 * A book cover for a collection, worked out from its id.
 *
 * Nobody uploads anything. The identity comes from the id — the same
 * collection is the same book on every visit and on every device, so a
 * learner recognises it on the shelf before they have read the title. That is
 * the identicon argument: identity without an upload, and it can never come
 * out ugly, because there is nothing here that isn't chosen.
 *
 * When authors are eventually allowed to upload a cover, **this stays the
 * default**. A shelf where some books have art and the rest have a grey
 * rectangle is a shelf that looks broken; a shelf where some books have art
 * and the rest have their own generated cover is just a shelf.
 *
 * **The palette is deliberately outside the token system.** These are not
 * interface colours — nothing about them means anything, they are ink on
 * paper — and a cover that changed with the theme would stop being the same
 * book. They are a small closed set rather than free hex so the shelf stays
 * coherent however many collections there are, and they are muted rather than
 * saturated so a row of them sits quietly next to Serika Dark.
 */

export interface Cover {
  /** The cover stock. */
  bg: string;
  /** The pattern printed on it — one step lighter than the stock, so it reads
   *  as texture rather than as a second element competing with the title. */
  ink: string;
  pattern: PatternName;
  /** Which cut of that pattern. The third dimension, and the cheap one: it
   *  moves an anchor, a spacing or an angle rather than adding a shape, so
   *  the number of covers multiplies without the number of things that can
   *  look wrong going up with it. */
  variant: number;
}

export type PatternName =
  | "diagonals"
  | "arcs"
  | "dots"
  | "bands"
  | "waves"
  | "grid"
  | "steps"
  | "columns";

/**
 * Thirteen stocks: twelve hues thirty degrees apart, plus one neutral slate.
 *
 * **Spread by hue, not chosen by eye.** The first set was picked for being
 * handsome one at a time and came out with five warm earth tones in it —
 * olive, brick, rust, umber, moss — which at this saturation all read
 * "brown". Five of seven books on a shelf looking like the same book is the
 * one thing a generated cover cannot afford, because recognising a book by
 * its colour is the whole reason for generating one.
 *
 * So they are laid out around the wheel at even spacing. Saturation varies by
 * hue rather than being constant, because the eye reads yellows and greens as
 * more colourful than blues at the same number.
 *
 * Lightness is 32%, which is where the second complaint went: at 24% these
 * were nearly black on a #323437 page, and a book that does not stand off the
 * shelf is a rectangle. 32% still carries white type at better than 7:1,
 * which is the constraint that stops it going higher.
 */
const STOCKS: Array<{ bg: string; ink: string }> = [
  { bg: "#3c6367", ink: "#51858a" }, // teal
  { bg: "#3b5568", ink: "#4f738c" }, // petrol
  { bg: "#3c4067", ink: "#51568a" }, // indigo
  { bg: "#504064", ink: "#6c5686" }, // violet
  { bg: "#624162", ink: "#845884" }, // plum
  { bg: "#64404d", ink: "#865667" }, // rose
  { bg: "#65453e", ink: "#885c53" }, // brick
  { bg: "#67503c", ink: "#8a6c51" }, // rust
  { bg: "#675c3c", ink: "#8a7c51" }, // amber
  { bg: "#5d653e", ink: "#7d8853" }, // olive
  { bg: "#466440", ink: "#5e8656" }, // moss
  { bg: "#406452", ink: "#56866e" }, // green
  { bg: "#4c5157", ink: "#666c75" }, // slate
];

const PATTERNS: PatternName[] = [
  "diagonals",
  "arcs",
  "dots",
  "bands",
  "waves",
  "grid",
  "steps",
  "columns",
];

/** How many cuts of each pattern. Thirteen stocks times eight patterns times
 *  this is how many covers there are — enough that a shelf of two dozen has
 *  no two alike, which is the whole job. */
export const VARIANTS = 3;

/**
 * A stable number from an id.
 *
 * The same hash the author avatars use, and for the same reason: a hash
 * rather than an index into the list, so adding a collection never re-covers
 * the existing ones. With `collections.length % 13` every book on the shelf
 * changes colour the day somebody publishes another one.
 */
function hash(id: string): number {
  let value = 0;
  for (let i = 0; i < id.length; i += 1) {
    value = (Math.imul(value, 31) + id.charCodeAt(i)) >>> 0;
  }
  // A finaliser, and it earns its four lines. Every id here is a UUID, so
  // every input has the same length and the same dashes in the same places —
  // and `value * 31 + c` leaves that structure sitting in the low bits.
  // Slicing three choices out of a poorly mixed word makes them correlate,
  // which shows up as two books that share a colour AND a pattern more often
  // than chance would explain. This is murmur3's avalanche step: it costs
  // nothing and makes the bits independent.
  value ^= value >>> 16;
  value = Math.imul(value, 0x85ebca6b) >>> 0;
  value ^= value >>> 13;
  value = Math.imul(value, 0xc2b2ae35) >>> 0;
  value ^= value >>> 16;
  return value >>> 0;
}

/**
 * The cover for one collection.
 *
 * The three choices are drawn from three different parts of the hash rather
 * than from the same end, so they do not move together — 13 × 8 × 3 really is
 * 312 covers and not thirteen with decoration.
 */
export function coverFor(id: string): Cover {
  const value = hash(id);
  const stock = STOCKS[value % STOCKS.length];
  const pattern = PATTERNS[(value >>> 7) % PATTERNS.length];
  const variant = (value >>> 15) % VARIANTS;
  return { ...stock, pattern, variant };
}

/**
 * The white the cover prints in.
 *
 * Fixed rather than themed, and inline rather than in a class string: the
 * stock underneath is always dark, so the type on it is always light — a
 * cover whose title followed the interface's foreground would be invisible on
 * a light theme, on a background that had not changed.
 */
export const COVER_INK = {
  title: "rgba(255,255,255,.94)",
  /**
   * The byline prints in the title's own white.
   *
   * It was dimmer, which is what type at the foot of a cover usually wants —
   * and it does not work here, because the pattern behind it is one step
   * lighter than the stock and a dimmed white lands within a shade of it.
   * Wherever a band or a wave ran under the name, the name stopped being
   * readable, and worst on exactly the patterns that look best.
   *
   * Full white clears the pattern on every stock, so nothing has to be
   * darkened behind it and the pattern can run to the bottom edge where it
   * belongs. The hierarchy is carried by size and weight instead — the title
   * is larger and set medium, the byline is small — which is the more honest
   * way to carry it anyway.
   */
  byline: "rgba(255,255,255,.94)",
  rule: "rgba(255,255,255,.5)",
  /** The sewn edge: dark down the left, one hairline of light beside it. Nine
   *  pixels of nothing much, and the whole of what says "book" rather than
   *  "tile". */
  spine: "rgba(0,0,0,.28)",
  spineEdge: "rgba(255,255,255,.07)",
} as const;

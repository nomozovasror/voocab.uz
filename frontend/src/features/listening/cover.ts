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
/**
 * The string a collection's cover is generated from.
 *
 * The id, unless the author has asked for a different book — `cover_seed` is
 * how they ask. Everything that draws a collection reads it through here, so
 * a re-covered course is the same new book on the shelf, in the editor and
 * on the learner's page. Anything reading `collection.id` directly would be
 * the one place still showing the old one.
 */
export function coverKeyOf(collection: {
  id: string;
  cover_seed?: string | null;
}): string {
  return collection.cover_seed || collection.id;
}

/** A seed for a cover nobody has to like. Hex and short, because the server
 *  validates the shape and nothing reads it except the hash. */
export function newCoverSeed(): string {
  return crypto.randomUUID().replace(/-/g, "").slice(0, 16);
}

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

  /**
   * A plate printed on the cover — the studio's status pill.
   *
   * Half-transparent black rather than a colour of its own, and that is the
   * whole trick: the stock underneath is one of thirteen hues, and a pill
   * with a fixed background would have to be chosen against each of them.
   * Darkening whatever is already there reads on all thirteen and cannot be
   * got wrong by adding a fourteenth.
   *
   * Fixed values for the same reason the ink is fixed: this prints ON the
   * cover, which is dark in every theme, so a themed foreground would go
   * invisible on a background that had not changed. `plateWarn` is amber
   * rather than the accent token for exactly that — the accent is purple in
   * Dracula, and "draft" would stop being the colour that means "your move".
   */
  plate: "rgba(0,0,0,.34)",
  plateText: "rgba(255,255,255,.85)",
  plateWarn: "#f0c33c",

  /**
   * Controls printed on a cover — the editor's banner.
   *
   * Same trick as the plate, and for the same reason: thirteen stocks, and a
   * button with a colour of its own would have to be chosen against each of
   * them. Darkening what is already there works on all thirteen.
   *
   * `accent` is the live Publish, and it is a fixed amber rather than the
   * theme's `--primary` because that is purple under Dracula — and a button
   * sitting on a cover that never changes with the theme cannot be the one
   * thing on it that does.
   */
  action: "rgba(0,0,0,.3)",
  actionHover: "rgba(0,0,0,.42)",
  actionText: "rgba(255,255,255,.9)",
  actionMuted: "rgba(255,255,255,.45)",
  accent: "#e2b714",
  accentText: "#2a2b1c",
  /** The muted white the banner's foot is set in. Under the title in
   *  weight, not in legibility: it carries the runtime and the save state,
   *  which are read at a glance or not at all. */
  faint: "rgba(255,255,255,.72)",
  /** The field's underline: invisible, then approached, then focused. */
  fieldHover: "rgba(255,255,255,.32)",
  fieldFocus: "rgba(255,255,255,.78)",
} as const;

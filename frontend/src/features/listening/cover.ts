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
}

export type PatternName =
  | "diagonals"
  | "arcs"
  | "dots"
  | "bands"
  | "waves";

/** Seven stocks. Deep teal, plum, olive, brick, indigo, slate, moss — all
 *  dark enough to carry white type at any weight, which is the constraint
 *  that decides the set. */
const STOCKS: Array<{ bg: string; ink: string }> = [
  { bg: "#2f4a4d", ink: "#3d5f63" },
  { bg: "#4a3c52", ink: "#5f4d6a" },
  { bg: "#4d4630", ink: "#61583c" },
  { bg: "#523a35", ink: "#684943" },
  { bg: "#33445c", ink: "#425875" },
  { bg: "#3c4046", ink: "#4e535a" },
  { bg: "#37472f", ink: "#475c3c" },
];

const PATTERNS: PatternName[] = [
  "diagonals",
  "arcs",
  "dots",
  "bands",
  "waves",
];

/**
 * A stable number from an id.
 *
 * The same hash the author avatars use, and for the same reason: a hash
 * rather than an index into the list, so adding a collection never re-covers
 * the existing ones. With `collections.length % 7` every book on the shelf
 * changes colour the day somebody publishes another one.
 */
function hash(id: string): number {
  let value = 0;
  for (let i = 0; i < id.length; i += 1) {
    value = (value * 31 + id.charCodeAt(i)) >>> 0;
  }
  return value;
}

/**
 * The cover for one collection.
 *
 * Colour and pattern are drawn from different parts of the hash — shifted
 * rather than taken from the same end — so the two do not move together and
 * seven stocks times five patterns really is thirty-five covers rather than
 * seven.
 */
export function coverFor(id: string): Cover {
  const value = hash(id);
  const stock = STOCKS[value % STOCKS.length];
  const pattern = PATTERNS[(value >>> 8) % PATTERNS.length];
  return { ...stock, pattern };
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
  author: "rgba(255,255,255,.55)",
  rule: "rgba(255,255,255,.5)",
  /** The sewn edge: dark down the left, one hairline of light beside it. Nine
   *  pixels of nothing much, and the whole of what says "book" rather than
   *  "tile". */
  spine: "rgba(0,0,0,.28)",
  spineEdge: "rgba(255,255,255,.07)",
} as const;

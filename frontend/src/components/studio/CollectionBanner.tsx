import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { COVER_INK, coverFor } from "@/features/listening/cover";
import { Pattern } from "@/features/listening/components/CollectionBook";

/**
 * The collection's cover, as the editor's whole header.
 *
 * It was a 104px thumbnail beside the title, and the two never agreed:
 * a portrait book is 144px tall and a title with a summary under it is
 * about fifty, so the row was a tall thing next to a short thing with air
 * either side of both. Shrinking the book to match would have made it
 * unreadable — a cover is recognised by its colour and its pattern, and at
 * sixty pixels it is a swatch.
 *
 * So the cover is not an illustration on this page: it is the header. The
 * band carries the same stock and the same pattern as the book on the shelf
 * — the author recognises the course before they read the name — and the
 * name, the state and the controls are printed on it, which is where a
 * book's title is anyway.
 *
 * **The pattern is TILED, not stretched.** It was stretched first — one SVG
 * on the cover's 156×214 viewBox with `preserveAspectRatio="none"` — and a
 * non-uniform scale is exactly what a circle cannot survive: the dots came
 * out as flat ellipses and the arcs as squashed ovals, which is a different
 * pattern wearing the same name. Tiling repeats the book's own figure at the
 * book's own ratio, so a circle is a circle and the band is recognisably the
 * same cover.
 *
 * Each tile is one SVG at `aspect-[156/214]`, full height, in a row that is
 * clipped by the band. No measuring: the aspect ratio does the arithmetic,
 * and a fixed count wide enough for the widest band means the extras are
 * simply cut off. Each SVG clips its own overflow, so a figure that runs off
 * the edge of one tile never bleeds into the next.
 *
 * **The pattern is quieter here than on the book**, and that is the whole
 * of what makes the type readable. A pattern is one step lighter than its
 * stock by design, so a line crossing a band or a wave loses exactly the
 * letters that land on it — on a book that costs four words of title, and
 * here it would cost a header. The first fix tried was a scrim over the
 * art, and it worked by making the band dark: the colour went with it, and
 * the colour IS the recognition. Fading the FIGURE instead leaves the stock
 * at full strength — same book, same hue, just a texture rather than a
 * picture, which is all a background has to be.
 */

/** How much of the figure survives behind a header. Enough to read as the
 *  same pattern from across the page, not enough to break a word. */
const PATTERN_OPACITY = 0.38;

/** Tiles across. Each is about 0.73 of the band's height wide, so a dozen
 *  covers thirteen hundred pixels — comfortably past the page's own 1000,
 *  and whatever is left over is clipped. */
const TILES = 12;

export function CollectionBanner({
  coverKey,
  children,
  className,
}: {
  /** `coverKeyOf(collection)` — the seed if it has one, the id if not. */
  coverKey: string;
  children: ReactNode;
  className?: string;
}) {
  const cover = coverFor(coverKey);

  return (
    <div
      className={cn(
        // Sharper on the sewn edge, softer on the outer — the way round a
        // real book is bound. Lifted off the page by its shadow, because the
        // band is an object and the page is not.
        "relative overflow-hidden rounded-l-[0.25rem] rounded-r-xl",
        "shadow-[0_6px_16px_rgba(0,0,0,0.34)]",
        className,
      )}
    >
      {/* The stock is one flat colour under all of the tiles rather than a
          rect inside each: nothing to seam, and the colour the author
          recognises is never touched by the figure's opacity. */}
      <div
        aria-hidden
        className="absolute inset-0 flex"
        style={{ backgroundColor: cover.bg }}
      >
        {Array.from({ length: TILES }, (_, i) => (
          <svg
            key={i}
            viewBox="0 0 156 214"
            className="aspect-[156/214] h-full w-auto shrink-0"
          >
            <g opacity={PATTERN_OPACITY}>
              <Pattern
                name={cover.pattern}
                ink={cover.ink}
                variant={cover.variant}
              />
            </g>
          </svg>
        ))}
      </div>

      {/* The sewn edge, wider than the book's because the band is. Nine
          pixels of nothing much, and the whole of what says "book" rather
          than "coloured rectangle". */}
      <span
        aria-hidden
        className="absolute inset-y-0 left-0 w-[0.6875rem]"
        style={{ backgroundColor: COVER_INK.spine }}
      />
      <span
        aria-hidden
        className="absolute inset-y-0 left-[0.6875rem] w-px"
        style={{ backgroundColor: COVER_INK.spineEdge }}
      />

      <div className="relative flex min-h-[9.375rem] flex-col justify-between gap-4 py-4 pr-5 pl-8">
        {children}
      </div>
    </div>
  );
}

/**
 * A control on the cover: half-transparent black, white type.
 *
 * `live` is the one the author is here to press — the amber Publish. Every
 * colour is inline and fixed, because all of them sit on a stock that never
 * changes with the theme.
 */
export function CoverButton({
  live,
  disabled,
  className,
  ...props
}: React.ComponentProps<"button"> & { live?: boolean }) {
  return (
    <button
      type="button"
      disabled={disabled}
      className={cn(
        "flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1.5 text-xs transition-colors duration-fast",
        "focus-visible:ring-2 focus-visible:ring-white/60 focus-visible:outline-none",
        disabled ? "cursor-not-allowed" : "hover:brightness-110",
        className,
      )}
      style={{
        backgroundColor: live && !disabled ? COVER_INK.accent : COVER_INK.action,
        color: live && !disabled
          ? COVER_INK.accentText
          : disabled
            ? COVER_INK.actionMuted
            : COVER_INK.actionText,
      }}
      {...props}
    />
  );
}

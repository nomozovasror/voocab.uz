import type { CSSProperties } from "react";

/**
 * The ground the header's islands float on.
 *
 * The header is three separate pills with gaps between them, and a page
 * scrolling underneath shows through those gaps — a line of a form or half a
 * question, sliding past behind the chrome. Something has to be back there in
 * the page's own colour.
 *
 * **Solid, not a pane.** Frosting the whole band was a mistake worth writing
 * down: it turned three floating islands into one continuous bar and took the
 * design's whole language with it. The band is not a surface. It is the page,
 * stopping.
 *
 * Fixed and empty, and both on purpose:
 *
 * - **Empty**, because the band is already contested. The brand island, the
 *   account island and the app's nav are in it, and on some pages a control
 *   docks into the middle too. A page that also pinned its own title row
 *   across the same band would run the title under one pill and the counter
 *   under the other, which is exactly what the take screen did.
 * - **Fixed**, because it holds no content and should hold no space. 60px is
 *   the header's own height, and at rest that is territory the header already
 *   occupies in the flow — so nothing of the page is ever hidden behind it.
 *
 * Anything of the page's that must sit ON this — a docked search field, a
 * docked player — takes `z-sticky` too and wins on document order, being
 * inside `<main>` and therefore later.
 *
 * It is per page rather than in `Layout` for one reason: the home page paints
 * a fixed star field behind everything, and a band of flat colour across the
 * top of it would cut the stars off. The day that page's background knows
 * about the header, this moves up a level and every route gets it.
 */
export function HeaderGround({ opening }: { opening?: Opening }) {
  return (
    <div aria-hidden className="fixed inset-x-0 top-0 z-sticky h-15">
      {/* The strip above the islands is never opened: a docked pill starts at
          12px, so anything let through up here would be let through above it. */}
      <div className="h-3 bg-background" />
      <div className="flex h-12">
        <div className="flex-1 bg-background" />
        {/*
          The window a glass dock needs.

          Frosted glass over an opaque colour is an opaque colour, so a docked
          pane can only mean something if the page is genuinely behind it. The
          ground therefore stops short on both sides of it and the paper shows
          through — and the pane covers the window with about twelve pixels to
          spare all round, so nothing of the page is ever exposed at the edges
          or under the pane's rounded corners.

          Zero without one, which is every page but the one that docks.
        */}
        <div
          className="shrink-0 ease-in-out transition-[width] motion-reduce:transition-none"
          style={{ width: opening?.width ?? 0, ...opening?.style }}
        />
        <div className="flex-1 bg-background" />
      </div>
    </div>
  );
}

/** How wide to hold the ground open, and the clock to do it on — so the window
 *  and whatever is landing in it move together. */
export interface Opening {
  width: number;
  style?: CSSProperties;
}

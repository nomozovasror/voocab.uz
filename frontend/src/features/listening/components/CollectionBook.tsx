import { Link } from "react-router-dom";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { COVER_INK, coverFor } from "@/features/listening/cover";
import type { PatternName } from "@/features/listening/cover";
import type { Collection } from "@/features/listening/types";

/**
 * A collection, as a book.
 *
 * The point is not decoration. A shelf of books is scannable in a way a
 * column of titles is not — the reader finds the one they were working
 * through by its colour, from across the page, before they have read a word.
 * That only works because the cover is derived from the id and never changes
 * (see cover.ts), so the book somebody half-finished last week is the same
 * book today.
 *
 * Four things carry the illusion, and all four are cheap:
 *
 * - **Portrait.** 156×214, near enough 3:4. A square tile is never a book,
 *   whatever is printed on it.
 * - **A spine.** Nine pixels of dark down the left edge with one hairline of
 *   light beside it. The smallest detail here and the one doing the most.
 * - **Asymmetric corners.** Sharper on the sewn edge, softer on the outer —
 *   which is the way round a real book is bound.
 * - **Lift.** Low shadow at rest, four pixels up and a deeper shadow on
 *   approach. Enough weight to feel like an object rather than a rectangle.
 *
 * The title is ON the cover, at the top, above the author at the foot —
 * because that is where a book's title is. Moved underneath, the cover stops
 * being a cover and becomes a picture with a label under it, and the whole
 * effect goes with it.
 */

/** The printed pattern, low-contrast, kept to the lower half so it never
 *  competes with the title. Drawn in the cover's own 156×214 space, so the
 *  whole book scales with its column and nothing needs measuring. */
function Pattern({ name, ink }: { name: PatternName; ink: string }) {
  if (name === "diagonals") {
    return (
      <g stroke={ink} strokeWidth={14}>
        <line x1={-30} y1={230} x2={120} y2={60} />
        <line x1={10} y1={250} x2={170} y2={70} />
        <line x1={55} y1={265} x2={200} y2={95} />
      </g>
    );
  }
  if (name === "arcs") {
    return (
      <g fill="none" stroke={ink} strokeWidth={10}>
        {[40, 66, 92, 118].map((r) => (
          <circle key={r} cx={150} cy={200} r={r} />
        ))}
      </g>
    );
  }
  if (name === "dots") {
    return (
      <g fill={ink}>
        {[150, 180, 210].map((cy) =>
          [34, 70, 106, 142].map((cx) => (
            <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r={7} />
          )),
        )}
      </g>
    );
  }
  if (name === "bands") {
    return (
      <g fill={ink}>
        {[128, 156, 184].map((y) => (
          <rect key={y} x={0} y={y} width={156} height={16} />
        ))}
      </g>
    );
  }
  return (
    <g fill="none" stroke={ink} strokeWidth={9}>
      {[170, 196, 222].map((y) => (
        <path
          key={y}
          d={`M-10 ${y} Q 40 ${y - 50} 90 ${y} T 190 ${y}`}
        />
      ))}
    </g>
  );
}

export function CollectionBook({ collection }: { collection: Collection }) {
  const cover = coverFor(collection.id);
  const { done, total } = collection.progress;
  const finished = total > 0 && done === total;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  return (
    <Link
      to={`/listening/collections/${collection.id}`}
      // The focus ring goes on the whole book rather than on the cover, so a
      // keyboard lands on something the size of the thing it is choosing.
      className="group/book block rounded-md focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
    >
      <div
        className={cn(
          // Sharper on the sewn edge, softer on the outer. The shadow is a
          // literal value because it is the object's weight rather than an
          // interface colour — there is no token for "this is a thing".
          "relative overflow-hidden rounded-l-sm rounded-r-md shadow-[0_6px_14px_rgba(0,0,0,0.32)]",
          "transition-[translate,box-shadow] duration-base ease-out motion-reduce:transition-none",
          "group-hover/book:-translate-y-1 group-hover/book:shadow-[0_12px_22px_rgba(0,0,0,0.4)]",
          "group-focus-visible/book:-translate-y-1",
        )}
      >
        {/* The SVG's own viewBox holds the portrait ratio, so the book scales
            with its column and nothing here needs a fixed height. */}
        <svg
          viewBox="0 0 156 214"
          className="block h-auto w-full"
          aria-hidden
        >
          <rect width={156} height={214} fill={cover.bg} />
          <Pattern name={cover.pattern} ink={cover.ink} />
        </svg>

        {/* The sewn edge. */}
        <span
          aria-hidden
          className="absolute inset-y-0 left-0 w-2"
          style={{ backgroundColor: COVER_INK.spine }}
        />
        <span
          aria-hidden
          className="absolute inset-y-0 left-2 w-px"
          style={{ backgroundColor: COVER_INK.spineEdge }}
        />

        {/* A rule over the title, which is a typographic habit older than any
            of this and the cheapest way to make a cover look set rather than
            typed. */}
        <span
          aria-hidden
          className="absolute top-8 left-5 h-0.5 w-8"
          style={{ backgroundColor: COVER_INK.rule }}
        />
        <p
          className="absolute top-11 right-3 left-5 line-clamp-4 text-sm leading-snug font-medium"
          style={{ color: COVER_INK.title }}
        >
          {collection.title}
        </p>
        {collection.author && (
          <p
            className="absolute right-3 bottom-4 left-5 truncate text-xs"
            style={{ color: COVER_INK.author }}
          >
            {collection.author.display_name}
          </p>
        )}
      </div>

      {/* Under the cover: how far through it the reader is, and nothing else.
          The author is on the cover where an author belongs, so repeating it
          here would be the same name twice in forty pixels. */}
      <div className="mt-3">
        <div
          className="h-0.5 overflow-hidden rounded-full bg-foreground/10"
          role="progressbar"
          aria-valuenow={done}
          aria-valuemin={0}
          aria-valuemax={total}
          aria-label={`${done} of ${total} done`}
        >
          <div
            className={cn(
              "h-full rounded-full transition-[width] duration-slow ease-out motion-reduce:transition-none",
              // Green, not the accent. Yellow means "this is the action" all
              // over this interface, and spending it on a progress bar — which
              // is a report, not an action — dilutes it everywhere else. Done
              // is green here because done is green everywhere here.
              done > 0 ? "bg-correct" : "bg-transparent",
            )}
            style={{ width: `${pct}%` }}
          />
        </div>
        <p className="mt-2 text-sm text-foreground">
          {finished ? (
            <span className="text-correct">Finished</span>
          ) : done === 0 ? (
            <span className="text-muted-foreground">Not started</span>
          ) : (
            <>
              <span className="tabular-nums">{done}</span> of{" "}
              <span className="tabular-nums">{total}</span> done
            </>
          )}
        </p>
      </div>
    </Link>
  );
}

/** A book, waiting. The cover's ratio comes from the same viewBox, so the
 *  shelf holds exactly the space the books will take. */
export function CollectionBookSkeleton() {
  return (
    <div>
      <div className="relative overflow-hidden rounded-l-sm rounded-r-md">
        <svg viewBox="0 0 156 214" className="block h-auto w-full" aria-hidden>
          <rect width={156} height={214} className="fill-foreground/10" />
        </svg>
      </div>
      <div className="mt-3">
        <div className="h-0.5 rounded-full bg-foreground/10" />
        <p className="mt-2 text-sm">
          <Skeleton className="inline-block h-[0.8em] w-24" />
        </p>
      </div>
    </div>
  );
}

import { Link } from "react-router-dom";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { COVER_INK, coverFor, coverKeyOf } from "@/features/listening/cover";
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

/**
 * The printed pattern: low-contrast, kept to the lower half so it never
 * competes with the title, and drawn in the cover's own 156×214 space so the
 * whole book scales with its column and nothing needs measuring.
 *
 * `variant` shifts an anchor, a spacing or an angle rather than adding a
 * shape. That is what makes the covers multiply cheaply: three cuts of eight
 * patterns is twenty-four figures, and there are still only eight ways for
 * one to look wrong.
 */
export function Pattern({
  name,
  ink,
  variant,
}: {
  name: PatternName;
  ink: string;
  variant: number;
}) {
  if (name === "diagonals") {
    // Lean, spacing and how far up the cover they reach.
    const lean = [0, 40, -35][variant];
    const gap = [40, 52, 34][variant];
    return (
      <g stroke={ink} strokeWidth={14}>
        {[0, 1, 2, 3].map((i) => (
          <line
            key={i}
            x1={-30 + i * gap}
            y1={230}
            x2={120 + i * gap + lean}
            y2={60}
          />
        ))}
      </g>
    );
  }
  if (name === "arcs") {
    // Which corner they radiate from.
    const [cx, cy] = [
      [150, 200],
      [6, 200],
      [78, 240],
    ][variant];
    return (
      <g fill="none" stroke={ink} strokeWidth={10}>
        {[40, 66, 92, 118].map((r) => (
          <circle key={r} cx={cx} cy={cy} r={r} />
        ))}
      </g>
    );
  }
  if (name === "dots") {
    const r = [7, 5, 9][variant];
    const step = [36, 26, 44][variant];
    const rows = [150, 180, 210];
    return (
      <g fill={ink}>
        {rows.map((cy) =>
          Array.from({ length: Math.ceil(156 / step) + 1 }, (_, i) => (
            <circle key={`${i}-${cy}`} cx={16 + i * step} cy={cy} r={r} />
          )),
        )}
      </g>
    );
  }
  if (name === "bands") {
    const height = [16, 9, 24][variant];
    const gap = [28, 20, 40][variant];
    return (
      <g fill={ink}>
        {[0, 1, 2].map((i) => (
          <rect
            key={i}
            x={0}
            y={128 + i * gap}
            width={156}
            height={height}
          />
        ))}
      </g>
    );
  }
  if (name === "grid") {
    const step = [26, 34, 20][variant];
    return (
      <g stroke={ink} strokeWidth={4}>
        {Array.from({ length: Math.ceil(156 / step) + 1 }, (_, i) => (
          <line key={`v${i}`} x1={i * step} y1={120} x2={i * step} y2={214} />
        ))}
        {Array.from({ length: Math.ceil(94 / step) + 1 }, (_, i) => (
          <line key={`h${i}`} x1={0} y1={120 + i * step} x2={156} y2={120 + i * step} />
        ))}
      </g>
    );
  }
  if (name === "steps") {
    const rise = [22, 16, 30][variant];
    return (
      <g fill={ink}>
        {[0, 1, 2, 3].map((i) => (
          <rect
            key={i}
            x={i * 39}
            y={214 - rise * (i + 1)}
            width={39}
            height={rise * (i + 1)}
          />
        ))}
      </g>
    );
  }
  if (name === "columns") {
    const width = [14, 9, 20][variant];
    const step = [30, 22, 40][variant];
    return (
      <g fill={ink}>
        {Array.from({ length: Math.ceil(156 / step) + 1 }, (_, i) => (
          <rect
            key={i}
            x={12 + i * step}
            y={116 + (i % 2) * 18}
            width={width}
            height={214}
          />
        ))}
      </g>
    );
  }
  const amp = [50, 32, 66][variant];
  const gap = [26, 20, 34][variant];
  return (
    <g fill="none" stroke={ink} strokeWidth={9}>
      {[0, 1, 2].map((i) => {
        const y = 170 + i * gap;
        return (
          <path key={i} d={`M-10 ${y} Q 40 ${y - amp} 90 ${y} T 190 ${y}`} />
        );
      })}
    </g>
  );
}

/**
 * The cover on its own — art, spine and rule, with the title where a title
 * goes.
 *
 * Separated out because the block above the practice list shows the same
 * cover at a third the size, and two implementations of one book is two
 * covers that drift. `showTitle` is off there: at 62px wide the title would
 * be four words of unreadable type, and the course's name is printed in full
 * eight pixels to its right.
 */
export function CollectionCover({
  coverKey,
  title,
  showTitle = true,
  compact,
  className,
}: {
  /** The string the cover is generated from — `coverKeyOf(collection)`,
   *  never a bare id: a collection the author has re-covered generates from
   *  its seed, and anywhere still passing the id draws the old book. */
  coverKey: string;
  title: string;
  showTitle?: boolean;
  /** The studio editor's 104px cut, beside the title being typed. Only the
   *  title's size and insets change — the art scales from its own viewBox —
   *  because the shelf's type at that width is four words that do not fit. */
  compact?: boolean;
  className?: string;
}) {
  const cover = coverFor(coverKey);
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-l-sm rounded-r-md",
        className,
      )}
    >
      {/* The SVG's own viewBox holds the portrait ratio, so the cover scales
          with whatever it is put in and nothing here needs a fixed height. */}
      <svg viewBox="0 0 156 214" className="block h-auto w-full" aria-hidden>
        <rect width={156} height={214} fill={cover.bg} />
        <Pattern name={cover.pattern} ink={cover.ink} variant={cover.variant} />
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

      {showTitle ? (
        <div
          className={cn(
            "absolute pr-1",
            compact ? "inset-x-4 top-3.5" : "inset-x-5 top-8",
          )}
        >
          <p
            className={cn(
              "line-clamp-4 leading-snug font-medium",
              compact ? "text-[0.65rem]" : "text-sm",
            )}
            style={{ color: COVER_INK.title }}
          >
            {title}
          </p>
          <span
            aria-hidden
            className={cn(
              "block",
              compact ? "mt-2 h-px w-5" : "mt-2.5 h-0.5 w-8",
            )}
            style={{ backgroundColor: COVER_INK.rule }}
          />
        </div>
      ) : (
        // Without the title the rule is all that is left of the typography,
        // and it is what keeps a small cover from reading as a swatch.
        <span
          aria-hidden
          className="absolute top-1/3 left-2.5 block h-px w-4"
          style={{ backgroundColor: COVER_INK.rule }}
        />
      )}
    </div>
  );
}

export function CollectionBook({ collection }: { collection: Collection }) {
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
          // The shadow is a literal value because it is the object's weight
          // rather than an interface colour — there is no token for "this is
          // a thing".
          "relative shadow-[0_6px_14px_rgba(0,0,0,0.32)]",
          "transition-[translate,box-shadow] duration-base ease-out motion-reduce:transition-none",
          "group-hover/book:-translate-y-1 group-hover/book:shadow-[0_12px_22px_rgba(0,0,0,0.4)]",
          "group-focus-visible/book:-translate-y-1",
        )}
      >
        <CollectionCover
          coverKey={coverKeyOf(collection)}
          title={collection.title}
        />

        {/* Both lines in the title's own white — see COVER_INK.byline for
            why a dimmed one could not survive the pattern behind it. */}
        <div
          className="absolute inset-x-5 bottom-3 pr-1 text-xs"
          style={{ color: COVER_INK.byline }}
        >
          {collection.author && (
            <p className="truncate">{collection.author.display_name}</p>
          )}
          {/* "materials", never "papers": in IELTS a paper is the whole exam,
              and a cover claiming "6 papers" promises six exams. The word is
              the one the rest of the page uses, so the two agree. */}
          <p className="tabular-nums">
            {total} material{total === 1 ? "" : "s"}
          </p>
        </div>
      </div>

      {/* Under the cover: how far through it the reader is, and nothing else.
          The author is on the cover where an author belongs, so repeating it
          here would be the same name twice in forty pixels.

          Kept tight. A book is a fixed ratio, so the cover's height is not
          negotiable and every pixel this strip spends is a pixel of the next
          row pushed below the fold. */}
      <div className="mt-2">
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
              // over this interface, and spending it on a progress bar —
              // which is a report, not an action — dilutes it everywhere
              // else. Done is green here because done is green everywhere.
              done > 0 ? "bg-correct" : "bg-transparent",
            )}
            style={{ width: `${pct}%` }}
          />
        </div>
        <p className="mt-1.5 text-xs text-foreground">
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
      <div className="mt-2">
        <div className="h-0.5 rounded-full bg-foreground/10" />
        <p className="mt-1.5 text-xs">
          <Skeleton className="inline-block h-[0.8em] w-24" />
        </p>
      </div>
    </div>
  );
}

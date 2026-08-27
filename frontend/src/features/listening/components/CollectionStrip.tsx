import { Link } from "react-router-dom";
import { Check, Library } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { Collection } from "@/features/listening/types";

/**
 * The courses, above the catalogue.
 *
 * The list answers what exists. The recommendation answers what to do
 * tonight. These answer the one neither can: what a route through the library
 * looks like when somebody who knows the exam has laid one out. That is the
 * whole reason they sit above the list rather than in it — a thousand papers
 * in a scrolling column is a filing cabinet, and a filing cabinet is not a
 * course.
 *
 * Every card carries how far the reader is through it, and that number is
 * counted from attempts they had already made rather than from having signed
 * up for anything. So a card is never a commitment: opening one costs
 * nothing, abandoning it leaves nothing behind, and a course they wandered
 * into last month still shows exactly what they did.
 *
 * **A shortlist, not a browser.** It shows a handful and says how many there
 * are, and the way to the rest is the switch above the list rather than more
 * rail. A rail is a bad place to look for something — three cards fit, the
 * scrollbar hides until it is reached for, and a mouse wheel cannot move it
 * sideways at all — so past a handful it stops being a display and becomes a
 * hiding place. The server orders these so the handful is the useful one: in
 * progress first, then untouched, then finished.
 */

/** How many the rail shows before deferring to the full list. Six is two
 *  screenfuls of rail at this card width — enough that scrolling it is
 *  worthwhile, few enough that scrolling it ends. */
export const STRIP_SIZE = 6;

/** A bar, and only where it means something.
 *
 *  At zero the bar is drawn as an empty track rather than skipped, because
 *  the row it sits in has a height either way and a card that grows when you
 *  start it would make the whole strip jump. */
function ProgressBar({ done, total }: { done: number; total: number }) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  return (
    <div className="mt-2.5">
      <div
        className="h-1 overflow-hidden rounded-full bg-foreground/10"
        role="progressbar"
        aria-valuenow={done}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-label={`${done} of ${total} done`}
      >
        <div
          className="h-full rounded-full bg-primary transition-[width] duration-slow ease-out motion-reduce:transition-none"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function CollectionCard({ collection }: { collection: Collection }) {
  const { done, total } = collection.progress;
  const finished = total > 0 && done === total;

  return (
    <Link
      to={`/listening/collections/${collection.id}`}
      // A fixed width and no shrinking: these scroll sideways, and a card that
      // squeezed to fit would make "how many are there" a question about the
      // window rather than about the library.
      className="flex w-64 shrink-0 flex-col rounded-2xl border border-border-subtle bg-card/40 p-4 transition-colors duration-fast hover:border-border hover:bg-surface-hover focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
    >
      <div className="flex items-start gap-2">
        <p className="min-w-0 flex-1 text-sm text-foreground">
          {collection.title}
        </p>
        {/* Finished gets a mark rather than "100%": the number is the same
            fact and the mark is the one somebody is pleased to see. */}
        {finished && (
          <span
            role="img"
            aria-label="Finished"
            className="inline-flex size-4 shrink-0 items-center justify-center rounded-full bg-correct/20 text-correct"
          >
            <Check className="size-3" strokeWidth={3} aria-hidden />
          </span>
        )}
      </div>

      {/* Two lines and then it stops. The summary is one line the author
          wrote about what the course is FOR; anything longer belongs on the
          collection's own page, where there is room to read it. */}
      {collection.summary && (
        <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
          {collection.summary}
        </p>
      )}

      <div className="mt-auto">
        <ProgressBar done={done} total={total} />
        <p className="mt-1.5 text-xs text-muted-foreground">
          <span className="tabular-nums">{done}</span> of{" "}
          <span className="tabular-nums">{total}</span> done
          {collection.author && (
            <>
              {" · "}
              <span className="truncate">{collection.author.display_name}</span>
            </>
          )}
        </p>
      </div>
    </Link>
  );
}

export function CollectionStrip({
  collections,
  total,
  onSeeAll,
}: {
  collections: Collection[];
  /** How many there are in all — not how many are shown. Without it the rail
   *  is silently truncated, which is the same bug the catalogue's own count
   *  exists to avoid. */
  total: number;
  onSeeAll: () => void;
}) {
  // Nothing published yet is not a state worth drawing. An empty rail with a
  // heading over it is the page announcing a feature rather than offering
  // one, and on a young library that is most of what the reader would see.
  if (collections.length === 0) return null;

  const shown = collections.slice(0, STRIP_SIZE);

  return (
    <section aria-label="Collections" className="mb-6">
      <div className="mb-2 flex items-center gap-2">
        <Library className="size-4 text-muted-foreground" aria-hidden />
        <h2 className="text-sm text-foreground">Courses and sets</h2>
        {/* Only once there is more than is showing. "See all 4" over four
            cards is a button that goes nowhere new. */}
        {total > shown.length && (
          <button
            type="button"
            onClick={onSeeAll}
            className="ml-auto rounded text-xs text-primary transition-colors hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            See all {total}
          </button>
        )}
      </div>
      {/* Sideways, with the scrollbar out of the way until reached for. A
          wrapping grid would push the catalogue below the fold the day
          somebody publishes a sixth course; a rail stays one row however many
          there are. The negative margin and padding let the cards run to the
          page's edge rather than stopping short of it, so it reads as
          continuing rather than ending. */}
      <div
        className={cn(
          "scrollbar-quiet -mx-4 flex gap-3 overflow-x-auto px-4 pb-2",
          // Every card lands square rather than half-shown, which is the
          // difference between a rail that has been scrolled and one that
          // looks broken.
          "snap-x snap-mandatory [&>*]:snap-start",
        )}
      >
        {shown.map((collection) => (
          <CollectionCard key={collection.id} collection={collection} />
        ))}
      </div>
    </section>
  );
}

/** The strip, waiting. Two cards rather than the real count, which nobody
 *  knows yet — and built from the real card's class strings so the space it
 *  holds is the space it will take. */
export function CollectionStripSkeleton() {
  return (
    <section aria-hidden className="mb-6">
      <div className="mb-2 flex items-center gap-2">
        <Skeleton className="size-4 rounded" />
        <h2 className="text-sm">
          <Skeleton className="inline-block h-[0.8em] w-32" />
        </h2>
      </div>
      <div className="flex gap-3 pb-2">
        {[0, 1].map((i) => (
          <div
            key={i}
            className="flex w-64 shrink-0 flex-col rounded-2xl border border-border-subtle bg-card/40 p-4"
          >
            <p className="text-sm">
              <Skeleton className="inline-block h-[0.8em] w-40 max-w-full" />
            </p>
            <p className="mt-1 text-xs">
              <Skeleton className="inline-block h-[0.8em] w-full" />
            </p>
            <div className="mt-2.5 h-1 rounded-full bg-foreground/10" />
            <p className="mt-1.5 text-xs">
              <Skeleton className="inline-block h-[0.8em] w-28" />
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}

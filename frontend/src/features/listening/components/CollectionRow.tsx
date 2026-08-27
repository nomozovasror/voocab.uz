import { Link } from "react-router-dom";
import { Check } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { Collection } from "@/features/listening/types";

/**
 * One course, as somebody choosing what to work through reads it.
 *
 * Built to the catalogue row's own proportions — the same padding, the same
 * rule between rows, the same numbered gutter — because the two lists share a
 * column and a switch, and a course that sat differently in the same space
 * would read as a different page rather than a different list.
 *
 * What replaces the difficulty chip on the right is the only thing a course
 * has that a material doesn't: how far through it the reader is. That figure
 * is counted from attempts they already made, so it is right without anybody
 * having enrolled in anything, and it is right months later.
 */
export function CollectionRow({
  collection,
  index,
  revealRef,
}: {
  collection: Collection;
  /** Its place in the list as it stands. Same as the catalogue's: filter or
   *  reorder and the numbers start again at 1. */
  index: number;
  revealRef?: (el: HTMLLIElement | null) => void;
}) {
  const { done, total } = collection.progress;
  const finished = total > 0 && done === total;
  const started = done > 0 && !finished;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  return (
    <li
      ref={revealRef}
      className={cn(
        "relative after:absolute after:inset-x-3 after:bottom-0 after:h-px after:bg-border-subtle after:transition-colors after:duration-fast last:after:hidden",
        "has-[a:hover]:after:bg-transparent has-[a:focus-visible]:after:bg-transparent",
        revealRef &&
          "scale-95 opacity-0 transition-[opacity,scale] delay-100 duration-base ease-out data-[visible=true]:scale-100 data-[visible=true]:opacity-100",
      )}
    >
      <Link
        to={`/listening/collections/${collection.id}`}
        className="group/row flex items-start gap-3 rounded-lg px-3 py-3.5 transition-colors duration-fast hover:bg-surface-hover focus-visible:bg-surface-hover focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        <span
          aria-hidden
          className="shrink-0 text-base tabular-nums text-foreground"
        >
          {index}.
        </span>

        <div className="min-w-0 flex-1">
          <span className="flex min-w-0 items-center gap-1.5">
            <span className="truncate text-base text-foreground">
              {collection.title}
            </span>
            {finished && (
              <span
                role="img"
                aria-label="Finished"
                title="You have worked through this one"
                className="inline-flex size-4 shrink-0 items-center justify-center rounded-full bg-correct/20 text-correct"
              >
                <Check className="size-3" strokeWidth={3} aria-hidden />
              </span>
            )}
          </span>
          <p className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-muted-foreground">
            <span className="tabular-nums">{total}</span>
            <span>material{total === 1 ? "" : "s"}</span>
            {collection.author && (
              <>
                <span aria-hidden className="opacity-60">
                  ·
                </span>
                <span className="truncate">
                  {collection.author.display_name}
                </span>
              </>
            )}
            {/* The summary comes last and is allowed to be cut off. It is the
                author's line about what the course is FOR, which matters when
                you are choosing between two and not at all when you are
                scanning ten. */}
            {collection.summary && (
              <>
                <span aria-hidden className="opacity-60">
                  ·
                </span>
                <span className="truncate">{collection.summary}</span>
              </>
            )}
          </p>
        </div>

        {/* Where the catalogue row puts a difficulty band. A course has no
            difficulty — it is a route, and the papers on it have their own —
            so the column carries the one thing only a course has. */}
        <div className="flex w-24 shrink-0 flex-col items-center justify-center gap-1.5 self-stretch">
          <div
            className="h-1 w-full overflow-hidden rounded-full bg-foreground/10"
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
          <span
            className={cn(
              "text-xs whitespace-nowrap tabular-nums",
              // Started and unfinished is the one state worth colouring: it
              // is the row the reader is most likely to be looking for.
              started ? "text-foreground" : "text-muted-foreground",
            )}
          >
            {done} / {total}
          </span>
        </div>
      </Link>
    </li>
  );
}

/** The same row, waiting. Built from the real one's class strings so the two
 *  cannot drift — see CLAUDE.md on why skeletons are never measured. */
export function CollectionRowSkeleton() {
  return (
    <li className="relative after:absolute after:inset-x-3 after:bottom-0 after:h-px after:bg-border-subtle last:after:hidden">
      <div className="flex items-start gap-3 px-3 py-3.5">
        <span aria-hidden className="shrink-0 text-base">
          <Skeleton className="inline-block h-[0.8em] w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5">
            <span className="text-base">
              <Skeleton className="inline-block h-[0.8em] w-48 max-w-full" />
            </span>
          </span>
          <p className="mt-1 flex h-5 items-center text-xs">
            <Skeleton className="inline-block h-[0.8em] w-64 max-w-full" />
          </p>
        </div>
        <div className="flex w-24 shrink-0 flex-col items-center justify-center gap-1.5 self-stretch">
          <div className="h-1 w-full rounded-full bg-foreground/10" />
          <span className="text-xs">
            <Skeleton className="inline-block h-[0.8em] w-10" />
          </span>
        </div>
      </div>
    </li>
  );
}

import { Link } from "react-router-dom";
import { Skeleton } from "@/components/ui/skeleton";
import type { WordListSummary } from "@/features/vocabulary/types";
import { formatCount } from "@/features/vocabulary/wordLists";
import {
  ListProgress,
  ListToggle,
} from "@/features/vocabulary/components/WordListControls";

/** The lists as cards: title, size, progress, Start/Stop. The title is the
 *  link to the list's own page; the card is not one big link, because it
 *  carries a button and a link inside a link is invalid. */
export function WordListCards({
  lists,
  describe = false,
}: {
  lists: WordListSummary[];
  describe?: boolean;
}) {
  return (
    <ul className="space-y-3">
      {lists.map((l) => (
        <li
          key={l.key}
          className="rounded-xl border border-border bg-card px-4 py-3.5"
        >
          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
            <div className="min-w-0">
              <h3 className="text-sm font-medium text-foreground">
                <Link
                  to={`/vocabulary/lists/${l.key}`}
                  className="rounded underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                >
                  {l.title}
                </Link>
              </h3>
              <p className="text-xs text-muted-foreground">
                {formatCount(l.word_count)} words
              </p>
            </div>
            <ListToggle listKey={l.key} title={l.title} active={l.active} />
          </div>
          {describe && (
            <p className="mt-2 text-sm text-muted-foreground">{l.description}</p>
          )}
          <ListProgress
            title={l.title}
            owned={l.owned}
            total={l.word_count}
            className="mt-3"
          />
        </li>
      ))}
    </ul>
  );
}

/** Built from the card's own class strings. */
export function WordListCardsSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <ul className="space-y-3" aria-hidden>
      {Array.from({ length: rows }, (_, i) => (
        <li
          key={i}
          className="rounded-xl border border-border bg-card px-4 py-3.5"
        >
          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
            <div className="min-w-0">
              <h3 className="text-sm font-medium">
                <Skeleton className="inline-block h-[0.8em] w-40" />
              </h3>
              <p className="text-xs">
                <Skeleton className="inline-block h-[0.8em] w-16" />
              </p>
            </div>
            <Skeleton className="h-7 w-14 rounded-lg" />
          </div>
          <div className="mt-3 flex items-center gap-3">
            <Skeleton className="h-1.5 flex-1 rounded-full" />
            <span className="text-xs">
              <Skeleton className="inline-block h-[0.8em] w-16" />
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}

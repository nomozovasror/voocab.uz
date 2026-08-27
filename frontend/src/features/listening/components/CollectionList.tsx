import { useEffect, useMemo, useRef } from "react";
import { Library } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { getErrorMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import { COLLECTIONS_PAGE, useCollections } from "@/features/listening/queries";
import { COURSE_STATUS_LABEL } from "@/features/listening/practice";
import type {
  CourseCovers,
  CourseLength,
  CourseStatus,
} from "@/features/listening/practice";
import {
  CollectionBook,
  CollectionBookSkeleton,
} from "@/features/listening/components/CollectionBook";

/**
 * The other list.
 *
 * A shelf rather than a column of rows, and that is the one place the two
 * lists deliberately part company. A paper is a line of facts — how long, how
 * hard, have I done it — and reads as a row. A course is a thing you pick up,
 * and the fastest way to find the one you were working through is to
 * recognise it, which a row of text cannot be. So courses are books
 * (CollectionBook), covered from their own id so the same course looks the
 * same forever.
 *
 * The order is the same argument as everywhere else here: in progress, then
 * untouched, then finished, so the thing somebody was in the middle of is the
 * first thing they see.
 *
 * Its one filter is the state a course is in for this reader — started, not
 * started, finished — which is the ordering asked as a question. Nothing else
 * the catalogue filters by applies: a part number, a task type and a
 * difficulty band all belong to a paper, not to a route through several.
 */
/**
 * The shelf. Wrapping rather than a rail: this is the whole list now, and a
 * rail is a place to hide things — three fit, the scrollbar hides until it is
 * reached for, and a mouse wheel cannot move it sideways at all.
 *
 * Four across, and the books are CAPPED rather than left to fill the column.
 * Uncapped they came out 186px wide — wider than they were drawn for — and a
 * book is a fixed ratio, so every pixel of extra width is another one and a
 * third of height. That is what pushed the second row off the bottom, and a
 * reader with seven collections seeing four has no reason to think there are
 * more. Capped at 160 the row is sixty pixels shorter, which is the
 * difference between the next row peeking and the next row not existing.
 *
 * The slack that leaves in each cell is spread evenly rather than pushed to
 * one side: an even shelf with air in it reads as a shelf, and a left-packed
 * one with a gap at the end reads as a mistake.
 */
const SHELF =
  "mt-4 grid grid-cols-2 justify-items-center gap-x-5 gap-y-6 sm:grid-cols-3 lg:grid-cols-4";

/** One place on the shelf. The cap is here rather than on the book itself so
 *  that anything else placed on a shelf lines up with the books. */
const SLOT = "w-full max-w-40";

/** The same entrance the catalogue rows use, applied to a book. */
const REVEAL =
  "scale-95 opacity-0 transition-[opacity,scale] delay-100 duration-base ease-out data-[visible=true]:scale-100 data-[visible=true]:opacity-100";

export function CollectionList({
  query,
  status,
  covers,
  length,
  revealRef,
}: {
  /** The same field that searches the catalogue. Passed in already settled —
   *  the page holds the typing, this holds a list. */
  query: string;
  status: CourseStatus;
  covers: CourseCovers;
  length: CourseLength;
  revealRef?: (el: HTMLLIElement | null) => void;
}) {
  // Built exactly as the page builds it, so the two calls share one cache
  // entry and switching lists draws from what the strip already fetched.
  const params = useMemo(() => {
    const next: Record<string, string> = {};
    if (query.trim()) next.q = query.trim();
    if (status !== "all") next.status = status;
    if (covers !== "all") next.covers = covers;
    if (length !== "all") next.length = length;
    return next;
  }, [query, status, covers, length]);
  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isPlaceholderData,
  } = useCollections(params);

  const rows = useMemo(
    () => data?.pages.flatMap((page) => page.items) ?? [],
    [data],
  );
  const total = data?.pages[0]?.total ?? 0;
  const narrowed =
    query.trim() !== "" ||
    status !== "all" ||
    covers !== "all" ||
    length !== "all";

  // The same sentinel the catalogue uses, for the same reasons — see the
  // note on it in ListeningPage.
  const bottom = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = bottom.current;
    if (!el || !hasNextPage || typeof IntersectionObserver === "undefined") {
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !isFetchingNextPage) void fetchNextPage();
      },
      { rootMargin: "400px 0px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  if (isError) {
    return (
      <div className="mt-6 rounded-xl border border-dashed border-border px-5 py-12 text-center">
        <p className="text-sm text-muted-foreground">
          {getErrorMessage(error) || "Couldn't load the collections."}
        </p>
        <Button
          variant="outline"
          size="sm"
          className="mt-4"
          onClick={() => void refetch()}
        >
          Try again
        </Button>
      </div>
    );
  }

  if (isLoading) {
    return (
      <>
        <Header loading />
        <SkeletonBlock label="Loading collections">
          <div className={SHELF}>
            {Array.from({ length: 4 }, (_, i) => (
              <div key={i} className={SLOT}>
                <CollectionBookSkeleton />
              </div>
            ))}
          </div>
        </SkeletonBlock>
      </>
    );
  }

  return (
    <>
      <Header count={total} status={status} narrowed={narrowed} />

      {rows.length === 0 ? (
        <div className="mt-6 flex flex-col items-center gap-2 rounded-xl border border-border-subtle py-16 text-center">
          <Library className="size-6 text-muted-foreground/60" aria-hidden />
          {/* Two different facts, said differently. A search that found
              nothing is a state the reader put the page in; an empty library
              is a state the library is in, and telling somebody to search
              harder for something that does not exist is the page wasting
              their time. */}
          <p className="text-sm text-muted-foreground">
            {narrowed
              ? "No collections match that."
              : "No collections have been published yet."}
          </p>
        </div>
      ) : (
        <>
          <ul
            className={cn(
              SHELF,
              "transition-opacity duration-fast",
              isPlaceholderData && "opacity-50",
            )}
          >
            {rows.map((collection) => (
              // Without the observer there is nothing to set `data-visible`,
              // so the class that starts a book invisible must not be there
              // either — the same rule the catalogue rows follow.
              <li
                key={collection.id}
                ref={revealRef}
                className={cn(SLOT, revealRef && REVEAL)}
              >
                <CollectionBook collection={collection} />
              </li>
            ))}
          </ul>

          {isFetchingNextPage && (
            <div className={cn(SHELF, "mt-6")} aria-hidden>
              <div className={SLOT}>
                <CollectionBookSkeleton />
              </div>
              <div className={SLOT}>
                <CollectionBookSkeleton />
              </div>
            </div>
          )}
          {hasNextPage && <div ref={bottom} aria-hidden className="h-8" />}
          {!hasNextPage && total > COLLECTIONS_PAGE && (
            <p className="py-6 text-center text-xs text-muted-foreground">
              That&apos;s all {total} of them.
            </p>
          )}
        </>
      )}
    </>
  );
}

/** The count line, at the catalogue header's own height.
 *
 *  No sort control: the order here is not a preference, it is where the
 *  reader is — in progress, then untouched, then finished — and offering to
 *  undo that would be offering to hide the course they were halfway through
 *  behind eleven they have never opened. */
function Header({
  count,
  status,
  narrowed,
  loading,
}: {
  count?: number;
  status?: CourseStatus;
  narrowed?: boolean;
  loading?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-4 px-3 py-1.5">
      <p className="flex items-center gap-2 text-xs text-muted-foreground">
        {loading ? (
          <Skeleton className="inline-block h-[0.8em] w-20" />
        ) : (
          <span>
            <span className="tabular-nums text-foreground">{count}</span>{" "}
            collection{count === 1 ? "" : "s"}
          </span>
        )}
      </p>
      {/* What the order is — but only while it is the interesting fact. Once
          a status is picked the whole list is that one thing, so the label
          says so instead; once anything else is narrowing it, the order is
          still true and no longer worth a line. */}
      <p className="text-xs text-muted-foreground">
        {status && status !== "all"
          ? COURSE_STATUS_LABEL[status]
          : narrowed
            ? null
            : "In progress first"}
      </p>
    </div>
  );
}

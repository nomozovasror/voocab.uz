import { useEffect, useMemo, useRef } from "react";
import { Library } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { getErrorMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import { COLLECTIONS_PAGE, useCollections } from "@/features/listening/queries";
import { COURSE_STATUS_LABEL } from "@/features/listening/practice";
import type { CourseStatus } from "@/features/listening/practice";
import {
  CollectionRow,
  CollectionRowSkeleton,
} from "@/features/listening/components/CollectionRow";

/**
 * The other list.
 *
 * Same column, same width, same rows-with-a-rule as the catalogue, because
 * the switch above them is a switch between two lists and not a link to
 * another page. What differs is what a row IS — a route through the library
 * rather than one paper — and the order they arrive in: in progress, then
 * untouched, then finished, so the thing somebody was in the middle of is the
 * first thing they see.
 *
 * Its one filter is the state a course is in for this reader — started, not
 * started, finished — which is the ordering asked as a question. Nothing else
 * the catalogue filters by applies: a part number, a task type and a
 * difficulty band all belong to a paper, not to a route through several.
 */
export function CollectionList({
  query,
  status,
  revealRef,
}: {
  /** The same field that searches the catalogue. Passed in already settled —
   *  the page holds the typing, this holds a list. */
  query: string;
  status: CourseStatus;
  revealRef?: (el: HTMLLIElement | null) => void;
}) {
  // Built exactly as the page builds it, so the two calls share one cache
  // entry and switching lists draws from what the strip already fetched.
  const params = useMemo(() => {
    const next: Record<string, string> = {};
    if (query.trim()) next.q = query.trim();
    if (status !== "all") next.status = status;
    return next;
  }, [query, status]);
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
  const narrowed = query.trim() !== "" || status !== "all";

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
          <ol>
            {Array.from({ length: 5 }, (_, i) => (
              <CollectionRowSkeleton key={i} />
            ))}
          </ol>
        </SkeletonBlock>
      </>
    );
  }

  return (
    <>
      <Header count={total} status={status} />

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
          <ol
            className={cn(
              "transition-opacity duration-fast",
              isPlaceholderData && "opacity-50",
            )}
          >
            {rows.map((collection, i) => (
              <CollectionRow
                key={collection.id}
                collection={collection}
                index={i + 1}
                revealRef={revealRef}
              />
            ))}
          </ol>

          {isFetchingNextPage && (
            <ol aria-hidden>
              <CollectionRowSkeleton />
              <CollectionRowSkeleton />
            </ol>
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
  loading,
}: {
  count?: number;
  status?: CourseStatus;
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
      {/* What the order is, or — once a status is picked — what the list has
          been narrowed to. The order stops being worth mentioning the moment
          everything in the list is the same one thing. */}
      <p className="text-xs text-muted-foreground">
        {status && status !== "all"
          ? COURSE_STATUS_LABEL[status]
          : "In progress first"}
      </p>
    </div>
  );
}

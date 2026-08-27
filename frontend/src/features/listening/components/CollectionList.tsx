import { useEffect, useMemo, useRef } from "react";
import { Library } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { getErrorMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import { COLLECTIONS_PAGE, useCollections } from "@/features/listening/queries";
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
 * It has no filters of its own and does not want any yet. A course has no
 * part number, no question type and no difficulty band; what it has is a
 * state (started, not started, finished) that the ordering already surfaces
 * better than a chip would.
 */
export function CollectionList({
  query,
  revealRef,
}: {
  /** The same field that searches the catalogue. Passed in already settled —
   *  the page holds the typing, this holds a list. */
  query: string;
  revealRef?: (el: HTMLLIElement | null) => void;
}) {
  const params = useMemo(
    () => (query.trim() ? { q: query.trim() } : {}),
    [query],
  );
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
  const searching = query.trim() !== "";

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
      <Header count={total} />

      {rows.length === 0 ? (
        <div className="mt-6 flex flex-col items-center gap-2 rounded-xl border border-border-subtle py-16 text-center">
          <Library className="size-6 text-muted-foreground/60" aria-hidden />
          {/* Two different facts, said differently. A search that found
              nothing is a state the reader put the page in; an empty library
              is a state the library is in, and telling somebody to search
              harder for something that does not exist is the page wasting
              their time. */}
          <p className="text-sm text-muted-foreground">
            {searching
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
function Header({ count, loading }: { count?: number; loading?: boolean }) {
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
      <p className="text-xs text-muted-foreground">In progress first</p>
    </div>
  );
}

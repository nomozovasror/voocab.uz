import { useEffect, useMemo, useRef } from "react";
import { Button } from "@/components/ui/button";
import { SkeletonBlock } from "@/components/ui/skeleton";
import { DrillGrid } from "@/features/listening/components/DrillGrid";
import {
  DrillRows,
  DrillRowsSkeleton,
} from "@/features/listening/components/DrillRows";
import { DRILL_PAGE, useDrills } from "@/features/listening/queries";
import { useRememberedChoice } from "@/lib/preferences";
import { getErrorMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { DrillPart, TaskFamily } from "@/features/listening/practice";

/**
 * Every drill of one kind — a list of question groups, not of materials.
 *
 * A row names the paper it was cut from and the numbers it carries there,
 * because that is what tells two maps apart: "Cambridge 16 Test 1" and
 * "Questions 15–20" are the whole of what a learner needs to know they have
 * not done this one. The clip's length is the other half — it is the promise
 * the row makes about how long this will take, so it is the CLIP's length and
 * never the recording's.
 */

/** Where a set of exercises stops being a list and starts being a map.
 *
 *  The collection page's number, for the collection page's reason: thirty is
 *  about a screenful of rows, below it every title is legible and above it the
 *  reader is scrolling past titles to find a shape. Only the DEFAULT —
 *  whichever they pick is remembered, and remembered per KIND, because four
 *  short-answer exercises and a hundred and eighty-eight multiple-choice ones
 *  are not the same decision.
 */
const GRID_FROM = 30;

const VIEWS = ["list", "grid"] as const;
type View = (typeof VIEWS)[number];

export function DrillList({
  family,
  query,
  part,
  showDone,
  revealRef,
}: {
  family: TaskFamily;
  /** Already settled — the page holds the typing, this holds a list. */
  query: string;
  part: DrillPart;
  showDone: boolean;
  revealRef?: (el: HTMLLIElement | null) => void;
}) {
  const params = useMemo(
    () => ({
      // The card's types, repeated on the wire — a card covering two kinds
      // asks for both in one query rather than merging two lists here, where
      // the paging and the totals would have to be merged too.
      type: family.types,
      ...(query.trim() ? { q: query.trim() } : {}),
      ...(part !== "all" ? { part } : {}),
      ...(showDone ? { done: true } : {}),
    }),
    [family, query, part, showDone],
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
  } = useDrills(params);

  const rows = useMemo(
    () => data?.pages.flatMap((page) => page.items) ?? [],
    [data],
  );
  const total = data?.pages[0]?.total ?? 0;
  const doneHidden = data?.pages[0]?.done_hidden ?? 0;

  const [view, setView] = useRememberedChoice<View>(
    `voocab-drill-view:${family.key}`,
    total >= GRID_FROM ? "grid" : "list",
    VIEWS,
  );

  // The map is only a map with every cell in it: numbered 1..30 and then
  // growing as you scroll is a grid whose numbers mean "how far you have
  // scrolled" rather than "which exercise". Cards page as you reach them,
  // the way every other list here does.
  useEffect(() => {
    if (view === "grid" && hasNextPage && !isFetchingNextPage) {
      void fetchNextPage();
    }
  }, [view, hasNextPage, isFetchingNextPage, fetchNextPage]);

  // The first one not done, in the order shown. Not a sequence anybody laid
  // out — these are not lessons — but "which do I do next" is still the
  // question the grid is most often opened with.
  const nextId = rows.find((row) => row.attempts === 0)?.group_id ?? null;

  // The same sentinel the catalogue and the shelf use, for the same reasons.
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
          {getErrorMessage(error) || "Couldn't load the exercises."}
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
      <SkeletonBlock label="Loading exercises">
        <DrillRowsSkeleton />
      </SkeletonBlock>
    );
  }

  return (
    <>
      <div className="mt-3 flex items-center justify-between gap-4 px-1">
        <p className="text-xs text-muted-foreground">
          <span className="tabular-nums text-foreground">{total}</span>{" "}
          {total === 1 ? "exercise" : "exercises"}
          {/* Never hide rows without saying so. */}
          {doneHidden > 0 && <> · {doneHidden} already done, put away</>}
        </p>
        {rows.length > 0 && <ViewToggle view={view} onChange={setView} />}
      </div>

      {rows.length === 0 ? (
        <div className="mt-3 rounded-xl border border-dashed border-border px-5 py-12 text-center">
          <p className="text-sm text-muted-foreground">
            {doneHidden > 0
              ? "You have done every one of these."
              : "Nothing here matches that."}
          </p>
        </div>
      ) : (
        <div
          className={cn(
            "transition-opacity duration-fast",
            isPlaceholderData && "opacity-50",
          )}
        >
          {view === "grid" ? (
            <DrillGrid items={rows} nextId={nextId} />
          ) : (
            <>
              <DrillRows
                items={rows}
                nextId={nextId}
                revealRef={revealRef}
              />
              {hasNextPage && (
                <div ref={bottom} aria-hidden className="h-8" />
              )}
              {!hasNextPage && total > DRILL_PAGE && (
                <p className="py-6 text-center text-xs text-muted-foreground">
                  That&apos;s all {total} of them.
                </p>
              )}
            </>
          )}
        </div>
      )}
    </>
  );
}

/** The same control the collection page uses, and deliberately identical:
 *  two grids in one app that are reached by two different-looking switches
 *  are two things to learn where there is one. */
function ViewToggle({
  view,
  onChange,
}: {
  view: View;
  onChange: (view: View) => void;
}) {
  return (
    <div
      role="group"
      aria-label="How to show the exercises"
      className="flex items-center gap-0.5 rounded-full bg-surface-sunken p-0.5"
    >
      {VIEWS.map((value) => (
        <Button
          key={value}
          type="button"
          variant="ghost"
          size="xs"
          aria-pressed={view === value}
          onClick={() => onChange(value)}
          className={cn(
            "rounded-full px-2.5 text-xs capitalize",
            view === value
              ? "bg-primary/15 text-primary hover:bg-primary/20 hover:text-primary"
              : "text-muted-foreground hover:bg-surface-hover hover:text-foreground",
          )}
        >
          {value}
        </Button>
      ))}
    </div>
  );
}

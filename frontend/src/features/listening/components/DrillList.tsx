import { useEffect, useMemo, useRef } from "react";
import { Link } from "react-router";
import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { QUESTION_TYPE_ICON } from "@/features/listening/parts";
import { DrillGrid } from "@/features/listening/components/DrillGrid";
import { DRILL_PAGE, useDrills } from "@/features/listening/queries";
import { useRememberedChoice } from "@/lib/preferences";
import { getErrorMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { DrillPart } from "@/features/listening/practice";
import type { PracticeDrill, QuestionGroupType } from "@/features/listening/types";

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

/** "2:14" — how long the clip runs. Minutes and seconds, because everything
 *  here is between about half a minute and eight, and a learner deciding
 *  whether to start one is asking a question about their next ten minutes. */
function clipLength(ms: number | null): string {
  if (ms == null) return "";
  const total = Math.round(ms / 1000);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/**
 * Cards on a grid rather than rows down the page.
 *
 * A drill row carries four short facts — the book, the numbers, the part, the
 * length — and none of them is long enough to earn a full line. Down a single
 * column that is a list three-quarters made of empty space, and eleven kinds
 * of task mean the reader is going to be looking at one of these often. Three
 * across puts a whole set of maps on one screen, which is the point of having
 * cut them out of their papers in the first place.
 */
const CARDS = "mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3";

/** Where a set of exercises stops being cards and starts being a map.
 *
 *  The collection page's number, for the collection page's reason: thirty is
 *  about a screenful, below it every title is legible and above it the reader
 *  is scrolling past titles to find a shape. Only the DEFAULT — whichever they
 *  pick is remembered, and remembered per KIND, because four short-answer
 *  drills and a hundred and eighty-eight multiple-choice ones are not the same
 *  decision. */
const GRID_FROM = 30;

const VIEWS = ["cards", "grid"] as const;
type View = (typeof VIEWS)[number];

export function DrillList({
  type,
  query,
  part,
  showDone,
  revealRef,
}: {
  type: QuestionGroupType;
  /** Already settled — the page holds the typing, this holds a list. */
  query: string;
  part: DrillPart;
  showDone: boolean;
  revealRef?: (el: HTMLLIElement | null) => void;
}) {
  const params = useMemo(
    () => ({
      type,
      ...(query.trim() ? { q: query.trim() } : {}),
      ...(part !== "all" ? { part } : {}),
      ...(showDone ? { done: true } : {}),
    }),
    [type, query, part, showDone],
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
    `voocab-drill-view:${type}`,
    total >= GRID_FROM ? "grid" : "cards",
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
        <ul className={CARDS}>
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-[5.5rem] rounded-xl" />
          ))}
        </ul>
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
              <ul className={CARDS}>
                {rows.map((drill) => (
                  <li key={drill.group_id} ref={revealRef}>
                    <DrillRow drill={drill} />
                  </li>
                ))}
              </ul>
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

function DrillRow({ drill }: { drill: PracticeDrill }) {
  const Icon = QUESTION_TYPE_ICON[drill.type];
  const done = drill.attempts > 0;
  return (
    <Link
      to={`/listening/drills/${drill.group_id}`}
      className={cn(
        "group flex h-full flex-col gap-1 rounded-xl border border-border-subtle bg-surface p-4",
        "transition-colors hover:border-border hover:bg-surface-hover",
        "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
      )}
    >
      <span className="flex items-start gap-2">
        <Icon
          className="mt-0.5 size-4 shrink-0 text-muted-foreground"
          aria-hidden
        />
        {/* Two lines, then clipped. A book and a test number is what tells two
            maps apart, and it does not fit on one line in a third of the
            column. */}
        <span className="line-clamp-2 min-w-0 flex-1 text-sm text-foreground">
          {drill.material_title}
        </span>
        {done && (
          <span className="flex shrink-0 items-center gap-1 text-xs text-correct">
            <Check className="size-3.5" aria-hidden />
            <span className="tabular-nums">
              {drill.best_score}/{drill.question_count}
            </span>
          </span>
        )}
      </span>

      <span className="mt-auto flex items-center gap-2 pt-2 text-xs text-muted-foreground">
        {/* The numbers the paper prints, not 1..N — the recording says these
            aloud. */}
        <span className="tabular-nums">
          Questions {drill.first_number}–{drill.last_number}
        </span>
        <span aria-hidden className="text-border">·</span>
        <span>Part {drill.part_number}</span>
        {drill.clip_ms != null && (
          <>
            <span aria-hidden className="text-border">·</span>
            <span className="tabular-nums">{clipLength(drill.clip_ms)}</span>
          </>
        )}
      </span>
    </Link>
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

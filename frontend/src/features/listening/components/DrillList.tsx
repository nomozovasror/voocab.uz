import { useEffect, useMemo, useRef } from "react";
import { Link } from "react-router";
import { ArrowRight, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { QUESTION_TYPE_ICON } from "@/features/listening/parts";
import { DRILL_PAGE, useDrills } from "@/features/listening/queries";
import { getErrorMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
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

export function DrillList({
  type,
  query,
  showDone,
  revealRef,
}: {
  type: QuestionGroupType;
  /** Already settled — the page holds the typing, this holds a list. */
  query: string;
  showDone: boolean;
  revealRef?: (el: HTMLLIElement | null) => void;
}) {
  const params = useMemo(
    () => ({
      type,
      ...(query.trim() ? { q: query.trim() } : {}),
      ...(showDone ? { done: true } : {}),
    }),
    [type, query, showDone],
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
          {getErrorMessage(error) || "Couldn't load the drills."}
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
      <SkeletonBlock label="Loading drills">
        <ul className="mt-3 space-y-2">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-[4.25rem] rounded-xl" />
          ))}
        </ul>
      </SkeletonBlock>
    );
  }

  return (
    <>
      <p className="mt-3 px-1 text-xs text-muted-foreground">
        <span className="tabular-nums text-foreground">{total}</span>{" "}
        {total === 1 ? "drill" : "drills"}
        {/* Never hide rows without saying so. */}
        {doneHidden > 0 && (
          <> · {doneHidden} already done, put away</>
        )}
      </p>

      {rows.length === 0 ? (
        <div className="mt-3 rounded-xl border border-dashed border-border px-5 py-12 text-center">
          <p className="text-sm text-muted-foreground">
            {doneHidden > 0
              ? "You have done every one of these."
              : "Nothing here matches that."}
          </p>
        </div>
      ) : (
        <>
          <ul
            className={cn(
              "mt-3 space-y-2 transition-opacity duration-fast",
              isPlaceholderData && "opacity-50",
            )}
          >
            {rows.map((drill) => (
              <li key={drill.group_id} ref={revealRef}>
                <DrillRow drill={drill} />
              </li>
            ))}
          </ul>
          {hasNextPage && <div ref={bottom} aria-hidden className="h-8" />}
          {!hasNextPage && total > DRILL_PAGE && (
            <p className="py-6 text-center text-xs text-muted-foreground">
              That&apos;s all {total} of them.
            </p>
          )}
        </>
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
        "group flex items-center gap-3 rounded-xl border border-border-subtle bg-surface px-4 py-3",
        "transition-colors hover:border-border hover:bg-surface-hover",
        "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
      )}
    >
      <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm text-foreground">
          {drill.material_title}
        </span>
        <span className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
          {/* The numbers the paper prints, not 1..N — the recording says
              these aloud. */}
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
      </span>
      {done && (
        <span className="flex shrink-0 items-center gap-1 text-xs text-correct">
          <Check className="size-3.5" aria-hidden />
          <span className="tabular-nums">
            {drill.best_score}/{drill.question_count}
          </span>
        </span>
      )}
      <ArrowRight
        className="size-4 shrink-0 text-muted-foreground/0 transition-colors group-hover:text-muted-foreground"
        aria-hidden
      />
    </Link>
  );
}

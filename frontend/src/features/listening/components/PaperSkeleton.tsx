import { Skeleton } from "@/components/ui/skeleton";

/**
 * The shapes a listening page holds open while its data is in flight.
 *
 * Every wrapper below repeats the real component's own class string rather
 * than a measured height. That is the only way the two can't drift: change
 * the padding on TakeAudio and the skeleton is wrong, unless the skeleton is
 * built out of the same box. Heights match by construction, not by luck.
 */

/** The recording's control box — see TakeAudio's outer div. */
export function AudioSkeleton() {
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3">
      <div className="flex items-center gap-3">
        <Skeleton className="size-9 shrink-0 rounded-full" />
        <Skeleton className="h-3 w-24" />
        <Skeleton className="ml-auto h-3 w-20" />
      </div>
      {/* 24px, not 4px. The real track is an `inline-block` range input
          sitting on a text baseline, so its wrapper is a line box — measured
          at 24px inside a 98px control. A bare 4px bar here left the paper
          below starting 22px too high. */}
      <div className="mt-3 flex h-6 items-center">
        <Skeleton className="h-1 w-full rounded-full" />
      </div>
    </div>
  );
}

/**
 * One part of the paper: its heading rule, then a few lines of questions.
 *
 * Two by default — not a claim about how many there are, which nothing knows
 * yet, but enough to reach the fold. One left a third of the viewport blank
 * below it, which is the empty page this was meant to replace. Real parts
 * append BELOW the fold when the data lands, moving nothing anyone is
 * already looking at.
 */
export function PaperSkeleton({ parts = 2 }: { parts?: number }) {
  return (
    <div className="space-y-10">
      {Array.from({ length: parts }, (_, i) => (
        <section key={i}>
          <h2 className="mb-4 border-b border-border pb-2 text-xs tracking-caps uppercase">
            <Skeleton className="inline-block h-[0.9em] w-16" />
          </h2>
          <div className="space-y-3">
            <Skeleton className="h-4 w-2/5" />
            {/* Uneven widths on purpose, and fixed rather than random: a
                stack of identical bars reads as a table, and a width that
                changed between renders would be a flicker. */}
            <Skeleton className="h-4 w-4/5" />
            <Skeleton className="h-4 w-3/5" />
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-4 w-1/2" />
          </div>
        </section>
      ))}
    </div>
  );
}

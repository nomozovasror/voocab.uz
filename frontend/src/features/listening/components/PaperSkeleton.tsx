import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import {
  PLAYER_DOCK_H,
  PLAYER_H,
} from "@/features/listening/components/TakeAudio";

/**
 * The shapes a listening page holds open while its data is in flight.
 *
 * Every wrapper below repeats the real component's own class string rather
 * than a measured height. That is the only way the two can't drift: change
 * the padding on TakeAudio and the skeleton is wrong, unless the skeleton is
 * built out of the same box. Heights match by construction, not by luck.
 */

/**
 * The recording's control box.
 *
 * Built from the player's own numbers rather than from measurements of it:
 * `PLAYER_H` is imported, and every row repeats the class the real one lays
 * out with — 72 of waveform, 4, 20 of part labels, 10, then a 50px control
 * row. Change the player and this either follows or fails to compile, which
 * is the only arrangement in which the paper below starts at the same y
 * before and after the material lands.
 */
export function PlayerSkeleton({
  settled,
  className,
}: {
  /** The review screen's player, which is small where it is and never grows
   *  — so the shape held open is the one row, not the tall card. */
  settled?: boolean;
  className?: string;
}) {
  if (settled) {
    return (
      <div
        style={{ height: PLAYER_DOCK_H }}
        // The docked row's own gutter and gaps: 12 of padding, the transport
        // cluster, the waveform in what is left, then the clock.
        className={cn(
          "flex items-center gap-2.5 rounded-xl border border-border bg-card px-3",
          className,
        )}
      >
        <Skeleton className="size-6 shrink-0 rounded-full" />
        <Skeleton className="h-8 w-8 shrink-0 rounded-md" />
        <Skeleton className="h-8 w-8 shrink-0 rounded-md" />
        <Skeleton className="h-1 min-w-0 flex-1 rounded-full" />
        <Skeleton className="h-8 w-8 shrink-0 rounded-md" />
        <Skeleton className="h-[0.9em] w-24 shrink-0" />
      </div>
    );
  }
  return (
    <div
      style={{ height: PLAYER_H }}
      className={cn(
        "rounded-xl border border-border bg-card px-3 pt-3",
        className,
      )}
    >
      {/* The waveform, drawn as one flat line — which is what the real one
          shows before its peaks have arrived anyway. */}
      <div className="flex h-18 items-center">
        <Skeleton className="h-1 w-full rounded-full" />
      </div>
      <div className="mt-1 flex h-5 items-center justify-center">
        <Skeleton className="h-[0.9em] w-16" />
      </div>
      {/* Play in the middle, the clock on the left, the switches on the
          right — the real row's three columns. */}
      <div className="mt-2.5 grid h-12 grid-cols-[1fr_auto_1fr] items-center">
        <Skeleton className="h-3.5 w-28" />
        <Skeleton className="size-12 rounded-full" />
        <Skeleton className="h-7 w-28 justify-self-end" />
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
          {/* The rule is above the heading, like the real one — a part is a
              break in a continuous paper, not a box around it. */}
          <h2 className="mb-4 flex items-baseline gap-3 border-t border-border pt-4 text-sm">
            <Skeleton className="inline-block h-[0.85em] w-14" />
            <Skeleton className="inline-block h-[0.75em] w-24" />
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

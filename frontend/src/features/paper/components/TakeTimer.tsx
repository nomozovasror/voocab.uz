import { cn } from "@/lib/utils";

/**
 * The clock above a paper, in whichever of its two meanings applies.
 *
 * ## Counting up is a measurement
 *
 * `14:20 / 20:00` — what this has taken, and what it is worth. Past the
 * second number the first turns amber and stops there: no red, no flashing,
 * no banner. Practice is where somebody finds out they read slowly, and a
 * page that panics at them for it has changed what practice is for. The
 * honest version of this feedback is a number that goes on counting in a
 * colour that means "look at me", which they can ignore for as long as they
 * like and will not be able to ignore afterwards.
 *
 * It stops when they are not there (`away`), because a measurement that
 * counts the tea break is measuring the tea break.
 *
 * ## Counting down is a constraint
 *
 * The exam's clock, and it is copied from the one the real computer-delivered
 * test shows rather than designed:
 *
 * - **Minutes only.** No seconds, ever. The real test hides them deliberately
 *   — a candidate watching a second hand in the last minute is a candidate
 *   not reading — and the last minute reads "< 1 min" rather than counting
 *   itself out.
 * - **Two warnings**, at ten minutes and at five, and they FLASH rather than
 *   merely change colour. A colour change is something you notice when you
 *   happen to look up; the warning has to reach somebody whose eyes are on
 *   the passage.
 * - **It does not stop.** Not for a hidden tab, not for an idle mouse. The
 *   real one does not.
 */

interface TakeTimerProps {
  mode: "countUp" | "countDown";
  /** Count-up: what has been spent. Count-down: what is left. Either way,
   *  milliseconds, and never negative. */
  ms: number;
  /** Count-up only: what the paper is worth, for the second number. */
  targetMs?: number | null;
  /** Count-up only: the clock is stopped because nobody is there. */
  away?: boolean;
  className?: string;
}

/** When the countdown starts asking to be looked at. Ten minutes, then five
 *  — the two the real test gives. */
const WARN_MS = [10 * 60_000, 5 * 60_000];

export function TakeTimer({
  mode,
  ms,
  targetMs,
  away,
  className,
}: TakeTimerProps) {
  if (mode === "countDown") {
    const left = Math.max(0, ms);
    const warning = WARN_MS.find((at) => left <= at) !== undefined;
    return (
      <p
        // Polite, not assertive: it changes every minute, and a screen reader
        // interrupting a sentence to say "fourteen minutes" is the audible
        // version of the flashing this page is careful about.
        aria-live="polite"
        className={cn(
          "shrink-0 text-sm font-medium tabular-nums",
          warning ? "text-destructive motion-safe:animate-pulse" : "text-foreground",
          className,
        )}
      >
        {minutesLeft(left)}
      </p>
    );
  }

  const over = targetMs != null && ms > targetMs;
  return (
    <p
      className={cn(
        "shrink-0 text-sm tabular-nums",
        over ? "text-attention" : "text-muted-foreground",
        className,
      )}
      title={
        away
          ? "Paused — the clock counts the time you are here"
          : targetMs != null
            ? "Time spent, and what this passage is worth"
            : undefined
      }
    >
      <span className={cn(away && "opacity-50")}>{clock(ms)}</span>
      {targetMs != null && (
        <span className="text-muted-foreground"> / {clock(targetMs)}</span>
      )}
    </p>
  );
}

/** `m:ss`, and `h:mm:ss` only once there is an hour to show. A leading zero
 *  on the minutes would make a five-minute paper read like a stopwatch. */
function clock(ms: number): string {
  const total = Math.floor(Math.max(0, ms) / 1000);
  const seconds = total % 60;
  const minutes = Math.floor(total / 60) % 60;
  const hours = Math.floor(total / 3600);
  const mm = hours > 0 ? String(minutes).padStart(2, "0") : String(minutes);
  return `${hours > 0 ? `${hours}:` : ""}${mm}:${String(seconds).padStart(2, "0")}`;
}

/** Whole minutes remaining, and never a number below one.
 *
 *  Rounded UP: with fifty seconds left the paper still has a minute on it in
 *  every sense a candidate cares about, and "0 min" beside a page that still
 *  accepts answers is the clock disagreeing with the page. */
function minutesLeft(ms: number): string {
  if (ms <= 0) return "Time is up";
  const minutes = Math.ceil(ms / 60_000);
  return minutes <= 1 ? "< 1 min" : `${minutes} min`;
}

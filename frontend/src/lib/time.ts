/** A position in a recording, as a player prints it: `4:07`. Rounds down, so
 *  the clock never shows a second the audio hasn't reached. */
export function fmtClock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** Tiny local "time ago" formatter — no date library, matches the mockup's
 *  vocabulary ("2h ago", "yesterday", "3d ago", "last week", "2 weeks ago"). */
export function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diffMs = Date.now() - then;
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  const week = 7 * day;

  if (diffMs < minute) return "just now";
  if (diffMs < hour) {
    const m = Math.floor(diffMs / minute);
    return `${m}m ago`;
  }
  if (diffMs < day) {
    const h = Math.floor(diffMs / hour);
    return `${h}h ago`;
  }
  if (diffMs < 2 * day) return "yesterday";
  if (diffMs < week) {
    const d = Math.floor(diffMs / day);
    return `${d}d ago`;
  }
  if (diffMs < 2 * week) return "last week";
  const w = Math.floor(diffMs / week);
  return `${w} weeks ago`;
}

/** The reader's own IANA zone, for the vocabulary practice module's daily
 *  time budget — "today" ends at midnight where THEY are, not where the
 *  server or its database happen to sit. Falls back to the same default the
 *  server documents for a caller that sends no `tz` at all, which is the one
 *  browser environment old enough not to answer this. */
export function localTimeZone(): string {
  try {
    return (
      Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Tashkent"
    );
  } catch {
    return "Asia/Tashkent";
  }
}

/** "in 12 minutes", "tomorrow", "in 3 days" — deliberately this coarse. The
 *  practice end screen's "next session" line is a nudge to come back, not a
 *  clock; a learner does not need to know it is 14:32:07, and printing that
 *  would make an estimate (FSRS intervals are never exact to the second)
 *  look like a promise. Past due prints as "now" rather than a negative
 *  duration, which is the ordinary case for a review that was already
 *  waiting when this session started. */
export function timeUntil(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diffMs = then - Date.now();
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;

  if (diffMs <= minute) return "now";
  if (diffMs < hour) return `in ${Math.round(diffMs / minute)}m`;
  if (diffMs < day) return `in ${Math.round(diffMs / hour)}h`;
  if (diffMs < 2 * day) return "tomorrow";
  return `in ${Math.round(diffMs / day)}d`;
}

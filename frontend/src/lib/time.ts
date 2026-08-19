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

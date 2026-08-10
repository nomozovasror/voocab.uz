/** Shared formatting for the Listening Studio (list now, editor next — kept
 *  here so both phases read the same vocabulary instead of drifting). */

/** "3:42" from milliseconds, or null when there's no duration to show. */
export function formatClock(ms: number | null | undefined): string | null {
  if (ms == null) return null;
  const totalSeconds = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** "form_completion" -> "form completion". */
export function formatQuestionType(type: string): string {
  return type.replace(/_/g, " ");
}

/** "1.2h" from milliseconds, always one decimal place. */
export function formatHours(ms: number): string {
  const hours = ms / 3_600_000;
  if (hours < 0.05) return "0h";
  return `${hours.toFixed(1)}h`;
}

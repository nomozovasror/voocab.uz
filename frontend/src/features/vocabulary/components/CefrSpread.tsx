import { CEFR_LEVELS, CEFR_TONE } from "@/features/vocabulary/cefr";
import { cn } from "@/lib/utils";

/**
 * A list's CEFR distribution as one proportional bar, the review page's
 * level bar without the filtering. Every level wears its colour — the letters are
 * printed in every segment, so colour never carries the fact alone.
 * Unrated words are not a segment (an unrated word is not a level); they
 * are said in words beside the bar.
 */
export function CefrSpread({
  counts,
  className,
}: {
  counts: Record<string, number>;
  className?: string;
}) {
  const present = CEFR_LEVELS.filter((l) => (counts[l] ?? 0) > 0);
  const unrated = counts.unrated ?? 0;
  if (!present.length && !unrated) return null;
  return (
    <div className={className}>
      {present.length > 0 && (
        <ul aria-label="Words by CEFR level" className="flex h-8 gap-1">
          {present.map((l) => (
            <li
              key={l}
              style={{ flexGrow: counts[l], flexBasis: 0 }}
              className={cn(
                "flex min-w-14 items-center justify-between rounded-md px-2.5 font-mono text-xs",
                CEFR_TONE[l].chip,
              )}
            >
              <span className="font-medium">{l}</span>
              <span className="tabular-nums opacity-75">
                <span className="sr-only"> words: </span>
                {counts[l].toLocaleString("en-US")}
              </span>
            </li>
          ))}
        </ul>
      )}
      {unrated > 0 && (
        <p className="mt-2 text-xs text-muted-foreground">
          {unrated.toLocaleString("en-US")} not yet rated
        </p>
      )}
    </div>
  );
}

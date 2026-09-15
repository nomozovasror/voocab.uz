import { ArrowDown } from "lucide-react";
import { cn } from "@/lib/utils";

export type ReviewScope = "mistakes" | "all";

/**
 * Which questions to show, and the shortcut to the next one that went wrong.
 *
 * **`Mistakes only` is the default**, and that is the page taking a position:
 * somebody who has just been marked is here to find out what they got wrong,
 * and a forty-question paper with twelve mistakes in it makes them scroll
 * past twenty-eight right answers to find each one. The right ones are still
 * there, one click away, for the reader who wants to check their working —
 * which is a different visit, and a rarer one.
 *
 * The chip is **locked to `All questions` on a clean sheet**. "Mistakes only"
 * over nothing is an empty page where a congratulation belongs, and a filter
 * that can be switched to a view with nothing in it is a control that can be
 * used to break the page.
 */
export function ReviewFilter({
  scope,
  onScope,
  mistakes,
  total,
  onNextMistake,
}: {
  scope: ReviewScope;
  onScope: (scope: ReviewScope) => void;
  mistakes: number;
  total: number;
  /** Absent when there is nothing left to jump to — either nothing went
   *  wrong, or the reader is already at the last one. */
  onNextMistake?: () => void;
}) {
  const locked = mistakes === 0;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Chip
        on={scope === "mistakes"}
        disabled={locked}
        onClick={() => onScope("mistakes")}
      >
        Mistakes only
        <Count n={mistakes} on={scope === "mistakes"} />
      </Chip>
      <Chip on={scope === "all"} onClick={() => onScope("all")}>
        All questions
        <Count n={total} on={scope === "all"} />
      </Chip>

      {onNextMistake && (
        <button
          type="button"
          onClick={onNextMistake}
          className="ml-auto inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-surface-hover hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          Next mistake
          <ArrowDown className="size-3.5" aria-hidden />
        </button>
      )}
    </div>
  );
}

function Chip({
  on,
  disabled,
  onClick,
  children,
}: {
  on: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
        on
          ? "bg-primary/10 text-primary"
          : "bg-surface-sunken text-muted-foreground hover:bg-surface-hover hover:text-foreground",
        disabled && "pointer-events-none opacity-40",
      )}
    >
      {children}
    </button>
  );
}

/** The count inside the chip, so choosing between the two views is a decision
 *  made before clicking rather than after. */
function Count({ n, on }: { n: number; on: boolean }) {
  return (
    <span
      className={cn(
        "tabular-nums",
        on ? "text-primary/60" : "text-muted-foreground/60",
      )}
    >
      {n}
    </span>
  );
}

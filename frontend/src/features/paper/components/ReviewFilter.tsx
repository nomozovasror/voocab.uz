import { cn } from "@/lib/utils";

export type ReviewScope = "mistakes" | "all";

/**
 * Which questions to show, and where the marks actually went.
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
 *
 * **The right of the row is a finding, not a control.** It was a "next
 * mistake" button, which could be pressed exactly once: it scrolled the
 * list, and this row went up the page with everything else. What sits there
 * now is the one thing scrolling cannot tell anybody — which task the marks
 * went on — and it needs no pressing to say it.
 */
export function ReviewFilter({
  scope,
  onScope,
  mistakes,
  total,
  worst,
}: {
  scope: ReviewScope;
  onScope: (scope: ReviewScope) => void;
  mistakes: number;
  total: number;
  /** The task the most marks went on, where one of them clearly did —
   *  `worstTask` withholds it on a one-task paper, on a tie, and on a
   *  single slip, because each of those would be the page reading a pattern
   *  into noise. */
  worst?: { heading: string; wrong: number; total: number } | null;
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

      {worst && (
        <p className="ml-auto flex items-baseline gap-2 text-xs">
          <span className="text-muted-foreground">Most lost in</span>
          <span className="text-foreground/80">{worst.heading}</span>
          <span className="tabular-nums text-muted-foreground">
            {worst.total - worst.wrong}/{worst.total}
          </span>
        </p>
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

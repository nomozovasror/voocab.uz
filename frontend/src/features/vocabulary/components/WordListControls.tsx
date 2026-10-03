import { Link } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  formatProgress,
  pendingMessage,
  useListToggle,
} from "@/features/vocabulary/wordLists";

/** `owned / word_count`, with a bar. The bar is decoration for the number
 *  beside it, which a screen reader gets as the progressbar's own value. */
export function ListProgress({
  title,
  owned,
  total,
  className,
}: {
  title: string;
  owned: number;
  total: number;
  className?: string;
}) {
  const pct = total > 0 ? Math.min(100, (owned / total) * 100) : 0;
  return (
    <div className={cn("flex items-center gap-3", className)}>
      {total > 0 && (
      <div
        role="progressbar"
        aria-label={`${title}: words you have`}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={owned}
        aria-valuetext={`${owned} of ${total}`}
        className="h-1.5 flex-1 overflow-hidden rounded-full bg-foreground/10"
      >
        <div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
      </div>
      )}
      <span className="text-xs tabular-nums text-muted-foreground">
        {formatProgress(owned, total)}
      </span>
    </div>
  );
}

/** Start / Stop, and — right after Start, once — the note about words the
 *  learner saved themselves that come first. Announced politely. */
export function ListToggle({
  listKey,
  title,
  active,
  size = "sm",
}: {
  listKey: string;
  title: string;
  active: boolean;
  size?: "sm" | "default";
}) {
  const { start, stop, busy } = useListToggle(listKey);
  const note = active && start.data ? pendingMessage(title, start.data.pending_saved) : null;
  return (
    <>
      <Button
        type="button"
        size={size}
        variant={active ? "outline" : "default"}
        disabled={busy}
        aria-label={`${active ? "Stop" : "Start"} ${title}`}
        onClick={() => (active ? stop.mutate() : start.mutate())}
      >
        {active ? "Stop" : "Start"}
      </Button>
      <p
        role="status"
        aria-live="polite"
        className={cn(
          "basis-full text-xs text-muted-foreground",
          !note && "sr-only",
        )}
      >
        {note}
      </p>
    </>
  );
}

export function BackLink() {
  return (
    <Link
      to="/vocabulary"
      className="inline-flex items-center gap-1 rounded text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
    >
      <ChevronLeft className="size-3.5" aria-hidden />
      Vocabulary
    </Link>
  );
}


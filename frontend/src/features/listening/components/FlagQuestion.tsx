import { Flag } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Mark a question to come back to.
 *
 * Straight from the real paper, where it is one of the few things a candidate
 * is told to do: answer what you can, mark what you are unsure of, come back.
 * The mark itself is worth nothing — what makes it useful is that the strip
 * along the bottom shows it, so "the two I wasn't sure about" is a thing you
 * can see from anywhere on a four-screen paper.
 *
 * Quiet until it is used. Forty of these down a page, each with a background
 * and a border, would compete with the questions for the whole of the reader's
 * attention to say nothing at all. Flagged, it takes the warning colour and
 * stops being quiet, which is the only moment it has anything to say.
 */
export function FlagQuestion({
  number,
  flagged,
  onToggle,
  className,
}: {
  /** The number as printed, for the label — a screen reader saying "flag"
   *  forty times over says nothing about which one it is on. */
  number: string;
  flagged: boolean;
  onToggle: () => void;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={flagged}
      aria-label={
        flagged
          ? `Question ${number} is flagged for review`
          : `Flag question ${number} for review`
      }
      title={flagged ? "Flagged — press F to unflag" : "Flag for review (F)"}
      className={cn(
        "inline-flex size-6 shrink-0 items-center justify-center rounded-md align-middle transition-colors duration-fast",
        "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
        flagged
          ? "text-attention hover:bg-surface-hover"
          : "text-muted-foreground/40 hover:bg-surface-hover hover:text-muted-foreground",
        className,
      )}
    >
      <Flag className="size-3.5" strokeWidth={flagged ? 2.5 : 2} aria-hidden />
    </button>
  );
}

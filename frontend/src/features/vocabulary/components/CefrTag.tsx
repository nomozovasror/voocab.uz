import { cn } from "@/lib/utils";
import { asLevel, toneOf } from "@/features/vocabulary/cefr";

/**
 * A word's level, wherever a word is shown.
 *
 * Four screens print this — the lookup popover mid-paper, the review's
 * list, the saved-words page, and the passage's own header line — and they
 * printed it four different ways, all of them a grey outlined chip that
 * looked exactly like the part of speech next to it. One component so the
 * colour cannot drift, and so the RULE cannot be forgotten at a call site:
 * the letters are always drawn. See `features/vocabulary/cefr.ts`.
 *
 * Nothing at all where the wire sent no level. An unrated word gets no
 * chip rather than a grey one — a grey chip in a row of coloured ones
 * reads as a fourth, easiest level, and what it actually means is that
 * nobody has said.
 */
export function CefrTag({
  level,
  className,
}: {
  level: string | null | undefined;
  className?: string;
}) {
  if (!asLevel(level)) return null;
  return (
    <span
      className={cn(
        "rounded px-1.5 py-px text-[0.65rem] leading-[1.4] font-medium",
        toneOf(level).chip,
        className,
      )}
    >
      {level}
    </span>
  );
}

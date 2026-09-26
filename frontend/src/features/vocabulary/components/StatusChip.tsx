import { cn } from "@/lib/utils";
import {
  STATUS_CHIP_LABEL,
  STATUS_CHIP_TONE,
  statusChip,
} from "@/features/vocabulary/status";
import type { WordStatus } from "@/features/vocabulary/types";

/**
 * A word's standing — Known / In rotation / Set aside / Leech — wherever a
 * word is shown. One component, for the same reason `CefrTag` is one
 * component: the words list and the word page printed this chip
 * differently once, and the fixes brief is explicit that it must never be
 * confused with the row's ACTION menu (`Mark as known`, and so on) — a
 * filled grey pill reads as a fact about the word, not a button.
 *
 * Deliberately not `CefrTag`'s colours: the fixes brief's §7/§8 rule is a
 * grey scale (dim / normal / dimmer / accent), never green, red or a CEFR
 * hue — those name a verdict or a difficulty, and this names neither.
 */
export function StatusChip({
  status,
  className,
}: {
  status: WordStatus;
  className?: string;
}) {
  const chip = statusChip(status);
  return (
    <span
      className={cn(
        "rounded-full bg-foreground/5 px-1.5 py-px text-[0.65rem] leading-[1.4] font-medium",
        STATUS_CHIP_TONE[chip],
        className,
      )}
    >
      {STATUS_CHIP_LABEL[chip]}
    </span>
  );
}

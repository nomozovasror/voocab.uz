import { cn } from "@/lib/utils";
import { LAYERS, SWATCH, type LayerId } from "@/features/reading/layers";

/**
 * Which marking is on the passage, as four buttons in the header's middle
 * island.
 *
 * The same island the take screen's highlighter and text-size tools hold, and
 * that is the argument for putting it there: on the review the passage is
 * still half the screen, so a control that governs how the passage is drawn
 * belongs where the passage's controls were an hour ago. It also costs the
 * text nothing — the island is chrome.
 *
 * **A radio group, not four checkboxes.** Exactly one layer is on, always
 * (`features/reading/layers.ts` says why), and `aria-pressed` on four
 * independent-looking buttons would tell a screen reader they can be
 * combined. What this is, is one question with four answers.
 *
 * A layer with nothing in it is not drawn at all. A passage the extraction
 * never reached has no vocabulary, a reader who highlighted nothing has no
 * marks, and a clean sheet has no mistakes — and a button that turns on a
 * layer with nothing under it is the page inviting somebody to press
 * something that does nothing. Absence reads as "not this paper"; a disabled
 * button reads as "not you".
 */
export function ReviewLayers({
  layer,
  onLayer,
  counts,
}: {
  layer: LayerId;
  onLayer: (next: LayerId) => void;
  /** How many marks each layer would draw. Zero hides it — see above. */
  counts: Record<LayerId, number>;
}) {
  const shown = LAYERS.filter((one) => counts[one.id] > 0);
  // One layer left is not a choice, and a single pressed button that cannot
  // be unpressed is a label pretending to be a control.
  if (shown.length < 2) return null;

  return (
    <div
      role="radiogroup"
      aria-label="What to mark on the passage"
      className="flex shrink-0 items-center gap-0.5"
    >
      {shown.map((one) => (
        <button
          key={one.id}
          type="button"
          role="radio"
          aria-checked={layer === one.id}
          onClick={() => onLayer(one.id)}
          title={`${one.meaning} (${counts[one.id]})`}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs whitespace-nowrap transition-colors duration-fast focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
            // The same two tones as the take screen's tool row, measured
            // there: `--muted-foreground` on the island's ground is 2.17:1
            // and unreadable, so a quiet control is the foreground at 70%.
            layer === one.id
              ? "bg-primary/15 text-primary"
              : "text-foreground/70 hover:bg-surface-hover hover:text-foreground",
          )}
        >
          <span
            aria-hidden
            className={cn("size-2 shrink-0 rounded-[2px]", SWATCH[one.id])}
          />
          {/* Below the split there is no room for four labelled buttons
              between the way out and the account — the take screen folds its
              own third group at the same width, and for the same reason.

              What folds is the labels of the layers that are OFF. The one
              that is on keeps its name, so the row still says what the
              passage is showing rather than becoming four coloured squares
              and a puzzle. */}
          <span className={layer === one.id ? "inline" : "hidden lg:inline"}>
            {one.label}
          </span>
        </button>
      ))}
    </div>
  );
}

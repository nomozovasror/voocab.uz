import { cn } from "@/lib/utils";
import { LAYERS, type LayerId } from "@/features/reading/layers";

/**
 * Which marking is on the passage — and therefore what is listed beside it
 * — as four buttons in the header's middle island.
 *
 * The same island the take screen's highlighter and text-size tools hold, and
 * that is the argument for putting it there: on the review the passage is
 * still half the screen, so a control that governs how the passage is drawn
 * belongs where the passage's controls were an hour ago. It also costs the
 * text nothing — the island is chrome.
 *
 * **It is the only control.** There was a second one — two tabs over the
 * analysis panel, reading *Mistakes* and *Vocabulary* — and the two shared
 * both their words and their effect, since pressing a tab already moved the
 * layer with it. Two controls that do one thing is a reader deciding which
 * of them is the real one. The counts came here when the tabs went, because
 * *Vocabulary 88* is most of the reason to press it.
 *
 * **It looks like the app's own navigation, because it IS navigation.** The
 * same pill, the same uppercase chip, the same amber for the one you are on
 * — a reader who has used the header knows what these are without being
 * taught twice.
 *
 * There were coloured squares in front of the names, one per layer. They
 * were a legend for marks that are already on the passage six inches away,
 * and a legend is what you need when the thing itself is not in front of
 * you. Here it is: the red is on the answers, the amber on the words. What
 * the swatches actually did was make four navigation chips look like a
 * settings panel.
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
      className="flex shrink-0 items-center gap-1"
    >
      {shown.map((one) => (
        <button
          key={one.id}
          type="button"
          role="radio"
          aria-checked={layer === one.id}
          onClick={() => onLayer(one.id)}
          title={one.meaning}
          // The app's own nav link, to the class: see `Layout`.
          className={cn(
            "rounded-full px-3 py-1.5 text-xs font-medium tracking-wide whitespace-nowrap uppercase transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
            layer === one.id
              ? "bg-primary/10 text-primary"
              : "text-muted-foreground hover:bg-foreground/5 hover:text-foreground",
          )}
        >
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
          {/* How much is under it. Quiet, and beside the name rather than
              in a pill: it is the size of the thing, not a badge saying
              something needs attention.

              Hidden with the label below the split, where the whole row has
              to fit between the way out and the account — a bare number
              floating beside a coloured square is not information anybody
              can use. */}
          <span
            className={cn(
              "ml-1.5 tabular-nums opacity-55",
              layer === one.id ? "inline" : "hidden lg:inline",
            )}
          >
            {counts[one.id]}
          </span>
        </button>
      ))}
    </div>
  );
}

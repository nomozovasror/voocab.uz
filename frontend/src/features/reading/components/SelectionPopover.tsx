import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Check, Copy, StickyNote } from "lucide-react";
import { cn } from "@/lib/utils";
import { Swatch } from "@/features/reading/components/PassageTools";
import { MARK_COLOURS, MARK_MEANING } from "@/features/reading/highlights";
import type { MarkColour } from "@/features/reading/highlights";
import type { Selected } from "@/features/reading/selection";

/**
 * The fast path: what to do with the words under your finger.
 *
 * The tool row in the header is the path a reader can SEE — it is there
 * before they have selected anything and it is how they learn the tools
 * exist. This is the one they use afterwards, because it arrives where their
 * attention already is instead of at the top of the screen.
 *
 * Four things, and no more: three colours and a note are what a reader does
 * to a stretch of prose. Everything else on the row is about the PAGE — its
 * size, which side it is on, what the questions want — and a popover that
 * carried those too would be the row again, in the way.
 *
 * ## Copy is here because the real test has it
 *
 * Computer-delivered IELTS lets a candidate copy a word out of the passage
 * and paste it into a completion answer, and the reason is worth keeping in
 * mind: a gap-fill answer has to be spelt exactly, the words are already on
 * screen, and typing them again is an opportunity to get one wrong that the
 * paper never intended to test.
 *
 * ## Why it is placed rather than anchored
 *
 * Fixed to the selection's own rectangle, in a portal. Inside the pane it
 * would be clipped by the pane's `overflow`, and scrolled away by the
 * scroll that is about to happen — the selection stays where it is on
 * screen, and so should the thing offering to act on it.
 */

/**
 * The selected words onto the clipboard, by whichever route works.
 *
 * `navigator.clipboard` first, and `execCommand` after it — which is
 * deprecated and still the one that works here. The modern API refuses
 * whenever the document is not focused, and that is not an edge case on this
 * screen: the words are already selected, the reader's pointer is over a
 * popover, and any of the ordinary ways a window loses focus leaves them
 * pressing a button that silently does nothing.
 *
 * The old call copies THE SELECTION, which is exactly what is wanted and is
 * why it needs no permission: the user has already said which words by
 * selecting them.
 *
 * Synchronous on purpose. Both paths have to run inside the click, because
 * a clipboard write that has been awaited is a clipboard write the browser
 * no longer counts as a gesture.
 */
function copy(text: string): boolean {
  try {
    if (document.execCommand("copy")) return true;
  } catch {
    /* fall through */
  }
  // Fire and forget: by here the gesture is spent, and a rejection is the
  // reader's own selection still being theirs to copy by hand.
  void navigator.clipboard?.writeText(text).catch(() => {});
  return true;
}

export function SelectionPopover({
  selected,
  onMark,
  onNote,
}: {
  selected: Selected | null;
  onMark: (colour: MarkColour) => void;
  onNote: (at: Selected) => void;
}) {
  const [copied, setCopied] = useState(false);
  // Cleared whenever the selection changes, so the tick belongs to the copy
  // that was actually made rather than lingering over the next word.
  useEffect(() => setCopied(false), [selected]);

  if (!selected) return null;

  const { rect } = selected;
  // Above the words where there is room, below them where there is not.
  const above = rect.top > 96;

  return createPortal(
    <div
      // `pointer-events-auto` on the panel and none on the frame: a fixed
      // box over the passage would otherwise swallow the click that starts
      // the next selection.
      className="pointer-events-none fixed inset-0 z-50"
      aria-hidden={false}
    >
      <div
        className={cn(
          "pointer-events-auto absolute flex -translate-x-1/2 items-center gap-0.5 rounded-xl border border-border bg-card p-1 shadow-lg",
          above ? "-translate-y-full" : "translate-y-2",
        )}
        style={{
          left: Math.min(
            Math.max(rect.left + rect.width / 2, 120),
            window.innerWidth - 120,
          ),
          top: above ? rect.top - 6 : rect.bottom,
        }}
        // The selection survives a press on this: a pointerdown anywhere
        // else collapses it, and the panel would then be acting on nothing.
        onMouseDown={(e) => e.preventDefault()}
      >
        {MARK_COLOURS.map((colour) => (
          <button
            key={colour}
            type="button"
            title={MARK_MEANING[colour]}
            aria-label={MARK_MEANING[colour]}
            onClick={() => onMark(colour)}
            className="flex size-7 items-center justify-center rounded-lg transition-colors duration-fast hover:bg-surface-hover focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            <Swatch colour={colour} />
          </button>
        ))}

        <span aria-hidden className="mx-0.5 h-4 w-px bg-border" />

        <button
          type="button"
          title="Write a note on this"
          onClick={() => onNote(selected)}
          className="flex size-7 items-center justify-center rounded-lg text-muted-foreground transition-colors duration-fast hover:bg-surface-hover hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          <StickyNote className="size-3.5" aria-hidden />
        </button>
        <button
          type="button"
          title="Copy — for an answer that has to be spelt exactly"
          onClick={() => setCopied(copy(selected.text))}
          className={cn(
            "flex size-7 items-center justify-center rounded-lg transition-colors duration-fast hover:bg-surface-hover focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
            copied
              ? "text-correct"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {copied ? (
            <Check className="size-3.5" aria-hidden />
          ) : (
            <Copy className="size-3.5" aria-hidden />
          )}
        </button>
      </div>
    </div>,
    document.body,
  );
}

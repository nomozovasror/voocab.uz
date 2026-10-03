import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { BookOpen, Check, Copy, StickyNote } from "lucide-react";
import { cn } from "@/lib/utils";
import { Swatch } from "@/features/reading/components/PassageTools";
import { MARK_MEANING, MARK_STYLES } from "@/features/reading/highlights";
import type { MarkStyle } from "@/features/reading/highlights";
import { cardPoint, useFollow } from "@/features/reading/anchor";
import { LOOKUP_BUDGET, LOOKUP_WORDS } from "@/features/reading/lookups";
import type { Selected } from "@/features/reading/selection";

/**
 * The fast path: what to do with the words under your finger.
 *
 * The tool row in the header is the path a reader can SEE — it is there
 * before they have selected anything and it is how they learn the tools
 * exist. This is the one they use afterwards, because it arrives where their
 * attention already is instead of at the top of the screen.
 *
 * Three colours, a note, a copy, and — the one thing here that is about the
 * WORDS rather than the marking of them — a look-up. Everything else on the
 * tool row is about the PAGE: its size, which side it is on, what the
 * questions want. A popover carrying those too would be the row again, in
 * the way.
 *
 * ## Why Look up belongs here and not only up there
 *
 * It is the action a reader reaches for at the exact moment this appears.
 * They have just selected a word because they do not know it; the toolbar
 * is at the top of the screen and this is under their finger. The row keeps
 * its copy because that is where somebody LEARNS the feature exists, and
 * this is where they use it.
 *
 * The count travels with it. `Look up 2` is not decoration — a reader
 * deciding whether this word is worth one of three has to be able to see
 * how many are left without going back to the top of the screen.
 *
 * ## Copy is here because the real test has it
 *
 * Computer-delivered IELTS lets a candidate copy a word out of the passage
 * and paste it into a completion answer, and the reason is worth keeping in
 * mind: a gap-fill answer has to be spelt exactly, the words are already on
 * screen, and typing them again is an opportunity to get one wrong that the
 * paper never intended to test.
 *
 * ## Why it is portalled, and how it still follows
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
  onLookup,
  lookupLeft,
  lookupFree,
  allowLookup,
}: {
  selected: Selected | null;
  onMark: (style: MarkStyle) => void;
  onNote: (at: Selected) => void;
  onLookup: (
    word: string,
    where: { paragraphIndex: number; offset: number },
    rect: DOMRect,
  ) => void;
  /** How many of the three are left. Shown on the button, because that is
   *  the number the decision is made against. */
  lookupLeft: number;
  /** This word has been opened before on this passage, so it costs nothing
   *  — and the button says so rather than leaving a reader to husband a
   *  look-up they would not be charged for. */
  lookupFree: boolean;
  /** False in an exam, where the control is absent rather than disabled. */
  allowLookup: boolean;
}) {
  const [copied, setCopied] = useState(false);
  // Cleared whenever the selection changes, so the tick belongs to the copy
  // that was actually made rather than lingering over the next word.
  useEffect(() => setCopied(false), [selected]);

  const rect = selected?.rect;
  // Above the words where there is room, below them where there is not —
  // decided when the selection is made and not again while the page scrolls,
  // so the bar never hops across the words.
  const above = useMemo(() => (rect ? rect.top > 96 : false), [rect]);
  const barRef = useRef<HTMLDivElement>(null);
  useFollow(barRef, rect, (b) =>
    cardPoint(b, above, window.innerWidth, 120, { above: 6, below: 0 }),
  );

  if (!selected) return null;

  const words = selected.text.trim().split(/\s+/).length;
  // Absent for a long selection rather than greyed out. Somebody who has
  // dragged across three sentences is reading them, not asking what they
  // mean, and a disabled control would answer a question they never asked.
  const askable = allowLookup && words <= LOOKUP_WORDS;
  const spent = lookupLeft === 0 && !lookupFree;

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
        ref={barRef}
        // The selection survives a press on this: a pointerdown anywhere
        // else collapses it, and the panel would then be acting on nothing.
        onMouseDown={(e) => e.preventDefault()}
      >
        {MARK_STYLES.map((colour) => (
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
        {askable && (
          <>
            <span aria-hidden className="mx-0.5 h-4 w-px bg-border" />
            <button
              type="button"
              disabled={spent}
              title={
                lookupFree
                  ? "Already looked up — this one is free"
                  : spent
                    ? `No look-ups left — ${LOOKUP_BUDGET} a passage`
                    : "What does this mean here?"
              }
              onClick={() =>
                onLookup(
                  selected.text.trim(),
                  {
                    paragraphIndex: selected.where.index,
                    offset: selected.where.start,
                  },
                  // The same box this popover is hanging off, so the answer
                  // arrives where the question was asked.
                  selected.rect,
                )
              }
              className={cn(
                "flex h-7 items-center gap-1 rounded-lg px-1.5 text-[0.7rem] transition-colors duration-fast focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                spent
                  ? "text-muted-foreground opacity-40"
                  : "text-muted-foreground hover:bg-surface-hover hover:text-foreground",
              )}
            >
              <BookOpen className="size-3.5" aria-hidden />
              {lookupFree ? "Free" : lookupLeft}
            </button>
          </>
        )}

        <span aria-hidden className="mx-0.5 h-4 w-px bg-border" />

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

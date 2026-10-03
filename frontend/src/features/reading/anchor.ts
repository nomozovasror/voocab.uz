import { useLayoutEffect, type RefObject } from "react";

/**
 * Keeping a fixed card on the words it is about.
 *
 * Both popovers (the selection tools and the dictionary card) are portalled
 * to `document.body` and `position: fixed`, because inside a pane they would
 * be clipped by its `overflow`. The cost is that they know nothing about
 * scrolling: placed once from a rect, they stay put while the words move
 * away underneath. A reader with a card too tall for the screen WANTS to
 * scroll to see the rest of it, so the card has to ride along.
 */

export interface Box {
  top: number;
  bottom: number;
  left: number;
  width: number;
  height: number;
}

export function toBox(r: DOMRect): Box {
  return {
    top: r.top,
    bottom: r.bottom,
    left: r.left,
    width: r.width,
    height: r.height,
  };
}

/** Shift a box by a delta. The anchor math in one pure place. */
export function shifted(box: Box, dx: number, dy: number): Box {
  return {
    top: box.top + dy,
    bottom: box.bottom + dy,
    left: box.left + dx,
    width: box.width,
    height: box.height,
  };
}

/** The live box: where the anchor element is now, plus how far the original
 *  box sat from it when the card opened (a selection is not its paragraph). */
export function followBox(
  opened: Box,
  anchorThen: Box,
  anchorNow: Box,
): Box {
  return shifted(
    opened,
    anchorNow.left - anchorThen.left,
    anchorNow.top - anchorThen.top,
  );
}

/** Above or below — decided ONCE, when the card opens. Re-deciding on every
 *  scroll frame would flip the card from one side of the word to the other
 *  as it crossed a threshold, which is exactly the jump a reader scrolling
 *  to see a tall card must not get. Above only when below does not fit and
 *  above does. */
export function opensAbove(
  box: Box,
  viewportHeight: number,
  below: number,
  above: number,
): boolean {
  return box.bottom + below > viewportHeight && box.top > above;
}

/** Horizontal clamp only, vertical follows the word wherever it goes. */
export function cardPoint(
  box: Box,
  above: boolean,
  viewportWidth: number,
  half: number,
  gap: { above: number; below: number },
): { left: number; top: number } {
  return {
    left: Math.min(
      Math.max(box.left + box.width / 2, half),
      viewportWidth - half,
    ),
    top: above ? box.top - gap.above : box.bottom + gap.below,
  };
}

/** The element that moves with the text under a point: the word, or failing
 *  that its paragraph. A Range would be tidier and does not survive the
 *  passage re-rendering its marks, which splits the text nodes under it. */
function anchorAt(box: Box): HTMLElement | null {
  const hit = document.elementFromPoint(
    box.left + box.width / 2,
    box.top + box.height / 2,
  );
  return (
    hit?.closest<HTMLElement>("[data-word]") ??
    hit?.closest<HTMLElement>("[data-paragraph-index]") ??
    null
  );
}

/**
 * Place `ref` at `point(box)` and keep placing it as any scroll container or
 * the window moves.
 *
 * Capture on `window`, because `scroll` does not bubble: the passage pane,
 * the review page and the window all scroll independently and this has to
 * hear every one. One rAF per frame at most, writing only `left` and `top`
 * — no reads except the anchor's rect, no transitions, so there is nothing
 * to switch off under `prefers-reduced-motion`: the card is simply where the
 * word is on every frame, not animated towards it.
 *
 * When the word scrolls out of its container the card goes with it; closing
 * is the reader's business (Esc, the close button).
 */
export function useFollow(
  ref: RefObject<HTMLElement | null>,
  rect: DOMRect | null | undefined,
  point: (box: Box) => { left: number; top: number },
) {
  useLayoutEffect(() => {
    const card = ref.current;
    if (!card || !rect) return;
    const opened = toBox(rect);
    const anchor = anchorAt(opened);
    const then = anchor ? toBox(anchor.getBoundingClientRect()) : null;
    let last = opened;

    const apply = () => {
      if (anchor && then && anchor.isConnected) {
        last = followBox(
          opened,
          then,
          toBox(anchor.getBoundingClientRect()),
        );
      }
      const { left, top } = point(last);
      card.style.left = `${left}px`;
      card.style.top = `${top}px`;
    };
    apply();
    // Nothing to follow: stay put, as before.
    if (!anchor) return;

    let frame = 0;
    const schedule = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        apply();
      });
    };
    window.addEventListener("scroll", schedule, { capture: true, passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.removeEventListener("scroll", schedule, { capture: true });
      window.removeEventListener("resize", schedule);
      if (frame) cancelAnimationFrame(frame);
    };
    // `point` is a closure over per-open constants; the rect is the identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rect]);
}

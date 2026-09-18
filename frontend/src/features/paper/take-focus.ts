import { useEffect, useState } from "react";

/**
 * Moving around the paper: which question is being worked on, and how to get
 * to another one.
 *
 * The navigator along the bottom and the paper itself are two views of one
 * position, and neither of them holds it. The DOM does: every question marks
 * its own visible container with `data-q-anchor`, and everything here works
 * off that attribute. A register of refs threaded up from three different
 * group components would say the same thing and be wrong the first time
 * somebody added a fourth.
 */

/** The attribute a group component puts on the visible box around one
 *  question — the fieldset for multiple choice, the row for matching, the
 *  gap's own span inside a form. Not the input: a multiple-choice input is
 *  `sr-only`, and scrolling to a one-pixel box lands nowhere. */
export const Q_ANCHOR = "data-q-anchor";

export function questionAnchor(id: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`[${Q_ANCHOR}="${CSS.escape(id)}"]`);
}

/**
 * Go to a question: put it on screen and give it the focus.
 *
 * Centred rather than scrolled to the top, and that is the whole reason this
 * is not `scrollIntoView()` with defaults: the page has a band stuck to the
 * top of it, and a question aligned to the top of the window arrives
 * underneath the band that sent you there.
 */
export function goToQuestion(id: string): void {
  const anchor = questionAnchor(id);
  if (!anchor) return;
  anchor.scrollIntoView({ behavior: "smooth", block: "center" });
  const field = anchor.querySelector<HTMLElement>(
    `input:not([disabled]), select:not([disabled]), textarea:not([disabled])`,
  );
  // `preventScroll`, because the smooth scroll above is already on its way
  // and focus would jump the page to the destination first.
  field?.focus({ preventScroll: true });
}

/**
 * Which question is being worked on.
 *
 * Focus first — somebody typing in question 12 is on question 12 wherever the
 * page happens to be scrolled. Otherwise the first question on screen, which
 * is what "where am I" means for someone reading rather than answering.
 *
 * The set of what is visible is KEPT rather than recomputed per callback: an
 * observer reports only what CHANGED, so a question tall enough to fill the
 * band stops being mentioned and a handler reading just the latest batch goes
 * on pointing at whichever one moved last.
 */
export function useQuestionSpy(ids: string[]): string | null {
  const [onScreen, setOnScreen] = useState<Set<string>>(() => new Set());
  const [focused, setFocused] = useState<string | null>(null);

  useEffect(() => {
    if (ids.length === 0) return;
    const visible = new Set<string>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const id = entry.target.getAttribute(Q_ANCHOR);
          if (!id) continue;
          if (entry.isIntersecting) visible.add(id);
          else visible.delete(id);
        }
        setOnScreen(new Set(visible));
      },
      // The upper half of the window, minus the band stuck to the top of it.
      // Narrow on purpose: the question under the reader's eye, not whatever
      // happens to be on the screen.
      { rootMargin: "-72px 0px -45% 0px" },
    );
    for (const id of ids) {
      const anchor = questionAnchor(id);
      if (anchor) observer.observe(anchor);
    }
    return () => observer.disconnect();
  }, [ids]);

  useEffect(() => {
    const onFocus = (event: FocusEvent) => {
      const target = event.target as HTMLElement | null;
      const anchor = target?.closest?.(`[${Q_ANCHOR}]`);
      const id = anchor?.getAttribute(Q_ANCHOR);
      if (id) setFocused(id);
    };
    window.addEventListener("focusin", onFocus);
    return () => window.removeEventListener("focusin", onFocus);
  }, []);

  // A question that has been scrolled away from is no longer where the reader
  // is, whatever still holds the focus.
  if (focused && onScreen.has(focused)) return focused;
  return ids.find((id) => onScreen.has(id)) ?? null;
}

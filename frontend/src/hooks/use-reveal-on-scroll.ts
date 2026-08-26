import { useCallback, useEffect, useRef } from "react";

/**
 * Marks elements as visible or not while they cross the viewport, so CSS can
 * animate them in and out.
 *
 * One observer for the whole list rather than one per row: a catalogue is a
 * few dozen rows and each of them holding its own observer is a few dozen
 * objects doing the same work against the same root.
 *
 * The state is written to `data-visible` on the element rather than to React
 * state, and that is the point — a list that re-rendered on every row crossing
 * the fold would be re-rendering constantly while somebody scrolls. Nothing in
 * the tree changes; only an attribute the stylesheet is watching.
 *
 * The observer is built on the first registration rather than in an effect,
 * because effects run after the refs are attached: an observer created there
 * would see its first entries a frame late, and every row already on screen
 * would skip its entrance.
 */
export function useRevealOnScroll(
  enabled = true,
  /** How much of an element must be showing before it counts as visible. */
  amount = 0.5,
) {
  const observer = useRef<IntersectionObserver | null>(null);

  useEffect(() => {
    return () => {
      observer.current?.disconnect();
      observer.current = null;
    };
  }, []);

  return useCallback(
    (element: HTMLElement | null) => {
      if (!element) return;

      // Nothing to animate, or nothing to animate with: show it and be done.
      // An element left hidden because IntersectionObserver is missing is a
      // row nobody can read.
      if (!enabled || typeof IntersectionObserver === "undefined") {
        element.dataset.visible = "true";
        return;
      }

      if (!observer.current) {
        observer.current = new IntersectionObserver(
          (entries) => {
            for (const entry of entries) {
              (entry.target as HTMLElement).dataset.visible = String(
                entry.isIntersecting,
              );
            }
          },
          { threshold: amount },
        );
      }
      const io = observer.current;
      io.observe(element);
      // React 19 calls a ref's returned cleanup when the element detaches,
      // which is how rows filtered out of the list stop being watched instead
      // of piling up inside the observer.
      return () => io.unobserve(element);
    },
    [enabled, amount],
  );
}

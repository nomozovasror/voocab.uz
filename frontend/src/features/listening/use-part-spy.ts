import { useEffect, useState } from "react";

/**
 * Which part is being read, for the chips in the header.
 *
 * A scroll position rather than a navigation step: every part is on the page
 * at once, and the chips are a way back to one, not a wizard.
 *
 * The set of what is on screen is KEPT rather than recomputed from each
 * callback. An observer reports only the sections whose visibility changed,
 * so a part tall enough to fill the whole band — one with a map in it — stops
 * being mentioned at all, and a handler that reads only the latest batch goes
 * on pointing at whichever part happened to change last.
 */
export function usePartSpy(parts: { id: string }[]): string | null {
  const [active, setActive] = useState<string | null>(null);

  useEffect(() => {
    if (parts.length < 2) return;
    const onScreen = new Set<string>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const id = entry.target.id.replace("part-", "");
          if (entry.isIntersecting) onScreen.add(id);
          else onScreen.delete(id);
        }
        // The first in the material's own order, not the one nearest the top
        // of the viewport: reading runs downwards, and a part half off the
        // top of the screen is still the part being read.
        setActive(parts.find((p) => onScreen.has(p.id))?.id ?? null);
      },
      // A band across the upper third. Narrow on purpose: the part under the
      // reader's eye, not whatever happens to be visible.
      { rootMargin: "-30% 0px -60% 0px" },
    );
    for (const part of parts) {
      const el = document.getElementById(`part-${part.id}`);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, [parts]);

  return active;
}

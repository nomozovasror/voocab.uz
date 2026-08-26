import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

/**
 * The middle of the header, held clear for a page.
 *
 * The nav lives there. A page with one control that stays on screen the whole
 * way down — the practice catalogue's search field, which sticks to the top —
 * needs the nav out of the way before it arrives, or the two would land on
 * each other.
 *
 * What crosses this boundary is a single boolean, and deliberately nothing
 * else. The field is never handed to the header to draw: it stays in the page
 * where it was written, sticks under its own `position: sticky`, and simply
 * ends up at the same height as the islands. That is what lets it *travel* —
 * an element that is re-parented arrives, and arriving is a cut. Moving is
 * what makes it read as one thing going somewhere rather than two things
 * swapping.
 */

interface HeaderCentre {
  claimed: boolean;
  claim: (claimed: boolean) => void;
}

const HeaderCentreContext = createContext<HeaderCentre | null>(null);

/** Layout side: `value` into the provider, `claimed` to style the nav. */
export function useHeaderCentreState() {
  const [claimed, setClaimed] = useState(false);
  const claim = useCallback((next: boolean) => setClaimed(next), []);
  const value = useMemo<HeaderCentre>(
    () => ({ claimed, claim }),
    [claimed, claim],
  );
  return { value, claimed };
}

export const HeaderCentreProvider = HeaderCentreContext.Provider;

/**
 * Page side: hold the centre clear while `active`.
 *
 * Released on unmount as well as on going inactive — navigating away
 * mid-scroll would otherwise leave the nav hidden for a field that no longer
 * exists. A page rendered outside a `Layout` (the studio has its own chrome)
 * finds no context and does nothing.
 */
export function useClaimHeaderCentre(active: boolean): void {
  const claim = useContext(HeaderCentreContext)?.claim;
  useEffect(() => {
    if (!claim) return;
    claim(active);
    return () => claim(false);
  }, [claim, active]);
}

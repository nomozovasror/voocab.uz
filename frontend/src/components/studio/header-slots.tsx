import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

/**
 * Lets a page put its own content in the Studio header.
 *
 * Two slots: `lead`, where the breadcrumbs normally sit, and `actions`, where
 * the notification and account buttons do. A page that claims a slot replaces
 * what was there — the editor's title belongs in the header rather than
 * repeated under a trail that already ends in it, and its publish button
 * belongs beside it rather than below the fold of a scrolling pane.
 *
 * Done with portals rather than by handing nodes up through context: the
 * content stays in the page's own tree, so its state, handlers and effects
 * work exactly as if it were rendered in place. Only the DOM node it lands in
 * comes from up here.
 *
 * Every function handed out is stable for the life of the provider, and that
 * is load-bearing rather than tidiness. `register` is used as a ref callback:
 * a new identity each render makes React detach and reattach the ref, which
 * sets state, which renders again — forever. `claim` is used in an effect
 * whose dependencies would change for the same reason, with the same result.
 */

type SlotName = "lead" | "actions";

interface HeaderSlots {
  lead: HTMLElement | null;
  actions: HTMLElement | null;
  claimed: { lead: number; actions: number };
  claim: (slot: SlotName, delta: number) => void;
  register: (slot: SlotName, el: HTMLElement | null) => void;
}

const HeaderSlotContext = createContext<HeaderSlots | null>(null);

export function StudioHeaderSlotProvider({ children }: { children: ReactNode }) {
  const [lead, setLead] = useState<HTMLElement | null>(null);
  const [actions, setActions] = useState<HTMLElement | null>(null);
  // Counted, not a boolean: during a route change the next page can claim a
  // slot before the previous one has released it, and a boolean would leave
  // the header showing nothing at all.
  const [claimed, setClaimed] = useState({ lead: 0, actions: 0 });

  const claim = useCallback((slot: SlotName, delta: number) => {
    setClaimed((prev) => ({
      ...prev,
      [slot]: Math.max(0, prev[slot] + delta),
    }));
  }, []);

  const register = useCallback((slot: SlotName, el: HTMLElement | null) => {
    // Guarded so re-rendering with the same node doesn't schedule a state
    // update that renders again.
    if (slot === "lead") setLead((prev) => (prev === el ? prev : el));
    else setActions((prev) => (prev === el ? prev : el));
  }, []);

  const value = useMemo<HeaderSlots>(
    () => ({ lead, actions, claimed, claim, register }),
    [lead, actions, claimed, claim, register],
  );

  return (
    <HeaderSlotContext.Provider value={value}>
      {children}
    </HeaderSlotContext.Provider>
  );
}

/** The header's own end: the slot targets to render, and whether a page has
 *  taken them over so the default content can step aside. */
export function useHeaderSlotTargets() {
  const ctx = useContext(HeaderSlotContext);
  const register = ctx?.register;

  const setLeadEl = useCallback(
    (el: HTMLElement | null) => register?.("lead", el),
    [register],
  );
  const setActionsEl = useCallback(
    (el: HTMLElement | null) => register?.("actions", el),
    [register],
  );

  return {
    setLeadEl,
    setActionsEl,
    leadTaken: (ctx?.claimed.lead ?? 0) > 0,
    actionsTaken: (ctx?.claimed.actions ?? 0) > 0,
  };
}

/**
 * A page's end. Claims the named slots for as long as the page is mounted and
 * hands back the two components that render into them.
 *
 *     const Header = useStudioHeader(["lead", "actions"]);
 *     <Header.Lead>…</Header.Lead>
 */
export function useStudioHeader(slots: SlotName[]) {
  const ctx = useContext(HeaderSlotContext);
  const claim = ctx?.claim;
  // Callers pass the array inline, so it is a new one every render; the join
  // is what makes the effect below depend on the contents instead.
  const key = slots.join(",");

  useEffect(() => {
    if (!claim) return;
    const names = key.split(",") as SlotName[];
    for (const name of names) claim(name, 1);
    return () => {
      for (const name of names) claim(name, -1);
    };
  }, [key, claim]);

  const lead = ctx?.lead ?? null;
  const actions = ctx?.actions ?? null;

  return useMemo(
    () => ({
      Lead: ({ children }: { children: ReactNode }) =>
        lead ? createPortal(children, lead) : null,
      Actions: ({ children }: { children: ReactNode }) =>
        actions ? createPortal(children, actions) : null,
    }),
    [lead, actions],
  );
}

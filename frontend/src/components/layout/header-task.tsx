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
 * The header, working for the page instead of the app.
 *
 * A page that fills the window has nowhere to put its own chrome. The
 * listening take screen solves that by scrolling: the player shrinks into
 * the header's middle island as the paper goes past, which is what
 * `header-center.tsx` is for — a boolean, the nav lifting out of the way,
 * and the page's own element travelling up under its own `sticky`.
 *
 * Reading cannot do any of that, because reading does not scroll. Two panes
 * hold their own scrollbars and the document never moves, so there is no
 * trigger and nothing to travel. What it needs instead is the header in a
 * different MODE from the moment the paper opens: the three islands stop
 * being the app's navigation and become this paper's controls, and stay
 * that way until the reader leaves.
 *
 * ## Why this hands over nodes, where the other one hands over a boolean
 *
 * `header-center` is careful not to re-parent anything, and the reason is
 * sound: an element that is re-parented mid-animation *arrives*, and
 * arriving reads as a cut where the design wants a movement. But that
 * argument is about a control in motion. Nothing here moves — the islands
 * are in task mode before the first paint and leave it when the page
 * unmounts — so there is no cut to avoid, and the page may as well put its
 * buttons where they belong.
 *
 * Through a PORTAL rather than through context state, and that part is not
 * a detail: the timer in the right island ticks once a second, and a node
 * passed through state would re-render the whole application shell — nav,
 * account menu and all — sixty times a minute to move one digit. A portal
 * re-renders the page's own subtree and writes into a div the header owns.
 */

export type TaskSide = "left" | "centre" | "right";

interface HeaderTask {
  /** Whether a page has taken the islands over. */
  active: boolean;
  setActive: (on: boolean) => void;
  slots: Record<TaskSide, HTMLElement | null>;
  /** One ref callback per side, and the SAME one every render.
   *
   *  A factory that built a closure per render looked tidier and hung the
   *  app: React detaches a ref whose identity changed and attaches the new
   *  one, so every render stored null and then the node again, and storing
   *  the node was a render. "Maximum update depth exceeded", on the first
   *  paint of the page. */
  binds: Record<TaskSide, (el: HTMLElement | null) => void>;
}

const HeaderTaskContext = createContext<HeaderTask | null>(null);

/** Layout side: `value` into the provider, `active` to switch the islands. */
export function useHeaderTaskState() {
  const [active, setActive] = useState(false);
  const [slots, setSlots] = useState<Record<TaskSide, HTMLElement | null>>({
    left: null,
    centre: null,
    right: null,
  });
  // Compared before setting as well: a ref callback still runs when the
  // element it is on is remounted, and storing the same node again would
  // loop for the same reason.
  const put = useCallback(
    (side: TaskSide, el: HTMLElement | null) =>
      setSlots((was) => (was[side] === el ? was : { ...was, [side]: el })),
    [],
  );
  const binds = useMemo<HeaderTask["binds"]>(
    () => ({
      left: (el) => put("left", el),
      centre: (el) => put("centre", el),
      right: (el) => put("right", el),
    }),
    [put],
  );
  const value = useMemo<HeaderTask>(
    () => ({ active, setActive, slots, binds }),
    [active, slots, binds],
  );
  return { value, active };
}

export const HeaderTaskProvider = HeaderTaskContext.Provider;

/**
 * Page side: hold the islands for as long as this component is mounted.
 *
 * Released on unmount as well, or navigating away would leave the app with
 * a back button to a paper nobody is sitting. A page rendered outside a
 * `Layout` — the studio has its own chrome — finds no context and does
 * nothing.
 */
export function useHeaderTask(active = true): void {
  const setActive = useContext(HeaderTaskContext)?.setActive;
  useEffect(() => {
    if (!setActive) return;
    setActive(active);
    return () => setActive(false);
  }, [setActive, active]);
}

/** Page side: draw these controls in one of the header's islands. */
export function HeaderSlot({
  side,
  children,
}: {
  side: TaskSide;
  children: ReactNode;
}) {
  const into = useContext(HeaderTaskContext)?.slots[side] ?? null;
  // Null until the layout has rendered the slot and the ref has run, which
  // is the render after `useHeaderTask` sets the mode. One frame with an
  // empty island, and no way for a page to draw into a header that is not
  // expecting it.
  return into ? createPortal(children, into) : null;
}

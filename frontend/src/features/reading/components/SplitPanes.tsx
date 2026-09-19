import { forwardRef, useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

/**
 * Two panes side by side, each scrolling on its own, with a divider the
 * reader can move.
 *
 * The shape of computer-delivered IELTS Reading, and it is a shape rather
 * than a decoration: the passage and the questions are read against each
 * other. One scroll, which is right for a listening paper, would mean
 * scrolling nine hundred words out of the way to reach question 9 and back
 * again to answer it.
 *
 * **The split is remembered, and it is not a preference.** `frontend/CLAUDE.md`
 * says preferences default to off and exist because somebody asked for the
 * behaviour; this is neither. It is the position of a thing on screen, like a
 * scroll position, and a reader who widened the passage once means it for the
 * next passage too.
 *
 * Below the breakpoint there is no split at all: two panes in 380px is two
 * columns of four words. What replaces it is a pair of tabs, which is the
 * same content addressed the only other way it can be.
 */

/** How the take screen finds the pane holding the passages, in either
 *  arrangement, so it can bring the right one into view as the reader moves
 *  down the questions. A DOM query rather than a ref threaded out through an
 *  imperative handle, for the reason `take-focus.ts` gives: the page already
 *  asks the document where the reader is, and one mechanism for "find the
 *  thing on screen" is better than two. */
export const LEFT_PANE = "data-left-pane";

const MIN_PERCENT = 25;
const MAX_PERCENT = 75;
const STORE_KEY = "voocab-reading-split";

function remembered(): number {
  try {
    const raw = Number(localStorage.getItem(STORE_KEY));
    if (Number.isFinite(raw) && raw >= MIN_PERCENT && raw <= MAX_PERCENT) {
      return raw;
    }
  } catch {
    /* private window, or site data switched off. The default is fine. */
  }
  return 50;
}

interface SplitPanesProps {
  left: React.ReactNode;
  right: React.ReactNode;
  /** What each side is called, for the tabs and for the divider's label. */
  leftLabel: string;
  rightLabel: string;
  /** False below the breakpoint, where the two become tabs instead. */
  split: boolean;
  /** Which side the tabs just put on screen. Only ever called in the tab
   *  arrangement — with a split there is no "showing", both are. Called
   *  AFTER the change has been painted, because a caller that wants to
   *  scroll the pane it has just revealed cannot measure it while it is
   *  still hidden. */
  onShowing?: (side: "left" | "right") => void;
  /** How tall the pair is, measured by the page from where they start. Null
   *  until the first measurement, which is one frame. */
  height: number | null;
  className?: string;
}

export const SplitPanes = forwardRef<HTMLDivElement, SplitPanesProps>(
  function SplitPanes(
    { left, right, leftLabel, rightLabel, split, onShowing, height, className },
    outerRef,
  ) {
  const [percent, setPercent] = useState(remembered);
  const [showing, setShowing] = useState<"left" | "right">("right");
  const frame = useRef<HTMLDivElement | null>(null);
  const dragging = useRef(false);

  const put = useCallback((next: number) => {
    const clamped = Math.min(MAX_PERCENT, Math.max(MIN_PERCENT, next));
    setPercent(clamped);
    try {
      localStorage.setItem(STORE_KEY, String(Math.round(clamped)));
    } catch {
      /* nothing to do about it, and nothing depends on it */
    }
  }, []);

  // After the paint, not in the click handler: the pane being revealed is
  // still `hidden` at the moment the tab is pressed, and a hidden element
  // measures as nothing.
  useEffect(() => {
    if (split) return;
    onShowing?.(showing);
  }, [split, showing, onShowing]);

  useEffect(() => {
    if (!split) return;
    const onMove = (e: PointerEvent) => {
      if (!dragging.current || !frame.current) return;
      const box = frame.current.getBoundingClientRect();
      put(((e.clientX - box.left) / box.width) * 100);
    };
    const onUp = () => {
      dragging.current = false;
      document.body.style.removeProperty("cursor");
      document.body.style.removeProperty("user-select");
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [split, put]);

  if (!split) {
    return (
      <div
        ref={outerRef}
        style={height ? { height } : undefined}
        className={cn("flex min-h-0 flex-col", className)}
      >
        {/* Tabs rather than a stack, and rather than a split nobody can read.
            The strip along the bottom still numbers every question, so this
            is only ever "which of the two am I looking at". */}
        <div
          role="tablist"
          aria-label="Passage or questions"
          className="mb-3 flex shrink-0 gap-1 rounded-lg bg-surface-sunken p-1"
        >
          {(
            [
              ["left", leftLabel],
              ["right", rightLabel],
            ] as const
          ).map(([side, label]) => (
            <button
              key={side}
              type="button"
              role="tab"
              aria-selected={showing === side}
              onClick={() => setShowing(side)}
              className={cn(
                "flex-1 rounded-md px-3 py-1.5 text-sm transition-colors duration-fast focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                showing === side
                  ? "bg-card text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        {/* Both stay MOUNTED and one is hidden. The questions carry typed
            answers and the focus timing that measures them, and unmounting
            the pane to look something up in the passage would throw both
            away — see take-session. */}
        <div
          {...{ [LEFT_PANE]: "" }}
          className="min-h-0 flex-1 overflow-y-auto"
          hidden={showing !== "left"}
        >
          {left}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto" hidden={showing !== "right"}>
          {right}
        </div>
      </div>
    );
  }

  return (
    <div
      ref={(el) => {
        frame.current = el;
        if (typeof outerRef === "function") outerRef(el);
        else if (outerRef) outerRef.current = el;
      }}
      style={height ? { height } : undefined}
      className={cn("flex min-h-0", className)}
    >
      <div
        {...{ [LEFT_PANE]: "" }}
        className="min-w-0 overflow-y-auto pr-5"
        style={{ width: `${percent}%` }}
      >
        {left}
      </div>

      {/* A real control, not a decorated border: it is draggable with a
          pointer and movable with the arrow keys, because a reader who works
          by keyboard has the same reason to widen the passage. */}
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label={`Resize ${leftLabel} and ${rightLabel}`}
        aria-valuenow={Math.round(percent)}
        aria-valuemin={MIN_PERCENT}
        aria-valuemax={MAX_PERCENT}
        tabIndex={0}
        onPointerDown={(e) => {
          e.preventDefault();
          dragging.current = true;
          document.body.style.cursor = "col-resize";
          document.body.style.userSelect = "none";
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowLeft") put(percent - 2);
          else if (e.key === "ArrowRight") put(percent + 2);
          else return;
          e.preventDefault();
        }}
        onDoubleClick={() => put(50)}
        className="group relative w-px shrink-0 cursor-col-resize bg-border focus-visible:outline-none"
      >
        {/* The line is one pixel and the grab area is sixteen. A divider you
            have to hit exactly is a divider nobody moves twice. */}
        <span
          aria-hidden
          className="absolute inset-y-0 -left-2 -right-2 transition-colors duration-fast group-hover:bg-primary/20 group-focus-visible:bg-primary/30"
        />
      </div>

      <div className="min-w-0 flex-1 overflow-y-auto pl-5">{right}</div>
    </div>
  );
  },
);

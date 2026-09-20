import { useEffect, useRef, useState } from "react";

/**
 * How long the paper has been open, and how long anybody was actually there.
 *
 * Two numbers, because they are two different facts and only one of them is
 * worth measuring somebody by. A candidate who opens a passage, switches to
 * another tab for twenty minutes and comes back did not spend twenty-three
 * minutes reading it — but that is what the page recorded, and "time spent"
 * on the statistics page, the pace figure, and every per-question timing
 * that feeds "where you lose marks" were all reading it.
 *
 * ## What counts as being there
 *
 * Two signals, and they answer different questions.
 *
 * `document.visibilityState` is the certain one: a hidden tab is not being
 * read, there is nothing to argue about, and the browser tells us the moment
 * it happens.
 *
 * Idleness is the uncertain one, and reading is exactly the case that makes
 * it uncertain — somebody working through nine hundred words of prose may
 * not touch the mouse or the keyboard for a long time, and they are
 * concentrating rather than absent. So the threshold here is minutes rather
 * than the seconds an idle timer usually wants. Three of them: long enough
 * that a slow reader is never called away, short enough that a walk to the
 * kitchen is not counted as study.
 */

/** How long without a mouse, a key or a scroll before nobody is there.
 *
 *  Deliberately long. The cost of being wrong in one direction is a minute
 *  or two of over-counting; in the other it is telling a careful reader they
 *  were not reading. */
export const IDLE_MS = 3 * 60_000;

/** How often the clock is read. A second, because the display counts in
 *  seconds — anything finer is arithmetic nobody sees. */
const TICK_MS = 1_000;

/** How often the accumulated total is handed back for saving. Every tick
 *  would write to localStorage sixty times a minute to record a number that
 *  only matters if the tab dies. */
const SAVE_EVERY = 5;

/** What makes it look like somebody is there. Scroll is in `capture` because
 *  it does not bubble, and on this page the thing being scrolled is a pane
 *  rather than the window — a reader can work through a whole passage
 *  without another one of these firing. */
const SIGNS = [
  "pointermove",
  "pointerdown",
  "keydown",
  "wheel",
  "scroll",
] as const;

export interface ActiveTime {
  /** Wall clock since the attempt was started, across reloads. */
  elapsedMs: number;
  /** The part of it somebody was present for. */
  activeMs: number;
  /** Whether the clock is currently NOT counting — the tab is hidden, or
   *  nothing has moved for `IDLE_MS`. The take screen says so rather than
   *  letting a stopped number look like a broken one. */
  away: boolean;
}

export function useActiveTime({
  startedAt,
  activeFrom = 0,
  onSample,
}: {
  /** When the attempt began, as a timestamp that survives a reload. */
  startedAt: number;
  /** Active time already banked by an earlier visit to this draft. */
  activeFrom?: number;
  /** Handed the running total every few seconds, for whoever persists it. */
  onSample?: (activeMs: number) => void;
}): ActiveTime {
  const active = useRef(activeFrom);
  const lastTick = useRef(Date.now());
  const lastSign = useRef(Date.now());
  const ticks = useRef(0);
  // Held in a ref so the interval below never has to be torn down and rebuilt
  // when the caller re-renders with a new closure.
  const sample = useRef(onSample);
  sample.current = onSample;

  const [state, setState] = useState<ActiveTime>(() => ({
    elapsedMs: Math.max(0, Date.now() - startedAt),
    activeMs: activeFrom,
    away: false,
  }));

  useEffect(() => {
    const seen = () => {
      lastSign.current = Date.now();
    };
    for (const sign of SIGNS) {
      window.addEventListener(sign, seen, { passive: true, capture: true });
    }
    // Coming BACK counts as a sign of life on its own. Without this, a reader
    // who returns to the tab and reads for two minutes before touching
    // anything is still counted as idle from before they left.
    const returned = () => {
      if (document.visibilityState === "visible") seen();
    };
    document.addEventListener("visibilitychange", returned);

    const id = window.setInterval(() => {
      const now = Date.now();
      const since = now - lastTick.current;
      lastTick.current = now;

      const here =
        document.visibilityState === "visible" &&
        now - lastSign.current < IDLE_MS;
      // `since` rather than TICK_MS: a sleeping laptop or a throttled
      // background tab does not fire this on time, and adding the nominal
      // second would quietly under-count an hour into forty minutes.
      if (here) active.current += since;

      ticks.current += 1;
      if (ticks.current % SAVE_EVERY === 0) sample.current?.(active.current);

      setState({
        elapsedMs: Math.max(0, now - startedAt),
        activeMs: active.current,
        away: !here,
      });
    }, TICK_MS);

    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", returned);
      for (const sign of SIGNS) {
        window.removeEventListener(sign, seen, { capture: true });
      }
      // On the way out, whatever has not been saved yet. Leaving the page is
      // the one moment the unsaved seconds are certain to be lost.
      sample.current?.(active.current);
    };
  }, [startedAt]);

  return state;
}

import { useEffect, useState } from "react";

/**
 * A value, held back until it stops changing.
 *
 * For the gap between what somebody is typing and what is worth acting on.
 * The input keeps the live value — a field that lags its own keystrokes is
 * a broken field — and whatever the typing COSTS reads this one instead.
 *
 * The catalogue's search is the case it was written for: the query is part
 * of a request now rather than a filter over an array already in hand, so
 * "riverside" typed at speed would be nine requests, eight of them answering
 * a question nobody finished asking.
 *
 * The first value passes through immediately (it is the initial state), and
 * every later one waits out `delay` of quiet. Clearing the field is not
 * special-cased: an empty query is a query like any other, and letting it
 * through early would make backspacing to nothing fetch the whole catalogue
 * on the way past.
 */
export function useDebounced<T>(value: T, delay: number): T {
  const [settled, setSettled] = useState(value);

  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), delay);
    // The cleanup is the whole mechanism: a change before the timer fires
    // cancels it, so only a pause long enough to be a pause gets through.
    return () => window.clearTimeout(timer);
  }, [value, delay]);

  return settled;
}

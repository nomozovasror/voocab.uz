import { useCallback, useEffect, useState } from "react";

/**
 * Small on/off choices a reader makes about how the interface behaves.
 *
 * In `localStorage`, like the theme, and for the same reason: these are about
 * this browser rather than about the account. Nothing here is worth a column,
 * a migration and a round trip, and a preference that fails to load because
 * the network did is worse than one that simply lives where it is read.
 *
 * The day one of these has to follow somebody between devices, it moves to
 * the user record and this hook keeps its shape — which is why the storage is
 * behind a hook at all rather than a `localStorage.getItem` at the call site.
 *
 * **Every one of these defaults to off.** A preference exists because
 * somebody wanted the behaviour, and a preference that is on before anybody
 * asked is not a preference, it is a behaviour with a switch attached.
 */

export const PREFERENCES = {
  /**
   * Let the cards beside the practice list follow whichever row is under the
   * pointer.
   *
   * Off by default. The swap is genuinely useful — it answers "is this hard,
   * have I done it, is it the part I keep losing marks on" without a click —
   * and it is also movement at the edge of vision every time the pointer
   * crosses the list on its way somewhere else. Which of those it is depends
   * on the reader, and the honest default for a thing that moves without
   * being asked is: it doesn't.
   *
   * With it off the panel stays what it is at rest — the reader's own
   * statistics — and the list is a list.
   */
  hoverPreview: "voocab-hover-preview",

  /**
   * Step over the dead air in a recording without being asked each time.
   *
   * Off by default, and the button in the player is the reason it can be. A
   * listening paper is largely quiet — the twenty and thirty second stretches
   * where a candidate reads ahead — and the switch on the player skips ONE of
   * them, the one that is happening. That is the right default: a jump the
   * reader asked for, when they asked for it.
   *
   * Turned on, every silence is stepped over automatically. That is a
   * different thing to want — it belongs to somebody who has decided how they
   * work, not to somebody meeting the feature — so it is a setting rather than
   * a second control on a player that is already full.
   */
  skipSilence: "voocab-skip-silence",
} as const;

export type PreferenceKey = (typeof PREFERENCES)[keyof typeof PREFERENCES];

function read(key: PreferenceKey): boolean {
  try {
    return localStorage.getItem(key) === "on";
  } catch {
    // Private windows and blocked site data both throw on access rather than
    // returning nothing. A preference is not worth a crash: the default is
    // the answer.
    return false;
  }
}

/**
 * One preference, and the setter that persists it.
 *
 * Reads once on mount rather than during render, so nothing here depends on
 * storage being available at the moment React first paints — and so the value
 * is the same on the server-rendered pass as it is on the client, if this
 * codebase ever has one.
 *
 * `storage` events are listened for so two tabs of the same app agree: turning
 * the preview on in one and going back to the other should not need a reload
 * to see it.
 */
export function usePreference(key: PreferenceKey): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(false);

  useEffect(() => {
    setOn(read(key));
    const onStorage = (event: StorageEvent) => {
      if (event.key === key) setOn(read(key));
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [key]);

  const set = useCallback(
    (next: boolean) => {
      setOn(next);
      try {
        localStorage.setItem(key, next ? "on" : "off");
      } catch {
        // Written where it can be; the session still behaves as asked.
      }
    },
    [key],
  );

  return [on, set];
}


/**
 * A remembered choice that is not a behaviour.
 *
 * The rule above — every preference defaults to off — is about behaviours:
 * something the interface does that nobody asked for. A view choice is not
 * one of those. It has no "off", and its default is worked out from what is
 * being looked at rather than from a principle: a collection of eight is a
 * list, a collection of two hundred is a grid, and the reader overriding
 * either should have that remembered.
 *
 * So it is a separate hook with an explicit fallback, and the caller decides
 * what the fallback is.
 */
function readChoice<T extends string>(
  key: string,
  allowed: readonly T[],
): T | null {
  let stored: string | null = null;
  try {
    stored = localStorage.getItem(key);
  } catch {
    // Private windows and blocked site data throw on access rather than
    // returning nothing. No choice is the answer.
  }
  return stored && (allowed as readonly string[]).includes(stored)
    ? (stored as T)
    : null;
}

export function useRememberedChoice<T extends string>(
  key: string,
  fallback: T,
  allowed: readonly T[],
): [T, (value: T) => void] {
  // Read on the first render rather than in an effect, so the first paint is
  // already right. An effect would show the fallback for one frame every time
  // — which for a remembered tab is the wrong list, visibly, on every visit.
  // The theme does the same thing for the same reason.
  const [chosen, setChosen] = useState<T | null>(() => readChoice(key, allowed));

  // And re-read when the key changes, because a lazy initialiser only runs
  // once and the key is per-collection: moving from one course to another
  // keeps this component mounted and would otherwise carry the first one's
  // choice into the second. Setting the same value is a no-op, so this costs
  // nothing on mount.
  useEffect(() => {
    setChosen(readChoice(key, allowed));
    // `allowed` is a literal at every call site; putting it in the deps would
    // re-run this on every render for nothing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const set = useCallback(
    (next: T) => {
      setChosen(next);
      try {
        localStorage.setItem(key, next);
      } catch {
        // Written where it can be; the session still behaves as asked.
      }
    },
    [key],
  );

  // An explicit choice wins over the fallback, worked out during render
  // rather than synced into a second piece of state: the fallback changes the
  // moment a collection loads and its size decides the default, and an effect
  // would show the old answer for a frame — a 200-lesson course drawn as a
  // list.
  return [chosen ?? fallback, set];
}

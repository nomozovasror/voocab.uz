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

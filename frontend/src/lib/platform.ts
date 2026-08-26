/**
 * Which modifier key this machine calls "the command key".
 *
 * A shortcut has to be BOTH listened for and printed with the right key, and
 * the two must be the same decision — a hint that says ⌘K on a keyboard where
 * Ctrl+K is what works is worse than no hint at all. So both read from
 * :func:`isApplePlatform`: the listener to know which modifier to accept, the
 * hint to know whether to draw the ⌘ key or write "Ctrl".
 */

let apple: boolean | null = null;

/** Mac, iPad or iPhone — the platforms where ⌘ is the modifier and Ctrl is
 *  something else entirely (Ctrl+K deletes to end of line in every text field
 *  on macOS, which is exactly why we must not bind it there). */
export function isApplePlatform(): boolean {
  if (apple !== null) return apple;
  if (typeof navigator === "undefined") return (apple = false);

  // The modern reading, where it exists. It reports "macOS" for every Apple
  // desktop regardless of the CPU, which the user-agent string does not.
  const data = (
    navigator as Navigator & { userAgentData?: { platform?: string } }
  ).userAgentData;
  if (data?.platform) return (apple = data.platform === "macOS");

  // `navigator.platform` is deprecated and still the most accurate thing left
  // in every browser that lacks the above; the user agent is the last resort
  // because iPadOS reports itself as a Mac in it, which here is the right
  // answer anyway.
  return (apple = /Mac|iPod|iPhone|iPad/.test(
    navigator.platform || navigator.userAgent,
  ));
}

/** Whether this keydown is holding the platform's own modifier — and only it.
 *
 *  Deliberately not "either meta or ctrl": on a Mac that would fire on the
 *  Ctrl+K that means "delete to end of line", and on Windows the Meta key is
 *  the Windows key, whose combinations belong to the desktop. `altKey` is
 *  excluded because ⌥⌘K and Ctrl+Alt+K are somebody else's shortcuts. */
export function hasPlatformModifier(event: KeyboardEvent): boolean {
  const modifier = isApplePlatform() ? event.metaKey : event.ctrlKey;
  return modifier && !event.altKey;
}

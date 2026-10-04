/**
 * Playing a word, in one place.
 *
 * Every card, the reveal and the word page play short files through this and
 * nothing else, for three reasons that are each easy to get wrong in a
 * component of their own:
 *
 * - **One voice at a time.** Starting a clip stops the previous one. A
 *   reveal's autoplay landing on top of the listen card's replay is two
 *   people talking, and nobody can tell which one said the word.
 * - **A missing file is "no audio", never an error.** A clip may 404 (the
 *   server queues what is not ready and the file can lag the row), the
 *   browser may refuse to start sound without a gesture, the network may
 *   drop. None of those may break a card. `playClip` never throws and says
 *   what happened, and the caller decides whether anyone needs to be told
 *   (nearly always: no).
 * - **Slower is not lower.** `0.75x` for the listen card is a slowdown with
 *   the pitch preserved; without `preservesPitch` a slowed voice drops into a
 *   different, worse-sounding one and the learner is practising to a sound
 *   nobody speaks in.
 *
 * Not used by "On the go": that screen owns ONE long-lived `<audio>` element
 * on purpose (it must keep playing with the screen locked, and the platform
 * ties the lock-screen controls to that element).
 */

/** What became of a request to play.
 *  - `started`: sound is on its way.
 *  - `blocked`: the browser wants a gesture first (autoplay policy). The file
 *    is fine; pressing a button will work.
 *  - `failed`: the file could not be played — missing, undecodable, offline.
 *    Treat as "no audio".
 *  - `replaced`: something else was played (or `stopAudio` ran) before this
 *    one could start. Not a failure, and not worth any message. */
export type PlayResult = "started" | "blocked" | "failed" | "replaced";

let current: HTMLAudioElement | null = null;

/** Stop whatever is playing, and make its pending `play()` resolve as
 *  `replaced`. Safe to call when nothing is. */
export function stopAudio(): void {
  if (!current) return;
  const el = current;
  current = null;
  el.pause();
}

/** Whether a clip is audible right now. The reveal's autoplay asks, so it
 *  does not restart a word the learner is still hearing. */
export function isPlaying(): boolean {
  return current !== null && !current.paused && !current.ended;
}

export function playClip(
  url: string,
  opts: { rate?: number; onEnded?: () => void } = {},
): Promise<PlayResult> {
  stopAudio();
  const el = new Audio(url);
  // `preservesPitch` is spec'd and in every current browser; the prefixed
  // spellings are for the Safari versions that still have only those.
  const pitched = el as HTMLAudioElement & {
    webkitPreservesPitch?: boolean;
    mozPreservesPitch?: boolean;
  };
  pitched.preservesPitch = true;
  pitched.webkitPreservesPitch = true;
  pitched.mozPreservesPitch = true;
  el.playbackRate = opts.rate ?? 1;
  current = el;

  el.addEventListener("ended", () => {
    if (current === el) current = null;
    opts.onEnded?.();
  });
  // A file that starts and then dies mid-way (the connection drops) must
  // not leave `current` pointing at a corpse for `isPlaying` to answer from.
  el.addEventListener("error", () => {
    if (current === el) current = null;
  });

  return el.play().then(
    () => "started" as const,
    (e: unknown) => {
      const wasCurrent = current === el;
      if (wasCurrent) current = null;
      if (!wasCurrent) return "replaced" as const;
      const name = e instanceof DOMException ? e.name : "";
      if (name === "NotAllowedError") return "blocked" as const;
      if (name === "AbortError") return "replaced" as const;
      return "failed" as const;
    },
  );
}

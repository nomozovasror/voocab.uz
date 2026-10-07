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
 * - **One element for the whole visit.** Every clip is the same long-lived
 *   `<audio>` with a new `src`, never `new Audio()` per play. iOS Safari lets
 *   an element play only inside a user gesture, or later, once a gesture has
 *   "unlocked" THAT element. A fresh element per clip is locked every time, so
 *   the listen card's first play (after a fetch) and the reveal's autoplay
 *   (after an awaited POST) would silently do nothing on an iPhone. See
 *   `armAudioUnlock`.
 *
 * Not used by "On the go": that screen owns ONE long-lived `<audio>` element
 * on purpose (it must keep playing with the screen locked, and the platform
 * ties the lock-screen controls to that element).
 */

import { mediaUrl } from "@/features/paper/api";

/** What became of a request to play.
 *  - `started`: sound is on its way.
 *  - `blocked`: the browser wants a gesture first (autoplay policy). The file
 *    is fine; pressing a button will work. The caller must SHOW this (a
 *    pulsing button, "Tap to play") — never silently nothing.
 *  - `failed`: the file could not be played — missing, undecodable, offline.
 *    Treat as "no audio".
 *  - `replaced`: something else was played (or `stopAudio` ran) before this
 *    one could start. Not a failure, and not worth any message. */
export type PlayResult = "started" | "blocked" | "failed" | "replaced";

/** A 1-sample silent WAV, built once. Played inside a gesture to unlock the
 *  shared element; nothing is heard and nothing is fetched. */
const SILENCE = (() => {
  const bytes = new Uint8Array(46);
  const v = new DataView(bytes.buffer);
  const text = (at: number, s: string) =>
    [...s].forEach((c, i) => v.setUint8(at + i, c.charCodeAt(0)));
  text(0, "RIFF");
  v.setUint32(4, 38, true);
  text(8, "WAVEfmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); // PCM
  v.setUint16(22, 1, true); // mono
  v.setUint32(24, 8000, true);
  v.setUint32(28, 16000, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  text(36, "data");
  v.setUint32(40, 2, true);
  return `data:audio/wav;base64,${btoa(String.fromCharCode(...bytes))}`;
})();

let shared: HTMLAudioElement | null = null;
/** Identifies the play that owns the element; 0 = nothing is playing. Every
 *  `playClip`/`stopAudio` moves it, so a promise or an `ended` that belongs
 *  to an earlier clip can tell it is stale. */
let owner = 0;
/** Monotonic ticket for `owner`, so a stale play can never match a new one
 *  (`owner` itself returns to 0 and would be reused). */
let claim = 0;
let ownerEnded: (() => void) | null = null;
let unlocked = false;

function element(): HTMLAudioElement {
  if (shared) return shared;
  const el = new Audio();
  // `preservesPitch` is spec'd and in every current browser; the prefixed
  // spellings are for the Safari versions that still have only those.
  const pitched = el as HTMLAudioElement & {
    webkitPreservesPitch?: boolean;
    mozPreservesPitch?: boolean;
  };
  pitched.preservesPitch = true;
  pitched.webkitPreservesPitch = true;
  pitched.mozPreservesPitch = true;
  el.addEventListener("ended", () => {
    const done = ownerEnded;
    owner = 0;
    ownerEnded = null;
    done?.();
  });
  // A file that starts and then dies mid-way (the connection drops) must
  // not leave `owner` pointing at a corpse for `isPlaying` to answer from.
  el.addEventListener("error", () => {
    owner = 0;
    ownerEnded = null;
  });
  shared = el;
  return el;
}

/**
 * Unlock the shared element for iOS Safari. Call once when a practice visit
 * begins (the vocabulary home and the practice page); returns the cleanup.
 *
 * How it works: on the first genuinely activating event the element plays a
 * silent clip and is paused again. After that, iOS lets the SAME element
 * change `src` and `play()` outside a gesture, which is exactly what the
 * listen card's first play and the reveal's autoplay do. The element outlives
 * route changes, so a press on the home screen's Start unlocks the practice
 * page that follows.
 *
 * Why these events: on iOS only `click`, `touchend` and `keydown` count as
 * activation; `touchstart` and `pointerdown` do not, so a `pointerdown`
 * unlock would silently fail on the very device this is for. Capture phase,
 * so a handler that stops propagation cannot hide the gesture from us.
 */
export function armAudioUnlock(): () => void {
  const events = ["click", "touchend", "keydown"] as const;
  function remove() {
    for (const e of events) document.removeEventListener(e, onGesture, true);
  }
  function onGesture() {
    if (unlocked) return remove();
    const el = element();
    // A real clip already started in this same gesture has unlocked it.
    if (owner !== 0) return;
    el.src = SILENCE;
    el.play().then(
      () => {
        unlocked = true;
        remove();
        // Not if a real clip took the element in the meantime.
        if (owner === 0) el.pause();
      },
      () => {
        /* Not an activating event after all; the next one tries again. */
      },
    );
  }
  if (!unlocked) for (const e of events) document.addEventListener(e, onGesture, true);
  return remove;
}

/** Stop whatever is playing, and make its pending `play()` resolve as
 *  `replaced`. Safe to call when nothing is. */
export function stopAudio(): void {
  if (!shared || owner === 0) return;
  owner = 0;
  ownerEnded = null;
  shared.pause();
}

/** Whether a clip is audible right now. The reveal's autoplay asks, so it
 *  does not restart a word the learner is still hearing. */
export function isPlaying(): boolean {
  return shared !== null && owner !== 0 && !shared.paused && !shared.ended;
}

export function playClip(
  url: string,
  opts: { rate?: number; onEnded?: () => void } = {},
): Promise<PlayResult> {
  stopAudio();
  const el = element();
  const mine = ++claim;
  owner = mine;
  ownerEnded = opts.onEnded ?? null;
  // The server sends local files as a path (`/media/…`) on ITS origin. The
  // dev SPA is on another origin, where that path is the app's own HTML page
  // and every clip "failed" -- resolved the way listening resolves its audio.
  el.src = mediaUrl(url);
  // Set after `src`: loading a new source resets `playbackRate` to
  // `defaultPlaybackRate` in some engines.
  el.playbackRate = opts.rate ?? 1;

  return el.play().then(
    () => {
      if (owner === mine) unlocked = true;
      return owner === mine ? ("started" as const) : ("replaced" as const);
    },
    (e: unknown) => {
      if (owner !== mine) return "replaced" as const;
      owner = 0;
      ownerEnded = null;
      const name = e instanceof DOMException ? e.name : "";
      if (name === "NotAllowedError") return "blocked" as const;
      if (name === "AbortError") return "replaced" as const;
      return "failed" as const;
    },
  );
}


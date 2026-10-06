/**
 * One recognition, as a promise — the browser half of the `speak` card.
 *
 * `SpeechRecognition` is the engine behind a phone keyboard's dictation, so
 * there is no server, model, queue or bill on our side (Chrome sends the
 * audio to Google, which is not ours but not "no server" either). It is also
 * the least dependable API this app touches: iOS Safari's support is partial
 * and only a real iPhone says what "partial" means here. So this file is
 * built around one rule: **whatever goes wrong, say which of three things
 * happened and let the card carry on.**
 *
 * - `heard` — alternatives to send to the server.
 * - `silence` — nothing usable was said. Not an attempt: see `SpeakCard`.
 * - `unsupported` — this device or permission cannot do it (no API, the
 *   microphone refused or missing, a service that will not answer). The card
 *   becomes a typing card for the rest of the session. The learner who
 *   refused the microphone once is not asked again every card.
 * - `aborted` — we stopped it ourselves (unmount, the next card).
 *
 * Deliberately never `continuous`, never `interimResults`, never restarted by
 * code: the microphone opens when the learner presses it and closes when the
 * recogniser has one answer. `lang` follows the learner's accent (`en-GB`
 * British, `en-US` American) and `maxAlternatives` is 5, per the brief. `SpeechGrammarList` is not used — it is dead in every engine.
 */

import type { Accent } from "@/features/vocabulary/types";

export type SpeechOutcome =
  | { kind: "heard"; alternatives: string[] }
  | { kind: "silence" }
  | { kind: "unsupported" }
  | { kind: "aborted" };

/** The few members used. TypeScript's DOM lib has no `SpeechRecognition`, and
 *  declaring a global of that name would collide the day it does. */
interface RecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((e: RecognitionResultEvent) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}

interface RecognitionResultEvent {
  results: ArrayLike<ArrayLike<{ transcript: string }>>;
}

type RecognitionCtor = new () => RecognitionLike;

function ctor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: RecognitionCtor;
    webkitSpeechRecognition?: RecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function speechSupported(): boolean {
  return ctor() !== null;
}

/** Errors that mean "not now, and asking again will not help": a refused or
 *  absent microphone, a blocked service, a language the engine lacks, or no
 *  network to the vendor's recogniser. */
const UNSUPPORTED_ERRORS = new Set([
  "not-allowed",
  "service-not-allowed",
  "audio-capture",
  "language-not-supported",
  "network",
]);

export interface Listening {
  /** Resolves once, whatever happens. */
  result: Promise<SpeechOutcome>;
  /** Ask for the answer now (the learner pressed the button again). Results
   *  gathered so far are still delivered. */
  stop: () => void;
  /** Drop it without an answer. */
  abort: () => void;
}

/** The recogniser's language for an accent. */
export const RECOGNITION_LANG: Record<Accent, string> = {
  british: "en-GB",
  american: "en-US",
};

export function listenOnce(accent: Accent = "british"): Listening {
  const Ctor = ctor();
  if (!Ctor) {
    return {
      result: Promise.resolve({ kind: "unsupported" }),
      stop: () => {},
      abort: () => {},
    };
  }

  const rec = new Ctor();
  rec.lang = RECOGNITION_LANG[accent];
  rec.maxAlternatives = 5;
  rec.interimResults = false;
  rec.continuous = false;

  let alternatives: string[] = [];
  let failure: string | null = null;
  let aborted = false;

  const result = new Promise<SpeechOutcome>((resolve) => {
    rec.onresult = (e) => {
      const first = e.results[0];
      if (!first) return;
      alternatives = Array.from(first, (a) => a.transcript.trim()).filter(Boolean);
    };
    rec.onerror = (e) => {
      failure = e.error;
    };
    // `end` fires after `error` and after a result alike — the one place the
    // outcome is decided, so there is exactly one resolution.
    rec.onend = () => {
      if (aborted || failure === "aborted") resolve({ kind: "aborted" });
      else if (failure && UNSUPPORTED_ERRORS.has(failure))
        resolve({ kind: "unsupported" });
      else if (alternatives.length > 0)
        resolve({ kind: "heard", alternatives: alternatives.slice(0, 5) });
      // `no-speech`, `nomatch` (which is an empty result) and anything we do
      // not know about: nothing to check.
      else resolve({ kind: "silence" });
    };
    try {
      rec.start();
    } catch {
      // `start()` throws if one is already running or the page may not use
      // the microphone at all.
      resolve({ kind: "unsupported" });
    }
  });

  return {
    result,
    stop: () => {
      try {
        rec.stop();
      } catch {
        /* already ended */
      }
    },
    abort: () => {
      aborted = true;
      try {
        rec.abort();
      } catch {
        /* already ended */
      }
    },
  };
}

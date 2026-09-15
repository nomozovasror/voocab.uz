import { useEffect, useState } from "react";
import { BARS } from "@/features/listening/components/Waveform";
import type { ListenedSpan } from "@/features/listening/types";

/**
 * The shape of a recording, as a row of peak heights.
 *
 * Peaks are computed in the browser, from the same URL the audio element is
 * playing. Two requests for one file, and that is the deliberate half of the
 * trade: decoding from a single fetch would mean the whole recording has to
 * arrive before anything can be played, and a candidate who pressed play
 * should not be waiting on a picture. The audio streams; the picture catches
 * up. The HTTP cache usually makes the second request free anyway.
 *
 * The decode also yields the other thing only the samples can say: where the
 * recording goes quiet for long enough to be worth skipping. One pass, two
 * products — a second decode to find the pauses would double the only
 * expensive thing on the page.
 *
 * Nothing about this is authored, and nothing is stored. The day peaks come
 * down with the material — which is the right answer at a thousand
 * materials — this hook keeps its signature and stops fetching.
 */

/** What one decode produces. `peaks` is null until it has; `silences` is
 *  simply empty, because "we found none" and "we have not looked" call for
 *  the same behaviour from everything that reads it. */
export interface WaveShape {
  peaks: number[] | null;
  silences: ListenedSpan[];
}

const NOTHING: WaveShape = { peaks: null, silences: [] };

/** Peaks by URL and resolution, for the life of the tab. The take page and
 *  the results page are the same recording, and docking the player, changing
 *  a theme or re-rendering a list must never decode six minutes of audio
 *  again. Keyed on the bucket count as well as the URL, because a cached
 *  array of the wrong length is a picture of the wrong recording. */
const CACHE = new Map<string, WaveShape>();

/** Coarse on purpose. The waveform is read as a silhouette — where the
 *  pauses are, how much is left — and at 8kHz a six-minute file decodes to a
 *  few megabytes instead of seventy. Nothing here is ever played. */
const DECODE_RATE = 8_000;

/** How finely the recording is checked for quiet, and how quiet counts.
 *  The threshold is about -34dBFS on a normalised buffer — it errs towards
 *  "only genuinely dead air", because the cost of being wrong is cutting a
 *  word off the front of a sentence. */
const QUIET_WINDOW_MS = 50;
const QUIET_RMS = 0.02;

/** The shortest stretch of quiet worth calling a silence.
 *
 *  Five seconds, and the number is the whole design of the feature. Speech is
 *  full of pauses — between sentences, between speakers, for effect — and
 *  skipping those would turn a recording into a stutter. What this is FOR is
 *  the dead air a listening paper is built out of: the twenty and thirty
 *  second stretches where a candidate is meant to be reading ahead or
 *  checking answers, and where somebody working through the paper for the
 *  second time is just waiting. */
const MIN_SILENCE_MS = 5_000;

/**
 * Where the recording goes quiet for long enough to be worth skipping.
 *
 * RMS over short windows rather than peak: a single click in the middle of
 * thirty seconds of room tone should not disqualify the stretch, and RMS is
 * what ignores it. Runs are closed at the first window that is NOT quiet, so
 * a silence ends exactly where the sound comes back.
 */
function silencesOf(buffer: AudioBuffer): ListenedSpan[] {
  if (buffer.numberOfChannels === 0) return [];
  const data = buffer.getChannelData(0);
  const rate = buffer.sampleRate;
  const window = Math.max(1, Math.round((rate * QUIET_WINDOW_MS) / 1000));
  const runs: ListenedSpan[] = [];
  let from: number | null = null;

  const close = (sample: number) => {
    if (from === null) return;
    const start = (from / rate) * 1000;
    const end = (sample / rate) * 1000;
    if (end - start >= MIN_SILENCE_MS) {
      runs.push({ start_ms: Math.round(start), end_ms: Math.round(end) });
    }
    from = null;
  };

  for (let i = 0; i < data.length; i += window) {
    const to = Math.min(i + window, data.length);
    let sum = 0;
    for (let j = i; j < to; j++) sum += data[j] * data[j];
    if (Math.sqrt(sum / (to - i)) < QUIET_RMS) {
      if (from === null) from = i;
    } else {
      close(i);
    }
  }
  close(data.length);
  return runs;
}

function context(): AudioContext {
  const Ctor: typeof AudioContext =
    window.AudioContext ??
    (window as unknown as { webkitAudioContext: typeof AudioContext })
      .webkitAudioContext;
  try {
    return new Ctor({ sampleRate: DECODE_RATE });
  } catch {
    // Safari refused the rate on older versions. A full-rate decode is worse
    // and still correct, which is the right way round.
    return new Ctor();
  }
}

/** How hard the contrast is pushed. Speech sits in a narrow band — a
 *  normalised talking recording is a wall of three-quarter-height bars with
 *  nothing to read in it. Raising each value to a power above one holds the
 *  peaks where they are and pulls everything below them down, which turns the
 *  wall back into a shape: sentences, breaths, the gap between speakers.
 *
 *  It is a lie about the amplitude and an honest picture of the structure,
 *  which is what the waveform is for. Nothing measures anything off it. */
const CONTRAST = 1.7;

/** The loudest sample in each bucket, scaled so the tallest bar is 1, then
 *  curved.
 *
 *  Peak rather than RMS: what the picture is for is finding the gaps between
 *  speakers, and RMS smooths exactly those away. Normalised because absolute
 *  level says nothing a learner wants — a quietly mastered recording would
 *  otherwise draw as a flat line. */
function peaksOf(buffer: AudioBuffer, buckets: number): number[] {
  const data = buffer.getChannelData(0);
  const per = Math.max(1, Math.floor(data.length / buckets));
  const out: number[] = [];
  let tallest = 0;

  for (let b = 0; b < buckets; b++) {
    const from = b * per;
    const to = Math.min(from + per, data.length);
    let peak = 0;
    for (let i = from; i < to; i++) {
      const v = data[i] < 0 ? -data[i] : data[i];
      if (v > peak) peak = v;
    }
    if (peak > tallest) tallest = peak;
    out.push(peak);
  }

  if (tallest <= 0) return out;
  return out.map((p) => Math.pow(p / tallest, CONTRAST));
}

/**
 * The peaks for one recording, or null while there are none.
 *
 * Null is a real answer and callers must draw something for it — the file is
 * still downloading, the browser refused to decode it, or there is no audio
 * at all. A player that only laid out once the peaks arrived would jump the
 * whole page when they did.
 */
export function useWaveform(src: string | null, buckets = BARS): WaveShape {
  const key = src ? `${buckets}|${src}` : null;
  const [shape, setShape] = useState<WaveShape>(() =>
    key ? (CACHE.get(key) ?? NOTHING) : NOTHING,
  );

  useEffect(() => {
    if (!src || !key) {
      setShape(NOTHING);
      return;
    }
    const cached = CACHE.get(key);
    if (cached) {
      setShape(cached);
      return;
    }
    setShape(NOTHING);

    const abort = new AbortController();
    let ctx: AudioContext | null = null;
    let dropped = false;

    void (async () => {
      try {
        const response = await fetch(src, { signal: abort.signal });
        if (!response.ok) return;
        const bytes = await response.arrayBuffer();
        if (dropped) return;
        ctx = context();
        const buffer = await ctx.decodeAudioData(bytes);
        if (dropped) return;
        const computed: WaveShape = {
          peaks: peaksOf(buffer, buckets),
          silences: silencesOf(buffer),
        };
        CACHE.set(key, computed);
        setShape(computed);
      } catch {
        // A picture is not worth an error in front of somebody sitting a
        // test. The player falls back to a plain track and everything else
        // about it still works.
      } finally {
        void ctx?.close();
      }
    })();

    return () => {
      dropped = true;
      abort.abort();
    };
  }, [src, key, buckets]);

  return shape;
}

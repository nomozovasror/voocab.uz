import { useCallback, useEffect, useRef, useState } from "react";
import type { TakeConfig } from "@/features/listening/take-config";
import type { ListenedSpan } from "@/features/listening/types";

/**
 * The recording, as a piece of state — with no view attached.
 *
 * The take page draws the same audio twice: a full player at the top of the
 * paper, and a strip in the header once that has scrolled away. Those are two
 * dresses on one thing, not two players, and the only way to be sure of that
 * is for neither of them to own the audio. So the element lives here, made
 * with `new Audio()` and never mounted: nothing in the tree can accidentally
 * become its parent, and no view can be the one that must stay rendered.
 *
 * It also watches. Every continuous run of playback is reported as a span, so
 * the server can work out — after grading, when it is safe to — which answers
 * the learner had to go back for. Runs are reported one at a time and
 * deliberately NOT merged: the same stretch played twice is two spans, and
 * that repetition is the entire signal.
 *
 * What the WAVEFORM shows is not this. It shows progress — everything left of
 * the playhead — because that is what a player means by a coloured bar, and a
 * picture that stayed grey where somebody had just skipped forward read as
 * broken rather than as honest. The spans are still collected; they are for
 * the server, after grading, and not for the reader mid-test.
 *
 * Every control obeys `config` rather than a flag written into a button, so
 * the exam page is this hook with a different constant — see take-config.ts.
 */

const SPEEDS = [0.75, 1, 1.25, 1.5] as const;
export const NUDGE_MS = 3_000;

/** Where a skip lands: this far before the sound comes back, so the first
 *  syllable is never clipped. */
const SKIP_LEAD_MS = 300;
/** How far ahead a silence counts as "about to happen" — both for offering
 *  the skip and for what pressing it acts on, so the button can never light
 *  up for something a press would not reach. */
export const SKIP_HINT_MS = 4_000;
/** How much of a silence has to be left for it to be worth skipping. Larger
 *  than the lead, which is what makes the landing point ineligible and stops
 *  the skip retriggering forever. */
const SKIP_GUARD_MS = 800;

export interface AudioEngine {
  playing: boolean;
  /** Where the playhead is, in ms. */
  atMs: number;
  lengthMs: number;
  speed: number;
  failed: boolean;
  finished: boolean;
  /** Whether the play button would do anything — the recording may have
   *  played its once. */
  canPlay: boolean;
  canPause: boolean;
  /** Whether every silence is stepped over without being asked. A setting,
   *  not a control — see lib/preferences.ts. */
  autoSkip: boolean;
  /** The silence the skip button would act on: the one the playhead is in,
   *  or one about to arrive. Null when there is nothing to skip, which is
   *  what makes the button inert rather than a click that does nothing. */
  skippable: ListenedSpan | null;
  config: TakeConfig;
  play: () => void;
  pause: () => void;
  toggle: () => void;
  seekTo: (ms: number) => void;
  nudge: (byMs: number) => void;
  cycleSpeed: () => void;
  /** Step over `skippable`, landing just before the sound comes back. */
  skipAhead: () => void;
  /** Play one stretch and stop at its end. The review's "hear it": there are
   *  no separate clips, only the whole recording seeked to the moment the
   *  author marked. */
  playRange: (startMs: number | null, endMs: number | null) => void;
  retry: () => void;
}

interface EngineOptions {
  src: string | null;
  /** From the material, so the track has a length before the file's metadata
   *  arrives and doesn't resize under the pointer. */
  durationMs: number | null;
  config: TakeConfig;
  /** The dead stretches, found in the decode (see use-waveform.ts). */
  silences?: ListenedSpan[];
  /** The reader's standing preference: step over every one of them without
   *  being asked. Off unless they have said otherwise. */
  autoSkip?: boolean;
  onSpan?: (span: ListenedSpan) => void;
  onSeekBack?: () => void;
}

export function useAudioEngine({
  src,
  durationMs,
  config,
  silences,
  autoSkip = false,
  onSpan,
  onSeekBack,
}: EngineOptions): AudioEngine {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  /**
   * Where a ranged play is to stop, in ms of AUDIO — not a timer.
   *
   * It was a `setTimeout` for the clip's duration, and that is why the last
   * word was being cut off. The timer started the moment `playRange` was
   * called; the sound started whenever the browser had finished seeking and
   * buffering to that position, which on a six-minute file is not the same
   * moment. Every millisecond of that gap came off the END, so the further
   * into a recording the answer was, the more of it went missing.
   *
   * Read on `timeupdate`, so the stop is measured against the same clock the
   * playing is. That fires about four times a second, so it can overshoot by
   * a fraction — which is the right direction to be wrong in: a moment of the
   * next sentence is nothing, and half of the answer is the bug.
   */
  const stopAtMs = useRef<number | null>(null);
  /** Where the current run of playback started, in ms of audio. Null when
   *  nothing is playing. */
  const runStart = useRef<number | null>(null);

  const [playing, setPlaying] = useState(false);
  const [atMs, setAtMs] = useState(0);
  const [lengthMs, setLengthMs] = useState(durationMs ?? 0);
  const [speed, setSpeed] = useState(1);
  const [finished, setFinished] = useState(false);
  const [failed, setFailed] = useState(false);

  // Handlers are attached once and read the callbacks through a ref, so a
  // parent that re-creates `onSpan` doesn't tear down and rebuild the
  // element — which would stop playback mid-word.
  const report = useRef({ onSpan, onSeekBack });
  report.current = { onSpan, onSeekBack };

  // Read by the timeupdate handler, which is attached once and must not be
  // rebuilt every time the reader toggles this — rebuilding the listeners
  // means rebuilding the element, and rebuilding the element stops the
  // recording mid-word.
  const skip = useRef({ on: autoSkip, runs: silences });
  skip.current = { on: autoSkip, runs: silences };

  const closeRun = useCallback((at: number) => {
    const from = runStart.current;
    runStart.current = null;
    if (from === null || at <= from) return;
    report.current.onSpan?.({
      start_ms: Math.round(from),
      end_ms: Math.round(at),
    });
  }, []);

  // One element per source, made outside the tree. Rebuilt only when the src
  // changes, which on these pages means never.
  useEffect(() => {
    if (!src) return;
    const audio = new Audio(src);
    audio.preload = "metadata";
    audioRef.current = audio;
    setFailed(false);

    const onLoaded = () => {
      const seconds = audio.duration;
      if (Number.isFinite(seconds) && seconds > 0) setLengthMs(seconds * 1000);
    };
    const onPlay = () => {
      setPlaying(true);
      setFinished(false);
      runStart.current = audio.currentTime * 1000;
    };
    const onPause = () => {
      setPlaying(false);
      stopAtMs.current = null;
      closeRun(audio.currentTime * 1000);
    };
    const onEnded = () => {
      closeRun(audio.currentTime * 1000);
      // A clip whose end lies past the end of the file — the last answer on
      // the paper, most of the time. The recording running out IS the stop,
      // and leaving the target armed would pause the next press on its very
      // first tick.
      stopAtMs.current = null;
      setPlaying(false);
      setFinished(true);
    };
    const onTime = () => {
      const at = audio.currentTime * 1000;
      // The end of a ranged play, on the audio's own clock. Before the skip
      // check, so a clip that ends inside a silence stops rather than being
      // carried past its own end by the skip.
      const until = stopAtMs.current;
      if (until != null && at >= until) {
        stopAtMs.current = null;
        audio.pause();
        setAtMs(at);
        return;
      }
      // Over the dead air, without being asked — the standing preference,
      // not the button. The run is left with a moment of it still to go, so
      // the first syllable on the other side is not clipped and the landing
      // point is outside the window that triggers a skip, which is what stops
      // this firing again on the very next tick.
      const { on, runs } = skip.current;
      if (on) {
        const run = (runs ?? []).find(
          (r) => at >= r.start_ms && at < r.end_ms - SKIP_GUARD_MS,
        );
        if (run) {
          const to = run.end_ms - SKIP_LEAD_MS;
          closeRun(at);
          audio.currentTime = to / 1000;
          runStart.current = to;
          setAtMs(to);
          return;
        }
      }
      setAtMs(at);
    };
    const onError = () => setFailed(true);

    audio.addEventListener("loadedmetadata", onLoaded);
    audio.addEventListener("play", onPlay);
    audio.addEventListener("pause", onPause);
    audio.addEventListener("ended", onEnded);
    audio.addEventListener("timeupdate", onTime);
    audio.addEventListener("error", onError);

    return () => {
      // A run left open when the page goes away is still a run that
      // happened.
      if (runStart.current !== null) closeRun(audio.currentTime * 1000);
      audio.removeEventListener("loadedmetadata", onLoaded);
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("pause", onPause);
      audio.removeEventListener("ended", onEnded);
      audio.removeEventListener("timeupdate", onTime);
      audio.removeEventListener("error", onError);
      stopAtMs.current = null;
      audio.pause();
      audio.src = "";
      audioRef.current = null;
    };
  }, [src, closeRun]);

  const canPlay = !failed && (config.allowReplay || !finished);
  const canPause = config.allowPause;

  const play = useCallback(() => {
    if (!canPlay) return;
    void audioRef.current?.play();
  }, [canPlay]);

  const pause = useCallback(() => {
    if (!canPause) return;
    audioRef.current?.pause();
  }, [canPause]);

  const toggle = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (!audio.paused) pause();
    else play();
  }, [pause, play]);

  const seekTo = useCallback(
    (toMs: number) => {
      const audio = audioRef.current;
      if (!audio || !config.allowSeek) return;
      const from = audio.currentTime * 1000;
      const target = Math.max(0, Math.min(toMs, lengthMs || toMs));
      // Any move backwards counts, including a −3s nudge — especially a −3s
      // nudge. It is the plainest "I missed that" the page ever sees.
      if (target < from) report.current.onSeekBack?.();
      if (!audio.paused) closeRun(from);
      // A seek is the reader taking over, so whatever clip was running is
      // over. `playRange` seeks first and sets its own stop after, which is
      // why this can clear unconditionally.
      stopAtMs.current = null;
      audio.currentTime = target / 1000;
      setAtMs(target);
      // Seeking away from the end un-finishes it; otherwise a candidate who
      // let it run out could never hear the part they jumped back to.
      if (target < (lengthMs || Infinity)) setFinished(false);
      if (!audio.paused) runStart.current = target;
    },
    [closeRun, config.allowSeek, lengthMs],
  );

  const nudge = useCallback(
    (byMs: number) => seekTo(atMs + byMs),
    [atMs, seekTo],
  );

  const cycleSpeed = useCallback(() => {
    if (!config.allowSpeed) return;
    setSpeed((was) => {
      const next = SPEEDS[(SPEEDS.indexOf(was as 1) + 1) % SPEEDS.length];
      if (audioRef.current) audioRef.current.playbackRate = next;
      return next;
    });
  }, [config.allowSpeed]);

  const playRange = useCallback(
    (startMs: number | null, endMs: number | null) => {
      const audio = audioRef.current;
      if (!audio) return;
      seekTo(startMs ?? 0);
      void audio.play();
      if (startMs != null && endMs != null) {
        stopAtMs.current = endMs;
      }
    },
    [seekTo],
  );

  // What a press would act on: the silence being sat through, or one close
  // enough that pressing now plainly means "not this one either".
  const runs = silences ?? [];
  const skippable =
    (config.allowSeek &&
      (runs.find((r) => atMs >= r.start_ms && r.end_ms - atMs > SKIP_GUARD_MS) ??
        runs.find(
          (r) => r.start_ms > atMs && r.start_ms - atMs <= SKIP_HINT_MS,
        ))) ||
    null;

  const skipAhead = useCallback(() => {
    // Jumping over the quiet is moving the playhead. A page that forbids the
    // one and offers the other is not enforcing anything — and in an exam the
    // dead air is part of the paper.
    if (!config.allowSeek || !skippable) return;
    seekTo(skippable.end_ms - SKIP_LEAD_MS);
  }, [config.allowSeek, seekTo, skippable]);

  const retry = useCallback(() => {
    setFailed(false);
    audioRef.current?.load();
  }, []);

  return {
    playing,
    atMs,
    lengthMs,
    speed,
    failed,
    finished,
    canPlay,
    canPause,
    autoSkip,
    skippable,
    config,
    play,
    pause,
    toggle,
    seekTo,
    nudge,
    cycleSpeed,
    skipAhead,
    playRange,
    retry,
  };
}

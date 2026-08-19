import {
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  type Ref,
} from "react";
import { Pause, Play, RotateCcw, Undo2, Redo2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { fmtClock } from "@/lib/time";
import type { TakeConfig } from "@/features/listening/take-config";
import type { ListenedSpan } from "@/features/listening/types";

/**
 * The recording, and the only controls over it the rules allow.
 *
 * Not `<audio controls>`. The browser's own bar has a seek handle, a speed
 * menu and a download button welded to it, and exam mode has to be able to
 * take those away — a page that shows the native control and then asks
 * candidates not to use it is not enforcing anything. Every control here is
 * drawn only if its rule permits it, and the rules arrive as a value (see
 * take-config.ts).
 *
 * It also watches. Every continuous run of playback is reported as a span, so
 * the server can work out — after grading, when it is safe to — which answers
 * the learner had to go back for. Runs are reported one at a time and
 * deliberately NOT merged: the same stretch played twice is two spans, and
 * that repetition is the entire signal.
 */

export interface TakeAudioHandle {
  /** Play one stretch and stop at its end. The review's "hear it" button:
   *  there are no separate clips, just the whole recording seeked to the
   *  moment the author marked. */
  playRange: (startMs: number | null, endMs: number | null) => void;
  /** For the space bar. Obeys the same rules the button does — if pausing is
   *  forbidden, the key does nothing rather than a thing the button won't. */
  toggle: () => void;
}

interface TakeAudioProps {
  src: string;
  /** From the material, so the bar has a length before the file's metadata
   *  arrives and doesn't resize under the pointer. */
  durationMs: number | null;
  config: TakeConfig;
  onSpan?: (span: ListenedSpan) => void;
  onSeekBack?: () => void;
  ref?: Ref<TakeAudioHandle>;
  className?: string;
}

const SPEEDS = [0.75, 1, 1.25, 1.5] as const;
const NUDGE_MS = 3_000;

export function TakeAudio({
  src,
  durationMs,
  config,
  onSpan,
  onSeekBack,
  ref,
  className,
}: TakeAudioProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const stopAt = useRef<number | undefined>(undefined);
  /** Where the current run of playback started, in ms of audio. Null when
   *  nothing is playing. */
  const runStart = useRef<number | null>(null);

  const [playing, setPlaying] = useState(false);
  const [atMs, setAtMs] = useState(0);
  const [lengthMs, setLengthMs] = useState(durationMs ?? 0);
  const [speed, setSpeed] = useState(1);
  const [scrub, setScrub] = useState<number | null>(null);
  const [finished, setFinished] = useState(false);
  const [failed, setFailed] = useState(false);

  const nowMs = () => (audioRef.current?.currentTime ?? 0) * 1000;

  const openRun = useCallback((at: number) => {
    runStart.current = at;
  }, []);

  const closeRun = useCallback(
    (at: number) => {
      const from = runStart.current;
      runStart.current = null;
      if (from === null || at <= from) return;
      onSpan?.({ start_ms: Math.round(from), end_ms: Math.round(at) });
    },
    [onSpan],
  );

  // A run left open when the page goes away is still a run that happened.
  useEffect(() => {
    const audio = audioRef.current;
    const open = runStart;
    return () => {
      if (audio && open.current !== null) closeRun(audio.currentTime * 1000);
    };
  }, [closeRun]);

  const play = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    void audio.play();
  }, []);

  const pause = useCallback(() => {
    audioRef.current?.pause();
  }, []);

  const seekTo = useCallback(
    (toMs: number) => {
      const audio = audioRef.current;
      if (!audio) return;
      const from = audio.currentTime * 1000;
      const target = Math.max(0, Math.min(toMs, lengthMs || toMs));
      // Any move backwards counts, including a −3s nudge — especially a −3s
      // nudge. It is the plainest "I missed that" the page ever sees.
      if (target < from) onSeekBack?.();
      if (!audio.paused) closeRun(from);
      window.clearTimeout(stopAt.current);
      audio.currentTime = target / 1000;
      setAtMs(target);
      // Seeking away from the end un-finishes it; otherwise a candidate who
      // let it run out could never hear the part they jumped back to.
      if (target < (lengthMs || Infinity)) setFinished(false);
      if (!audio.paused) openRun(target);
    },
    [closeRun, lengthMs, onSeekBack, openRun],
  );

  const canPlay = !failed && (config.allowReplay || !finished);

  useImperativeHandle(
    ref,
    () => ({
      playRange: (startMs, endMs) => {
        const audio = audioRef.current;
        if (!audio) return;
        window.clearTimeout(stopAt.current);
        seekTo(startMs ?? 0);
        void audio.play();
        if (startMs != null && endMs != null) {
          stopAt.current = window.setTimeout(
            () => audio.pause(),
            Math.max(0, (endMs - startMs) / (audio.playbackRate || 1)),
          );
        }
      },
      toggle: () => {
        const audio = audioRef.current;
        if (!audio) return;
        if (!audio.paused) {
          if (config.allowPause) audio.pause();
        } else if (canPlay) {
          void audio.play();
        }
      },
    }),
    [canPlay, config.allowPause, seekTo],
  );

  const shown = scrub ?? atMs;
  const pct = lengthMs > 0 ? (shown / lengthMs) * 100 : 0;

  if (failed) {
    return (
      <div className={cn("rounded-lg border border-border bg-card p-4", className)}>
        <p className="text-sm text-foreground">couldn&apos;t load the recording.</p>
        <button
          type="button"
          onClick={() => {
            setFailed(false);
            audioRef.current?.load();
          }}
          className="mt-2 inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-foreground/8 hover:text-foreground"
        >
          <RotateCcw className="size-3.5" aria-hidden />
          try again
        </button>
        {/* Kept mounted so load() has something to reload. */}
        <audio ref={audioRef} src={src} preload="metadata" className="hidden" />
      </div>
    );
  }

  return (
    <div
      className={cn(
        "rounded-lg border border-border bg-card px-4 py-3",
        className,
      )}
    >
      <audio
        ref={audioRef}
        src={src}
        preload="metadata"
        onLoadedMetadata={(e) => {
          const d = e.currentTarget.duration;
          if (Number.isFinite(d) && d > 0) setLengthMs(d * 1000);
        }}
        onPlay={() => {
          setPlaying(true);
          setFinished(false);
          openRun(nowMs());
        }}
        onPause={() => {
          setPlaying(false);
          window.clearTimeout(stopAt.current);
          closeRun(nowMs());
        }}
        onEnded={() => {
          setPlaying(false);
          setFinished(true);
          closeRun(nowMs());
        }}
        onTimeUpdate={(e) => setAtMs(e.currentTarget.currentTime * 1000)}
        onError={() => setFailed(true)}
      />

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={playing ? pause : play}
          disabled={!canPlay && !playing}
          aria-label={playing ? "Pause" : "Play"}
          title={
            playing
              ? config.allowPause
                ? "pause"
                : "the recording plays through"
              : finished && !config.allowReplay
                ? "the recording plays once"
                : "play"
          }
          // With pausing forbidden the button stays visible and goes inert
          // rather than disappearing mid-play: a control that vanishes under
          // the cursor reads as a bug, not as a rule.
          className={cn(
            "flex size-9 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground transition-opacity",
            ((playing && !config.allowPause) || (!playing && !canPlay)) &&
              "pointer-events-none opacity-40",
          )}
        >
          {playing ? (
            <Pause className="size-4" aria-hidden />
          ) : (
            <Play className="size-4 translate-x-px" aria-hidden />
          )}
        </button>

        <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">
          {fmtClock(shown)} / {fmtClock(lengthMs)}
        </span>

        <div className="ml-auto flex items-center gap-1">
          {config.allowSeek && (
            <>
              <NudgeButton
                label="back 3 seconds"
                onClick={() => seekTo(atMs - NUDGE_MS)}
              >
                <Undo2 className="size-3.5" aria-hidden />
                3s
              </NudgeButton>
              <NudgeButton
                label="forward 3 seconds"
                onClick={() => seekTo(atMs + NUDGE_MS)}
              >
                3s
                <Redo2 className="size-3.5" aria-hidden />
              </NudgeButton>
            </>
          )}
          {config.allowSpeed && (
            <button
              type="button"
              onClick={() => {
                const next = SPEEDS[(SPEEDS.indexOf(speed as 1) + 1) % SPEEDS.length];
                setSpeed(next);
                if (audioRef.current) audioRef.current.playbackRate = next;
              }}
              title="playback speed"
              className="rounded-md px-2 py-1 font-mono text-xs text-muted-foreground transition-colors hover:bg-foreground/8 hover:text-foreground"
            >
              {speed}×
            </button>
          )}
        </div>
      </div>

      <input
        type="range"
        min={0}
        max={Math.max(lengthMs, 1)}
        step={100}
        value={shown}
        disabled={!config.allowSeek}
        aria-label="Position in the recording"
        // Dragging fires continuously; committing on every tick would seek a
        // hundred times and report a hundred one-frame spans. The handle
        // moves on input, the audio moves on release.
        onChange={(e) => setScrub(Number(e.currentTarget.value))}
        onPointerUp={() => {
          if (scrub !== null) seekTo(scrub);
          setScrub(null);
        }}
        onKeyUp={() => {
          if (scrub !== null) seekTo(scrub);
          setScrub(null);
        }}
        onBlur={() => setScrub(null)}
        style={{
          background: `linear-gradient(to right, var(--primary) ${pct}%, color-mix(in oklab, var(--foreground) 15%, transparent) ${pct}%)`,
        }}
        className={cn(
          "mt-3 h-1 w-full appearance-none rounded-full outline-none",
          "[&::-webkit-slider-thumb]:size-3 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-primary",
          "[&::-moz-range-thumb]:size-3 [&::-moz-range-thumb]:appearance-none [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:bg-primary",
          "focus-visible:ring-2 focus-visible:ring-ring",
          config.allowSeek
            ? "cursor-pointer"
            : // Still drawn, because it is the only thing telling the
              // candidate how far through they are.
              "cursor-default [&::-moz-range-thumb]:opacity-0 [&::-webkit-slider-thumb]:opacity-0",
        )}
      />
    </div>
  );
}

function NudgeButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className="flex items-center gap-1 rounded-md px-2 py-1 font-mono text-xs text-muted-foreground transition-colors hover:bg-foreground/8 hover:text-foreground"
    >
      {children}
    </button>
  );
}

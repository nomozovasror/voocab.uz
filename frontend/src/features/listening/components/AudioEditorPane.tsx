import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ArrowRightFromLine,
  ArrowRightToLine,
  Crosshair,
  Gauge,
  Info,
  Loader2,
  MoveHorizontal,
  Pause,
  Play,
  Repeat,
  RotateCcw,
  Scissors,
  Upload,
  ZoomIn,
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { formatClock } from "@/features/studio/format";
import { mediaUrl } from "@/features/listening/api";
import { useAudioAsset } from "@/features/listening/queries";
import type { AudioSegment } from "@/features/listening/types";
// Type-only: erased at compile time, so these never pull the real library
// into the eager graph — only the `await import(...)` calls below do, and
// each becomes its own chunk (verified in the build output).
import type WaveSurfer from "wavesurfer.js";
import type RegionsPluginType from "wavesurfer.js/dist/plugins/regions.js";
import type { Region } from "wavesurfer.js/dist/plugins/regions.js";

const SNAP_THRESHOLD_MS = 250;
const MIN_SILENCE_MS = 300;
const SILENCE_WINDOW_MS = 20;
// -34dBFS-ish on a normalized decode buffer. Tunable; errs toward "only very
// quiet stretches count" so bands stay meaningful rather than noisy.
const SILENCE_RMS_THRESHOLD = 0.02;
// A part must be at least this long — enforced client-side (on the numeric
// inputs and via the region's own `minLength`) so an inverted/zero-length
// range is never even sent to the server (§2: fix the cause, not the toast).
const MIN_PART_LENGTH_MS = 500;
const MIN_PART_LENGTH_SEC = MIN_PART_LENGTH_MS / 1000;
// 250px/sec already resolves individual words; beyond that the bars scatter
// into hair-thin lines and the waveform stops reading as a shape.
const ZOOM_MAX_PX_PER_SEC = 250;
// Trim view keeps this much audio visible either side of the part, so the
// author can still see (and adjust against) what falls just outside it.
const FOCUS_PAD_MS = 5000;
// The part row's controls are only obvious once someone has used them, so the
// hint opens itself for the first few materials, then stays behind the ⓘ.
const HELP_KEY = "voocab:part-range-help";
const HELP_SHOW_LIMIT = 3;

function readHelpCount(): number {
  if (typeof window === "undefined") return HELP_SHOW_LIMIT;
  const raw = window.localStorage.getItem(HELP_KEY);
  const n = raw === null ? 0 : Number(raw);
  return Number.isFinite(n) ? n : 0;
}

/** The slider is 0–100 over a log curve between fit-to-width and the max, so
 *  each step feels like the same proportional change. */
function sliderToZoom(value: number, minPx: number): number {
  const min = Math.max(1, minPx);
  const max = Math.max(ZOOM_MAX_PX_PER_SEC, min * 2);
  return Math.round(min * Math.pow(max / min, value / 100));
}

function zoomToSlider(px: number, minPx: number): number {
  const min = Math.max(1, minPx);
  const max = Math.max(ZOOM_MAX_PX_PER_SEC, min * 2);
  if (px <= min) return 0;
  return Math.round((Math.log(px / min) / Math.log(max / min)) * 100);
}
// Regions are real DOM elements (not canvas), so unlike the waveform's own
// colors, a live CSS reference works and needs no manual re-resolution.
const REGION_COLOR = "color-mix(in srgb, var(--primary) 18%, transparent)";

function fmt(ms: number): string {
  return formatClock(ms) ?? "0:00";
}

/** "1:02" — seconds are enough for a part boundary; ms are still what's
 *  stored in state/persisted, just not what the author has to type. */
function formatMinSec(ms: number): string {
  const totalSec = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function parseMinSec(text: string): number | null {
  const m = /^(\d+):([0-5]?\d)$/.exec(text.trim());
  if (!m) return null;
  return (Number(m[1]) * 60 + Number(m[2])) * 1000;
}

function clampPartStart(ms: number, endMs: number): number {
  return Math.min(Math.max(0, Math.round(ms)), Math.max(0, endMs - MIN_PART_LENGTH_MS));
}

function clampPartEnd(ms: number, startMs: number, durationMs: number): number {
  const ceiling = durationMs > 0 ? durationMs : Math.max(ms, startMs + MIN_PART_LENGTH_MS);
  return Math.max(Math.min(Math.round(ms), ceiling), Math.min(startMs + MIN_PART_LENGTH_MS, ceiling));
}

/** Canvas `fillStyle` can't read CSS custom properties — resolve literal
 *  color strings from the active theme's tokens at call time. */
function readThemeColors() {
  if (typeof window === "undefined") {
    return { wave: "#646669", progress: "#e2b714" };
  }
  const styles = getComputedStyle(document.documentElement);
  const wave = styles.getPropertyValue("--muted-foreground").trim() || "#646669";
  const progress = styles.getPropertyValue("--primary").trim() || "#e2b714";
  return { wave, progress };
}

interface SilenceRun {
  start: number; // ms
  end: number; // ms
}

/** RMS over ~20ms windows; a run below threshold for >300ms counts as
 *  silence. Runs off the 'decode' event (not render), reads the decoded
 *  buffer's channel data into local loop variables only — never stores the
 *  AudioBuffer itself once this returns. */
function computeSilences(buffer: AudioBuffer): SilenceRun[] {
  const sr = buffer.sampleRate;
  if (buffer.numberOfChannels === 0) return [];
  const data = buffer.getChannelData(0);
  const windowSize = Math.max(1, Math.round((sr * SILENCE_WINDOW_MS) / 1000));
  const runs: SilenceRun[] = [];
  let runStart: number | null = null;

  const flush = (endSample: number) => {
    if (runStart === null) return;
    const startMs = (runStart / sr) * 1000;
    const endMs = (endSample / sr) * 1000;
    if (endMs - startMs >= MIN_SILENCE_MS) runs.push({ start: startMs, end: endMs });
    runStart = null;
  };

  for (let i = 0; i < data.length; i += windowSize) {
    const end = Math.min(i + windowSize, data.length);
    let sumSq = 0;
    for (let j = i; j < end; j++) sumSq += data[j] * data[j];
    const rms = Math.sqrt(sumSq / (end - i));
    if (rms < SILENCE_RMS_THRESHOLD) {
      if (runStart === null) runStart = i;
    } else {
      flush(i);
    }
  }
  flush(data.length);
  return runs;
}

type SnapCandidate = { ms: number; kind: "silence" | "segment"; index: number };

export interface AudioEditorHandle {
  togglePlay: () => void;
}

interface AudioEditorPaneProps {
  audioAssetId: string | null;
  audioUrl: string | null;
  /** Best-known duration before the waveform has decoded (from the
   *  material's own resolved snapshot). */
  durationMsHint: number | null;
  /** True for a single-part material (Part 1 or Part 4 alone) — the author
   *  trims the shared recording to that part's range, so the range block +
   *  waveform region are shown. False for a full test: the recording already
   *  contains all four parts in sequence, there's nothing to trim, and the
   *  parts are purely question groupings — no region, no range UI at all. */
  hasPartRange: boolean;
  /** 1-based, for a single-part material — what the marked range will be
   *  used as. Null for a full test, which has no single part to name. */
  partNumber?: number | null;
  partAudioStart?: number | null;
  partAudioEnd?: number | null;
  onSetPartStart?: (ms: number) => void;
  onSetPartEnd?: (ms: number) => void;
  /** Clears the part range back to "whole audio" (both bounds null) and
   *  re-arms drag-to-create on the waveform. */
  onResetPart?: () => void;
  onUpload: (file: File) => void;
  uploading: boolean;
  /** A save error already known to be about the part's range, humanized by
   *  the page — rendered inline in the part block, never the raw server
   *  string. */
  partError?: string | null;
}

export const AudioEditorPane = forwardRef<AudioEditorHandle, AudioEditorPaneProps>(
  function AudioEditorPane(
    {
      audioAssetId,
      audioUrl,
      durationMsHint,
      hasPartRange,
      partNumber,
      partAudioStart,
      partAudioEnd,
      onSetPartStart,
      onSetPartEnd,
      onResetPart,
      onUpload,
      uploading,
      partError,
    },
    ref,
  ) {
    const containerRef = useRef<HTMLDivElement>(null);
    const wsRef = useRef<WaveSurfer | null>(null);
    const regionsRef = useRef<RegionsPluginType | null>(null);
    const partRegionRef = useRef<Region | null>(null);
    const disableDragSelectionRef = useRef<(() => void) | null>(null);

    const [ready, setReady] = useState(false);
    const [decoding, setDecoding] = useState(false);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [currentMs, setCurrentMs] = useState(0);
    const [durationMs, setDurationMs] = useState(0);
    const [playing, setPlaying] = useState(false);
    const [speed, setSpeed] = useState(1);
    const [loop, setLoop] = useState(false);
    const [zoomPx, setZoomPx] = useState(40);
    const [minZoomPx, setMinZoomPx] = useState(10);
    const [silences, setSilences] = useState<SilenceRun[]>([]);
    const [flash, setFlash] = useState<{ kind: "silence" | "segment"; index: number } | null>(
      null,
    );
    const [search, setSearch] = useState("");
    const [dragOver, setDragOver] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);

    // Drives the custom scroll track below the waveform. Fed by wavesurfer's
    // own `scroll` event (which reports the visible time window) rather than
    // DOM measurements — the element that actually scrolls lives inside the
    // library's shadow root, out of our reach.
    const trackRef = useRef<HTMLDivElement>(null);
    const draggingTrackRef = useRef(false);
    const [view, setView] = useState({ start: 0, end: 0 });

    // Trim view. wavesurfer can't actually crop a waveform, and cropping it
    // for real would mean re-encoding audio the whole dedup/transcribe
    // pipeline is built on sharing — so this zooms the padded range to fill
    // the viewport and clamps scrolling to it. The author sees only the part
    // (±5s); the file underneath is untouched.
    const [focused, setFocused] = useState(false);
    const focusWindowRef = useRef<{ start: number; end: number } | null>(null);
    const [helpOpen, setHelpOpen] = useState(false);

    const totalSec = (durationMs || durationMsHint || 0) / 1000;
    const visibleSec = Math.max(0, view.end - view.start);
    const canScroll = totalSec > 0 && visibleSec > 0 && visibleSec < totalSec - 0.01;
    const thumbPct =
      totalSec > 0 && visibleSec > 0 ? Math.min(100, (visibleSec / totalSec) * 100) : 100;
    const thumbLeftPct =
      totalSec > 0 ? Math.min(100 - thumbPct, (view.start / totalSec) * 100) : 0;
    const scrollFraction =
      totalSec > visibleSec ? view.start / (totalSec - visibleSec) : 0;

    const scrollToPointer = useCallback(
      (clientX: number) => {
        const track = trackRef.current;
        const ws = wsRef.current;
        if (!track || !ws || !canScroll) return;
        const rect = track.getBoundingClientRect();
        const fraction = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
        ws.setScrollTime(fraction * (totalSec - visibleSec));
      },
      [canScroll, totalSec, visibleSec],
    );

    const onTrackPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
      if (!canScroll) return;
      draggingTrackRef.current = true;
      e.currentTarget.setPointerCapture(e.pointerId);
      scrollToPointer(e.clientX);
    };

    const onTrackPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
      if (draggingTrackRef.current) scrollToPointer(e.clientX);
    };

    const endTrackDrag = (e: React.PointerEvent<HTMLDivElement>) => {
      draggingTrackRef.current = false;
      if (e.currentTarget.hasPointerCapture(e.pointerId)) {
        e.currentTarget.releasePointerCapture(e.pointerId);
      }
    };

    // Live-read by event handlers created once per audio load, so toggling
    // these controls doesn't require tearing down the wavesurfer instance.
    const loopRef = useRef(loop);
    const altPressedRef = useRef(false);
    const silencesRef = useRef<SilenceRun[]>([]);
    const partStartRef = useRef(partAudioStart);
    const partEndRef = useRef(partAudioEnd);
    const durationRef = useRef(0);
    const hasPartRangeRef = useRef(hasPartRange);
    useEffect(() => {
      hasPartRangeRef.current = hasPartRange;
    }, [hasPartRange]);
    useEffect(() => {
      loopRef.current = loop;
    }, [loop]);
    useEffect(() => {
      silencesRef.current = silences;
    }, [silences]);
    useEffect(() => {
      partStartRef.current = partAudioStart;
      partEndRef.current = partAudioEnd;
    }, [partAudioStart, partAudioEnd]);

    const { data: asset, isLoading: assetLoading } = useAudioAsset(
      audioAssetId ?? undefined,
    );

    const snapCandidates = useMemo<SnapCandidate[]>(() => {
      const list: SnapCandidate[] = [];
      silences.forEach((run, i) =>
        list.push({ ms: (run.start + run.end) / 2, kind: "silence", index: i }),
      );
      if (asset?.transcript_status === "ready") {
        asset.segments.forEach((seg, i) => {
          list.push({ ms: seg.start_ms, kind: "segment", index: i });
          list.push({ ms: seg.end_ms, kind: "segment", index: i });
        });
      }
      return list;
    }, [silences, asset]);
    const snapCandidatesRef = useRef(snapCandidates);
    useEffect(() => {
      snapCandidatesRef.current = snapCandidates;
    }, [snapCandidates]);

    const effectiveDurationMs = durationMs || asset?.duration_ms || durationMsHint || 0;
    useEffect(() => {
      durationRef.current = effectiveDurationMs;
    }, [effectiveDurationMs]);

    /** The single play control. With a range marked it plays that range: the
     *  playhead jumps to the range's head whenever it sits outside it, and the
     *  'timeupdate' guard stops (or loops) at its tail. */
    const togglePlayback = useCallback(() => {
      const ws = wsRef.current;
      if (!ws) return;
      if (ws.isPlaying()) {
        ws.pause();
        return;
      }
      const region = partRegionRef.current;
      if (region && hasPartRangeRef.current) {
        const t = ws.getCurrentTime();
        // Parked at the tail counts as outside — otherwise pressing play after
        // it stopped there would play nothing at all.
        if (t < region.start - 0.01 || t >= region.end - 0.05) ws.setTime(region.start);
      }
      void ws.play();
    }, []);

    useImperativeHandle(ref, () => ({ togglePlay: togglePlayback }), [togglePlayback]);

    // --- Clamp before persisting: a part shorter than MIN_PART_LENGTH_MS or
    // an inverted range must never reach the server (§2 — fix the cause).
    const commitPartStart = useCallback(
      (ms: number) => {
        const endMs = partEndRef.current ?? durationRef.current;
        onSetPartStart?.(clampPartStart(ms, endMs));
      },
      [onSetPartStart],
    );
    const commitPartEnd = useCallback(
      (ms: number) => {
        const startMs = partStartRef.current ?? 0;
        onSetPartEnd?.(clampPartEnd(ms, startMs, durationRef.current));
      },
      [onSetPartEnd],
    );

    const flashSnap = useCallback((kind: "silence" | "segment", index: number) => {
      setFlash({ kind, index });
      window.setTimeout(() => setFlash((f) => (f?.kind === kind && f.index === index ? null : f)), 450);
    }, []);

    const snapNearest = useCallback((sec: number): SnapCandidate | null => {
      const ms = sec * 1000;
      let best: SnapCandidate | null = null;
      let bestDist = SNAP_THRESHOLD_MS;
      for (const c of snapCandidatesRef.current) {
        const d = Math.abs(c.ms - ms);
        if (d <= bestDist) {
          bestDist = d;
          best = c;
        }
      }
      return best;
    }, []);

    const attachRegionListeners = useCallback(
      (region: Region) => {
        region.on("update", (side) => {
          if (!side || altPressedRef.current) return;
          const candidate = snapNearest(side === "start" ? region.start : region.end);
          if (!candidate) return;
          const snappedSec = candidate.ms / 1000;
          if (side === "start") region.setOptions({ start: snappedSec });
          else region.setOptions({ end: snappedSec });
          flashSnap(candidate.kind, candidate.index);
        });
        region.on("update-end", () => {
          commitPartStart(region.start * 1000);
          commitPartEnd(region.end * 1000);
        });
      },
      [commitPartEnd, commitPartStart, flashSnap, snapNearest],
    );

    const armDragSelection = useCallback((regions: RegionsPluginType) => {
      disableDragSelectionRef.current?.();
      disableDragSelectionRef.current = regions.enableDragSelection({
        drag: true,
        resize: true,
        resizeStart: true,
        resizeEnd: true,
        minLength: MIN_PART_LENGTH_SEC,
        color: REGION_COLOR,
      });
    }, []);

    // Builds the on-waveform region for this material's one trimmable part
    // (single-part materials only — see `hasPartRange`). Called once audio is
    // ready: either the part already has an explicit range (addRegion) or it
    // doesn't yet, in which case the author drags one out (enableDragSelection).
    const syncRegionForActivePart = useCallback(
      (durationSecArg?: number) => {
        const regions = regionsRef.current;
        if (!regions) return;
        const durationSec = durationSecArg ?? durationRef.current / 1000;

        partRegionRef.current?.remove();
        partRegionRef.current = null;
        disableDragSelectionRef.current?.();
        disableDragSelectionRef.current = null;

        const hasExplicitRange = partStartRef.current != null || partEndRef.current != null;
        if (hasExplicitRange) {
          const startSec = (partStartRef.current ?? 0) / 1000;
          const endSec = (partEndRef.current ?? durationSec * 1000) / 1000;
          // Listeners are attached generically via the plugin-level
          // 'region-created' handler below (addRegion emits it too) — attach
          // here would double-bind the same region.
          regions.addRegion({
            start: startSec,
            end: endSec,
            drag: true,
            resize: true,
            resizeStart: true,
            resizeEnd: true,
            minLength: MIN_PART_LENGTH_SEC,
            color: REGION_COLOR,
          });
        } else {
          // No range marked yet for this part: let the author drag one out on
          // the empty waveform instead of forcing a full-width default.
          armDragSelection(regions);
        }
      },
      [armDragSelection],
    );

    // Leaving trim view is "show the whole clip again": drop the clamp and
    // zoom back out to fit-to-width, which is where the editor opens.
    const minZoomPxRef = useRef(minZoomPx);
    useEffect(() => {
      minZoomPxRef.current = minZoomPx;
    }, [minZoomPx]);

    const exitFocus = useCallback(() => {
      focusWindowRef.current = null;
      setFocused(false);
      const ws = wsRef.current;
      if (!ws) return;
      const fit = minZoomPxRef.current;
      setZoomPx(fit);
      ws.zoom(fit);
      ws.setScrollTime(0);
    }, []);

    const handleResetPart = useCallback(() => {
      partRegionRef.current?.remove();
      partRegionRef.current = null;
      exitFocus();
      onResetPart?.();
      if (regionsRef.current) armDragSelection(regionsRef.current);
    }, [armDragSelection, exitFocus, onResetPart]);

    // --- Alt held = snapping disabled, for fine manual control -------------
    useEffect(() => {
      const onDown = (e: KeyboardEvent) => {
        if (e.key === "Alt") altPressedRef.current = true;
      };
      const onUp = (e: KeyboardEvent) => {
        if (e.key === "Alt") altPressedRef.current = false;
      };
      window.addEventListener("keydown", onDown);
      window.addEventListener("keyup", onUp);
      return () => {
        window.removeEventListener("keydown", onDown);
        window.removeEventListener("keyup", onUp);
      };
    }, []);

    // --- Re-resolve canvas colors when the theme changes --------------------
    useEffect(() => {
      const observer = new MutationObserver(() => {
        const c = readThemeColors();
        wsRef.current?.setOptions({
          waveColor: c.wave,
          progressColor: c.progress,
          cursorColor: c.progress,
        });
      });
      observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["data-theme"],
      });
      return () => observer.disconnect();
    }, []);

    // --- Wavesurfer lifecycle: one instance per audioUrl, destroyed on ------
    // unmount/change. Silence detection runs once per decode, off the render
    // path (a microtask after 'decode'), and never retains the AudioBuffer.
    useEffect(() => {
      if (!audioUrl || !containerRef.current) return;
      let disposed = false;
      setReady(false);
      setDecoding(true);
      setLoadError(null);
      setSilences([]);
      partRegionRef.current = null;
      focusWindowRef.current = null;
      setFocused(false);

      void (async () => {
        const [{ default: WS }, { default: RegionsPlugin }] = await Promise.all([
          import("wavesurfer.js"),
          import("wavesurfer.js/dist/plugins/regions.js"),
        ]);
        if (disposed || !containerRef.current) return;

        const colors = readThemeColors();
        const regions = RegionsPlugin.create();
        // Single source of truth for "the part region got (re)created",
        // whether via the initial hydrate (addRegion) or an author drag
        // (enableDragSelection) — both emit this, so one handler covers both
        // without double-binding listeners.
        regions.on("region-created", (region) => {
          partRegionRef.current = region;
          attachRegionListeners(region);
          disableDragSelectionRef.current?.();
          disableDragSelectionRef.current = null;
        });

        const ws = WS.create({
          container: containerRef.current,
          url: mediaUrl(audioUrl),
          height: 64,
          waveColor: colors.wave,
          progressColor: colors.progress,
          cursorColor: colors.progress,
          cursorWidth: 2,
          barWidth: 2,
          barGap: 1,
          barRadius: 2,
          normalize: true,
          // Doesn't affect playback quality — only how fine-grained the
          // decoded buffer is, which keeps a 30-minute file's silence scan
          // (and memory footprint) cheap.
          sampleRate: 8000,
          // wavesurfer scrolls its own element inside a shadow root, so our
          // CSS can't reach that scrollbar and our listeners never see its
          // scroll events. Hide it here and drive a custom track off the
          // library's own `scroll` event instead.
          hideScrollbar: true,
          plugins: [regions],
        });
        wsRef.current = ws;
        regionsRef.current = regions;

        ws.on("ready", (durationSec) => {
          if (disposed) return;
          setReady(true);
          setDecoding(false);
          setDurationMs(durationSec * 1000);
          // Fit-to-width by default — a fixed px/sec floor means a 30-minute
          // file opens unusable (a few hundred px for the whole clip). Zoom
          // back in later; `fit` always returns here.
          const containerWidth = containerRef.current?.clientWidth || 600;
          const fit = Math.max(1, Math.floor(containerWidth / Math.max(durationSec, 1)));
          setMinZoomPx(fit);
          setZoomPx(fit);
          ws.zoom(fit);
          // Full-test materials have nothing to trim — no region, no
          // drag-selection — the recording already contains all four parts
          // in sequence and the parts are purely question groupings.
          if (hasPartRangeRef.current) syncRegionForActivePart(durationSec);
          setView({ start: 0, end: durationSec });
        });
        ws.on("scroll", (visibleStartTime: number, visibleEndTime: number) => {
          if (disposed) return;
          setView({ start: visibleStartTime, end: visibleEndTime });
          // In trim view, pull the viewport back inside the padded range.
          // setScrollTime re-emits 'scroll', but the corrected value is in
          // bounds by construction, so this settles after one pass.
          const win = focusWindowRef.current;
          if (!win) return;
          const visible = visibleEndTime - visibleStartTime;
          const maxStart = Math.max(win.start, win.end - visible);
          const clamped = Math.min(Math.max(visibleStartTime, win.start), maxStart);
          if (Math.abs(clamped - visibleStartTime) > 0.05) ws.setScrollTime(clamped);
        });
        ws.on("decode", () => {
          if (disposed) return;
          const buffer = ws.getDecodedData();
          if (!buffer) return;
          const run = () => {
            if (disposed) return;
            setSilences(computeSilences(buffer));
          };
          // Off the main render path: after decode, before the next paint's
          // urgent work, so a long clip doesn't jank the 'ready' transition.
          const ric = (window as { requestIdleCallback?: (cb: () => void) => number })
            .requestIdleCallback;
          if (ric) ric(run);
          else window.setTimeout(run, 0);
        });
        // Playback is bounded by the marked range, whatever started it — so
        // there's one play button, not one for the clip and one for the part.
        // Enforced here rather than via region.play() because the playhead can
        // also enter the range by seeking or clicking the waveform.
        ws.on("timeupdate", (t) => {
          setCurrentMs(t * 1000);
          const region = partRegionRef.current;
          if (!region || !hasPartRangeRef.current || !ws.isPlaying()) return;
          if (t >= region.end - 0.02) {
            if (loopRef.current) ws.setTime(region.start);
            else ws.pause();
          }
        });
        ws.on("play", () => setPlaying(true));
        ws.on("pause", () => setPlaying(false));
        ws.on("finish", () => {
          if (loopRef.current) void ws.play();
        });
        ws.on("error", (err) => {
          if (disposed) return;
          setLoadError(err?.message || "couldn't decode this audio.");
          setDecoding(false);
        });
      })();

      return () => {
        disposed = true;
        disableDragSelectionRef.current?.();
        disableDragSelectionRef.current = null;
        wsRef.current?.destroy();
        wsRef.current = null;
        regionsRef.current = null;
        partRegionRef.current = null;
      };
      // Only the audio source should tear down/recreate the instance —
      // zoom/loop/etc are pushed via refs or dedicated calls, not a remount.
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [audioUrl]);

    // --- Keep the region in sync when start/end change from elsewhere (the
    // m:ss inputs) rather than a drag on the region itself. ------------------
    useEffect(() => {
      if (!hasPartRange) return;
      const region = partRegionRef.current;
      if (!region || !ready) return;
      const startSec = (partAudioStart ?? 0) / 1000;
      const endSec = (partAudioEnd ?? effectiveDurationMs) / 1000;
      const patch: Partial<{ start: number; end: number }> = {};
      if (Math.abs(region.start - startSec) > 0.01) patch.start = startSec;
      if (Math.abs(region.end - endSec) > 0.01) patch.end = endSec;
      if (Object.keys(patch).length > 0) region.setOptions(patch);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [hasPartRange, partAudioStart, partAudioEnd, ready]);

    useEffect(() => {
      if (wsRef.current) wsRef.current.setPlaybackRate(speed);
    }, [speed]);

    // The hint opens itself for the first few materials so the row's controls
    // get explained before they're needed, then retires behind the ⓘ. Only
    // the automatic showings are counted — opening it deliberately doesn't
    // spend one of them.
    useEffect(() => {
      if (!hasPartRange || !ready) return;
      if (readHelpCount() >= HELP_SHOW_LIMIT) return;
      const t = window.setTimeout(() => {
        setHelpOpen(true);
        window.localStorage.setItem(HELP_KEY, String(readHelpCount() + 1));
      }, 700);
      return () => window.clearTimeout(t);
    }, [hasPartRange, ready]);

    const applyZoom = (px: number, keepFocus = false) => {
      // Reaching for the zoom slider means the author wants the whole clip
      // back under their control, so it silently leaves trim view rather than
      // fighting the scroll clamp.
      if (!keepFocus && focusWindowRef.current) {
        focusWindowRef.current = null;
        setFocused(false);
      }
      setZoomPx(px);
      const ws = wsRef.current;
      if (!ws) return;
      ws.zoom(px);
      // Zoom changes the visible window without necessarily scrolling. Derive
      // it from px-per-second — the one number we know exactly — rather than
      // from wavesurfer's internal element sizes.
      requestAnimationFrame(() => {
        const el = wsRef.current;
        const viewportPx = containerRef.current?.clientWidth ?? 0;
        if (!el || !viewportPx) return;
        const dur = el.getDuration();
        const start = el.getScroll() / px;
        const visible = viewportPx / px;
        setView({ start, end: Math.min(dur, start + visible) });
      });
    };

    const seekBy = (deltaMs: number) => wsRef.current?.skip(deltaMs / 1000);

    const enterFocus = () => {
      const ws = wsRef.current;
      const host = containerRef.current;
      if (!ws || !host) return;
      const dur = durationRef.current;
      const startMs = Math.max(0, (partAudioStart ?? 0) - FOCUS_PAD_MS);
      const endMs = Math.min(dur, (partAudioEnd ?? dur) + FOCUS_PAD_MS);
      const spanSec = Math.max(0.5, (endMs - startMs) / 1000);
      focusWindowRef.current = { start: startMs / 1000, end: endMs / 1000 };
      setFocused(true);
      applyZoom(Math.max(1, host.clientWidth / spanSec), true);
      // After the zoom has been laid out — scrolling to a position the old
      // px/sec can't reach would land in the wrong place.
      requestAnimationFrame(() => ws.setScrollTime(startMs / 1000));
    };

    const toggleFocus = () => (focused ? exitFocus() : enterFocus());

    const segments = useMemo(() => asset?.segments ?? [], [asset]);
    const filteredSegments = useMemo(() => {
      if (!search.trim()) return segments;
      const q = search.trim().toLowerCase();
      return segments.filter((s) => s.text.toLowerCase().includes(q));
    }, [segments, search]);

    const currentSegmentIndex = useMemo(() => {
      if (!playing && currentMs === 0) return -1;
      return segments.findIndex((s) => currentMs >= s.start_ms && currentMs < s.end_ms);
    }, [segments, currentMs, playing]);

    // --- No audio yet: drag-and-drop upload zone instead of the player -----
    if (!audioUrl) {
      return (
        <div className="space-y-3">
          <div className="mb-3 flex items-center gap-2.5 text-xs tracking-wide text-muted-foreground">
            audio
            <span className="h-px flex-1 bg-border" aria-hidden />
          </div>
          <label
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              const f = e.dataTransfer.files?.[0];
              if (f) onUpload(f);
            }}
            className={cn(
              "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-6 py-14 text-center text-muted-foreground transition-colors",
              dragOver ? "border-primary text-foreground" : "border-border",
              uploading && "pointer-events-none opacity-60",
            )}
          >
            {uploading ? (
              <Loader2 className="size-5 animate-spin text-primary" aria-hidden />
            ) : (
              <Upload className="size-5" aria-hidden />
            )}
            <span>drop audio here, or click to browse</span>
            <span className="text-[11px] text-muted-foreground">mp3, wav, m4a</span>
            <input
              ref={fileInputRef}
              type="file"
              accept="audio/*"
              className="hidden"
              disabled={uploading}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) onUpload(f);
                e.target.value = "";
              }}
            />
          </label>
        </div>
      );
    }

    const processing =
      asset?.transcript_status === "pending" || asset?.transcript_status === "processing";
    const failed = asset?.transcript_status === "failed";
    const partDurationMs = Math.max(
      0,
      (partAudioEnd ?? effectiveDurationMs) - (partAudioStart ?? 0),
    );
    // Null on both bounds means "not trimmed" — the part plays the whole clip.
    const hasExplicitRange = partAudioStart != null || partAudioEnd != null;

    return (
      <div>
        <div className="mb-3 flex items-center gap-2.5 text-xs tracking-wide text-muted-foreground">
          audio
          <span className="h-px flex-1 bg-border" aria-hidden />
          <span className="tabular-nums">{fmt(effectiveDurationMs)}</span>
        </div>

        <div className="relative rounded-lg bg-card px-4 py-3.5">
          {/* Scroll position doubles as the card's top edge: invisible while
              the whole clip fits, fading in as a moving rule once zooming
              makes there be somewhere to scroll to. */}
          <div
            ref={trackRef}
            onPointerDown={onTrackPointerDown}
            onPointerMove={onTrackPointerMove}
            onPointerUp={endTrackDrag}
            onPointerCancel={endTrackDrag}
            role="scrollbar"
            aria-orientation="horizontal"
            aria-valuenow={Math.round(scrollFraction * 100)}
            aria-label="Scroll waveform"
            tabIndex={-1}
            className={cn(
              "absolute inset-x-0 top-0 z-20 h-[3px] overflow-hidden rounded-t-lg transition-opacity duration-300",
              canScroll ? "cursor-grab opacity-100" : "pointer-events-none opacity-0",
            )}
          >
            <div
              className="absolute inset-y-0 bg-foreground/35 transition-[width,left] duration-200 ease-out hover:bg-foreground/55"
              style={{ width: `${thumbPct}%`, left: `${thumbLeftPct}%` }}
            />
          </div>

          {/* Silence is already legible in the waveform itself (the flat
              stretches), so no band overlay is drawn — one pinned to this
              wrapper can't stay aligned with the content wavesurfer scrolls
              and rescales on zoom. The computed runs are still used, as snap
              targets when dragging the part handles. */}
          <div className="relative mt-1">
            {/* Explicit height: wavesurfer renders into a shadow root, so this
                host derives no intrinsic height from it and would collapse to
                zero — dropping the controls below on top of the waveform.
                Must match the `height` passed to WaveSurfer.create. */}
            <div ref={containerRef} className="relative z-10 h-16 w-full" />
            {(decoding || !ready) && !loadError && (
              <div className="absolute inset-0 z-20 flex items-center justify-center gap-2 bg-card text-xs text-muted-foreground">
                <Loader2 className="size-3.5 animate-spin text-primary" aria-hidden />
                decoding waveform…
              </div>
            )}
            {loadError && (
              <div className="absolute inset-0 z-20 flex items-center justify-center bg-card px-3 text-center text-xs text-destructive">
                {loadError} — try replacing the file.
              </div>
            )}
          </div>

          {/* Transport — centred under the waveform, skip buttons flanking
              play, elapsed/total tucked to the right so the trio stays
              optically centred. */}
          <div className="relative mt-3 flex items-center justify-center gap-3">
            {/* Settings live in popovers on the otherwise empty left side:
                a compact trigger showing the current value, a slider inside. */}
            <div className="absolute left-0 flex items-center gap-1">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    aria-label="Playback speed"
                    className="flex h-7 w-12 items-center justify-center rounded-md text-xs tabular-nums text-muted-foreground transition-colors hover:bg-foreground/8 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                  >
                    {speed.toFixed(1)}×
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="w-44 p-3">
                  <div className="flex items-center gap-2">
                    <Gauge className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                    <input
                      type="range"
                      min={0.5}
                      max={2}
                      step={0.05}
                      value={speed}
                      onChange={(e) => setSpeed(Number(e.target.value))}
                      aria-label="Playback speed"
                      className="h-1 flex-1 accent-primary"
                    />
                  </div>
                  <div className="mt-2 text-center text-xs tabular-nums text-foreground">
                    {speed.toFixed(1)}×
                  </div>
                </DropdownMenuContent>
              </DropdownMenu>

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    aria-label="Waveform zoom"
                    className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-foreground/8 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                  >
                    <ZoomIn className="size-3.5" aria-hidden />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="w-48 p-3">
                  <div className="flex items-center gap-2">
                    <ZoomIn className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                    {/* Logarithmic: fit-to-width can be ~3px/sec on a long
                        file while the top end is 250, so a linear slider would
                        cram every useful value into its first few pixels. */}
                    <input
                      type="range"
                      min={0}
                      max={100}
                      step={1}
                      value={zoomToSlider(zoomPx, minZoomPx)}
                      onChange={(e) =>
                        applyZoom(sliderToZoom(Number(e.target.value), minZoomPx))
                      }
                      aria-label="Waveform zoom"
                      className="h-1 flex-1 accent-primary"
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => applyZoom(minZoomPx)}
                    className="mt-2 w-full rounded px-2 py-1 text-center text-xs text-muted-foreground transition-colors hover:bg-foreground/8 hover:text-foreground"
                  >
                    fit whole clip
                  </button>
                </DropdownMenuContent>
              </DropdownMenu>

              <button
                type="button"
                onClick={() => setLoop((v) => !v)}
                aria-pressed={loop}
                aria-label={hasExplicitRange ? "Loop the part" : "Loop"}
                title={hasExplicitRange ? "Loop the part" : "Loop"}
                className={cn(
                  "flex size-7 items-center justify-center rounded-md transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                  loop
                    ? "bg-primary/15 text-primary"
                    : "text-muted-foreground hover:bg-foreground/8 hover:text-foreground",
                )}
              >
                <Repeat className="size-3.5" aria-hidden />
              </button>
            </div>

            <button
              type="button"
              onClick={() => seekBy(-3000)}
              aria-label="Back 3 seconds"
              className="rounded-md bg-foreground/8 px-2.5 py-1 text-xs text-foreground transition-colors hover:bg-foreground/14 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              −3s
            </button>
            <button
              type="button"
              onClick={togglePlayback}
              disabled={!ready}
              aria-label={
                playing ? "Pause" : hasExplicitRange ? "Play the part" : "Play"
              }
              className="flex size-9 shrink-0 items-center justify-center rounded-full border border-foreground/15 text-foreground transition-colors hover:border-primary/50 hover:text-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-40"
            >
              {playing ? <Pause className="size-4" /> : <Play className="size-4" />}
            </button>
            <button
              type="button"
              onClick={() => seekBy(3000)}
              aria-label="Forward 3 seconds"
              className="rounded-md bg-foreground/8 px-2.5 py-1 text-xs text-foreground transition-colors hover:bg-foreground/14 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              +3s
            </button>
            <span className="absolute right-0 text-xs tabular-nums text-muted-foreground">
              {fmt(currentMs)} / {fmt(effectiveDurationMs)}
            </span>
          </div>

          {/* Footer — one row. The part range used to be a bordered panel of
              three stacked rows (a card inside the card) plus a separate
              "replace audio" row; everything it said is now either implicit
              (the fields ARE the range, so the read-only echo of them was
              redundant) or folded into an affordance: "set start/end at the
              playhead" is the ⌖ button attached to each field. Only a
              single-part material gets the range controls — a full test has
              nothing to trim, its recording already runs all four parts in
              sequence. */}
          <div className="mt-2.5 flex items-center gap-2 border-t border-border pt-2.5 text-[11px]">
            {hasPartRange && (
              <>
                <DropdownMenu open={helpOpen} onOpenChange={setHelpOpen}>
                  <DropdownMenuTrigger asChild>
                    <button
                      type="button"
                      title="How the part range works"
                      aria-label="How the part range works"
                      className={cn(
                        "flex size-5 shrink-0 items-center justify-center rounded-full transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                        helpOpen
                          ? "bg-primary/15 text-primary"
                          : "text-muted-foreground hover:bg-foreground/8 hover:text-foreground",
                      )}
                    >
                      <Info className="size-3.5" aria-hidden />
                    </button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent
                    align="start"
                    side="top"
                    sideOffset={8}
                    className="w-[19rem] p-0"
                  >
                    {/* The one thing the author actually needs to know leads,
                        and it's the only emphasized line — the icon rows below
                        are reference, so their weight stays flat. */}
                    <p className="border-b border-border px-3.5 py-3 text-xs leading-relaxed text-foreground">
                      The stretch you mark on the waveform is what learners hear as
                      {partNumber ? ` Part ${partNumber}` : " this part"}.
                    </p>
                    <ul className="space-y-2.5 px-3.5 py-3 text-[11px] leading-relaxed text-muted-foreground">
                      <HelpRow icon={<MoveHorizontal className="size-3.5" aria-hidden />}>
                        Drag across the waveform to mark it — the edges snap to pauses in
                        the speech.
                      </HelpRow>
                      {/* The fields lost their "start"/"end" words to icons,
                          so the help card is now where those icons get named. */}
                      <HelpRow icon={<ArrowRightFromLine className="size-3.5" aria-hidden />}>
                        The two fields are where the part begins and ends — type a time in
                        directly if you already know it.
                      </HelpRow>
                      <HelpRow icon={<Crosshair className="size-3.5" aria-hidden />}>
                        Sets that edge to wherever playback has reached.
                      </HelpRow>
                      <HelpRow icon={<Scissors className="size-3.5" aria-hidden />}>
                        Zooms in on just the marked stretch, keeping 5s either side.
                      </HelpRow>
                      <HelpRow icon={<Play className="size-3.5" aria-hidden />}>
                        Once a range is marked, play stays inside it — you always hear
                        exactly what learners will.
                      </HelpRow>
                      <HelpRow icon={<RotateCcw className="size-3.5" aria-hidden />}>
                        Clears the marking and brings the whole recording back.
                      </HelpRow>
                    </ul>
                    <div className="border-t border-border px-3.5 py-2.5">
                      <button
                        type="button"
                        onClick={() => setHelpOpen(false)}
                        className="w-full rounded bg-foreground/8 py-1.5 text-center text-[11px] text-foreground transition-colors hover:bg-foreground/14"
                      >
                        Got it
                      </button>
                    </div>
                  </DropdownMenuContent>
                </DropdownMenu>

                <span className="flex h-7 shrink-0 items-center text-muted-foreground">
                  part{partNumber ? ` ${partNumber}` : ""}
                </span>
                <RangeField
                  ms={partAudioStart ?? 0}
                  onCommit={commitPartStart}
                  onPlayhead={() => commitPartStart(currentMs)}
                  label="Part start"
                  icon={<ArrowRightFromLine className="size-3.5 shrink-0" aria-hidden />}
                />
                {/* No separator arrow between the fields — the |→ and →| icons
                    inside them already say which edge is which. */}
                <RangeField
                  ms={partAudioEnd ?? effectiveDurationMs}
                  onCommit={commitPartEnd}
                  onPlayhead={() => commitPartEnd(currentMs)}
                  label="Part end"
                  icon={<ArrowRightToLine className="size-3.5 shrink-0" aria-hidden />}
                />
                {/* Only once a range is actually marked — an untrimmed part
                    has no length worth stating, and labelling it invited the
                    reading that "whole clip" was a setting. */}
                {hasExplicitRange && (
                  <span className="flex h-7 shrink-0 items-center tabular-nums text-foreground">
                    {fmt(partDurationMs)}
                  </span>
                )}

                <span className="mx-0.5 flex items-center gap-0.5">
                  <IconButton
                    label={focused ? "Show the whole recording" : "Trim view — just this part"}
                    onClick={toggleFocus}
                    disabled={!ready || !hasExplicitRange}
                    pressed={focused}
                  >
                    <Scissors className="size-3.5" aria-hidden />
                  </IconButton>
                  {/* No play/loop here — the transport's own play button is
                      bound to the marked range, so a second pair would be two
                      controls for one job. */}
                  <IconButton
                    label="Reset part range"
                    onClick={handleResetPart}
                    disabled={!ready || !hasExplicitRange}
                  >
                    <RotateCcw className="size-3.5" aria-hidden />
                  </IconButton>
                </span>

                {partError && (
                  <span
                    className="flex h-7 min-w-0 items-center truncate text-destructive"
                    title={partError}
                  >
                    {partError}
                  </span>
                )}
              </>
            )}

            {/* Quiet and last: this discards the current audio. */}
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="ml-auto flex h-7 shrink-0 items-center gap-1.5 rounded-md px-2 text-muted-foreground transition-colors hover:bg-foreground/8 hover:text-foreground disabled:opacity-50"
            >
              {uploading ? (
                <Loader2 className="size-3.5 animate-spin text-primary" aria-hidden />
              ) : (
                <Upload className="size-3.5" aria-hidden />
              )}
              {uploading ? "replacing…" : "replace audio"}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="audio/*"
              className="hidden"
              disabled={uploading}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) onUpload(f);
                e.target.value = "";
              }}
            />
          </div>
        </div>

        <div className="mt-5 mb-3 flex items-center gap-2.5 text-xs tracking-wide text-muted-foreground">
          transcript
          <span className="h-px flex-1 bg-border" aria-hidden />
          <span>auto</span>
        </div>

        {asset?.transcript_status === "ready" && (
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="search transcript…"
            aria-label="Search transcript"
            className="mb-3 w-full rounded-md border border-border bg-transparent px-3 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:outline-none"
          />
        )}

        <div className="text-sm leading-loose">
          {asset === undefined && assetLoading && (
            <p className="text-xs text-muted-foreground">loading transcript…</p>
          )}

          {failed && (
            <div className="space-y-1 rounded-md bg-destructive/10 px-3 py-2.5 text-xs text-destructive">
              <p className="font-medium">transcription failed</p>
              {asset?.transcript_error && <p>{asset.transcript_error}</p>}
              <p>replace the audio and try again.</p>
            </div>
          )}

          {asset?.transcript_status === "ready" && filteredSegments.length === 0 && (
            <p className="text-xs text-muted-foreground">no matches.</p>
          )}

          {asset?.transcript_status === "ready" &&
            filteredSegments.map((seg) => {
              const trueIndex = segments.indexOf(seg);
              return (
                <TranscriptSegment
                  key={seg.order_index}
                  segment={seg}
                  current={trueIndex === currentSegmentIndex}
                  flashed={flash?.kind === "segment" && flash.index === trueIndex}
                  search={search}
                  onClick={() => void wsRef.current?.play(seg.start_ms / 1000)}
                />
              );
            })}

          {/* No fabricated progress (§2 honesty constraint) — the worker
              writes all segments at once, so there's no partial figure to
              show, only that it's in flight and the clip's total length. */}
          {processing && (
            <div className="flex items-center gap-2 px-2 py-2 text-xs text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin text-primary" aria-hidden />
              transcribing… ({fmt(effectiveDurationMs)} clip)
            </div>
          )}
        </div>
      </div>
    );
  },
);

/** One line of the help card: the icon in its own gutter so the sentences
 *  align down a single edge, both columns at the same weight — the emphasis
 *  belongs to the lead paragraph, not to reference rows. */
function HelpRow({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <li className="flex gap-2.5">
      <span className="mt-px flex size-4 shrink-0 items-center justify-center text-muted-foreground">
        {icon}
      </span>
      <span className="min-w-0">{children}</span>
    </li>
  );
}

/** A 28px square control for the part row. Icon-only because the row is the
 *  compact form of what used to be three rows of labelled buttons — the
 *  accessible name carries the label, and `title` surfaces it on hover. */
function IconButton({
  label,
  onClick,
  disabled,
  pressed,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  pressed?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      aria-pressed={pressed}
      className={cn(
        "flex size-7 items-center justify-center rounded-md transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-40 disabled:hover:bg-transparent",
        pressed
          ? "bg-primary/15 text-primary"
          : "text-muted-foreground hover:bg-foreground/8 hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

/** A time input with "set from the playhead" attached to it. Pairing the two
 *  removes the separate `set start` / `set end` buttons: the action belongs to
 *  the field it fills, so it reads as one control instead of two.
 *
 *  The two halves are deliberately drawn differently — the input side is a
 *  recessed well, the button side is a raised key with its own divider and a
 *  hover state. Sharing one flat background made the button invisible. */
function RangeField({
  ms,
  onCommit,
  onPlayhead,
  label,
  icon,
}: {
  ms: number;
  onCommit: (ms: number) => void;
  onPlayhead: () => void;
  label: string;
  /** Marks which edge this is: |→ opens the range, →| closes it. The words
   *  "start"/"end" said the same thing in twice the height, and the icons
   *  read left-to-right the way the timeline does. */
  icon: React.ReactNode;
}) {
  return (
    <span className="flex h-7 shrink-0 items-stretch overflow-hidden rounded-md border border-border/80 focus-within:border-primary">
      <label className="flex cursor-text items-center gap-1.5 pl-2 text-muted-foreground">
        {icon}
        <TimeField ms={ms} onCommit={onCommit} label={label} bare />
      </label>
      <button
        type="button"
        onClick={onPlayhead}
        title={`${label} at playhead`}
        aria-label={`${label} at playhead`}
        className="flex w-8 shrink-0 items-center justify-center border-l border-border/80 bg-foreground/8 text-muted-foreground transition-colors hover:bg-primary/15 hover:text-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        <Crosshair className="size-3.5" aria-hidden />
      </button>
    </span>
  );
}

function TimeField({
  ms,
  onCommit,
  label,
  bare,
}: {
  ms: number;
  onCommit: (ms: number) => void;
  label: string;
  /** Rendered inside RangeField, which owns the border and background. */
  bare?: boolean;
}) {
  const [draft, setDraft] = useState(() => formatMinSec(ms));
  const focused = useRef(false);

  useEffect(() => {
    if (!focused.current) setDraft(formatMinSec(ms));
  }, [ms]);

  const commit = () => {
    const parsed = parseMinSec(draft);
    if (parsed != null) onCommit(parsed);
    else setDraft(formatMinSec(ms));
  };

  return (
    <input
      type="text"
      value={draft}
      aria-label={label}
      onFocus={() => {
        focused.current = true;
      }}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        focused.current = false;
        commit();
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter") e.currentTarget.blur();
        else if (e.key === "Escape") {
          setDraft(formatMinSec(ms));
          e.currentTarget.blur();
        }
      }}
      className={cn(
        "text-center text-[11px] tabular-nums text-foreground focus:outline-none",
        bare
          ? "w-10 bg-transparent p-0 text-left"
          : "w-12 rounded border border-transparent bg-foreground/6 px-1.5 py-0.5 focus:border-primary",
      )}
    />
  );
}

function TranscriptSegment({
  segment,
  current,
  flashed,
  search,
  onClick,
}: {
  segment: AudioSegment;
  current: boolean;
  flashed: boolean;
  search: string;
  onClick: () => void;
}) {
  const text = segment.text;
  const q = search.trim();
  let content: React.ReactNode = text;
  if (q) {
    const idx = text.toLowerCase().indexOf(q.toLowerCase());
    if (idx >= 0) {
      content = (
        <>
          {text.slice(0, idx)}
          <mark className="bg-transparent text-primary">
            {text.slice(idx, idx + q.length)}
          </mark>
          {text.slice(idx + q.length)}
        </>
      );
    }
  }

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-start gap-2.5 rounded-md px-2 py-1 text-left transition-colors hover:bg-foreground/6",
        current && "bg-foreground/6",
        flashed && "ring-1 ring-primary/60",
      )}
    >
      <span className="mt-0.5 shrink-0 text-[11px] tabular-nums text-muted-foreground">
        {fmt(segment.start_ms)}
      </span>
      <span className={cn(current ? "text-foreground" : "text-muted-foreground")}>
        {content}
      </span>
    </button>
  );
}

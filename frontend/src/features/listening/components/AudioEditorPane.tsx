import {
  Fragment,
  forwardRef,
  memo,
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
  ArrowDown,
  ArrowUp,
  Gauge,
  Info,
  Loader2,
  MousePointerClick,
  MoveHorizontal,
  Pause,
  Pencil,
  Play,
  Repeat,
  RotateCcw,
  Scissors,
  Upload,
  X,
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
import {
  useAudioAsset,
  useUpdateSegmentText,
} from "@/features/listening/queries";
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
// How long a mark taken from the playhead runs for. Roughly a spoken phrase:
// long enough to hear the answer in context, short enough not to give away
// the next one.
const DEFAULT_MARK_MS = 4000;
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
  return Math.min(
    Math.max(0, Math.round(ms)),
    Math.max(0, endMs - MIN_PART_LENGTH_MS),
  );
}

function clampPartEnd(ms: number, startMs: number, durationMs: number): number {
  const ceiling =
    durationMs > 0 ? durationMs : Math.max(ms, startMs + MIN_PART_LENGTH_MS);
  return Math.max(
    Math.min(Math.round(ms), ceiling),
    Math.min(startMs + MIN_PART_LENGTH_MS, ceiling),
  );
}

/** Canvas `fillStyle` can't read CSS custom properties — resolve literal
 *  color strings from the active theme's tokens at call time. */
function readThemeColors() {
  if (typeof window === "undefined") {
    return { wave: "#646669", progress: "#e2b714" };
  }
  const styles = getComputedStyle(document.documentElement);
  const wave =
    styles.getPropertyValue("--muted-foreground").trim() || "#646669";
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
    if (endMs - startMs >= MIN_SILENCE_MS)
      runs.push({ start: startMs, end: endMs });
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

/** Compare words the way a reader does: without the punctuation stuck to
 *  them, and without case. */
function stripWord(word: string): string {
  return word.toLowerCase().replace(/[^a-z0-9']/g, "");
}

export interface MarkRange {
  startMs: number;
  endMs: number;
}

export interface AudioEditorHandle {
  togglePlay: () => void;
  /** What the author is pointing at when they ask to mark where an answer is
   *  said. A transcript selection is used straight away — the words carry
   *  exact timings. With nothing selected but a transcript to click, the
   *  caller puts the pane into picking mode. Only with no transcript at all
   *  does it fall back to the playhead. */
  pickTarget: () =>
    | { kind: "selection"; range: MarkRange }
    | { kind: "needs-pick" }
    | { kind: "playhead"; range: MarkRange }
    | null;
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
  /** While true the transcript is a target: clicking a line reports it back
   *  instead of playing from it. */
  picking?: boolean;
  onPickSegment?: (range: MarkRange) => void;
  onCancelPick?: () => void;
  /** Where answers have been marked, so the transcript can show them. The
   *  marked seconds are tinted and the answer inside them is picked out —
   *  found by matching the text, never marked by hand. */
  marks?: { startMs: number; endMs: number; answers: string[] }[];
  /** Places the answer is said, found in the transcript, offered while
   *  picking so the author can take one instead of hunting for it. */
  suggestions?: {
    answer: string;
    startMs: number;
    endMs: number;
    wordStartMs: number;
    context: string;
  }[];
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

export const AudioEditorPane = forwardRef<
  AudioEditorHandle,
  AudioEditorPaneProps
>(function AudioEditorPane(
  {
    audioAssetId,
    audioUrl,
    durationMsHint,
    hasPartRange,
    picking,
    onPickSegment,
    onCancelPick,
    marks,
    suggestions,
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
  const [flash, setFlash] = useState<{
    kind: "silence" | "segment";
    index: number;
  } | null>(null);
  const [search, setSearch] = useState("");
  const [dragOver, setDragOver] = useState(false);

  // Whether the transcript follows playback. Mirrored into a ref because the
  // wavesurfer handlers read it outside React's render cycle, while the back
  // button needs a re-render: it stays hidden while following, since following
  // is already keeping the line in view.
  const [following, setFollowing] = useState(true);
  const followRef = useRef(true);
  const setFollow = useCallback((value: boolean) => {
    followRef.current = value;
    setFollowing(value);
  }, []);
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
  const canScroll =
    totalSec > 0 && visibleSec > 0 && visibleSec < totalSec - 0.01;
  const thumbPct =
    totalSec > 0 && visibleSec > 0
      ? Math.min(100, (visibleSec / totalSec) * 100)
      : 100;
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
      const fraction = Math.min(
        1,
        Math.max(0, (clientX - rect.left) / rect.width),
      );
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

  const effectiveDurationMs =
    durationMs || asset?.duration_ms || durationMsHint || 0;
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
    // Pressing play is the signal that the author wants to follow the audio
    // again, whatever they scrolled to while it was paused.
    setFollow(true);
    const region = partRegionRef.current;
    if (region && hasPartRangeRef.current) {
      const t = ws.getCurrentTime();
      // Parked at the tail counts as outside — otherwise pressing play after
      // it stopped there would play nothing at all.
      if (t < region.start - 0.01 || t >= region.end - 0.05)
        ws.setTime(region.start);
    }
    void ws.play();
  }, []);


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

  // The wavesurfer instance is built once per audioUrl, so its handlers close
  // over whatever these were on that render. The page rebuilds onSetPartStart
  // /onSetPartEnd every render, so reach them through refs — otherwise a
  // region drag writes through a stale callback.
  const commitStartRef = useRef(commitPartStart);
  const commitEndRef = useRef(commitPartEnd);
  useEffect(() => {
    commitStartRef.current = commitPartStart;
    commitEndRef.current = commitPartEnd;
  }, [commitPartStart, commitPartEnd]);

  const flashSnap = useCallback(
    (kind: "silence" | "segment", index: number, ms = 450) => {
      setFlash({ kind, index });
      window.setTimeout(
        () =>
          setFlash((f) => (f?.kind === kind && f.index === index ? null : f)),
        ms,
      );
    },
    [],
  );

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
        const candidate = snapNearest(
          side === "start" ? region.start : region.end,
        );
        if (!candidate) return;
        const snappedSec = candidate.ms / 1000;
        if (side === "start") region.setOptions({ start: snappedSec });
        else region.setOptions({ end: snappedSec });
        flashSnap(candidate.kind, candidate.index);
      });
      region.on("update-end", () => {
        commitStartRef.current(region.start * 1000);
        commitEndRef.current(region.end * 1000);
      });
    },
    [flashSnap, snapNearest],
  );

  /** Writes a newly created region to the part, snapping it first.
   *
   *  Drag-selection never emits 'update-end': the plugin builds the region
   *  internally and only calls saveRegion() on pointerup, so the listeners
   *  attached at 'region-created' arrive too late to catch the drag that
   *  created it. Without this the first drag left the fields untouched and
   *  only a second drag — which resizes the now-existing region, and does
   *  emit 'update-end' — appeared to work.
   *
   *  The guard is the region's own bounds versus the part's, rather than a
   *  flag saying who created it: addRegion() hydrating saved bounds matches
   *  and writes nothing, anything else differs and gets committed. */
  const commitRegionIfChanged = useCallback(
    (region: Region) => {
      const knownStart = partStartRef.current;
      const knownEnd = partEndRef.current;
      if (knownStart != null || knownEnd != null) {
        const effStart = knownStart ?? 0;
        const effEnd = knownEnd ?? durationRef.current;
        const same =
          Math.abs(effStart - region.start * 1000) < 20 &&
          Math.abs(effEnd - region.end * 1000) < 20;
        if (same) return;
      }

      let startSec = region.start;
      let endSec = region.end;
      if (!altPressedRef.current) {
        const startSnap = snapNearest(startSec);
        const endSnap = snapNearest(endSec);
        const snappedStart = startSnap ? startSnap.ms / 1000 : startSec;
        const snappedEnd = endSnap ? endSnap.ms / 1000 : endSec;
        // Snapping both edges toward each other could collapse a short
        // selection below the minimum — keep the raw bounds if it would.
        if (snappedEnd - snappedStart >= MIN_PART_LENGTH_SEC) {
          startSec = snappedStart;
          endSec = snappedEnd;
          region.setOptions({ start: startSec, end: endSec });
          if (startSnap) flashSnap(startSnap.kind, startSnap.index);
          if (endSnap) flashSnap(endSnap.kind, endSnap.index);
        }
      }
      commitStartRef.current(startSec * 1000);
      commitEndRef.current(endSec * 1000);
    },
    [flashSnap, snapNearest],
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

      const hasExplicitRange =
        partStartRef.current != null || partEndRef.current != null;
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
        commitRegionIfChanged(region);
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
        const fit = Math.max(
          1,
          Math.floor(containerWidth / Math.max(durationSec, 1)),
        );
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
        const clamped = Math.min(
          Math.max(visibleStartTime, win.start),
          maxStart,
        );
        if (Math.abs(clamped - visibleStartTime) > 0.05)
          ws.setScrollTime(clamped);
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
        const ric = (
          window as { requestIdleCallback?: (cb: () => void) => number }
        ).requestIdleCallback;
        if (ric) ric(run);
        else window.setTimeout(run, 0);
      });
      // Playback is bounded by the marked range, whatever started it — so
      // there's one play button, not one for the clip and one for the part.
      // Enforced here rather than via region.play() because the playhead can
      // also enter the range by seeking or clicking the waveform.
      ws.on("timeupdate", (t) => {
        // Quantised. wavesurfer emits this ~60×/s and every emit re-renders
        // the transcript; 50ms is the coarsest step that still lands cleanly
        // inside a spoken word (they run ~250ms and up), so word highlighting
        // tracks the voice without paying for three quarters of the renders.
        // Returning `prev` unchanged makes React bail out entirely.
        setCurrentMs((prev) => {
          const ms = Math.round(t * 1000);
          return Math.abs(prev - ms) >= 50 ? ms : prev;
        });
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
    let visible = segments;

    // Trim view narrows the transcript to the part, the same way it narrows
    // the waveform: outside the marked seconds nothing belongs to this part,
    // so it is neither worth reading nor worth marking an answer against.
    if (focused && partAudioStart != null && partAudioEnd != null) {
      visible = visible.filter(
        (s) => s.start_ms < partAudioEnd && s.end_ms > partAudioStart,
      );
    }

    const q = search.trim().toLowerCase();
    if (!q) return visible;
    return visible.filter((s) => s.text.toLowerCase().includes(q));
  }, [segments, search, focused, partAudioStart, partAudioEnd]);

  // The last segment that has started, not the one strictly containing the
  // playhead: speech has gaps between sentences, and requiring containment
  // left "no current segment" during every pause — which unhighlighted the
  // line and blinked the back button off between chunks.
  /** Segment order index -> the answers marked over it. Memoised because the
   *  rows are, and a fresh array per render would defeat that. */
  const marksBySegment = useMemo(() => {
    const map = new Map<number, string[]>();
    if (!marks || marks.length === 0) return map;
    for (const segment of segments) {
      const answers = marks
        .filter((m) => segment.start_ms < m.endMs && segment.end_ms > m.startMs)
        .flatMap((m) => m.answers);
      if (answers.length > 0) map.set(segment.order_index, answers);
    }
    return map;
  }, [marks, segments]);

  const currentSegmentIndex = useMemo(() => {
    if (!playing && currentMs === 0) return -1;
    let found = -1;
    for (let i = 0; i < segments.length; i++) {
      if (segments[i].start_ms > currentMs) break;
      found = i;
    }
    return found;
  }, [segments, currentMs, playing]);

  // Which word inside that line is being said. "Last one started", for the
  // same reason as the line itself: there are gaps between words, and
  // requiring containment would drop the highlight in every one of them.
  const activeWordIndex = useMemo(() => {
    if (currentSegmentIndex < 0) return -1;
    const words = segments[currentSegmentIndex]?.words ?? [];
    let found = -1;
    for (let i = 0; i < words.length; i++) {
      if (words[i].start_ms > currentMs) break;
      found = i;
    }
    return found;
  }, [segments, currentSegmentIndex, currentMs]);

  // --- Follow along: keep the segment being spoken in view ----------------
  // Correcting a mishearing. Stored against this asset, never the shared
  // blob — see the endpoint's own note.
  const [editingSegment, setEditingSegment] = useState<number | null>(null);
  const updateSegment = useUpdateSegmentText(audioAssetId ?? undefined);

  const listRef = useRef<HTMLDivElement>(null);
  // The range built up in this picking session. Held so a shift-click has
  // something to extend from, and so the marked lines can be tinted.
  const [pickRange, setPickRange] = useState<MarkRange | null>(null);
  const pickRangeRef = useRef<MarkRange | null>(null);
  const pickingRef = useRef(false);
  const onPickSegmentRef = useRef(onPickSegment);
  // Held in a ref because `selectionRange` is declared further down, once the
  // transcript segments it reads exist.
  const selectionRangeRef = useRef<(() => MarkRange | null) | null>(null);
  const shiftHeldRef = useRef(false);
  useEffect(() => {
    pickingRef.current = !!picking;
    onPickSegmentRef.current = onPickSegment;
    if (!picking) {
      setPickRange(null);
      pickRangeRef.current = null;
    }
  }, [picking, onPickSegment]);

  useEffect(() => {
    if (!picking) return;
    const onKey = (e: KeyboardEvent) => {
      shiftHeldRef.current = e.shiftKey;
      if (e.key === "Escape") onCancelPick?.();
    };
    const onKeyUp = (e: KeyboardEvent) => {
      shiftHeldRef.current = e.shiftKey;
    };
    const onDown = (e: MouseEvent) => {
      shiftHeldRef.current = e.shiftKey;
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("mousedown", onDown, true);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("mousedown", onDown, true);
    };
  }, [picking, onCancelPick]);

  /** Segments are looked up in the DOM by order index rather than kept in a
   *  ref map: the map's entries were rewritten on every timeupdate (the ref
   *  callbacks are recreated each render), which is a lot of churn to carry
   *  for a lookup the DOM already indexes. */
  /** How far a line sits from the top of the scroll box's content.
   *
   *  Measured from the rectangles rather than read off `offsetTop`, which is
   *  relative to the nearest *positioned* ancestor — that used to be the
   *  scroll box, then the line grew a `relative` wrapper of its own and every
   *  offset silently became ~0, so scrolling anywhere landed at the top. */
  const offsetWithin = (box: HTMLElement, el: HTMLElement): number =>
    box.scrollTop + (el.getBoundingClientRect().top - box.getBoundingClientRect().top);

  const segmentEl = (orderIndex: number | undefined): HTMLElement | null => {
    const box = listRef.current;
    if (!box || orderIndex === undefined) return null;
    return box.querySelector<HTMLElement>(`[data-order="${orderIndex}"]`);
  };

  const currentOrderIndex =
    currentSegmentIndex >= 0
      ? segments[currentSegmentIndex]?.order_index
      : undefined;

  // Whether the spoken line is fully inside the pane. Answered by the browser
  // rather than by comparing rectangles ourselves: an IntersectionObserver
  // rooted at the scroll box is the one measurement that can't disagree with
  // what's actually on screen, and it re-fires on its own as the pane scrolls,
  // so no scroll handler or timing window is involved.
  const [activeFullyVisible, setActiveFullyVisible] = useState(true);
  // Which way the spoken line went, so the button points at it. Kept when the
  // button hides so the icon doesn't flip during the fade out.
  const [activeDirection, setActiveDirection] = useState<"up" | "down">("up");

  useEffect(() => {
    const box = listRef.current;
    const el = segmentEl(currentOrderIndex);
    if (!box || !el) {
      setActiveFullyVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        setActiveFullyVisible(entry.intersectionRatio >= 0.99);
        // The observer already hands us both rectangles in the same space,
        // so the direction costs nothing extra to derive.
        if (entry.rootBounds) {
          setActiveDirection(
            entry.boundingClientRect.top < entry.rootBounds.top ? "up" : "down",
          );
        }
      },
      { root: box, threshold: [0, 0.5, 0.99, 1] },
    );
    observer.observe(el);
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentOrderIndex, filteredSegments]);

  // Following stands down on real input, never on scroll events: our own
  // smooth scroll emits those too, and no timing window reliably separates the
  // tail of one from the start of the author's. A wheel, a drag, or a key is
  // unambiguously theirs.
  const onTranscriptInput = () => setFollow(false);

  const scrollToCurrent = useCallback(() => {
    const box = listRef.current;
    const el = segmentEl(currentOrderIndex);
    if (!box || !el) return;

    // The spoken line sits second from the top: the line before it stays
    // visible above as context, and everything still to come fills the pane
    // below. Scrolling to the *previous* segment's offset puts it there
    // exactly, whatever height either line wrapped to.
    const i = filteredSegments.findIndex(
      (s) => s.order_index === currentOrderIndex,
    );
    const previous =
      i > 0 ? segmentEl(filteredSegments[i - 1].order_index) : null;

    box.scrollTo({
      top: offsetWithin(box, previous ?? el),
      behavior: "smooth",
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentOrderIndex, filteredSegments]);

  // Keyed on the spoken line alone: including scrollToCurrent would also fire
  // this when the search filter changes, dragging the pane around while
  // someone is typing a query.
  useEffect(() => {
    if (followRef.current) scrollToCurrent();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentOrderIndex]);

  // One stable handler for every row, so the memoised rows keep their props.
  const selectSegment = useCallback(
    (segment: AudioSegment) => {
      // Asked to point at a moment: the click names the line rather than
      // playing it. Playing here would be the opposite of what was asked.
      if (pickingRef.current) {
        // Plain click names the line; shift-click stretches the mark to reach
        // it. Dragging was the obvious alternative and turned out not to be:
        // each line is a button, and browsers don't reliably let a selection
        // be dragged across those.
        const line = { startMs: segment.start_ms, endMs: segment.end_ms };
        const held = pickRangeRef.current;
        const next =
          shiftHeldRef.current && held
            ? {
                startMs: Math.min(held.startMs, line.startMs),
                endMs: Math.max(held.endMs, line.endMs),
              }
            : line;
        pickRangeRef.current = next;
        setPickRange(next);
        // Applied as it goes, so the gap's chip shows the mark while the
        // author is still deciding whether to extend it.
        onPickSegmentRef.current?.(next);
        return;
      }
      // Selecting a phrase to mark an answer against is a drag that ends in a
      // click on this same line. Playing from the top of the line then would
      // fight the gesture.
      if (window.getSelection()?.toString().trim()) return;
      // Jumping to a line is also "follow from here".
      setFollow(true);
      void wsRef.current?.play(segment.start_ms / 1000);
    },
    [setFollow],
  );

  const showBackToPlaying = !following && !activeFullyVisible;

  /** Times the current transcript selection against the word timings, so a
   *  marked range is the words themselves rather than the line holding them.
   *  Null when nothing inside the transcript is selected. */
  const selectionRange = useCallback((): MarkRange | null => {
    const selection = window.getSelection();
    const picked = selection?.toString().trim().toLowerCase() ?? "";

    if (picked && listRef.current && selection && selection.rangeCount > 0) {
      // Only a selection inside the transcript counts — text selected
      // elsewhere on the page has no timing behind it.
      const range = selection.getRangeAt(0);
      if (listRef.current.contains(range.commonAncestorContainer)) {
        const strip = (w: string) => w.toLowerCase().replace(/[^a-z0-9']/g, "");
        const wanted = new Set(picked.split(/\s+/).map(strip).filter(Boolean));
        const hits = segments
          .flatMap((segment) => segment.words)
          .filter((word) => wanted.has(strip(word.word)));
        if (hits.length > 0) {
          return {
            startMs: Math.min(...hits.map((w) => w.start_ms)),
            endMs: Math.max(...hits.map((w) => w.end_ms)),
          };
        }
        // Selected text we can't time word-for-word: fall back to the line it
        // sits in rather than inventing a precision we don't have.
        const segment = segments.find((sg) =>
          sg.text.toLowerCase().includes(picked),
        );
        if (segment) return { startMs: segment.start_ms, endMs: segment.end_ms };
      }
    }

    return null;
  }, [segments]);

  const pickTarget = useCallback((): ReturnType<
    AudioEditorHandle["pickTarget"]
  > => {
    const fromSelection = selectionRange();
    if (fromSelection) return { kind: "selection", range: fromSelection };
    // A transcript to click is a better target than the playhead, so ask for
    // the click rather than guessing from wherever playback happens to be.
    if (segments.length > 0) return { kind: "needs-pick" };
    const ws = wsRef.current;
    if (!ws) return null;
    const startMs = Math.round(ws.getCurrentTime() * 1000);
    return {
      kind: "playhead",
      range: { startMs, endMs: startMs + DEFAULT_MARK_MS },
    };
  }, [segments, selectionRange]);

  useEffect(() => {
    selectionRangeRef.current = selectionRange;
  }, [selectionRange]);

  useImperativeHandle(
    ref,
    () => ({ togglePlay: togglePlayback, pickTarget }),
    [togglePlayback, pickTarget],
  );

  /** Scrolls the transcript to a moment and flashes the line there. Used by
   *  the suggestions: they say "look here", and looking is all they do —
   *  committing the mark stays a deliberate click on the line itself. */
  const revealAt = useCallback(
    (ms: number) => {
      const at = segments.findIndex(
        (seg) => ms >= seg.start_ms && ms < seg.end_ms,
      );
      const target =
        at >= 0 ? segments[at] : segments.find((seg) => seg.start_ms >= ms);
      if (!target) return;
      const box = listRef.current;
      const el = segmentEl(target.order_index);
      if (!box || !el) return;

      // Following would drag the pane back to whatever is playing.
      setFollow(false);
      const position = filteredSegments.findIndex(
        (seg) => seg.order_index === target.order_index,
      );
      const previous =
        position > 0
          ? segmentEl(filteredSegments[position - 1].order_index)
          : null;
      box.scrollTo({
        top: offsetWithin(box, previous ?? el),
        behavior: "smooth",
      });

      // Flashed on arrival, not on departure: fired at the same time as the
      // scroll, the pulse is half over before the line is even in view.
      // `scrollend` is the exact signal; the timer is there for browsers that
      // don't send it, and is cleared if it does.
      const targetIndex = segments.indexOf(target);
      let fired = false;
      const flash = () => {
        if (fired) return;
        fired = true;
        box.removeEventListener("scrollend", flash);
        flashSnap("segment", targetIndex, 900);
      };
      box.addEventListener("scrollend", flash, { once: true });
      window.setTimeout(flash, 600);
    },
    [segments, filteredSegments, flashSnap, setFollow],
  );

  const resumeFollowing = () => {
    setFollow(true);
    scrollToCurrent();
  };

  // --- No audio yet: drag-and-drop upload zone instead of the player -----
  if (!audioUrl) {
    return (
      <div>
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
          <span className="text-[11px] text-muted-foreground">
            mp3, wav, m4a
          </span>
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
    asset?.transcript_status === "pending" ||
    asset?.transcript_status === "processing";
  const failed = asset?.transcript_status === "failed";
  const partDurationMs = Math.max(
    0,
    (partAudioEnd ?? effectiveDurationMs) - (partAudioStart ?? 0),
  );
  // Null on both bounds means "not trimmed" — the part plays the whole clip.
  const hasExplicitRange = partAudioStart != null || partAudioEnd != null;

  return (
    // A column, so the player keeps its natural height and the transcript
    // takes whatever is left and scrolls inside it — the page itself no
    // longer scrolls the player out of reach. The "audio" and "transcript"
    // rules are gone: the card and the list are already distinct, and the
    // duration they carried is in the transport.
    <div className="flex h-full min-h-0 flex-col">
      <div className="relative shrink-0 rounded-lg bg-card px-4 py-3.5">
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
            canScroll
              ? "cursor-grab opacity-100"
              : "pointer-events-none opacity-0",
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
              <Loader2
                className="size-3.5 animate-spin text-primary"
                aria-hidden
              />
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
                  <Gauge
                    className="size-3.5 shrink-0 text-muted-foreground"
                    aria-hidden
                  />
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
                  <ZoomIn
                    className="size-3.5 shrink-0 text-muted-foreground"
                    aria-hidden
                  />
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
            {playing ? (
              <Pause className="size-4" />
            ) : (
              <Play className="size-4" />
            )}
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
                    The stretch you mark on the waveform is what learners hear
                    as
                    {partNumber ? ` Part ${partNumber}` : " this part"}.
                  </p>
                  <ul className="space-y-2.5 px-3.5 py-3 text-[11px] leading-relaxed text-muted-foreground">
                    <HelpRow
                      icon={<MoveHorizontal className="size-3.5" aria-hidden />}
                    >
                      Drag across the waveform to mark it — the edges snap to
                      pauses in the speech.
                    </HelpRow>
                    {/* The fields lost their "start"/"end" words to icons,
                          so the help card is now where those icons get named. */}
                    <HelpRow
                      icon={
                        <ArrowRightFromLine className="size-3.5" aria-hidden />
                      }
                    >
                      The two fields are where the part begins and ends — type a
                      time in directly if you already know it.
                    </HelpRow>
                    <HelpRow
                      icon={<ArrowRightToLine className="size-3.5" aria-hidden />}
                    >
                      The button beside each one sets that edge to wherever
                      playback has reached.
                    </HelpRow>
                    <HelpRow
                      icon={<Scissors className="size-3.5" aria-hidden />}
                    >
                      Zooms in on just the marked stretch, keeping 5s either
                      side.
                    </HelpRow>
                    <HelpRow icon={<Play className="size-3.5" aria-hidden />}>
                      Once a range is marked, play stays inside it — you always
                      hear exactly what learners will.
                    </HelpRow>
                    <HelpRow
                      icon={<RotateCcw className="size-3.5" aria-hidden />}
                    >
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
                icon={
                  <ArrowRightFromLine
                    className="size-3.5 shrink-0"
                    aria-hidden
                  />
                }
              />
              {/* No separator arrow between the fields — the |→ and →| icons
                    inside them already say which edge is which. */}
              <RangeField
                ms={partAudioEnd ?? effectiveDurationMs}
                onCommit={commitPartEnd}
                onPlayhead={() => commitPartEnd(currentMs)}
                label="Part end"
                icon={
                  <ArrowRightToLine className="size-3.5 shrink-0" aria-hidden />
                }
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
                  label={
                    focused
                      ? "Show the whole recording"
                      : "Trim view — just this part"
                  }
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
              <Loader2
                className="size-3.5 animate-spin text-primary"
                aria-hidden
              />
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

      {/* The transcript half: search pinned, list scrolling under it. One
            wrapper owns the gap below the player so it doesn't change with
            whether the search box is there. */}
      <div className="relative mt-4 flex min-h-0 flex-1 flex-col">
        {asset?.transcript_status === "ready" && (
          <div className="relative mb-2 shrink-0">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape" && search) {
                  e.stopPropagation();
                  setSearch("");
                }
              }}
              placeholder="search transcript…"
              aria-label="Search transcript"
              className="w-full rounded-md border border-border bg-transparent py-1.5 pr-8 pl-3 text-xs text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:outline-none"
            />
            {search && (
              <button
                type="button"
                onClick={() => setSearch("")}
                title="Clear search"
                aria-label="Clear search"
                className="absolute inset-y-0 right-0 flex w-8 items-center justify-center text-muted-foreground transition-colors hover:text-foreground"
              >
                <X className="size-3.5" aria-hidden />
              </button>
            )}
          </div>
        )}

        {/* Under the search box, directly above the lines it's asking to be
            clicked — over the search it read as a note about searching. */}
        {picking && (
          <div className="mb-2 shrink-0 rounded-md border border-primary/40 bg-primary/10 px-2.5 py-1.5 text-[11px] text-foreground">
            <div className="flex items-center gap-2">
              <MousePointerClick
                className="size-3.5 shrink-0 text-primary"
                aria-hidden
              />
              {pickRange ? (
                <span className="tabular-nums">
                  marked {fmt(pickRange.startMs)}–{fmt(pickRange.endMs)} ·
                  shift-click another line to extend
                </span>
              ) : (
                <span>click the line where this answer is said</span>
              )}
              <button
                type="button"
                onClick={onCancelPick}
                className={cn(
                  "ml-auto rounded px-2 py-0.5 transition-colors",
                  pickRange
                    ? "bg-primary/20 text-primary hover:bg-primary/30"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {pickRange ? "done" : "cancel"}
              </button>
            </div>

            {/* Offered, never applied on the author's behalf: a word said
                twice makes the first match the wrong one often enough that
                the choice has to stay theirs. */}
            {!pickRange && (suggestions?.length ?? 0) > 0 && (
              <div className="mt-1.5 border-t border-primary/20 pt-1.5">
                <span className="text-muted-foreground">
                  found in the transcript — jump to it, then click the line
                </span>
                <div className="mt-1 flex flex-wrap gap-1">
                  {suggestions?.map((s, i) => (
                    <button
                      key={i}
                      type="button"
                      title={s.context}
                      onClick={() => revealAt(s.wordStartMs)}
                      className="flex items-center gap-1.5 rounded border border-primary/30 bg-card px-1.5 py-0.5 transition-colors hover:border-primary"
                    >
                      <span className="tabular-nums text-primary">
                        {fmt(s.wordStartMs)}
                      </span>
                      <span className="max-w-40 truncate text-muted-foreground">
                        {s.answer}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* min-h-0 is what actually makes this scroll: a flex child's default
              min-height is its content, so without it the list would push the
              column taller instead of overflowing inside it. */}
        <div
          ref={listRef}
          onWheel={onTranscriptInput}
          onTouchStart={onTranscriptInput}
          onKeyDown={onTranscriptInput}
          // Covers dragging the scrollbar itself. It also fires when a segment
          // is clicked, but that segment's own click handler re-arms following
          // afterwards — pointerdown lands first, click has the last word.
          onPointerDown={onTranscriptInput}
          className={cn(
            // `leading-loose` set wrapped lines within one line of speech as
            // far apart as two separate ones, so a long line read as several.
            // Relaxed keeps them together while the rows' own padding still
            // separates one line of speech from the next.
            "scrollbar-quiet relative min-h-0 flex-1 overflow-y-auto pr-1 text-[15px] leading-relaxed",
            // `select-none` while picking: shift-click is how a mark is
            // stretched over several lines, and shift-click is also how a
            // browser extends a text selection — so every extension came with
            // the transcript turning blue behind it.
            picking &&
              "cursor-crosshair rounded-md ring-1 ring-primary/40 select-none",
          )}
        >
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

          {asset?.transcript_status === "ready" &&
            filteredSegments.length === 0 && (
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
                  flashed={
                    flash?.kind === "segment" && flash.index === trueIndex
                  }
                  search={search}
                  // -1 for every other row, so their props stay constant and
                  // the memo keeps them out of the playback re-render.
                  activeWordIndex={
                    trueIndex === currentSegmentIndex ? activeWordIndex : -1
                  }
                  marked={
                    !!pickRange &&
                    seg.start_ms < pickRange.endMs &&
                    seg.end_ms > pickRange.startMs
                  }
                  markedAnswers={marksBySegment.get(seg.order_index)}
                  editing={editingSegment === seg.order_index}
                  onEdit={() => setEditingSegment(seg.order_index)}
                  onEditCancel={() => setEditingSegment(null)}
                  onEditSave={(text) => {
                    setEditingSegment(null);
                    if (text.trim() && text !== seg.text) {
                      updateSegment.mutate({
                        orderIndex: seg.order_index,
                        text,
                      });
                    }
                  }}
                  onSelect={selectSegment}
                />
              );
            })}

          {/* No fabricated progress (§2 honesty constraint) — the worker
              writes all segments at once, so there's no partial figure to
              show, only that it's in flight and the clip's total length. */}
          {processing && (
            <div className="flex items-center gap-2 px-2 py-2 text-xs text-muted-foreground">
              <Loader2
                className="size-3.5 animate-spin text-primary"
                aria-hidden
              />
              transcribing… ({fmt(effectiveDurationMs)} clip)
            </div>
          )}
        </div>

        {/* Shown exactly when the spoken line isn't on screen — scrolled past
            in either direction, or jumped away from. Floats over the foot of
            the list rather than taking a row of its own, so the transcript
            keeps its full height whether or not it's showing.

            Kept mounted and faded rather than added and removed, so it eases
            out as well as in; an unmounted element has nothing left to
            animate. It's taken out of the tab order and hidden from screen
            readers while invisible. */}
        {currentOrderIndex !== undefined && (
          <button
            type="button"
            onClick={resumeFollowing}
            aria-hidden={!showBackToPlaying}
            tabIndex={showBackToPlaying ? 0 : -1}
            className={cn(
              "absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1.5 text-[11px] text-foreground shadow-lg",
              // `translate`, not `transform`: Tailwind v4's translate-* set
              // the standalone `translate` property, so a transition listing
              // only `transform` left the movement instant and just faded the
              // opacity — which read as the button snapping into place.
              "transition-[opacity,translate,border-color,color] duration-300 ease-out motion-reduce:transition-none",
              "hover:border-primary hover:text-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
              showBackToPlaying
                ? "translate-y-0 opacity-100"
                : "pointer-events-none translate-y-4 opacity-0",
            )}
          >
            {activeDirection === "up" ? (
              <ArrowUp className="size-3.5 text-primary" aria-hidden />
            ) : (
              <ArrowDown className="size-3.5 text-primary" aria-hidden />
            )}
            back to playing
          </button>
        )}
      </div>
    </div>
  );
});

/** One line of the help card: the icon in its own gutter so the sentences
 *  align down a single edge, both columns at the same weight — the emphasis
 *  belongs to the lead paragraph, not to reference rows. */
function HelpRow({
  icon,
  children,
}: {
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
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
  /** Marks which edge this is: |→ opens the range, →| closes it, read
   *  left-to-right the way the timeline does. It rides on the button rather
   *  than sitting in the field: the button is the thing that acts on that
   *  edge, and the field then holds nothing but the time. */
  icon: React.ReactNode;
}) {
  return (
    <span className="flex h-7 shrink-0 items-stretch overflow-hidden rounded-md border border-border/80 focus-within:border-primary">
      <label className="flex cursor-text items-center pl-2 text-muted-foreground">
        <TimeField ms={ms} onCommit={onCommit} label={label} bare />
      </label>
      <button
        type="button"
        onClick={onPlayhead}
        title={`${label} at playhead`}
        aria-label={`${label} at playhead`}
        className="flex w-8 shrink-0 items-center justify-center border-l border-border/80 bg-foreground/8 text-muted-foreground transition-colors hover:bg-primary/15 hover:text-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        {icon}
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

/** Memoised: the highlight moves one row at a time, but without this every
 *  row re-rendered on each playback tick. `onSelect` takes the segment rather
 *  than being closed over per row, so the prop stays referentially stable and
 *  the memo actually holds. */
const TranscriptSegment = memo(function TranscriptSegment({
  segment,
  current,
  flashed,
  search,
  activeWordIndex,
  marked,
  markedAnswers,
  editing,
  onEdit,
  onEditCancel,
  onEditSave,
  onSelect,
}: {
  segment: AudioSegment;
  current: boolean;
  flashed: boolean;
  search: string;
  /** Inside the range being picked right now. */
  marked: boolean;
  /** Answers marked over this line, picked out within its text. */
  markedAnswers?: string[];
  /** Being corrected right now. */
  editing: boolean;
  onEdit: () => void;
  onEditCancel: () => void;
  onEditSave: (text: string) => void;
  /** Index into `segment.words` of the word being said, or -1. */
  activeWordIndex: number;
  onSelect: (segment: AudioSegment) => void;
}) {
  const text = segment.text;
  const q = search.trim();
  let content: React.ReactNode = text;

  // Word-by-word only on the line being spoken, and only when nothing is
  // being searched: the two highlights mean different things and would fight
  // over the same text. Falls back to the plain line whenever the ASR gave us
  // no word timings for it.
  // The words of every answer marked over this line, so they can be picked
  // out wherever they fall in it. Matching the text is the whole trick: the
  // author marks the seconds, never the word.
  const answerWords = new Set(
    (markedAnswers ?? []).flatMap((a) =>
      a.toLowerCase().split(/\s+/).map(stripWord).filter(Boolean),
    ),
  );

  // Word-by-word is dropped on a corrected line: the timings are still the
  // ASR's and no longer match the words that are there.
  if (!q && current && !segment.edited && segment.words.length > 0) {
    content = (
      <span className="whitespace-pre-wrap">
        {segment.words.map((w, i) => (
          <span
            key={i}
            className={cn(
              "transition-colors duration-150",
              answerWords.has(stripWord(w.word)) &&
                "font-semibold text-primary underline decoration-primary/50 underline-offset-4",
              i === activeWordIndex
                ? "text-primary"
                : i < activeWordIndex
                  ? "text-foreground"
                  : "text-muted-foreground",
            )}
          >
            {/* Whisper usually hands back words with their leading space
                already attached; add one only when it didn't. */}
            {i > 0 && !/^\s/.test(w.word) ? " " : ""}
            {w.word}
          </span>
        ))}
      </span>
    );
  } else if (!q && answerWords.size > 0) {
    content = (
      <span className="whitespace-pre-wrap">
        {text.split(/(\s+)/).map((token, i) =>
          answerWords.has(stripWord(token)) ? (
            <span
              key={i}
              className="font-semibold text-primary underline decoration-primary/50 underline-offset-4"
            >
              {token}
            </span>
          ) : (
            <Fragment key={i}>{token}</Fragment>
          ),
        )}
      </span>
    );
  } else if (q) {
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

  // The ASR mishears, and an author who spots it should be able to fix it —
  // otherwise every downstream check (does the answer appear here?) inherits
  // the mistake.
  if (editing) {
    return (
      <div className="flex w-full items-start gap-2.5 rounded-md bg-foreground/6 px-2 py-1">
        <span className="mt-1.5 shrink-0 text-[11px] tabular-nums text-muted-foreground">
          {fmt(segment.start_ms)}
        </span>
        <textarea
          autoFocus
          defaultValue={text}
          rows={2}
          aria-label={`Transcript line at ${fmt(segment.start_ms)}`}
          onBlur={(e) => onEditSave(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              onEditCancel();
            } else if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              e.currentTarget.blur();
            }
          }}
          className="min-w-0 flex-1 resize-y rounded border border-primary bg-transparent px-1.5 py-0.5 text-sm text-foreground focus:outline-none"
        />
      </div>
    );
  }

  return (
    <div
      data-order={segment.order_index}
      role="button"
      tabIndex={0}
      onClick={() => onSelect(segment)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(segment);
        }
      }}
      className={cn(
        "group/line relative flex w-full cursor-pointer items-start gap-2.5 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-foreground/6",
        current && "bg-foreground/6",
        // Two different things: the faint tint says "an answer is marked
        // here", the strong one says "this is what you're picking right now".
        (markedAnswers?.length ?? 0) > 0 && "bg-primary/8",
        marked && "bg-primary/15",
        flashed && "line-flash",
      )}
    >
      <span className="mt-1 shrink-0 text-xs tabular-nums text-muted-foreground">
        {fmt(segment.start_ms)}
      </span>
      <span className={cn(current ? "text-foreground" : "text-muted-foreground")}>
        {content}
        {/* Both of these follow the last word rather than sitting in a column
            of their own. Held in the row as flex siblings they reserved their
            width whether or not they were showing, and every line ended in a
            band of empty space. */}
        {segment.edited && (
          <span
            title="You corrected this line"
            className="ml-1.5 align-baseline text-[9px] text-muted-foreground/60"
          >
            edited
          </span>
        )}
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onEdit();
          }}
          title="Correct this line"
          aria-label={`Correct the line at ${fmt(segment.start_ms)}`}
          className="ml-1 hidden translate-y-0.5 rounded p-0.5 text-muted-foreground group-hover/line:inline-flex group-focus-within/line:inline-flex hover:text-foreground"
        >
          <Pencil className="size-3" aria-hidden />
        </button>
      </span>
    </div>
  );
});

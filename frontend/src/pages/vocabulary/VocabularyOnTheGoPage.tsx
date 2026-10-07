import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, Minus, Pause, Play, Plus, SkipBack, SkipForward } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { getErrorMessage } from "@/lib/api";
import { toast } from "@/lib/toast";
import { mediaUrl } from "@/features/paper/api";
import { stopAudio } from "@/features/vocabulary/audio";
import { releaseSilence, silenceUrl } from "@/features/vocabulary/silence";
import { onTheGoKey, settingsKey, vocabularyApi } from "@/features/vocabulary/api";
import { OptionPill } from "@/features/vocabulary/components/OptionPill";
import type {
  OnTheGoItem,
  OnTheGoOrder,
  VocabularySettings,
} from "@/features/vocabulary/types";

const DEFAULT_ORDER: OnTheGoOrder = "meaning_first";
const DEFAULT_PAUSE_S = 3;
const MIN_PAUSE_S = 1;
const MAX_PAUSE_S = 10;
/** The gap after every item, before the next. Fixed: only the pause between an
 *  item's two parts is the learner's. */
const GAP_MS = 1500;

/** One stretch of sound inside an item: a speech file, or silence. */
type Segment = { kind: "word" | "definition" | "silence"; src: string };

/** An item laid out as segments, in the learner's order and with the
 *  learner's pause AS THEY WERE when the item started — a change on the
 *  controls applies from the next item, never mid-sentence. */
function plan(item: OnTheGoItem, order: OnTheGoOrder, pauseS: number): Segment[] {
  const word: Segment = { kind: "word", src: mediaUrl(item.word_url) };
  const meaning: Segment = { kind: "definition", src: mediaUrl(item.definition_url) };
  const [first, second] = order === "word_first" ? [word, meaning] : [meaning, word];
  return [
    first,
    { kind: "silence", src: silenceUrl(pauseS * 1000) },
    second,
    { kind: "silence", src: silenceUrl(GAP_MS) },
  ];
}

/**
 * `/vocabulary/on-the-go` — the words, as sound, with the screen optional.
 *
 * Each item is TWO files the server already has — the word's own audio (the
 * learner's accent, exactly what the reveal plays) and the sense's masked
 * definition — and THIS page sequences them: meaning first or word first, with
 * a pause between them, both chosen on this screen and saved to the account.
 * (A file the server composed could not be reversed or re-timed; the lock
 * screen it was baked for is for a native app to solve.) It plays the list back
 * to back and does nothing clever, and that is the design:
 *
 * - **No timers.** The pause and the gap are SILENCE played on the same
 *   `<audio>` element (`silence.ts`: a WAV of exactly N seconds, a Blob URL),
 *   so the element is "playing" through them. A `setTimeout` is throttled in a
 *   background tab and frozen on a locked Android screen; an element that is
 *   playing is not. The pause is the whole point of the mode — it is where the
 *   learner tries to remember.
 * - **One `<audio>` element, kept for the whole visit.** The next segment is
 *   loaded by setting its `src` in the SAME call stack as the `ended` event
 *   (or the headphone's "next"), never through a render. A new element per
 *   segment, or a `play()` that waits for React, is what a locked phone
 *   refuses.
 * - **The word is never shown, and never in the metadata.** The lock screen
 *   shows `On the go · 3 / 40`: a title carrying the word would put the answer
 *   on the lock screen during the very pause meant for thinking. The wire does
 *   not carry it either (`OnTheGoItem` has an id and two files).
 * - **Listening is not recalling.** An exposure is logged when the WORD part
 *   has finished playing (`ended` on that segment, whichever order) and
 *   nothing else happens: no FSRS, no schedule. Once per item per pass, so
 *   `Previous` and replays cannot count one hearing twice; skipping an item
 *   before its word ends logs nothing.
 * - **Playing is an INTENT, not `el.paused`.** `ended` fires AFTER `pause`
 *   (the spec pauses a finished element first), so at the moment a segment
 *   ends `el.paused` is already true; deciding "keep playing?" from it stops
 *   the list after the first segment. `intent` is what the learner wants: it
 *   turns on with any play, off with a pause they asked for, and
 *   `ended`/an error simply continue under it. Next/Previous keep whatever it
 *   currently is.
 * - **The list plays once and stops.** "That's all", and Start again.
 *
 * Headphones and the lock screen drive it through the Media Session API
 * (play, pause, next, previous). See the module CLAUDE.md for what still
 * needs testing on a real phone.
 */
export default function VocabularyOnTheGoPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data, isPending, isError } = useQuery({
    queryKey: onTheGoKey,
    queryFn: () => vocabularyApi.onTheGo(),
    // Never refetched under a listener: a new list landing mid-track would
    // swap the files under `index`.
    staleTime: Infinity,
    gcTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  // The order and the pause. Playing does not wait for them (the defaults are
  // the server's own); the controls appear once they are known, because the
  // PUT needs the rest of the row.
  const settingsQuery = useQuery({
    queryKey: settingsKey,
    queryFn: () => vocabularyApi.settings(),
  });
  const settings = settingsQuery.data;
  const order = settings?.on_the_go_order ?? DEFAULT_ORDER;
  const pauseS = settings?.on_the_go_pause_s ?? DEFAULT_PAUSE_S;

  const saveKey = ["vocabulary", "settings", "on-the-go"] as const;
  const save = useMutation({
    mutationKey: saveKey,
    mutationFn: (change: Pick<VocabularySettings, "on_the_go_order"> | Pick<VocabularySettings, "on_the_go_pause_s">) => {
      const current = qc.getQueryData<VocabularySettings>(settingsKey);
      if (!current) throw new Error("settings not loaded");
      return vocabularyApi.updateSettings({
        daily_minutes: current.daily_minutes,
        direction: current.direction,
        exercise_types: current.exercise_types,
        ...change,
      });
    },
    // Optimistic: the pill moves at once. The server's answer wins — but only
    // the LAST one in a burst of clicks, so a slow early response cannot put
    // an old value back over a newer click.
    onMutate: (change) => {
      qc.setQueryData<VocabularySettings>(settingsKey, (old) =>
        old ? { ...old, ...change } : old,
      );
    },
    onSuccess: (server) => {
      if (qc.isMutating({ mutationKey: saveKey }) <= 1) qc.setQueryData(settingsKey, server);
    },
    onError: (e) => {
      toast(getErrorMessage(e));
      if (qc.isMutating({ mutationKey: saveKey }) <= 1)
        void qc.invalidateQueries({ queryKey: settingsKey });
    },
  });

  const items = data?.items ?? [];
  const total = items.length;

  const audioRef = useRef<HTMLAudioElement | null>(null);
  // A stable callback ref rather than an effect's cleanup: by the time an
  // effect cleans up, React has already cleared `audioRef`, and a detached
  // `<audio>` that is still playing keeps playing. Leaving the page must
  // stop the sound.
  const setAudio = useCallback((el: HTMLAudioElement | null) => {
    if (!el) audioRef.current?.pause();
    audioRef.current = el;
  }, []);
  const [index, setIndex] = useState(0);
  const [started, setStarted] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [finished, setFinished] = useState(false);
  // Read from event handlers that fire between renders (`timeupdate`,
  // `ended`), where state is a step behind the element's `src`.
  const indexRef = useRef(0);
  const intent = useRef(false);
  const posted = useRef<Set<string>>(new Set());
  // The item being played, laid out once when it starts, and which of its
  // segments the element is on.
  const segments = useRef<Segment[]>([]);
  const segmentRef = useRef(0);
  // What the controls say right now, read when an item STARTS.
  const choice = useRef({ order, pauseS });
  choice.current = { order, pauseS };

  // The Blob URLs of the silences die with the screen.
  useEffect(() => releaseSilence, []);

  /** Put segment `k` of the current item on the element, optionally playing. */
  function playSegment(k: number, play: boolean) {
    const el = audioRef.current;
    const segment = segments.current[k];
    if (!el || !segment) return;
    segmentRef.current = k;
    el.src = segment.src;
    if (play) {
      // A refusal here would be the browser's autoplay policy; the user
      // pressed something to get here, so it is unlikely, and the button
      // simply shows Play.
      el.play().catch(() => {
        intent.current = false;
        setPlaying(false);
      });
    }
  }

  /** Point the one element at the start of item `i`, optionally playing it. */
  function load(i: number, play: boolean) {
    const el = audioRef.current;
    const item = items[i];
    if (!el || !item) return;
    // The practice clips share nothing with this element; make sure none is
    // still talking over the list.
    stopAudio();
    intent.current = play;
    indexRef.current = i;
    setIndex(i);
    setStarted(true);
    setFinished(false);
    // Laid out now, so a change on the controls waits for the next item.
    segments.current = plan(item, choice.current.order, choice.current.pauseS);
    playSegment(0, play);
  }

  function finish() {
    intent.current = false;
    audioRef.current?.pause();
    setFinished(true);
    setPlaying(false);
  }

  function startAgain() {
    posted.current = new Set();
    load(0, true);
  }

  /** `autoplay` is explicit: `ended` and an error under playback pass true;
   *  the Next button and headphone keys pass nothing and keep the intent. */
  function next(autoplay: boolean = intent.current) {
    const i = indexRef.current;
    if (i + 1 < total) load(i + 1, finished || autoplay);
    else finish();
  }

  function previous() {
    // At the first item "previous" means "from the top of this one".
    load(Math.max(0, indexRef.current - 1), finished || intent.current);
  }

  function togglePlay() {
    const el = audioRef.current;
    if (!el) return;
    if (finished) startAgain();
    else if (!started) load(index, true);
    else if (intent.current) {
      intent.current = false;
      el.pause();
    } else {
      intent.current = true;
      void el.play().catch(() => {
        intent.current = false;
        setPlaying(false);
      });
    }
  }

  // The handlers the element and the Media Session call are registered once;
  // this ref is how they always reach THIS render's functions.
  const controls = useRef({ next, previous, togglePlay });
  controls.current = { next, previous, togglePlay };

  /** A segment finished: the word's end is the exposure, then the next
   *  segment, or the next item once the gap has played. */
  function onSegmentEnded() {
    const item = items[indexRef.current];
    const k = segmentRef.current;
    if (item && segments.current[k]?.kind === "word" && !posted.current.has(item.word_id)) {
      posted.current.add(item.word_id);
      // A log, not a promise: a failed POST costs one row and is never worth
      // interrupting the listening for.
      vocabularyApi.onTheGoExposure(item.word_id).catch(() => {});
    }
    if (k + 1 < segments.current.length) playSegment(k + 1, intent.current);
    else controls.current.next(intent.current);
  }

  /** A segment that will not load: silence is simply passed over; a speech
   *  file that fails takes its whole item with it (half an item teaches
   *  nothing), and the list keeps playing if the learner was listening. */
  function onSegmentError() {
    if (!started) return;
    const k = segmentRef.current;
    if (segments.current[k]?.kind === "silence" && k + 1 < segments.current.length)
      playSegment(k + 1, intent.current);
    else controls.current.next(intent.current);
  }

  // Lock-screen and headphone controls. Metadata is the position only.
  useEffect(() => {
    if (!("mediaSession" in navigator) || total === 0) return;
    navigator.mediaSession.metadata = new MediaMetadata({
      title: `On the go · ${index + 1} / ${total}`,
      artist: "voocab",
    });
  }, [index, total]);

  useEffect(() => {
    if (!("mediaSession" in navigator)) return;
    navigator.mediaSession.playbackState = playing ? "playing" : "paused";
  }, [playing]);

  useEffect(() => {
    if (!("mediaSession" in navigator)) return;
    const ms = navigator.mediaSession;
    ms.setActionHandler("play", () => {
      if (!intent.current) controls.current.togglePlay();
    });
    ms.setActionHandler("pause", () => {
      intent.current = false;
      audioRef.current?.pause();
    });
    ms.setActionHandler("nexttrack", () => controls.current.next());
    ms.setActionHandler("previoustrack", () => controls.current.previous());
    return () => {
      for (const a of ["play", "pause", "nexttrack", "previoustrack"] as const)
        ms.setActionHandler(a, null);
      ms.metadata = null;
      ms.playbackState = "none";
    };
  }, []);

  // Esc leaves, as on the practice page; arrows step. Neither while a field
  // has focus (there is none here, but the rule travels).
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      if (e.key === "Escape") {
        e.preventDefault();
        navigate("/vocabulary");
      } else if (e.key === "ArrowRight" && total > 0) {
        e.preventDefault();
        controls.current.next();
      } else if (e.key === "ArrowLeft" && total > 0) {
        e.preventDefault();
        controls.current.previous();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [navigate, total]);

  if (isPending) return <OnTheGoSkeleton />;

  if (isError || !data) {
    return (
      <Shell>
        <p className="text-sm text-destructive">Your words couldn&apos;t be loaded.</p>
      </Shell>
    );
  }

  const controlsBar = settings ? (
    <OrderAndPause
      order={order}
      pauseS={pauseS}
      onOrder={(next) => save.mutate({ on_the_go_order: next })}
      onPause={(next) => save.mutate({ on_the_go_pause_s: next })}
    />
  ) : null;

  const preparing = data.preparing;
  const preparingLine =
    preparing > 0 ? (
      <p className="mt-6 text-xs text-muted-foreground">
        {preparing} more {preparing === 1 ? "word is" : "words are"} being prepared
      </p>
    ) : null;

  if (total === 0) {
    return (
      <Shell>
        <p className="text-sm text-muted-foreground">No words in rotation yet.</p>
        {preparingLine}
      </Shell>
    );
  }

  return (
    <Shell>
      {controlsBar}
      {/* Not controlled by React: `src` is set by `load`, in the same call
       *  as the event that asked for it. */}
      <audio
        ref={setAudio}
        preload="auto"
        onPlay={() => {
          intent.current = true;
          setPlaying(true);
        }}
        // `pause` fires just before `ended`; that one is the file finishing,
        // not the learner pausing, and `ended` carries on (or `finish`
        // stops) — so it must not flip the button to Play for a moment.
        onPause={(e) => {
          if (e.currentTarget.ended) return;
          setPlaying(false);
        }}
        onEnded={onSegmentEnded}
        // The list never stalls on a file that will not load.
        onError={onSegmentError}
      />

      {finished ? (
        <div className="py-10">
          <p className="text-xl text-foreground">That&apos;s all</p>
          <Button type="button" autoFocus onClick={startAgain} className="mt-6">
            Start again
          </Button>
        </div>
      ) : (
        <>
          <div className="flex items-center justify-center gap-6">
            <button
              type="button"
              aria-label="Previous"
              onClick={previous}
              className="flex size-12 items-center justify-center rounded-full text-muted-foreground transition-colors duration-fast hover:bg-surface-hover hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              <SkipBack className="size-5" aria-hidden />
            </button>
            <button
              type="button"
              autoFocus
              aria-label={playing ? "Pause" : "Play"}
              onClick={togglePlay}
              className="flex size-24 items-center justify-center rounded-full bg-primary text-primary-foreground transition-colors duration-fast hover:bg-primary/80 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none"
            >
              {playing ? (
                <Pause className="size-10" aria-hidden />
              ) : (
                <Play className="size-10" aria-hidden />
              )}
            </button>
            <button
              type="button"
              aria-label="Next"
              onClick={() => next()}
              className="flex size-12 items-center justify-center rounded-full text-muted-foreground transition-colors duration-fast hover:bg-surface-hover hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              <SkipForward className="size-5" aria-hidden />
            </button>
          </div>
          <p className="mt-6 text-sm tabular-nums text-muted-foreground">
            {index + 1} / {total}
          </p>
        </>
      )}
      {preparingLine}
    </Shell>
  );
}

/** Heading, back link and the centred column every state shares. */
function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto w-full max-w-xl pb-24 pt-2">
      <header className="pb-6">
        <Link
          to="/vocabulary"
          className="inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          <ChevronLeft className="size-3.5" aria-hidden />
          Vocabulary
        </Link>
        <h1 className="mt-2 text-2xl font-semibold text-foreground">On the go</h1>
      </header>
      <div className="flex min-h-[40vh] flex-col items-center justify-center text-center">
        {children}
      </div>
    </div>
  );
}

function OnTheGoSkeleton() {
  return (
    <SkeletonBlock
      label="Loading your words"
      className="mx-auto w-full max-w-xl pb-24 pt-2"
    >
      <header className="pb-6">
        <p className="text-xs">
          <Skeleton className="inline-block h-[0.8em] w-20" />
        </p>
        <h1 className="mt-2 text-2xl font-semibold">
          <Skeleton className="inline-block h-[0.8em] w-28" />
        </h1>
      </header>
      <div className="flex min-h-[40vh] flex-col items-center justify-center">
        <Skeleton className="size-24 rounded-full" />
      </div>
    </SkeletonBlock>
  );
}

/** The learner's two choices, above the player: what plays first, and how long
 *  the pause between the two parts is. Changes apply from the next item. */
function OrderAndPause({
  order,
  pauseS,
  onOrder,
  onPause,
}: {
  order: OnTheGoOrder;
  pauseS: number;
  onOrder: (order: OnTheGoOrder) => void;
  onPause: (seconds: number) => void;
}) {
  const stepper =
    "flex size-8 items-center justify-center rounded-full bg-surface-hover text-muted-foreground transition-colors duration-fast hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-50 disabled:hover:text-muted-foreground";
  return (
    <div className="mb-8 flex w-full flex-wrap items-center justify-center gap-x-6 gap-y-3">
      <div role="radiogroup" aria-label="Order" className="flex gap-1.5">
        <OptionPill on={order === "meaning_first"} onClick={() => onOrder("meaning_first")}>
          Meaning first
        </OptionPill>
        <OptionPill on={order === "word_first"} onClick={() => onOrder("word_first")}>
          Word first
        </OptionPill>
      </div>
      <div role="group" aria-label="Pause between the two parts" className="flex items-center gap-2">
        <button
          type="button"
          aria-label="Shorter pause"
          disabled={pauseS <= MIN_PAUSE_S}
          onClick={() => onPause(pauseS - 1)}
          className={stepper}
        >
          <Minus className="size-4" aria-hidden />
        </button>
        <span
          aria-live="polite"
          className="min-w-20 text-center text-xs font-medium tabular-nums text-foreground"
        >
          Pause: {pauseS} s
        </span>
        <button
          type="button"
          aria-label="Longer pause"
          disabled={pauseS >= MAX_PAUSE_S}
          onClick={() => onPause(pauseS + 1)}
          className={stepper}
        >
          <Plus className="size-4" aria-hidden />
        </button>
      </div>
    </div>
  );
}

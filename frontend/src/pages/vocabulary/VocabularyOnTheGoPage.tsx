import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { onTheGoKey, vocabularyApi } from "@/features/vocabulary/api";

/**
 * `/vocabulary/on-the-go` — the words, as sound, with the screen optional.
 *
 * Each item is ONE file the server rendered: the definition, a pause, the
 * word, a short tail. This page plays them back to back and does nothing
 * clever, and that is the design:
 *
 * - **No timers.** The three-second pause is inside every file. A
 *   `setTimeout` between clips dies the moment an iPhone locks (the page is
 *   suspended; the audio element is not), and the pause is the whole point of
 *   the mode — it is where the learner tries to remember.
 * - **One `<audio>` element, kept for the whole visit.** Items are loaded by
 *   setting its `src` in the SAME call stack as the `ended` event (or the
 *   headphone's "next"), never through a render. A new element per item, or a
 *   `play()` that waits for React, is what a locked phone refuses.
 * - **The word is never on the screen, and never in the metadata.** The lock
 *   screen shows `On the go · 3 / 40`: a title carrying the word would put
 *   the answer on the lock screen during the very pause meant for thinking.
 *   The wire does not carry it either (`OnTheGoItem` has an id, a file and
 *   two numbers).
 * - **Listening is not recalling.** An exposure is logged once the word part
 *   has played (`currentTime >= word_offset_ms`) and nothing else happens: no
 *   FSRS, no schedule. Once per item per pass, so `Previous` and replays
 *   cannot count one hearing twice.
 * - **The list plays once and stops.** "That's all", and Start again.
 *
 * Headphones and the lock screen drive it through the Media Session API
 * (play, pause, next, previous). See the module CLAUDE.md for what still
 * needs testing on a real iPhone.
 */
export default function VocabularyOnTheGoPage() {
  const navigate = useNavigate();
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
  const posted = useRef<Set<string>>(new Set());

  /** Point the one element at item `i`, optionally playing it. */
  function load(i: number, play: boolean) {
    const el = audioRef.current;
    const item = items[i];
    if (!el || !item) return;
    indexRef.current = i;
    setIndex(i);
    setStarted(true);
    setFinished(false);
    el.src = item.url;
    if (play) {
      // A refusal here would be the browser's autoplay policy; the user
      // pressed something to get here, so it is unlikely, and the button
      // simply shows Play.
      el.play().catch(() => setPlaying(false));
    }
  }

  function finish() {
    audioRef.current?.pause();
    setFinished(true);
    setPlaying(false);
  }

  function startAgain() {
    posted.current = new Set();
    load(0, true);
  }

  function next() {
    const i = indexRef.current;
    if (i + 1 < total) load(i + 1, finished || isAudible());
    else finish();
  }

  function previous() {
    // At the first item "previous" means "from the top of this one".
    load(Math.max(0, indexRef.current - 1), finished || isAudible());
  }

  function isAudible() {
    const el = audioRef.current;
    return Boolean(el && started && !el.paused);
  }

  function togglePlay() {
    const el = audioRef.current;
    if (!el) return;
    if (finished) startAgain();
    else if (!started) load(index, true);
    else if (el.paused) void el.play().catch(() => setPlaying(false));
    else el.pause();
  }

  // The handlers the element and the Media Session call are registered once;
  // this ref is how they always reach THIS render's functions.
  const controls = useRef({ next, previous, togglePlay });
  controls.current = { next, previous, togglePlay };

  function onTimeUpdate() {
    const el = audioRef.current;
    const item = items[indexRef.current];
    if (!el || !item || posted.current.has(item.word_id)) return;
    if (el.currentTime * 1000 >= item.word_offset_ms) {
      posted.current.add(item.word_id);
      // A log, not a promise: a failed POST costs one row and is never worth
      // interrupting the listening for.
      vocabularyApi.onTheGoExposure(item.word_id).catch(() => {});
    }
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
      if (audioRef.current?.paused) controls.current.togglePlay();
    });
    ms.setActionHandler("pause", () => audioRef.current?.pause());
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
      {/* Not controlled by React: `src` is set by `load`, in the same call
       *  as the event that asked for it. */}
      <audio
        ref={setAudio}
        preload="auto"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => controls.current.next()}
        // A file that will not load is skipped; the list never stalls on one.
        onError={() => started && controls.current.next()}
        onTimeUpdate={onTimeUpdate}
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
              onClick={next}
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

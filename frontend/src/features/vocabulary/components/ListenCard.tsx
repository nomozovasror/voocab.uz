import { useEffect, useRef, useState } from "react";
import { Volume2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { GapField } from "@/features/paper/components/GapField";
import { playClip, stopAudio } from "@/features/vocabulary/audio";
import type { PracticeListenPrompt } from "@/features/vocabulary/types";

/** The slowed rate. A toggle rather than a slider: one decision, one key's
 *  worth of attention, and it is the only speed anybody asked for. */
const SLOW_RATE = 0.75;

/**
 * `listen`: hear the word, type it. A play button, a field, and nothing else.
 *
 * **The spelling is never on this screen before the answer.** Not in the
 * placeholder, not in an aria-label, not in a `title`. The prompt object does
 * not even carry it; the reveal does, after the answer. That is the entire
 * exercise — everything below is in service of it.
 *
 * ## Sound
 *
 * - **It plays once by itself when the card appears and never repeats by
 *   itself.** Whoever wants it again presses; a card that repeats on a timer
 *   is one the learner cannot think under.
 * - **Replay is the button or `Tab`.** When the word came from a recording
 *   (`audio.context_url`) presses ALTERNATE word -> context -> word, and the
 *   button says which one the next press plays, so nobody has to remember
 *   the count. The automatic first play is the word and is not a press.
 * - **`0.75x` stays for the session** — the page holds it, so the next card
 *   starts slow too. Whoever needed it for one word needs it for the next.
 *
 * ## Why Tab replays, and what that costs
 *
 * `Tab` in the field is taken for replay, because the hands are on the
 * letters and reaching for a mouse (or for Shift-less arrow gymnastics) to
 * hear a word again is exactly the break in flow the brief rules out. A key
 * that is normally "leave the field" becoming "play again" is a keyboard trap
 * waiting to happen, so it is bounded:
 *
 * - **Only forward, only plain `Tab`, only inside this field.** `Shift+Tab`
 *   is untouched and walks BACKWARDS to everything else on the card, and the
 *   controls that need reaching (Can't listen now, the play button, `0.75x`)
 *   are placed BEFORE the field in the DOM, in the order they are drawn, so
 *   that walk finds all of them. Focus never leaves the field on a replay —
 *   a screen reader hears no focus change, and the caret stays where the
 *   learner was typing.
 * - **Forward Tab is captured ONLY while focus is in the answer field.**
 *   Shift+Tab and Esc always leave, and Tab is left alone during IME
 *   composition and with any modifier held.
 * - **It says so, on screen,** in the hint line the field is `aria-describedby`.
 * - **After the answer the field is disabled**, so `Tab` is an ordinary Tab
 *   again and walks the reveal.
 * - `Esc` leaves the page from anywhere (the page's own listener).
 */
export function ListenCard({
  prompt,
  value,
  onChange,
  onSubmit,
  onExit,
  onCantListen,
  onUnavailable,
  slow,
  onToggleSlow,
  disabled,
  tone,
  turnKey,
}: {
  prompt: PracticeListenPrompt;
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onExit: () => void;
  /** "Can't listen now": every remaining listen card this session becomes
   *  its typing fallback. No penalty, no confirmation. */
  onCantListen: () => void;
  /** The word's file could not be played at all. This card becomes its
   *  typing fallback — the same "no audio" rule as the server's, applied when
   *  the file is missing after the card was already served. */
  onUnavailable: () => void;
  slow: boolean;
  onToggleSlow: () => void;
  disabled: boolean;
  tone: string;
  turnKey: string;
}) {
  const { audio } = prompt;
  const [contextBroken, setContextBroken] = useState(false);
  const hasContext = Boolean(audio.context_url) && !contextBroken;
  // What the NEXT press plays. The automatic first play was the word.
  const [next, setNext] = useState<"word" | "context">("word");
  // The browser refused to play without a gesture (iOS Safari before it is
  // unlocked). Shown, never silent: the button pulses and says "Tap to play".
  const [blocked, setBlocked] = useState(false);

  // The handlers below are called from the mount effect and from key events;
  // refs keep them reading the current rate and state without re-running the
  // autoplay when the learner flips `0.75x` or answers.
  const slowRef = useRef(slow);
  slowRef.current = slow;
  const disabledRef = useRef(disabled);
  disabledRef.current = disabled;

  async function play(kind: "word" | "context") {
    const url = kind === "context" ? audio.context_url : audio.url;
    if (!url) return;
    const result = await playClip(url, { rate: slowRef.current ? SLOW_RATE : 1 });
    if (result === "blocked") setBlocked(true);
    else if (result === "started") setBlocked(false);
    if (result !== "failed") return;
    if (kind === "context") {
      // The longer clip is missing; the word alone still works.
      setContextBroken(true);
      setNext("word");
    } else if (!disabledRef.current) {
      // Never mid-answer: once the answer is in, the reveal has the word.
      onUnavailable();
    }
  }

  function replay() {
    void play(hasContext ? next : "word");
    if (hasContext) setNext((n) => (n === "word" ? "context" : "word"));
  }

  // Once, when the card appears. `turnKey` remounts this component per turn
  // (and the page keys it), so "mount" is exactly "a card appeared".
  useEffect(() => {
    void play("word");
    return () => stopAudio();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const nextLabel = blocked
    ? "Tap to play"
    : !hasContext
    ? "Play again"
    : next === "word"
      ? "Play the word"
      : "Play in context";

  return (
    <div className="text-center">
      {/* First in the DOM, because Tab inside the field is spent on replay
       *  and Shift+Tab is how a keyboard learner reaches everything else. */}
      <div className="flex justify-end">
        <button
          type="button"
          onClick={onCantListen}
          className="rounded text-xs text-muted-foreground underline-offset-2 transition-colors hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          Can&apos;t listen now
        </button>
      </div>

      <div className="mt-2 flex flex-col items-center gap-2">
        <button
          type="button"
          onClick={replay}
          aria-label={nextLabel}
          className={cn(
            "flex size-16 items-center justify-center rounded-full bg-primary text-primary-foreground transition-colors duration-fast hover:bg-primary/80 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none",
            blocked && "animate-pulse",
          )}
        >
          <Volume2 className="size-7" aria-hidden />
        </button>
        <p className="text-xs text-muted-foreground" aria-hidden>
          {nextLabel}
        </p>
        <button
          type="button"
          aria-pressed={slow}
          onClick={onToggleSlow}
          className={cn(
            "rounded-full px-2.5 py-0.5 font-mono text-xs transition-colors duration-fast focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
            slow
              ? "bg-primary/20 text-primary-ink"
              : "bg-surface-hover text-muted-foreground hover:text-foreground",
          )}
        >
          <span className="sr-only">Slow down: </span>
          {SLOW_RATE}×
        </button>
      </div>

      <div className="mt-6 flex justify-center">
        <GapField
          key={turnKey}
          autoFocus
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              onSubmit();
            } else if (e.key === "Escape") {
              e.preventDefault();
              e.stopPropagation();
              onExit();
            } else if (
              e.key === "Tab" &&
              // Never mid-composition (an IME may use Tab to pick a
              // candidate), and never with any modifier.
              !e.nativeEvent.isComposing &&
              !e.shiftKey &&
              !e.altKey &&
              !e.ctrlKey &&
              !e.metaKey &&
              !disabled
            ) {
              // Replay, and keep focus here — see the note above.
              e.preventDefault();
              replay();
            }
          }}
          disabled={disabled}
          aria-label="Type the word you hear"
          aria-describedby={`listen-hint-${turnKey}`}
          tone={tone}
          className="w-56 text-center"
        />
      </div>
      <p
        id={`listen-hint-${turnKey}`}
        className="mt-3 text-xs text-muted-foreground"
      >
        Tab to hear it again · Enter to check
      </p>
    </div>
  );
}

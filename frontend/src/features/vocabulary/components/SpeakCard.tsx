import { useEffect, useRef, useState } from "react";
import { Mic } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { toast } from "@/lib/toast";
import { getErrorMessage } from "@/lib/api";
import { vocabularyApi } from "@/features/vocabulary/api";
import { playClip, stopAudio } from "@/features/vocabulary/audio";
import { listenOnce, type Listening } from "@/features/vocabulary/speech";
import { SpeakerButton } from "@/features/vocabulary/components/SpeakerButton";
import type {
  Accent,
  AudioOut,
  PracticeSpeakPrompt,
} from "@/features/vocabulary/types";

type Phase =
  /** Waiting for the learner to press the microphone. */
  | "idle"
  /** The microphone is open — one recognition, never more. */
  | "listening"
  /** Alternatives are with the server. */
  | "checking"
  /** The recogniser did not catch the word. Not an answer, not a wrong one. */
  | "retry"
  /** Three misses: the word is shown. Nothing is recorded. */
  | "missed";

/** True where a key press is the control's own business — a field, a button,
 *  a link. Space on a focused button already activates it. */
function isInteractive(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    ["INPUT", "TEXTAREA", "SELECT", "BUTTON", "A"].includes(target.tagName) ||
    target.isContentEditable
  );
}

/**
 * `speak`: the definition is read out, the learner says the word.
 *
 * ## Two outcomes that are NOT the same, and must not look alike
 *
 * - **"I didn't catch that"** is the recogniser failing, and recognisers fail
 *   often (accents, a noisy room, a clipped word). It is the system's miss,
 *   never the learner's: grey, neutral, with a way to try again, never red
 *   and never the word "wrong". Up to three tries. If all three miss, the
 *   word and its sound are shown and NOTHING is written — no FSRS, no review
 *   log, not requeued — because an `Again` here would be a wrong rejection
 *   wearing a disguise.
 * - **"I don't know"** is the learner's own choice to open the answer. It IS
 *   an answer: `Again`, posted with `gave_up`, and the normal reveal follows.
 *
 * One button for the second, always visible, honestly labelled. There is no
 * "Next" or "Skip" on the card itself: a consequence-free way past would
 * become the way to avoid the exercise, and would break the schedule.
 *
 * ## The microphone opens only on the learner's press
 *
 * The button, or `Space` when focus is not on a control (on a control, Space
 * already does that control's job — on the microphone button that is the
 * same thing). One recognition per press, never continuous, never restarted
 * by code. While it is open the button says so in words, not only by colour.
 *
 * ## Silence is not an attempt
 *
 * A recogniser that heard nothing (`no-speech`) gives us no alternatives to
 * send, and the contract takes 1 to 5. So it is handled here, shown as the
 * same "I didn't catch that", and does NOT use up one of the three — the
 * learner did not get a turn judged. They always have "I don't know".
 *
 * ## If it cannot work
 *
 * No API, a refused microphone, a recogniser that cannot reach its service:
 * `onUnsupported` and the page turns this and every later speak card of the
 * session into its typing fallback. It does not ask again each card.
 */
export function SpeakCard({
  prompt,
  wordId,
  disabled,
  onCaught,
  onGiveUp,
  onUnsupported,
  onMissContinue,
  accent = "british",
}: {
  prompt: PracticeSpeakPrompt;
  wordId: string;
  /** An answer is in flight, or its reveal is showing. */
  disabled: boolean;
  /** The server matched; `matched` is what `given` carries. */
  onCaught: (matched: string) => void;
  onGiveUp: () => void;
  onUnsupported: () => void;
  /** After three misses: move on without recording anything. */
  onMissContinue: () => void;
  /** The learner's accent setting: the recogniser listens for it. */
  accent?: Accent;
}) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [miss, setMiss] = useState<{ answer: string | null; audio: AudioOut | null } | null>(null);

  const attempt = useRef<1 | 2 | 3>(1);
  const listening = useRef<Listening | null>(null);
  const alive = useRef(true);
  // Autoplay refused by the browser: the speaker says "Tap to play".
  const [tapDefinition, setTapDefinition] = useState(false);
  const [tapMiss, setTapMiss] = useState(false);

  useEffect(() => {
    alive.current = true;
    // The definition, once. Whoever missed it presses the speaker beside it.
    if (prompt.definition_audio_url)
      void playClip(prompt.definition_audio_url).then((r) => {
        if (alive.current && r === "blocked") setTapDefinition(true);
      });
    return () => {
      alive.current = false;
      listening.current?.abort();
      stopAudio();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function start() {
    if (disabled || phase === "listening" || phase === "checking" || phase === "missed")
      return;
    // The definition must not be in the room while the microphone is open.
    stopAudio();
    const l = listenOnce(accent);
    listening.current = l;
    setPhase("listening");
    const outcome = await l.result;
    if (listening.current !== l || !alive.current) return;
    listening.current = null;

    if (outcome.kind === "aborted") {
      setPhase("idle");
      return;
    }
    if (outcome.kind === "unsupported") {
      onUnsupported();
      return;
    }
    if (outcome.kind === "silence") {
      setPhase("retry");
      return;
    }

    setPhase("checking");
    const n = attempt.current;
    try {
      const res = await vocabularyApi.speakCheck({
        word_id: wordId,
        alternatives: outcome.alternatives.map((a) => a.slice(0, 200)),
        attempt: n,
      });
      if (!alive.current) return;
      if (res.caught) {
        onCaught(res.matched ?? outcome.alternatives[0]);
      } else if (n < 3) {
        attempt.current = (n + 1) as 2 | 3;
        setPhase("retry");
      } else {
        setMiss({ answer: res.answer, audio: res.audio });
        setPhase("missed");
        // Always, not only when the Pronunciation setting is on: showing the
        // word's sound is the point of this reveal (brief, section 5).
        if (res.audio)
          void playClip(res.audio.url).then((r) => {
            if (alive.current && r === "blocked") setTapMiss(true);
          });
      }
    } catch (e) {
      if (!alive.current) return;
      // The check itself failed (network, server). That says nothing about
      // the learner's pronunciation, so it is neither a miss nor an attempt.
      toast(getErrorMessage(e));
      setPhase("idle");
    }
  }

  function toggleMic() {
    if (phase === "listening") listening.current?.stop();
    else void start();
  }

  function giveUp() {
    if (disabled || phase === "checking" || phase === "missed") return;
    listening.current?.abort();
    listening.current = null;
    onGiveUp();
  }

  // Space opens (or closes) the microphone while focus is not on a control;
  // Enter continues from the three-miss reveal under the same condition.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.repeat || isInteractive(e.target)) return;
      if (e.key === " " && !disabled && phase !== "missed") {
        e.preventDefault();
        toggleMic();
      } else if (e.key === "Enter" && phase === "missed") {
        e.preventDefault();
        onMissContinue();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
    // `toggleMic`/`start` close over this render's phase.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, disabled]);

  const open = phase === "listening";
  const status =
    phase === "listening"
      ? "Listening… say the word"
      : phase === "checking"
        ? "Checking…"
        : null;

  return (
    <div className="text-center">
      <p className="text-xl leading-relaxed text-foreground">
        {prompt.definition}
        {prompt.definition_audio_url && (
          <SpeakerButton
            url={prompt.definition_audio_url}
            label="Hear the definition again"
            needsTap={tapDefinition}
            onPlay={() => setTapDefinition(false)}
            className="ml-1 align-middle"
          />
        )}
      </p>

      {phase === "missed" ? (
        <div className="mt-8 rounded-xl border border-border bg-card px-5 py-4">
          <p className="text-xs text-muted-foreground">The word was</p>
          {miss?.answer && (
            <p className="mt-1 text-2xl font-semibold text-foreground">
              {miss.answer}
              {miss.audio && (
                <SpeakerButton
                  url={miss.audio.url}
                  needsTap={tapMiss}
                  onPlay={() => setTapMiss(false)}
                  className="ml-1.5 align-middle"
                />
              )}
            </p>
          )}
          <Button type="button" autoFocus onClick={onMissContinue} className="mt-4">
            Next
          </Button>
          <p className="mt-3 text-xs text-muted-foreground">
            It comes back next session · Esc to stop
          </p>
        </div>
      ) : (
        <>
          <div role="status" className="mt-8 flex min-h-28 flex-col items-center justify-start gap-3">
            {phase === "retry" ? (
              // Grey and plain, on purpose: this is the recogniser's miss.
              <div className="rounded-xl border border-border bg-surface-sunken px-5 py-3">
                <p className="text-sm text-muted-foreground">I didn&apos;t catch that</p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  autoFocus
                  disabled={disabled}
                  onClick={() => void start()}
                  className="mt-2 gap-1.5"
                >
                  <Mic aria-hidden />
                  Try again
                </Button>
              </div>
            ) : (
              <>
                <button
                  type="button"
                  autoFocus
                  disabled={disabled || phase === "checking"}
                  aria-pressed={open}
                  aria-label={open ? "Stop listening" : "Say the word"}
                  onClick={toggleMic}
                  className={cn(
                    "relative flex size-16 items-center justify-center rounded-full transition-colors duration-fast focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none disabled:opacity-50",
                    open
                      ? "bg-primary text-primary-foreground"
                      : "bg-primary/15 text-primary-ink hover:bg-primary/25",
                  )}
                >
                  {open && (
                    // The microphone is open: a ring that breathes (and the
                    // words below say it too — colour and motion alone are
                    // not a state anybody can rely on).
                    <span
                      aria-hidden
                      className="absolute -inset-1.5 animate-pulse rounded-full border-2 border-primary"
                    />
                  )}
                  <Mic className="size-7" aria-hidden />
                </button>
                <p className="text-xs text-muted-foreground">
                  {status ?? "Press the button or Space, then say the word"}
                </p>
              </>
            )}
          </div>

          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={disabled || phase === "checking"}
            onClick={giveUp}
            className="mt-6 text-muted-foreground"
          >
            I don&apos;t know
          </Button>
        </>
      )}
    </div>
  );
}

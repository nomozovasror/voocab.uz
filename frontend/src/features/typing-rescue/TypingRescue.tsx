import { useCallback, useEffect, useRef, useState } from "react";
import { Heart, Volume2, VolumeX } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { sound } from "@/features/typing-rescue/sound";
import { translate } from "@/features/typing-rescue/translations";
import { useCanvasFx, type Point } from "@/features/typing-rescue/useCanvasFx";
import {
  useTypingRescueGame,
  type FallingWord,
  type GameEvent,
} from "@/features/typing-rescue/useTypingRescueGame";

const TOTAL_LIVES = 3;

interface Popup {
  id: number;
  uz: string;
  xPct: number;
  yPx: number;
}

/** A falling word: typed prefix in accent, the rest in foreground. */
function Word({ word, isTarget }: { word: FallingWord; isTarget: boolean }) {
  return (
    <span
      className={cn(
        "absolute -translate-x-1/2 font-mono text-lg font-medium whitespace-nowrap select-none",
        isTarget && "rounded-md bg-primary/10 px-1 ring-1 ring-primary/40",
      )}
      style={{ left: `${word.x}%`, top: `${word.y}px` }}
    >
      <span className="text-primary">{word.text.slice(0, word.typed)}</span>
      <span className="text-foreground">{word.text.slice(word.typed)}</span>
    </span>
  );
}

/**
 * Typing Rescue: keyboard-first falling-words game shown inside the connection
 * gate. Self-contained and reusable. Layers are kept separate:
 *  - game state machine (idle → preview → playing → gameover),
 *  - canvas effects (arrows + particles + shockwaves),
 *  - generative sound (Tone.js, lazy-loaded).
 * The component only wires emitted events to sound + canvas + translation popups.
 */
export function TypingRescue() {
  const fieldRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const handlerRef = useRef<(e: GameEvent) => void>(() => {});
  const popupId = useRef(0);
  const [muted, setMuted] = useState(sound.isMuted);
  const [popups, setPopups] = useState<Popup[]>([]);

  const fx = useCanvasFx(canvasRef, fieldRef);
  const game = useTypingRescueGame((e) => handlerRef.current(e), fieldRef);
  const { snapshot, start, restart, startPreview, getWordPos } = game;
  const { status, words, score, lives, waveBanner, targetId } = snapshot;

  const playingLike = status === "playing" || status === "preview";
  const showStart = status === "idle" || status === "preview";

  // Word center in canvas pixels, for arrows/explosions to aim at.
  const wordCanvasPos = useCallback(
    (wordId: number): Point | null => {
      const p = getWordPos(wordId);
      const c = canvasRef.current;
      if (!p || !c) return null;
      return { x: (p.xPct / 100) * c.clientWidth, y: p.yPx + 14 };
    },
    [getWordPos],
  );

  // Run the self-playing preview behind the start screen — silently.
  useEffect(() => {
    sound.setSuppressed(true);
    startPreview();
  }, [startPreview]);

  // Wire game events → sound + canvas + translation popups (fresh each render;
  // the game reads it through a ref, so this always sees the latest closures).
  handlerRef.current = (e: GameEvent) => {
    const f = fx.current;
    switch (e.type) {
      case "shot":
        sound.shot();
        f?.fire(() => wordCanvasPos(e.wordId));
        break;
      case "destroy": {
        sound.explosion();
        const pos = wordCanvasPos(e.wordId);
        if (f && pos) f.burst(pos, "destroy");
        const fieldPos = getWordPos(e.wordId);
        const uz = translate(e.word);
        if (fieldPos && uz) {
          const id = popupId.current++;
          setPopups((prev) => [
            ...prev,
            { id, uz, xPct: fieldPos.xPct, yPx: fieldPos.yPx },
          ]);
          setTimeout(
            () => setPopups((prev) => prev.filter((p) => p.id !== id)),
            1500,
          );
        }
        break;
      }
      case "wrong":
        sound.wrong();
        break;
      case "lifeLost":
        sound.lifeLost();
        f?.flashRed();
        f?.shake();
        break;
      case "gameover":
        sound.gameOver();
        break;
      case "wave":
        sound.waveStart();
        break;
    }
  };

  const handleStart = () => {
    void sound.init(); // first user gesture unlocks audio
    sound.setSuppressed(false);
    setPopups([]);
    start();
  };

  const handleRestart = () => {
    sound.setSuppressed(false);
    setPopups([]);
    restart();
  };

  const toggleMute = () => {
    void sound.init();
    const next = !muted;
    sound.setMuted(next);
    setMuted(next);
  };

  return (
    <div className="flex w-full max-w-2xl flex-col gap-3">
      {/* HUD */}
      <div className="flex h-6 items-center justify-between px-1">
        <div className="font-mono text-sm text-muted-foreground">
          {(status === "playing" || status === "gameover") && (
            <>
              Score <span className="text-foreground">{score}</span>
            </>
          )}
        </div>
        <div className="flex items-center gap-3">
          {(status === "playing" || status === "gameover") && (
            <div
              className="flex items-center gap-1"
              aria-label={`${lives} lives left`}
            >
              {Array.from({ length: TOTAL_LIVES }, (_, i) => (
                <Heart
                  key={i}
                  className={cn(
                    "size-4",
                    i < lives
                      ? "fill-destructive text-destructive"
                      : "text-muted-foreground/40",
                  )}
                  aria-hidden
                />
              ))}
            </div>
          )}
          <button
            onClick={toggleMute}
            className="rounded-md p-1 text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            aria-label={muted ? "Unmute" : "Mute"}
          >
            {muted ? <VolumeX className="size-4" /> : <Volume2 className="size-4" />}
          </button>
        </div>
      </div>

      {/* Play field */}
      <div
        ref={fieldRef}
        className="relative h-[min(58vh,540px)] min-h-80 overflow-hidden rounded-xl border border-border bg-background/40"
      >
        <canvas
          ref={canvasRef}
          className="pointer-events-none absolute inset-0 h-full w-full"
        />

        {playingLike &&
          words.map((w) => (
            <Word key={w.id} word={w} isTarget={w.id === targetId} />
          ))}

        {/* Translation popups (rise + fade). */}
        {popups.map((p) => (
          <div
            key={p.id}
            className="pointer-events-none absolute text-center"
            style={{
              left: `${p.xPct}%`,
              top: `${p.yPx}px`,
              animation: "tr-rise 1.5s ease-out forwards",
            }}
          >
            <div className="font-semibold whitespace-nowrap text-primary">
              {p.uz}
            </div>
          </div>
        ))}

        {/* Wave banner (animated; keyed to replay each wave). */}
        {waveBanner !== null && status === "playing" && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <span
              key={waveBanner}
              className="font-mono text-4xl font-bold tracking-widest text-primary"
              style={{ animation: "tr-wave 1600ms ease-out" }}
            >
              WAVE {waveBanner}
            </span>
          </div>
        )}

        {/* Start screen — the preview keeps playing behind this scrim. */}
        {showStart && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-5 bg-background/50 px-6 text-center backdrop-blur-[0.5px]">
            <div className="space-y-2" style={{ animation: "tr-fade-in 0.4s ease-out" }}>
              <p className="text-2xl font-semibold text-foreground">
                Typing&nbsp;Rescue
              </p>
              <p className="max-w-sm text-sm text-muted-foreground">
                Type the falling words before they hit the bottom. Every
                keystroke fires a shot; clear a word to score and learn its
                meaning. You have 3 lives.
              </p>
            </div>
            <Button size="lg" onClick={handleStart}>
              Start
            </Button>
          </div>
        )}

        {/* Game over screen */}
        {status === "gameover" && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-background/85 backdrop-blur-sm">
            <div
              className="space-y-1 text-center"
              style={{ animation: "tr-pop 0.4s ease-out" }}
            >
              <p className="text-2xl font-semibold text-foreground">Game over</p>
              <p className="text-sm text-muted-foreground">
                Score: <span className="text-primary">{score}</span>
              </p>
            </div>
            <Button onClick={handleRestart}>Play again</Button>
          </div>
        )}
      </div>

      <p className="text-center font-mono text-xs text-muted-foreground">
        {status === "playing"
          ? "Type the letters — words lock on automatically"
          : "Keyboard-first · IELTS vocabulary"}
      </p>
    </div>
  );
}

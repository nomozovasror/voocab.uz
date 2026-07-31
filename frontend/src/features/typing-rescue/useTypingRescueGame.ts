import { useCallback, useEffect, useRef, useState } from "react";
import {
  LONG_WORDS,
  MEDIUM_WORDS,
  SHORT_WORDS,
} from "@/features/typing-rescue/words";

export interface FallingWord {
  id: number;
  text: string;
  /** Center x, percent of field width. */
  x: number;
  /** Top y, pixels from the top of the field. */
  y: number;
  /** Leading letters typed correctly so far (0 = not started). */
  typed: number;
}

/** idle → (preview attract loop) → playing → gameover. */
export type GameStatus = "idle" | "preview" | "playing" | "gameover";

export interface GameSnapshot {
  status: GameStatus;
  words: FallingWord[];
  score: number;
  lives: number;
  wave: number;
  /** Wave number to show as a banner, or null. */
  waveBanner: number | null;
  targetId: number | null;
}

/** Effects the game emits; the component maps these to sound + canvas. */
export type GameEvent =
  | { type: "shot"; wordId: number }
  | { type: "destroy"; wordId: number; word: string }
  | { type: "wrong" }
  | { type: "lifeLost" }
  | { type: "gameover" }
  | { type: "wave"; wave: number };

const START_LIVES = 3;
const MAX_WORDS = 12;
const WORDS_PER_WAVE = 8;
const BANNER_MS = 1600;
const AUTO_TYPE_S = 0.42; // preview auto-typing cadence (calm, not hectic)

function waveConfig(wave: number) {
  const tiers =
    wave <= 1
      ? [SHORT_WORDS]
      : wave === 2
        ? [SHORT_WORDS, MEDIUM_WORDS]
        : [SHORT_WORDS, MEDIUM_WORDS, LONG_WORDS];
  return {
    tiers,
    speed: 34 + (wave - 1) * 10, // px/s — wave 1 is slow
    spawnMs: Math.max(850, 2500 - (wave - 1) * 220),
  };
}

function idleSnapshot(): GameSnapshot {
  return {
    status: "idle",
    words: [],
    score: 0,
    lives: START_LIVES,
    wave: 1,
    waveBanner: null,
    targetId: null,
  };
}

/**
 * Typing Rescue game engine + state machine (idle → preview → playing →
 * gameover). All mutable state lives in refs, advanced by a requestAnimationFrame
 * loop that publishes an immutable snapshot for the DOM. `preview` runs the same
 * loop but auto-types (attract mode for the start screen background). Rules only
 * — arrows/particles live in the separate canvas layer, wired via emitted events.
 */
export function useTypingRescueGame(
  onEvent: (event: GameEvent) => void,
  fieldRef: React.RefObject<HTMLDivElement | null>,
) {
  const [snapshot, setSnapshot] = useState<GameSnapshot>(idleSnapshot);

  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const emit = useCallback((e: GameEvent) => onEventRef.current(e), []);

  const words = useRef<FallingWord[]>([]);
  const score = useRef(0);
  const lives = useRef(START_LIVES);
  const wave = useRef(1);
  const waveProgress = useRef(0);
  const targetId = useRef<number | null>(null);
  const status = useRef<GameStatus>("idle");
  const nextId = useRef(1);
  const lastFrame = useRef(0);
  const lastSpawn = useRef(0);
  const breakUntil = useRef(0); // no spawning until this time (wave break)
  const bannerUntil = useRef(0);
  const wavePending = useRef(false); // quota hit; hold the wave until field clears
  const autoAccum = useRef(0);
  const raf = useRef(0);

  const publish = useCallback(() => {
    setSnapshot({
      status: status.current,
      words: words.current.map((w) => ({ ...w })),
      score: score.current,
      lives: lives.current,
      wave: wave.current,
      waveBanner:
        performance.now() < bannerUntil.current ? wave.current : null,
      targetId: targetId.current,
    });
  }, []);

  const spawn = useCallback(() => {
    if (words.current.length >= MAX_WORDS) return;
    const { tiers } = waveConfig(wave.current);
    let text = "";
    for (let attempt = 0; attempt < 6; attempt++) {
      const tier = tiers[Math.floor(Math.random() * tiers.length)];
      text = tier[Math.floor(Math.random() * tier.length)];
      if (!words.current.some((w) => w.text === text)) break;
    }
    words.current.push({
      id: nextId.current++,
      text,
      x: 6 + Math.random() * 74,
      y: 0,
      typed: 0,
    });
  }, []);

  const advanceWave = useCallback(
    (now: number) => {
      wave.current += 1;
      waveProgress.current = 0;
      // Only the real game gets a wave break + banner + sound.
      if (status.current === "playing") {
        breakUntil.current = now + BANNER_MS;
        bannerUntil.current = now + BANNER_MS;
        emit({ type: "wave", wave: wave.current });
      }
    },
    [emit],
  );

  // Core letter application — shared by real keystrokes and preview auto-typing.
  const applyKey = useCallback(
    (char: string) => {
      const s = status.current;
      if (s !== "playing" && s !== "preview") return;

      const target = words.current.find((w) => w.id === targetId.current);
      if (target) {
        if (target.text[target.typed] === char) {
          target.typed += 1;
          emit({ type: "shot", wordId: target.id });
          if (target.typed >= target.text.length) {
            const done = target;
            emit({ type: "destroy", wordId: done.id, word: done.text });
            words.current = words.current.filter((w) => w.id !== done.id);
            score.current += 1;
            targetId.current = null;
            waveProgress.current += 1;
            // Hit the quota? Don't switch waves yet — stop spawning and let the
            // player clear whatever is still falling first (see frame()).
            if (waveProgress.current >= WORDS_PER_WAVE) {
              wavePending.current = true;
            }
          }
        } else {
          emit({ type: "wrong" });
        }
      } else {
        let chosen: FallingWord | null = null;
        for (const w of words.current) {
          if (w.text[0] === char && (chosen === null || w.y > chosen.y)) {
            chosen = w;
          }
        }
        if (chosen) {
          const picked = chosen;
          picked.typed = 1;
          targetId.current = picked.id;
          emit({ type: "shot", wordId: picked.id });
        }
      }
      publish();
    },
    [emit, publish],
  );

  const frame = useCallback(
    (now: number) => {
      const dt = Math.min((now - lastFrame.current) / 1000, 0.05);
      lastFrame.current = now;

      const playing = status.current === "playing";
      const height = fieldRef.current?.clientHeight ?? 600;
      const { speed, spawnMs } = waveConfig(wave.current);

      const survivors: FallingWord[] = [];
      for (const w of words.current) {
        w.y += speed * dt;
        if (w.y >= height) {
          if (targetId.current === w.id) targetId.current = null;
          if (playing) {
            lives.current -= 1;
            emit({ type: "lifeLost" });
          }
        } else {
          survivors.push(w);
        }
      }
      words.current = survivors;

      // Quota reached and the field is now clear → run the wave transition.
      if (wavePending.current && words.current.length === 0) {
        wavePending.current = false;
        advanceWave(now);
      }

      // Spawn — paused during the wave break and while a wave is pending
      // (so the field can empty out before the next wave begins).
      if (
        !wavePending.current &&
        now >= breakUntil.current &&
        now - lastSpawn.current >= spawnMs
      ) {
        spawn();
        lastSpawn.current = now;
      }

      // Preview attract mode types on its own.
      if (status.current === "preview") {
        autoAccum.current += dt;
        if (autoAccum.current >= AUTO_TYPE_S) {
          autoAccum.current = 0;
          const target = words.current.find((w) => w.id === targetId.current);
          let ch: string | null = null;
          if (target) {
            ch = target.text[target.typed] ?? null;
          } else {
            let low: FallingWord | null = null;
            for (const w of words.current) if (!low || w.y > low.y) low = w;
            ch = low ? low.text[0] : null;
          }
          if (ch) applyKey(ch);
        }
      }

      if (playing && lives.current <= 0) {
        lives.current = 0;
        status.current = "gameover";
        targetId.current = null;
        emit({ type: "gameover" });
      }

      publish();

      if (status.current === "playing" || status.current === "preview") {
        raf.current = requestAnimationFrame(frame);
      }
    },
    [advanceWave, applyKey, emit, fieldRef, publish, spawn],
  );

  const begin = useCallback(
    (mode: "playing" | "preview") => {
      words.current = [];
      score.current = 0;
      lives.current = START_LIVES;
      wave.current = 1;
      waveProgress.current = 0;
      targetId.current = null;
      status.current = mode;
      nextId.current = 1;
      autoAccum.current = 0;
      wavePending.current = false;
      const now = performance.now();
      lastFrame.current = now;
      lastSpawn.current = now;
      if (mode === "playing") {
        breakUntil.current = now + BANNER_MS; // brief "WAVE 1" intro
        bannerUntil.current = now + BANNER_MS;
        emit({ type: "wave", wave: 1 });
      } else {
        breakUntil.current = 0;
        bannerUntil.current = 0;
      }
      publish();
      cancelAnimationFrame(raf.current);
      raf.current = requestAnimationFrame(frame);
    },
    [emit, frame, publish],
  );

  const start = useCallback(() => begin("playing"), [begin]);
  const startPreview = useCallback(() => begin("preview"), [begin]);

  // Real keyboard input only drives the real game.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (status.current !== "playing") return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key.length === 1 && /[a-zA-Z]/.test(e.key)) {
        applyKey(e.key.toLowerCase());
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [applyKey]);

  useEffect(() => () => cancelAnimationFrame(raf.current), []);

  /** Current center/top position of a word (for the canvas to aim at). */
  const getWordPos = useCallback((id: number) => {
    const w = words.current.find((x) => x.id === id);
    return w ? { xPct: w.x, yPx: w.y } : null;
  }, []);

  return { snapshot, start, restart: start, startPreview, getWordPos };
}

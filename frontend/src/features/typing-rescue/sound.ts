// Type-only import: erased at build time, so it adds nothing to the bundle.
// The actual Tone.js library is loaded lazily via dynamic import in init(), so
// it only downloads when the game is played (not audio files — all synthesized).
import type * as ToneNS from "tone";

/**
 * Generative sound effects for Typing Rescue — everything is synthesized with
 * Tone.js at runtime, so no audio files are bundled (small bundle, no licensing).
 *
 * The audio context can only start from a user gesture (browser autoplay
 * policy), so `init()` must be called from a click/keypress. Volumes are kept
 * low and short so it stays pleasant, and everything routes through a master
 * bus that the mute toggle flips.
 */
const MUTE_KEY = "typing-rescue-muted";

class SoundEngine {
  private ready = false;
  private suppressed = false;
  private muted = readStoredMute();
  private tone?: typeof import("tone");
  private master?: ToneNS.Volume;
  private blip?: ToneNS.Synth;
  private noise?: ToneNS.NoiseSynth;
  private melody?: ToneNS.Synth;

  /** Start the audio context and build the synths. Safe to call repeatedly. */
  async init(): Promise<void> {
    if (this.ready) return;
    const Tone = await import("tone");
    this.tone = Tone;
    await Tone.start();

    this.master = new Tone.Volume(-12).toDestination();
    this.blip = new Tone.Synth({
      oscillator: { type: "triangle" },
      envelope: { attack: 0.001, decay: 0.05, sustain: 0, release: 0.02 },
    }).connect(this.master);
    this.blip.volume.value = -4;
    this.noise = new Tone.NoiseSynth({
      noise: { type: "white" },
      envelope: { attack: 0.001, decay: 0.16, sustain: 0 },
    }).connect(this.master);
    this.noise.volume.value = -10;
    this.melody = new Tone.Synth({
      oscillator: { type: "sine" },
      envelope: { attack: 0.004, decay: 0.14, sustain: 0, release: 0.05 },
    }).connect(this.master);
    this.melody.volume.value = -6;

    this.ready = true;
    this.applyMute();
  }

  get isMuted(): boolean {
    return this.muted;
  }

  /** Silence all effects regardless of init/mute state (used for the preview). */
  setSuppressed(suppressed: boolean): void {
    this.suppressed = suppressed;
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
    try {
      localStorage.setItem(MUTE_KEY, muted ? "1" : "0");
    } catch {
      /* ignore storage failures */
    }
    this.applyMute();
  }

  private applyMute(): void {
    if (this.master) this.master.mute = this.muted;
  }

  /** Correct keystroke — a short, high tick. */
  shot(): void {
    if (this.suppressed) return;
    this.blip?.triggerAttackRelease("C6", 0.03);
  }

  /** Word cleared — a noise burst plus a low thump. */
  explosion(): void {
    if (this.suppressed || !this.tone) return;
    const now = this.tone.now();
    this.noise?.triggerAttackRelease("8n", now);
    this.melody?.triggerAttackRelease("C3", 0.09, now);
  }

  /** Wrong key while aiming — a low, soft blip. */
  wrong(): void {
    if (this.suppressed) return;
    this.melody?.triggerAttackRelease("A2", 0.08);
  }

  /** A word reached the bottom — heavier, lower. */
  lifeLost(): void {
    if (this.suppressed || !this.tone) return;
    const now = this.tone.now();
    this.noise?.triggerAttackRelease("4n", now);
    this.melody?.triggerAttackRelease("E2", 0.22, now);
  }

  /** Game over — a short descending motif. */
  gameOver(): void {
    if (this.suppressed || !this.tone) return;
    const now = this.tone.now();
    ["E4", "C4", "A3", "E3"].forEach((note, i) => {
      this.melody?.triggerAttackRelease(note, 0.16, now + i * 0.15);
    });
  }

  /** New wave — a quick rising two-note. */
  waveStart(): void {
    if (this.suppressed || !this.tone) return;
    const now = this.tone.now();
    ["C5", "G5"].forEach((note, i) => {
      this.blip?.triggerAttackRelease(note, 0.09, now + i * 0.1);
    });
  }
}

function readStoredMute(): boolean {
  try {
    return localStorage.getItem(MUTE_KEY) === "1";
  } catch {
    return false;
  }
}

/** Shared singleton — the game and the mute button talk to the same engine. */
export const sound = new SoundEngine();

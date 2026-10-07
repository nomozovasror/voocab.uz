/**
 * Silence as a FILE, for On the go.
 *
 * The pause between an item's two parts, and the gap between items, are not
 * timers: a `setTimeout` is throttled in a background tab and frozen on a
 * locked Android screen, and the pause is the whole point of the mode. They
 * are a WAV of exactly N seconds played on the SAME `<audio>` element as the
 * speech, so the element is "playing" through the pause and the platform keeps
 * it (and its lock-screen controls) alive.
 *
 * 8 kHz, mono, 8-bit: silence needs no more, and ten seconds is 80 kB. Built
 * client-side once per length and kept as a Blob URL (there are at most ten
 * pause lengths and one gap length, so the cache never grows).
 */

const SAMPLE_RATE = 8000;
const urls = new Map<number, string>();

/** The bytes of a WAV holding `ms` of silence (8-bit PCM: 0x80 is zero). */
export function silenceWav(ms: number): Uint8Array<ArrayBuffer> {
  const samples = Math.round((SAMPLE_RATE * ms) / 1000);
  const bytes = new Uint8Array(44 + samples);
  const v = new DataView(bytes.buffer);
  const text = (at: number, s: string) =>
    [...s].forEach((c, i) => v.setUint8(at + i, c.charCodeAt(0)));
  text(0, "RIFF");
  v.setUint32(4, 36 + samples, true);
  text(8, "WAVEfmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); // PCM
  v.setUint16(22, 1, true); // mono
  v.setUint32(24, SAMPLE_RATE, true);
  v.setUint32(28, SAMPLE_RATE, true); // byte rate: 1 byte per sample
  v.setUint16(32, 1, true); // block align
  v.setUint16(34, 8, true); // bits per sample
  text(36, "data");
  v.setUint32(40, samples, true);
  bytes.fill(0x80, 44);
  return bytes;
}

/** A Blob URL for `ms` of silence, made on first use. */
export function silenceUrl(ms: number): string {
  let url = urls.get(ms);
  if (!url) {
    url = URL.createObjectURL(new Blob([silenceWav(ms)], { type: "audio/wav" }));
    urls.set(ms, url);
  }
  return url;
}

/** Release every Blob URL (the screen is closing). */
export function releaseSilence(): void {
  for (const url of urls.values()) URL.revokeObjectURL(url);
  urls.clear();
}

import { memo, useCallback, useRef } from "react";
import { cn } from "@/lib/utils";
import { fmtClock } from "@/lib/time";

/**
 * The recording, drawn.
 *
 * A progress bar answers "how far through am I". A waveform answers two more
 * questions a candidate working through a listening paper actually has: where
 * the pauses are, and how much is left to come.
 *
 * **Coloured to the playhead, not by what was heard.** It was the other way
 * round for a while, on the argument that a bar filled to the playhead claims
 * a candidate who dragged to the end had listened to the whole recording —
 * which is true, and beside the point. Nudge forward three seconds and the
 * bars you passed stayed grey; click back and the ones ahead stayed lit. Both
 * are correct under "heard" and both read as the picture being broken. A
 * coloured bar in a player means position, and a picture that argues with
 * what everyone already knows it means is a picture nobody trusts. The spans
 * are still collected — they go to the server after grading, where they can
 * be read carefully rather than glanced at.
 *
 * **The count and the thickness are one decision, and it is a narrow
 * window.** Two hundred hair-thin bars of speech is a hedge — the eye reads a
 * wall, not a shape. Sixty fat ones is a bar chart: at five or six pixels
 * apiece, with gaps as wide again, it stops looking like a recording. What
 * reads as a waveform is a slim bar with a tighter gap, which puts the count
 * near a hundred and the bar near half its slot. The contrast is exaggerated
 * to match (see the curve in use-waveform.ts) and silence is drawn as a short
 * stub rather than nothing, so a pause reads as a pause and not as a
 * rendering fault.
 *
 * **Drawn as elements, at proportional widths.** It was an SVG for a while,
 * on the theory that two `<path>` nodes beat a hundred and twelve boxes while
 * the player animates its own size. That was solving the wrong problem — the
 * expensive reflow was the DOCUMENT's, and it is fixed by the card being out
 * of the flow (see TakeAudio) — and it cost the one thing the bars needed:
 * round ends. An SVG scaled with `preserveAspectRatio="none"` scales x and y
 * by different factors, so a corner radius comes out as an ellipse and the
 * rounding disappears. A `<span>` with `rounded-full` is round at every size,
 * for nothing.
 *
 * Widths are percentages of the row rather than pixels, so the count never
 * changes as the player shrinks — a different silhouette appearing halfway
 * through the movement is the one thing this must not do. `justify-between`
 * spreads what is left over into the gaps, which is what keeps the bar and
 * the gap in proportion at every width.
 */

/** One part of the recording, as the strip shows it: where it starts, and
 *  what it is called. Where it ENDS is the next one's start — held that way
 *  so nothing has to be recomputed when the duration finally arrives from the
 *  file's own metadata. */
export interface WavePart {
  id: string;
  label: string;
  startMs: number;
}

interface WaveformProps {
  /** Null while the file is still being decoded, or if it never was. A flat
   *  resting line is drawn instead, at the same size, so nothing on the page
   *  moves when the real shape arrives. */
  peaks: number[] | null;
  atMs: number;
  lengthMs: number;
  /** Drawn as hairlines across the bars, so the recording stops being an
   *  undifferentiated six minutes. Empty where the author never marked
   *  them. */
  parts?: WavePart[];
  onSeek?: (ms: number) => void;
  className?: string;
}

/** How much of the row the loudest bar is allowed to take. Filling it edge to
 *  edge makes the recording look like a hedge again, whatever the bars are
 *  shaped like; a fifth of the row left as air is what lets the shape read as
 *  a shape and gives the playhead somewhere to be. */
const AMP = 0.8;

/** How many readings the recording is drawn as. Exported because the hook
 *  that decodes the file has to produce exactly this many, and two numbers
 *  that must agree should not be written down twice. */
export const BARS = 112;

/** How much of each bar's slot the bar itself takes; the rest is the gap.
 *  Slightly more bar than gap, which is what stops a row of readings reading
 *  as a barcode — equal bar and gap is a picket fence, and there is no
 *  recording in a picket fence. */
const BAR = 0.55;

/** The shortest a bar is ever drawn. Silence has to look like something —
 *  drawn at its true height it disappears, and a row of gaps where the
 *  speakers pause reads as the picture having failed rather than as a pause.
 *  Small, because a stub is meant to be read as an absence: too tall and a
 *  pause looks like quiet talking. */
const STUB = 0.09;

const Bars = memo(function Bars({
  peaks,
  played,
}: {
  peaks: number[] | null;
  /** How many bars are behind the playhead. A count rather than a time: the
   *  picture only changes when a whole bar has gone by, so this re-renders a
   *  hundred and twelve nodes about once every three seconds instead of four
   *  times a second. */
  played: number;
}) {
  // A resting line while there is nothing decoded — the same count, so the
  // picture grows out of the line rather than replacing it.
  const shape = peaks ?? Array.from({ length: BARS }, () => 0);
  const count = shape.length;

  return (
    <div
      aria-hidden
      className={cn(
        "pointer-events-none absolute inset-0 flex items-center justify-between",
        !peaks && "animate-pulse",
      )}
    >
      {shape.map((peak, i) => (
        <span
          key={i}
          className={cn(
            "shrink-0 rounded-full",
            i < played ? "bg-primary" : "bg-muted-foreground/40",
          )}
          style={{
            width: `${(BAR / count) * 100}%`,
            height: `${Math.max(STUB, peak) * AMP * 100}%`,
          }}
        />
      ))}
    </div>
  );
});

export function Waveform({
  peaks,
  atMs,
  lengthMs,
  parts,
  onSeek,
  className,
}: WaveformProps) {
  const track = useRef<HTMLDivElement | null>(null);
  const pct = lengthMs > 0 ? Math.min(100, (atMs / lengthMs) * 100) : 0;
  // Rounded, so a bar turns the moment the playhead is more than half way
  // across it — which is what makes the colour line up with the cursor rather
  // than trailing a bar behind it.
  const played = Math.round((pct / 100) * (peaks?.length ?? BARS));

  const seekAt = useCallback(
    (clientX: number) => {
      const el = track.current;
      if (!el || !onSeek || lengthMs <= 0) return;
      const box = el.getBoundingClientRect();
      const at = (clientX - box.left) / Math.max(1, box.width);
      onSeek(Math.max(0, Math.min(1, at)) * lengthMs);
    },
    [lengthMs, onSeek],
  );

  const seekable = !!onSeek;

  return (
    <div
      ref={track}
      // A slider rather than a picture with a click handler: it is the
      // control that moves the playhead, and a keyboard has to be able to
      // reach it. The bars underneath are `aria-hidden` scenery.
      role={seekable ? "slider" : "presentation"}
      tabIndex={seekable ? 0 : undefined}
      aria-label={seekable ? "Position in the recording" : undefined}
      aria-valuemin={seekable ? 0 : undefined}
      aria-valuemax={seekable ? Math.round(lengthMs / 1000) : undefined}
      aria-valuenow={seekable ? Math.round(atMs / 1000) : undefined}
      aria-valuetext={
        seekable ? `${fmtClock(atMs)} of ${fmtClock(lengthMs)}` : undefined
      }
      onPointerDown={
        seekable
          ? (e) => {
              e.currentTarget.setPointerCapture(e.pointerId);
              seekAt(e.clientX);
            }
          : undefined
      }
      onPointerMove={
        seekable
          ? (e) => {
              // Only while the pointer is down — `buttons` is the one flag
              // that says so without a piece of state per drag.
              if (e.buttons === 1) seekAt(e.clientX);
            }
          : undefined
      }
      onKeyDown={
        seekable
          ? (e) => {
              const by =
                e.key === "ArrowRight" || e.key === "ArrowUp"
                  ? 5_000
                  : e.key === "ArrowLeft" || e.key === "ArrowDown"
                    ? -5_000
                    : 0;
              if (by === 0 && e.key !== "Home" && e.key !== "End") return;
              e.preventDefault();
              if (e.key === "Home") onSeek?.(0);
              else if (e.key === "End") onSeek?.(lengthMs);
              else onSeek?.(atMs + by);
            }
          : undefined
      }
      className={cn(
        "relative h-full w-full touch-none rounded-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
        seekable && "cursor-pointer",
        className,
      )}
    >
      <Bars peaks={peaks} played={played} />

      {/* Where the parts begin, drawn across the bars. Behind the playhead and
          inert: this is scenery, not a control — the labels underneath are
          what you click. The first part starts at nought, where a line would
          only be the left edge. */}
      {lengthMs > 0 &&
        (parts ?? [])
          .filter((part) => part.startMs > 0 && part.startMs < lengthMs)
          .map((part) => (
            <span
              key={part.id}
              aria-hidden
              className="pointer-events-none absolute inset-y-0 w-px bg-audio-marker"
              style={{ left: `${(part.startMs / lengthMs) * 100}%` }}
            />
          ))}

      {/* The playhead, outside the memoised bars so it can move smoothly
          without redrawing sixty-four of them. Foreground rather than the
          accent: yellow already means "played" here, and a playhead in the
          same colour would be invisible against the very bars it is the
          leading edge of. */}
      <span
        aria-hidden
        className="pointer-events-none absolute inset-y-0 w-px bg-foreground"
        style={{ left: `${pct}%` }}
      >
        <span className="absolute -top-px left-1/2 size-1.5 -translate-x-1/2 rounded-full bg-foreground" />
      </span>
    </div>
  );
}

/**
 * The parts, named under the recording.
 *
 * Each label sits over the middle of its own stretch rather than at its
 * boundary, because it names the stretch — a label at the line reads as
 * belonging to whichever side you happen to look at first. They are buttons:
 * "where does part 3 start" is a question a learner asks by going there.
 *
 * The part being played is in the accent; the parts already gone past are
 * dimmed. That is the same reading the bars give, said in words for the one
 * thing the bars cannot say — which part this is.
 */
export function PartStrip({
  parts,
  lengthMs,
  atMs,
  onJump,
  className,
}: {
  parts: WavePart[];
  lengthMs: number;
  atMs: number;
  onJump?: (part: WavePart) => void;
  className?: string;
}) {
  if (parts.length === 0 || lengthMs <= 0) {
    return <div className={className} aria-hidden />;
  }
  const at = currentPart(parts, atMs);
  return (
    <div className={cn("relative", className)}>
      {parts.map((part, i) => {
        const end = parts[i + 1]?.startMs ?? lengthMs;
        const middle = ((part.startMs + end) / 2 / lengthMs) * 100;
        return (
          <button
            key={part.id}
            type="button"
            onClick={() => onJump?.(part)}
            title={`Play from ${part.label}`}
            style={{ left: `${middle}%` }}
            className={cn(
              "absolute top-0 -translate-x-1/2 rounded-md px-1.5 text-xs whitespace-nowrap transition-colors duration-fast",
              "hover:bg-surface-hover focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
              i === at
                ? "text-primary"
                : i < at
                  ? "text-muted-foreground/60"
                  : "text-muted-foreground",
            )}
          >
            {part.label}
          </button>
        );
      })}
    </div>
  );
}

/** Which part the playhead is in. The last one it has passed the start of —
 *  which is also the right answer at nought, and the right answer for a
 *  recording with one part in it. */
export function currentPart(parts: WavePart[], atMs: number): number {
  let at = 0;
  for (let i = 0; i < parts.length; i++) {
    if (atMs >= parts[i].startMs) at = i;
  }
  return at;
}

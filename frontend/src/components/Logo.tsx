import { useId } from "react";
import { cn } from "@/lib/utils";

/**
 * The voocab mark, rendered inline so it recolors with the active theme:
 * the rounded square uses the `card` token, the letter mark uses `primary`.
 * Geometry mirrors public/voocab.svg and src/lib/favicon.ts.
 */
const LOGO_PATH =
  "M200.84 457L83.6523 133.025H193.76L305.82 457H200.84ZM319.004 447.234L270.42 304.656L322.666 133.025H431.064L319.004 447.234Z";

/**
 * The mark is two closed subpaths — the V's left and right stroke. Splitting
 * them here (rather than hardcoding two strings) keeps a single source of
 * geometry while letting the strokes be masked and lit independently.
 */
const STROKES = LOGO_PATH.split("Z")
  .filter((d) => d.trim())
  .map((d) => `${d}Z`);

export type LogoAnimation =
  /** Still — the default, for headers and other chrome. */
  | "none"
  /** Looping wipe-then-shine — for waits. */
  | "loading"
  /** Looping: the outline is drawn, then the fill sweeps in behind it. */
  | "stroke"
  /** Redraws itself on hover — for the header mark. */
  | "hover"
  /** Looping: the strokes land like two typed keys. */
  | "keystroke"
  /** One-shot reveal — for splash screens and first paint. */
  | "draw";

export function Logo({
  className,
  animate = "none",
}: {
  className?: string;
  animate?: LogoAnimation;
}) {
  // Unique per instance so several logos on one page don't share defs.
  const uid = useId().replace(/:/g, "");
  const clipId = `logo-clip-${uid}`;
  const shineId = `logo-shine-${uid}`;
  const loading = animate === "loading";
  const stroke = animate === "stroke";

  return (
    <svg
      viewBox="0 0 512 533"
      className={cn(
        loading && "logo--loading",
        stroke && "logo--stroke",
        animate === "hover" && "logo--hover",
        animate === "keystroke" && "logo--keystroke",
        animate === "draw" && "logo--draw",
        className,
      )}
      fill="none"
      aria-hidden="true"
    >
      <defs>
        {/* Keeps the gloss inside the tile's rounded corners. */}
        <clipPath id={clipId}>
          <rect y="21" width="512" height="512" rx="156" />
        </clipPath>
        <linearGradient id={shineId} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" className="logo-shine-edge" />
          <stop offset="50%" className="logo-shine-peak" />
          <stop offset="100%" className="logo-shine-edge" />
        </linearGradient>
      </defs>

      <rect y="21" width="512" height="512" rx="156" className="fill-card" />

      {/* A dim copy underneath, so the mark still reads while the wipe runs. */}
      {loading && (
        <g className="logo-ghost">
          {STROKES.map((d, i) => (
            <path key={i} d={d} className="fill-primary" />
          ))}
        </g>
      )}

      <g className="logo-strokes">
        {STROKES.map((d, i) => (
          <path key={i} d={d} className="logo-stroke fill-primary" />
        ))}
      </g>

      {/* Outline drawn on top; pathLength=1 lets dashoffset run 1→0 without
          measuring the real path length. */}
      {(stroke || animate === "draw" || animate === "hover") &&
        STROKES.map((d, i) => (
          <path key={i} d={d} pathLength={1} className="logo-outline" />
        ))}

      {loading && (
        <g clipPath={`url(#${clipId})`}>
          <g transform="skewX(-18)">
            <rect
              className="logo-shine"
              x="-620"
              y="-60"
              width="300"
              height="660"
              fill={`url(#${shineId})`}
            />
          </g>
        </g>
      )}
    </svg>
  );
}

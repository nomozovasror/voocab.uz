/**
 * The voocab mark, rendered inline so it recolors with the active theme:
 * the rounded square uses the `card` token, the letter mark uses `primary`.
 * Geometry mirrors public/voocab.svg and src/lib/favicon.ts.
 */
const LOGO_PATH =
  "M200.84 457L83.6523 133.025H193.76L305.82 457H200.84ZM319.004 447.234L270.42 304.656L322.666 133.025H431.064L319.004 447.234Z";

export function Logo({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 512 533"
      className={className}
      fill="none"
      aria-hidden="true"
    >
      <rect y="21" width="512" height="512" rx="156" className="fill-card" />
      <path d={LOGO_PATH} className="fill-primary" />
    </svg>
  );
}

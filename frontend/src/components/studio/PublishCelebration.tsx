import { useEffect, useRef, useState } from "react";
import { Check, Copy, ExternalLink, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { PublishMilestone } from "@/features/studio/milestones";

/**
 * The moment an author reaches a milestone by publishing.
 *
 * Not every publish: see features/studio/milestones. This is what gets shown
 * on the counts worth stopping for, and it takes the screen — publishing is
 * the end of hours of work, and a four-word toast in the corner gave it the
 * same weight as "part renamed". The two things an author wants next are
 * right here as well: the link, and a way to see what a learner sees.
 *
 * It stays until it is dismissed — by the close button, Escape, or a click
 * outside. Nothing times out: this is the one screen an author might want to
 * sit with, and the link to copy is on it. A panel that took itself away
 * while they were reaching for that link would be worse than no panel.
 *
 * Confetti is drawn on a canvas rather than assembled from DOM nodes: a few
 * hundred moving elements is what canvas is for, and it leaves nothing behind
 * when the overlay goes. `prefers-reduced-motion` skips the fall and keeps
 * the panel.
 */

/** How long the confetti falls for — not how long the panel lasts. */
const CONFETTI_MS = 4200;
const PIECES = 140;

interface PublishCelebrationProps {
  /** The milestone reached — what the moment is actually about. */
  milestone: PublishMilestone;
  /** The material just published, named under the headline. */
  materialTitle: string;
  /** Where a learner would take it — offered to copy and to open. */
  url: string;
  onClose: () => void;
}

export function PublishCelebration({
  milestone,
  materialTitle,
  url,
  onClose,
}: PublishCelebrationProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const width = canvas.offsetWidth;
    const height = canvas.offsetHeight;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.scale(dpr, dpr);

    // Read from the theme so the confetti belongs to the app rather than
    // arriving from a library with its own palette.
    const styles = getComputedStyle(document.documentElement);
    const colors = ["--primary", "--success", "--warning", "--foreground"]
      .map((token) => styles.getPropertyValue(token).trim())
      .filter(Boolean);

    // Two bursts from the lower corners, the way a party popper actually
    // throws: up and inward, then gravity does the rest.
    const pieces = Array.from({ length: PIECES }, (_, i) => {
      const fromLeft = i % 2 === 0;
      const angle = (fromLeft ? -60 : -120) + (Math.random() - 0.5) * 46;
      const speed = 11 + Math.random() * 13;
      const radians = (angle * Math.PI) / 180;
      return {
        x: fromLeft ? width * 0.08 : width * 0.92,
        y: height * 0.92,
        vx: Math.cos(radians) * speed,
        vy: Math.sin(radians) * speed,
        size: 5 + Math.random() * 6,
        spin: (Math.random() - 0.5) * 0.3,
        rotation: Math.random() * Math.PI,
        color: colors[i % colors.length] || "#888",
      };
    });

    let frame = 0;
    let raf = 0;
    const render = () => {
      frame += 1;
      ctx.clearRect(0, 0, width, height);
      for (const piece of pieces) {
        piece.vy += 0.32; // gravity
        piece.vx *= 0.99; // drag
        piece.x += piece.vx;
        piece.y += piece.vy;
        piece.rotation += piece.spin;

        ctx.save();
        ctx.translate(piece.x, piece.y);
        ctx.rotate(piece.rotation);
        ctx.globalAlpha = Math.max(0, 1 - frame / (CONFETTI_MS / 16));
        ctx.fillStyle = piece.color;
        // Rectangles, not circles: they catch the rotation, which is what
        // reads as paper rather than bubbles.
        ctx.fillRect(-piece.size / 2, -piece.size / 4, piece.size, piece.size / 2);
        ctx.restore();
      }
      if (frame < CONFETTI_MS / 16) raf = requestAnimationFrame(render);
    };
    raf = requestAnimationFrame(render);
    return () => cancelAnimationFrame(raf);
  }, []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      // Clipboard permission can be refused; the link is on screen either way.
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Material published"
      className="fixed inset-0 z-[60] flex items-center justify-center bg-background/70 backdrop-blur-sm"
      onClick={onClose}
    >
      <canvas
        ref={canvasRef}
        aria-hidden
        className="pointer-events-none absolute inset-0 size-full"
      />

      <div
        onClick={(e) => e.stopPropagation()}
        className="relative mx-4 w-full max-w-sm rounded-2xl border border-border bg-card p-6 text-center shadow-2xl motion-safe:animate-[celebrate_320ms_cubic-bezier(0.2,0.9,0.3,1.3)]"
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute top-3 right-3 rounded-md p-1 text-muted-foreground transition-colors hover:text-foreground"
        >
          <X className="size-4" aria-hidden />
        </button>

        {/* The count leads on a repeat milestone — it is the thing being
            marked — and a tick leads on the first, where there is no number
            worth showing yet. */}
        <div className="mx-auto mb-4 flex size-14 items-center justify-center rounded-full bg-success/15 text-success">
          {milestone.count === 1 ? (
            <Check className="size-7" aria-hidden />
          ) : (
            <span className="text-xl font-semibold tabular-nums">
              {milestone.count}
            </span>
          )}
        </div>

        <h2 className="text-lg font-medium text-foreground">
          {milestone.title}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">{milestone.message}</p>
        <p className="mt-3 truncate text-xs text-muted-foreground">
          Just published:{" "}
          <span className="text-foreground">{materialTitle}</span>
        </p>

        <div className="mt-5 flex justify-center gap-2">
          <Button type="button" variant="outline" size="sm" onClick={() => void copy()}>
            {copied ? (
              <Check className="size-3.5" aria-hidden />
            ) : (
              <Copy className="size-3.5" aria-hidden />
            )}
            {copied ? "Copied" : "Copy link"}
          </Button>
          <Button type="button" size="sm" asChild>
            <a href={url} target="_blank" rel="noreferrer">
              <ExternalLink className="size-3.5" aria-hidden />
              Open
            </a>
          </Button>
        </div>
      </div>
    </div>
  );
}

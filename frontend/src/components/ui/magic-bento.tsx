import {
  useCallback,
  useEffect,
  useRef,
  type CSSProperties,
  type ReactNode,
} from "react";
import { cn } from "@/lib/utils";

/**
 * Magic-Bento style cursor effects for a grid of cards.
 *
 * Three layers, all driven by CSS custom properties the pointer handler writes
 * onto each card — no animation library:
 *   --glow-x / --glow-y   cursor position within the card (%)
 *   --glow-intensity      0…1, full inside the card and falling off with
 *                         distance so neighbours light up faintly too
 *
 * The card styling itself lives in globals.css (`.magic-card`), so any card can
 * opt in by carrying that class.
 *
 * Deliberately dependency-free: the reference implementation drives this with
 * GSAP, but the effect is a gradient position plus an opacity ramp, which CSS
 * does natively. One rAF-throttled pointermove listener serves the whole grid
 * rather than one per card.
 */

const SPOTLIGHT_RADIUS = 320; // px — how far a card still feels the cursor
const PARTICLE_COUNT = 12; // matches the reference component's default

/** Sprinkle drifting motes inside the hovered card. Each one gets its own
 *  start point, drift vector, duration and delay so they never look banded. */
function spawnParticles(card: HTMLElement) {
  for (let i = 0; i < PARTICLE_COUNT; i++) {
    const p = document.createElement("span");
    p.className = "magic-particle";
    p.style.left = `${10 + Math.random() * 80}%`;
    p.style.top = `${10 + Math.random() * 80}%`;
    p.style.setProperty("--dx", `${(Math.random() - 0.5) * 90}px`);
    p.style.setProperty("--dy", `${(Math.random() - 0.5) * 90}px`);
    p.style.setProperty("--dur", `${2.4 + Math.random() * 1.8}s`);
    p.style.setProperty("--delay", `${(i / PARTICLE_COUNT) * 1.2}s`);
    card.appendChild(p);
  }
}

function clearParticles(card: HTMLElement) {
  for (const p of card.querySelectorAll(".magic-particle")) p.remove();
}

export function MagicBento({
  children,
  className,
  style,
  spotlight = true,
}: {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
  /** The soft ambient light that follows the cursor across the whole grid. */
  spotlight?: boolean;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const glowRef = useRef<HTMLDivElement>(null);
  const frame = useRef(0);

  const clear = useCallback(() => {
    const root = rootRef.current;
    if (!root) return;
    for (const card of root.querySelectorAll<HTMLElement>(".magic-card")) {
      card.style.setProperty("--glow-intensity", "0");
    }
    if (glowRef.current) glowRef.current.style.opacity = "0";
  }, []);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;

    // Honour the OS setting: no cursor choreography for people who opted out.
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (reduced.matches) return;

    const onMove = (e: PointerEvent) => {
      cancelAnimationFrame(frame.current);
      frame.current = requestAnimationFrame(() => {
        const cards = root.querySelectorAll<HTMLElement>(".magic-card");
        for (const card of cards) {
          const r = card.getBoundingClientRect();
          const x = e.clientX - r.left;
          const y = e.clientY - r.top;

          // Distance from the cursor to the card's nearest edge (0 when inside).
          const dx = Math.max(r.left - e.clientX, 0, e.clientX - r.right);
          const dy = Math.max(r.top - e.clientY, 0, e.clientY - r.bottom);
          const dist = Math.hypot(dx, dy);
          const intensity = Math.max(0, 1 - dist / SPOTLIGHT_RADIUS);

          card.style.setProperty("--glow-x", `${(x / r.width) * 100}%`);
          card.style.setProperty("--glow-y", `${(y / r.height) * 100}%`);
          card.style.setProperty("--glow-intensity", intensity.toFixed(3));
        }

        if (glowRef.current) {
          const rootRect = root.getBoundingClientRect();
          glowRef.current.style.transform = `translate3d(${e.clientX - rootRect.left}px, ${e.clientY - rootRect.top}px, 0)`;
          glowRef.current.style.opacity = "1";
        }
      });
    };

    // Particles are per-card and delegated, so cards can come and go with the
    // data without re-binding anything.
    const onOver = (e: PointerEvent) => {
      const card = (e.target as HTMLElement).closest<HTMLElement>(".magic-card");
      if (!card || card.dataset.particles === "on") return;
      card.dataset.particles = "on";
      spawnParticles(card);
    };
    const onOut = (e: PointerEvent) => {
      const card = (e.target as HTMLElement).closest<HTMLElement>(".magic-card");
      if (!card) return;
      // Ignore moves between children of the same card.
      const to = e.relatedTarget as Node | null;
      if (to && card.contains(to)) return;
      delete card.dataset.particles;
      clearParticles(card);
    };

    root.addEventListener("pointermove", onMove);
    root.addEventListener("pointerleave", clear);
    root.addEventListener("pointerover", onOver);
    root.addEventListener("pointerout", onOut);
    return () => {
      cancelAnimationFrame(frame.current);
      root.removeEventListener("pointermove", onMove);
      root.removeEventListener("pointerleave", clear);
      root.removeEventListener("pointerover", onOver);
      root.removeEventListener("pointerout", onOut);
      for (const card of root.querySelectorAll<HTMLElement>(".magic-card")) {
        delete card.dataset.particles;
        clearParticles(card);
      }
    };
  }, [clear]);

  // Click ripple, expanding from the pointer inside the card that was hit.
  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const card = (e.target as HTMLElement).closest<HTMLElement>(".magic-card");
    if (!card) return;
    const r = card.getBoundingClientRect();
    const ripple = document.createElement("span");
    ripple.className = "magic-ripple";
    ripple.style.left = `${e.clientX - r.left}px`;
    ripple.style.top = `${e.clientY - r.top}px`;
    ripple.addEventListener("animationend", () => ripple.remove());
    card.appendChild(ripple);
  };

  return (
    <div
      ref={rootRef}
      className={cn("relative", className)}
      style={style}
      onPointerDown={onPointerDown}
    >
      {spotlight && (
        <div
          ref={glowRef}
          aria-hidden
          className="pointer-events-none absolute top-0 left-0 -z-10 size-[520px] -translate-x-1/2 -translate-y-1/2 opacity-0 transition-opacity duration-300"
          style={{
            marginLeft: "-260px",
            marginTop: "-260px",
            background:
              "radial-gradient(circle, color-mix(in srgb, var(--primary) 9%, transparent) 0%, transparent 62%)",
          }}
        />
      )}
      {children}
    </div>
  );
}

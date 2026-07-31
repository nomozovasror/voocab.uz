import { useEffect, useRef } from "react";

export interface Point {
  x: number;
  y: number;
}

/** Imperative effects layer, driven by the game via these methods. */
export interface CanvasFx {
  /** Fire a projectile from the base toward a (homing) target position. */
  fire: (getTarget: () => Point | null) => void;
  /** Particle burst: "hit" (small, per letter) or "destroy" (big, per word). */
  burst: (at: Point, kind: "hit" | "destroy") => void;
  /** Brief red screen flash (life lost). */
  flashRed: () => void;
  /** Short screen shake of the container (life lost). */
  shake: () => void;
  /** Base position (bottom-center) in css px, where projectiles launch from. */
  base: () => Point;
}

interface Projectile {
  x: number;
  y: number;
  getTarget: () => Point | null;
  last: Point;
}

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
  max: number;
  size: number;
}

interface Ring {
  x: number;
  y: number;
  r: number;
  maxR: number;
  life: number;
  max: number;
}

const PROJECTILE_SPEED = 1400; // px/s
const HIT_RADIUS = 14;

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/**
 * Canvas rendering layer for arrows + particles, deliberately separate from the
 * game state machine (it only knows positions and effects, not rules). Runs its
 * own requestAnimationFrame loop; keeps object counts small for 60fps.
 */
export function useCanvasFx(
  canvasRef: React.RefObject<HTMLCanvasElement | null>,
  containerRef: React.RefObject<HTMLDivElement | null>,
) {
  const fx = useRef<CanvasFx | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const projectiles: Projectile[] = [];
    const particles: Particle[] = [];
    const rings: Ring[] = [];
    let redAlpha = 0;
    let shakeUntil = 0;
    let dims = { w: canvas.clientWidth, h: canvas.clientHeight };

    // Colors from Serika tokens (never hardcoded).
    let primary = cssVar("--primary");
    let destructive = cssVar("--destructive");

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      dims = { w: canvas.clientWidth, h: canvas.clientHeight };
      canvas.width = Math.max(1, Math.round(dims.w * dpr));
      canvas.height = Math.max(1, Math.round(dims.h * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      // Re-read tokens in case the theme changed.
      primary = cssVar("--primary");
      destructive = cssVar("--destructive");
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);

    const base = (): Point => ({ x: dims.w / 2, y: dims.h - 6 });

    const spawnBurst = (at: Point, kind: "hit" | "destroy") => {
      if (kind === "destroy") {
        rings.push({ x: at.x, y: at.y, r: 4, maxR: 52, life: 0.5, max: 0.5 });
      }
      const count = kind === "destroy" ? 18 : 5;
      const spMin = kind === "destroy" ? 120 : 60;
      const spMax = kind === "destroy" ? 260 : 150;
      for (let i = 0; i < count; i++) {
        const a = Math.random() * Math.PI * 2;
        const sp = spMin + Math.random() * (spMax - spMin);
        const max = 0.4 + Math.random() * (kind === "destroy" ? 0.4 : 0.2);
        particles.push({
          x: at.x,
          y: at.y,
          vx: Math.cos(a) * sp,
          vy: Math.sin(a) * sp,
          life: max,
          max,
          size: (kind === "destroy" ? 2 : 1.5) + Math.random() * 2,
        });
      }
    };

    fx.current = {
      fire: (getTarget) => {
        const b = base();
        const t = getTarget() ?? b;
        projectiles.push({ x: b.x, y: b.y, getTarget, last: t });
      },
      burst: spawnBurst,
      flashRed: () => {
        redAlpha = 0.35;
      },
      shake: () => {
        shakeUntil = performance.now() + 300;
      },
      base,
    };

    let raf = 0;
    let prev = performance.now();

    const frame = (now: number) => {
      const dt = Math.min((now - prev) / 1000, 0.05);
      prev = now;

      ctx.clearRect(0, 0, dims.w, dims.h);

      // Projectiles (homing arrows) — with a soft glow.
      ctx.strokeStyle = primary;
      ctx.fillStyle = primary;
      ctx.lineWidth = 2;
      ctx.shadowBlur = 10;
      ctx.shadowColor = primary;
      for (let i = projectiles.length - 1; i >= 0; i--) {
        const p = projectiles[i];
        const target = p.getTarget() ?? p.last;
        p.last = target;
        const dx = target.x - p.x;
        const dy = target.y - p.y;
        const dist = Math.hypot(dx, dy);
        const step = PROJECTILE_SPEED * dt;
        if (dist <= step + HIT_RADIUS) {
          spawnBurst(target, "hit");
          projectiles.splice(i, 1);
          continue;
        }
        const nx = dx / dist;
        const ny = dy / dist;
        p.x += nx * step;
        p.y += ny * step;
        // Head + short tail.
        ctx.beginPath();
        ctx.moveTo(p.x - nx * 10, p.y - ny * 10);
        ctx.lineTo(p.x, p.y);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(p.x, p.y, 2.5, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.shadowBlur = 0;

      // Shockwave rings (word destroyed).
      ctx.strokeStyle = primary;
      ctx.lineWidth = 2;
      for (let i = rings.length - 1; i >= 0; i--) {
        const r = rings[i];
        r.life -= dt;
        if (r.life <= 0) {
          rings.splice(i, 1);
          continue;
        }
        const t = 1 - r.life / r.max;
        ctx.globalAlpha = (1 - t) * 0.7;
        ctx.beginPath();
        ctx.arc(r.x, r.y, r.r + (r.maxR - r.r) * t, 0, Math.PI * 2);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;

      // Particles.
      for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i];
        p.life -= dt;
        if (p.life <= 0) {
          particles.splice(i, 1);
          continue;
        }
        p.x += p.vx * dt;
        p.y += p.vy * dt;
        p.vy += 240 * dt; // gentle gravity
        ctx.globalAlpha = Math.max(0, p.life / p.max);
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;

      // Red flash overlay (life lost).
      if (redAlpha > 0) {
        ctx.globalAlpha = redAlpha;
        ctx.fillStyle = destructive;
        ctx.fillRect(0, 0, dims.w, dims.h);
        ctx.globalAlpha = 1;
        ctx.fillStyle = primary;
        redAlpha = Math.max(0, redAlpha - dt * 1.2);
      }

      // Screen shake (applied to the DOM container, so words shake too).
      const container = containerRef.current;
      if (container) {
        if (now < shakeUntil) {
          const left = (shakeUntil - now) / 300;
          const amp = 8 * left;
          const dxs = (Math.random() * 2 - 1) * amp;
          const dys = (Math.random() * 2 - 1) * amp;
          container.style.transform = `translate(${dxs}px, ${dys}px)`;
        } else if (container.style.transform) {
          container.style.transform = "";
        }
      }

      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      fx.current = null;
    };
  }, [canvasRef, containerRef]);

  return fx;
}

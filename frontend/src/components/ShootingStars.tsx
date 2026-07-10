import { useEffect, useRef } from "react";
import { useTheme } from "@/theme/useTheme";
import { cn } from "@/lib/utils";

/**
 * Grok-inspired starfield with occasional shooting stars, on <canvas>.
 *
 * Faithful port of UsmanDevCraft/grok-shooting-stars:
 *   - Stars live in polar coords and orbit the *bottom-right corner*
 *     (center = (width, height)), radius up to the full diagonal, which gives
 *     the signature slow sweeping drift.
 *   - Flicker is a cheap brightness oscillation; stars are white.
 *   - One shooting star at a time (rare spawn) with a white gradient trail.
 *   - Backdrop is painted a near-black #161618 each frame.
 *
 * Kept beyond the original: devicePixelRatio scaling for crisp stars, a
 * transparent backdrop (stars sit on the live theme background instead of a
 * hard #161618 box), and a static render under `prefers-reduced-motion`.
 *
 * Render as a fixed, full-viewport layer behind content, e.g.
 * `<ShootingStars className="fixed inset-0 -z-10" />`.
 */

// Star count scales with the canvas area (~one star per this many px²) so large
// displays stay well-populated, clamped to keep small screens and 4K/5K sane.
const STAR_AREA_PER_STAR = 1100;
const MIN_STARS = 240;
const MAX_STARS = 1800;

// Twinkle brightness = max(0, sin + BIAS) / (1 + BIAS). A smaller bias means
// stars spend more of each cycle fully faded out (and dwell there) before
// returning; larger keeps them lit longer.
const TWINKLE_BIAS = 0.5;

// Rotation is rigid (angular), so a star's on-screen speed grows with its
// radius — and radius grows with the display. Scale angular speed down on
// larger-than-reference displays so the drift feels consistent everywhere.
const SPEED_REF_DIAGONAL = 1600;

// Screensaver behavior: hide (and pause) the field while scrolling, then fade
// it slowly back in once scrolling has been idle for a moment. The idle wait
// grows with scroll depth — near the top it returns quickly, but further down
// the page it waits longer, since the user is likely reading.
const MIN_IDLE_DELAY = 400; // at the top: return quickly
const MAX_IDLE_DELAY = 10000; // at the bottom: wait long (barely needed there)
const FADE_OUT_MS = 400; // quick hide when scrolling starts
const FADE_IN_MS = 5000; // slow, screensaver-style return

interface Star {
  angle: number;
  radius: number;
  speed: number;
  size: number;
  phase: number;
  twinkleSpeed: number;
}

interface ShootingStar {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
  initialLife: number;
}

export function ShootingStars({ className }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { theme } = useTheme();

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduced = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;

    // Dark themes get white stars; light themes get black so they stay visible.
    const starRgb = theme.appearance === "light" ? "0, 0, 0" : "255, 255, 255";

    let width = 0;
    let height = 0;
    let stars: Star[] = [];
    const shootingStars: ShootingStar[] = [];

    const initStars = () => {
      const maxRadius = Math.sqrt(width ** 2 + height ** 2);
      const speedScale = Math.min(1, SPEED_REF_DIAGONAL / maxRadius);
      const count = Math.round(
        Math.min(
          MAX_STARS,
          Math.max(MIN_STARS, (width * height) / STAR_AREA_PER_STAR),
        ),
      );
      stars = Array.from({ length: count }, () => ({
        angle: Math.random() * Math.PI * 2,
        // sqrt keeps density uniform across area; a plain random clusters stars
        // near the (bottom-right) orbit center.
        radius: Math.sqrt(Math.random()) * maxRadius,
        speed: (Math.random() * 0.0003 + 0.00015) * speedScale,
        size: Math.random() * 0.9 + 0.5,
        // Individual phase + speed so stars twinkle and blink out at their own
        // pace (slower speed → longer off-dwell).
        phase: Math.random() * Math.PI * 2,
        twinkleSpeed: Math.random() * 0.0008 + 0.0005,
      }));
    };

    const resize = () => {
      width = canvas.clientWidth;
      height = canvas.clientHeight;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      initStars();
    };

    const spawnShootingStar = () => {
      // Rare spawn so shooting stars stay occasional (~once every ~13s).
      if (shootingStars.length === 0 && Math.random() < 0.0012) {
        shootingStars.push({
          x: Math.random() * width * 0.5,
          y: Math.random() * height * 0.5,
          vx: 3 + Math.random() * 2,
          vy: 1 + Math.random() * 1.5,
          life: 80,
          initialLife: 80,
        });
      }
    };

    const draw = () => {
      // Orbit center is the bottom-right corner.
      const centerX = width;
      const centerY = height;

      // Transparent backdrop: the theme background shows through, so there's no
      // hard-edged box and the field blends with any theme.
      ctx.clearRect(0, 0, width, height);

      const now = Date.now();
      for (const star of stars) {
        if (!reduced) star.angle += star.speed;
        const x = centerX + star.radius * Math.cos(star.angle);
        const y = centerY + star.radius * Math.sin(star.angle);

        // Twinkle that fully fades to 0 and dwells there for part of each star's
        // cycle, so stars blink out for a while before fading back in.
        const wave = Math.sin(now * star.twinkleSpeed + star.phase);
        const flicker = reduced
          ? 0.7
          : Math.max(0, wave + TWINKLE_BIAS) / (1 + TWINKLE_BIAS);
        if (flicker <= 0) continue;

        ctx.beginPath();
        ctx.fillStyle = `rgba(${starRgb}, ${flicker})`;
        ctx.arc(x, y, star.size, 0, Math.PI * 2);
        ctx.fill();
      }

      if (reduced) return;

      spawnShootingStar();
      for (let i = shootingStars.length - 1; i >= 0; i--) {
        const s = shootingStars[i];
        const opacity = s.life / s.initialLife;

        const grad = ctx.createLinearGradient(
          s.x,
          s.y,
          s.x - s.vx * 35,
          s.y - s.vy * 35,
        );
        grad.addColorStop(0, `rgba(${starRgb}, ${opacity})`);
        grad.addColorStop(1, `rgba(${starRgb}, 0)`);
        ctx.strokeStyle = grad;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(s.x, s.y);
        ctx.lineTo(s.x - s.vx * 18, s.y - s.vy * 18);
        ctx.stroke();

        s.x += s.vx;
        s.y += s.vy;
        s.life -= 1;

        if (s.life <= 0) shootingStars.splice(i, 1);
      }
    };

    let raf = 0;
    const animate = () => {
      draw();
      raf = requestAnimationFrame(animate);
    };

    const start = () => {
      if (reduced) {
        draw();
      } else {
        cancelAnimationFrame(raf);
        raf = requestAnimationFrame(animate);
      }
    };

    // Pause + fade out on scroll; fade back in after a short idle.
    let idleTimer = 0;
    let hidden = false;
    const onScroll = () => {
      if (!hidden) {
        hidden = true;
        canvas.style.transition = `opacity ${FADE_OUT_MS}ms ease`;
        canvas.style.opacity = "0";
        cancelAnimationFrame(raf);
      }
      // Wait longer the further down the page we are: scaled by scroll
      // fraction so the top returns quickly and the very bottom waits fully.
      const maxScroll =
        document.documentElement.scrollHeight - window.innerHeight;
      const frac = maxScroll > 0 ? window.scrollY / maxScroll : 0;
      const delay = MIN_IDLE_DELAY + frac * (MAX_IDLE_DELAY - MIN_IDLE_DELAY);
      clearTimeout(idleTimer);
      idleTimer = window.setTimeout(() => {
        hidden = false;
        canvas.style.transition = `opacity ${FADE_IN_MS}ms ease`;
        canvas.style.opacity = "1";
        start();
      }, delay);
    };

    canvas.style.opacity = "1";
    resize();
    window.addEventListener("resize", resize);
    window.addEventListener("scroll", onScroll, { passive: true });
    start();

    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(idleTimer);
      window.removeEventListener("resize", resize);
      window.removeEventListener("scroll", onScroll);
    };
  }, [theme.appearance]);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      // <canvas> is a replaced element and won't stretch from `inset-0` alone;
      // an explicit full size makes it cover the viewport.
      className={cn("pointer-events-none block h-full w-full", className)}
    />
  );
}

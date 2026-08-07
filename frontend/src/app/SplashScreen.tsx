import { useEffect, useState, type ReactNode } from "react";
import { Logo } from "@/components/Logo";
import { cn } from "@/lib/utils";

/**
 * First-entry splash: the mark draws itself once, then the overlay fades and
 * hands over to the app.
 *
 * Shown once per browser session — a returning tab or an in-app navigation
 * gets straight through. (For every cold load instead, drop the sessionStorage
 * check; for once ever, swap it for localStorage.)
 *
 * The app renders underneath the whole time, so this covers boot work rather
 * than adding to it, and anyone who asked for reduced motion skips it.
 */
const SPLASH_KEY = "voocab:splash-seen";

// Start delay (0.25s for the trailing stroke) + 1.15s draw, per .logo--draw.
const DRAW_MS = 1400;
const HOLD_MS = 260; // beat on the finished mark before leaving
const FADE_MS = 380;

export function SplashScreen({ children }: { children: ReactNode }) {
  const [done, setDone] = useState(
    () =>
      sessionStorage.getItem(SPLASH_KEY) === "1" ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    if (done) return;
    sessionStorage.setItem(SPLASH_KEY, "1");
    const fade = setTimeout(() => setLeaving(true), DRAW_MS + HOLD_MS);
    const gone = setTimeout(() => setDone(true), DRAW_MS + HOLD_MS + FADE_MS);
    return () => {
      clearTimeout(fade);
      clearTimeout(gone);
    };
  }, [done]);

  return (
    <>
      {children}
      {!done && (
        <div
          className={cn(
            "fixed inset-0 z-100 grid place-items-center bg-background transition-opacity ease-out",
            leaving && "opacity-0",
          )}
          style={{ transitionDuration: `${FADE_MS}ms` }}
          aria-hidden
        >
          <Logo animate="draw" className="size-24" />
        </div>
      )}
    </>
  );
}

import { cn } from "@/lib/utils";

/**
 * One bar standing in for something that hasn't arrived.
 *
 * `bg-foreground/10` rather than a surface token, and that is deliberate: in
 * serika-dark `--card`, `--muted`, `--secondary` and `--accent` are all the
 * same `#2c2e31`, so a skeleton painted in any of them would be invisible on
 * a card. An alpha off the foreground reads on every surface in every theme.
 *
 * A `<span>` with `block` as its default display, not a `<div>`: a bar often
 * has to stand in for TEXT inside a real `<h1>` or `<p>`, and in a row laid
 * out with `items-baseline` a block element has no baseline to align to and
 * drags the row out of true. Sat inside the real element as
 * `inline-block h-[0.85em]`, the element's own line-height sets the height —
 * so the row is the same before and after the words arrive.
 *
 * Always `aria-hidden`. A screen reader should hear the loading state once,
 * from the region that owns it, not a dozen empty boxes.
 */
export function Skeleton({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn("block animate-pulse rounded bg-foreground/10", className)}
    />
  );
}

/**
 * The wrapper a page's skeleton sits in.
 *
 * Deliberately NOT carrying `loader-deferred`, which every other loader here
 * does. That delay exists because LogoLoader *replaces* the page: its arrival
 * is a state change and its departure is a reflow, so it has to earn its
 * entrance. A shape-matched skeleton is the opposite — it occupies the space
 * the content will occupy, so there is no reflow for a delay to hide. Worse,
 * 250ms of delay plus a 200ms fade over a 300ms wait means the shape finishes
 * appearing exactly as it is thrown away: a blank page with extra steps.
 *
 * The flash it would have guarded against is already bounded — a second visit
 * is served from cache with `isLoading` false, so this is only ever seen on a
 * genuinely cold fetch.
 *
 * `role="status"` here and nowhere inside: the bars are each `aria-hidden`,
 * so a screen reader hears the label once instead of a wall of nothing.
 */
export function SkeletonBlock({
  label = "Loading",
  className,
  children,
}: {
  label?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label={label}
      className={className}
    >
      {children}
    </div>
  );
}

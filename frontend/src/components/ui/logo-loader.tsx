import { Logo } from "@/components/Logo";
import { cn } from "@/lib/utils";

/**
 * Brand-mark loading state. Use wherever a wait is long enough to be worth
 * showing something — route transitions, first paint, blocking fetches — so
 * waiting looks like part of the product rather than a generic spinner.
 *
 * For inline/button-sized waits keep using <Spinner>; this one is page-scale.
 */
export function LogoLoader({
  /** Off by default — the animated mark alone reads as "working", and a word
   *  under it just adds noise. Pass a string when the wait needs explaining. */
  label = null,
  className,
  size = "md",
  /** Fill the viewport (splash / connection gate) instead of the section. */
  fullscreen = false,
}: {
  label?: string | null;
  className?: string;
  size?: "sm" | "md" | "lg";
  fullscreen?: boolean;
}) {
  const markSize =
    size === "sm" ? "size-8" : size === "lg" ? "size-20" : "size-12";

  return (
    <div
      className={cn(
        "loader-deferred flex flex-col items-center justify-center gap-3 text-muted-foreground",
        fullscreen ? "min-h-svh" : "min-h-[65svh]",
        className,
      )}
      role="status"
      aria-live="polite"
    >
      <Logo animate="stroke" className={markSize} />
      {label && <span className="text-sm">{label}</span>}
    </div>
  );
}

import { Loader2 } from "lucide-react";
import { LogoLoader } from "@/components/ui/logo-loader";
import { cn } from "@/lib/utils";

/** Spinning loader icon. */
export function Spinner({ className }: { className?: string }) {
  return (
    <Loader2
      className={cn("size-5 animate-spin text-muted-foreground", className)}
      aria-hidden
    />
  );
}

/**
 * Centered full-section loading state for route/page-level waits.
 * Delegates to the animated brand mark — page-scale waits get the logo,
 * inline ones keep <Spinner>.
 */
export function PageLoader({ label }: { label?: string }) {
  return <LogoLoader label={label ?? null} />;
}

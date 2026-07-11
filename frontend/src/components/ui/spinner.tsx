import { Loader2 } from "lucide-react";
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

/** Centered full-section loading state for route/page-level waits. */
export function PageLoader({ label = "Loading…" }: { label?: string }) {
  return (
    <div
      className="flex min-h-64 flex-col items-center justify-center gap-3 text-muted-foreground"
      role="status"
      aria-live="polite"
    >
      <Spinner className="size-6" />
      <span className="text-sm">{label}</span>
    </div>
  );
}

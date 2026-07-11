import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import { subscribeToasts, type ToastItem, type ToastKind } from "@/lib/toast";
import { cn } from "@/lib/utils";

const AUTO_DISMISS_MS = 6000;

const ICONS: Record<ToastKind, typeof Info> = {
  error: AlertCircle,
  success: CheckCircle2,
  info: Info,
};

const TONE: Record<ToastKind, string> = {
  error: "border-destructive/40 text-destructive",
  success: "border-emerald-500/40 text-emerald-600 dark:text-emerald-400",
  info: "border-border text-foreground",
};

/**
 * Renders the toast stack. Subscribes to the global toast bus (lib/toast) so
 * any code — including the query client's error handlers — can surface a
 * message without prop/context wiring. Mount once, near the app root.
 */
export function Toaster() {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  useEffect(() => {
    return subscribeToasts((toast) => {
      setToasts((prev) => [...prev, toast]);
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== toast.id));
      }, AUTO_DISMISS_MS);
    });
  }, []);

  const dismiss = (id: string) =>
    setToasts((prev) => prev.filter((t) => t.id !== id));

  if (toasts.length === 0) return null;

  return (
    <div
      className="pointer-events-none fixed inset-x-0 bottom-0 z-50 flex flex-col items-center gap-2 p-4 sm:items-end"
      role="region"
      aria-label="Notifications"
    >
      {toasts.map((toast) => {
        const Icon = ICONS[toast.kind];
        return (
          <div
            key={toast.id}
            role={toast.kind === "error" ? "alert" : "status"}
            className={cn(
              "pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-xl border bg-background/95 px-4 py-3 shadow-lg backdrop-blur-sm",
              TONE[toast.kind],
            )}
          >
            <Icon className="mt-0.5 size-5 shrink-0" aria-hidden />
            <p className="flex-1 text-sm text-foreground">{toast.message}</p>
            <button
              onClick={() => dismiss(toast.id)}
              className="shrink-0 rounded-md p-0.5 text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              aria-label="Dismiss notification"
            >
              <X className="size-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
}

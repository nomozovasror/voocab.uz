import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Info,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { subscribeToasts } from "@/lib/toast";
import type { ToastItem, ToastKind, ToastPosition } from "@/lib/toast";
import { cn } from "@/lib/utils";

/**
 * Renders the toast stack. Subscribes to the global bus (lib/toast) so any
 * code — including the query client's error handlers, which are not
 * components — can surface a message with no prop or context wiring. Mount
 * once, near the app root.
 *
 * A toast leaves in two steps: the item is marked closing, the card plays its
 * exit, and only then is it dropped from the list. Removing it outright made
 * it vanish, which reads as a glitch next to the way it arrived.
 */

const EXIT_MS = 200;

const ICONS: Record<ToastKind, typeof Info> = {
  error: AlertCircle,
  success: CheckCircle2,
  warning: AlertTriangle,
  info: Info,
};

/** Only the border and the icon carry the kind. A fully tinted card competes
 *  with the page for attention long after it has been read. */
const TONE: Record<ToastKind, { border: string; accent: string }> = {
  error: { border: "border-destructive/40", accent: "text-destructive" },
  success: { border: "border-success/40", accent: "text-success" },
  warning: { border: "border-warning/40", accent: "text-warning" },
  info: { border: "border-border", accent: "text-muted-foreground" },
};

const POSITIONS: Record<ToastPosition, string> = {
  // Newest nearest the screen edge in both directions, which is why the top
  // stacks are reversed: the last child of a column-reverse is the top one.
  "top-left": "top-0 left-0 items-start flex-col-reverse",
  "top-center": "top-0 inset-x-0 items-center flex-col-reverse",
  "top-right": "top-0 right-0 items-end flex-col-reverse",
  "bottom-left": "bottom-0 left-0 items-start flex-col",
  "bottom-center": "bottom-0 inset-x-0 items-center flex-col",
  "bottom-right": "bottom-0 right-0 items-end flex-col",
};

const POSITION_ORDER = Object.keys(POSITIONS) as ToastPosition[];

export function Toaster() {
  const [items, setItems] = useState<ToastItem[]>([]);
  const [closing, setClosing] = useState<ReadonlySet<string>>(new Set());

  useEffect(() => {
    return subscribeToasts((event) => {
      if (event.type === "dismiss") {
        setClosing((prev) => new Set(prev).add(event.id));
        return;
      }

      const incoming = event.toast;
      setItems((prev) => {
        const at = prev.findIndex((item) => item.id === incoming.id);
        if (at === -1) return [...prev, incoming];
        // Same id: replace in place rather than stack a second card, so
        // "Saving…" can become "Saved" without the two overlapping.
        const next = [...prev];
        next[at] = incoming;
        return next;
      });
      // A reused id may be mid-exit; showing it again brings it back.
      setClosing((prev) => {
        if (!prev.has(incoming.id)) return prev;
        const next = new Set(prev);
        next.delete(incoming.id);
        return next;
      });
    });
  }, []);

  const close = useCallback((id: string) => {
    setClosing((prev) => (prev.has(id) ? prev : new Set(prev).add(id)));
  }, []);

  const remove = useCallback((id: string) => {
    setItems((prev) => prev.filter((item) => item.id !== id));
    setClosing((prev) => {
      if (!prev.has(id)) return prev;
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  }, []);

  if (items.length === 0) return null;

  return (
    <>
      {POSITION_ORDER.map((position) => {
        const stack = items.filter((item) => item.position === position);
        if (stack.length === 0) return null;
        return (
          <div
            key={position}
            className={cn(
              "pointer-events-none fixed z-50 flex gap-2 p-4",
              POSITIONS[position],
            )}
            role="region"
            aria-label="Notifications"
          >
            {stack.map((item) => (
              <ToastCard
                key={item.id}
                toast={item}
                closing={closing.has(item.id)}
                onClose={close}
                onRemoved={remove}
              />
            ))}
          </div>
        );
      })}
    </>
  );
}

interface ToastCardProps {
  toast: ToastItem;
  closing: boolean;
  onClose: (id: string) => void;
  onRemoved: (id: string) => void;
}

function ToastCard({ toast, closing, onClose, onRemoved }: ToastCardProps) {
  const { id, kind, title, message, action, duration, position } = toast;
  const Icon = ICONS[kind];
  const tone = TONE[kind];
  const fromTop = position.startsWith("top");

  // Held back one frame so the browser has a "before" to animate from: set
  // straight to the final classes, there is no transition to run.
  const [entered, setEntered] = useState(false);
  useEffect(() => {
    const frame = requestAnimationFrame(() => setEntered(true));
    return () => cancelAnimationFrame(frame);
  }, []);

  // Hovering pauses the countdown and holds what is left of it. A toast with
  // an Undo button is unusable otherwise: reaching for it is exactly when the
  // toast would time out.
  const [paused, setPaused] = useState(false);
  const remainingRef = useRef(duration);
  // Keyed on the item itself, not on its duration: a toast replaced under the
  // same id is a new object with the same numbers, and it deserves its full
  // time rather than whatever was left of the one it replaced. Declared
  // before the timer below so the reset lands first when both re-run.
  useEffect(() => {
    remainingRef.current = toast.duration;
  }, [toast]);

  useEffect(() => {
    if (toast.duration <= 0 || paused || closing) return;
    const startedAt = Date.now();
    const timer = setTimeout(() => onClose(id), remainingRef.current);
    return () => {
      clearTimeout(timer);
      remainingRef.current -= Date.now() - startedAt;
    };
  }, [toast, paused, closing, id, onClose]);

  // The exit is timed rather than driven by transitionend: the element has
  // several properties in flight, and a card whose event never fires (a
  // background tab, reduced motion) would stay on screen for good.
  const onDismiss = toast.onDismiss;
  useEffect(() => {
    if (!closing) return;
    const timer = setTimeout(() => {
      onRemoved(id);
      onDismiss?.();
    }, EXIT_MS);
    return () => clearTimeout(timer);
  }, [closing, id, onRemoved, onDismiss]);

  const hidden = closing || !entered;

  return (
    <div
      role={kind === "error" ? "alert" : "status"}
      onPointerEnter={() => setPaused(true)}
      onPointerLeave={() => setPaused(false)}
      onFocusCapture={() => setPaused(true)}
      onBlurCapture={() => setPaused(false)}
      className={cn(
        "pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-xl border bg-card/95 px-4 py-3 shadow-lg backdrop-blur-sm",
        "transition-all duration-200 ease-out motion-reduce:transition-none",
        tone.border,
        hidden
          ? cn("scale-95 opacity-0", fromTop ? "-translate-y-2" : "translate-y-2")
          : "translate-y-0 scale-100 opacity-100",
      )}
    >
      <Icon className={cn("mt-0.5 size-5 shrink-0", tone.accent)} aria-hidden />

      <div className="flex-1 space-y-0.5">
        {title && (
          <p className={cn("text-sm font-medium", tone.accent)}>{title}</p>
        )}
        <p
          className={cn(
            "text-sm",
            title ? "text-muted-foreground" : "text-foreground",
          )}
        >
          {message}
        </p>
      </div>

      {action && (
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            action.onClick();
            onClose(id);
          }}
          className="mt-px shrink-0"
        >
          {action.label}
        </Button>
      )}

      <button
        type="button"
        onClick={() => onClose(id)}
        aria-label="Dismiss notification"
        className="mt-0.5 shrink-0 rounded-md p-0.5 text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        <X className="size-4" aria-hidden />
      </button>
    </div>
  );
}

/**
 * Minimal, dependency-free toast bus. Anything can `toast(...)` — including
 * non-React code like the query client's error handlers — and the <Toaster/>
 * component subscribes and renders. Kept tiny on purpose: no context
 * threading, and no imperative ref, which is what lets `lib/query-client.ts`
 * raise a toast at all.
 */

export type ToastKind = "error" | "success" | "warning" | "info";

export type ToastPosition =
  | "top-left"
  | "top-center"
  | "top-right"
  | "bottom-left"
  | "bottom-center"
  | "bottom-right";

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastOptions {
  message: string;
  /** A short lead above the message. Without one the message stands alone,
   *  which is the right shape for the one-line API errors most callers send. */
  title?: string;
  kind?: ToastKind;
  /** Milliseconds on screen; 0 keeps it until dismissed. Hovering pauses the
   *  countdown, so a toast with an action stays reachable. */
  duration?: number;
  position?: ToastPosition;
  action?: ToastAction;
  onDismiss?: () => void;
  /** Reuse an id to replace a toast already on screen rather than stack a
   *  second one under it — "Saving…" becoming "Saved" is one toast. */
  id?: string;
}

export interface ToastItem extends ToastOptions {
  id: string;
  kind: ToastKind;
  duration: number;
  position: ToastPosition;
}

/** Dismissal travels the bus too, so code that raised a toast from outside
 *  React can take it back — the "Saving…" case again. */
export type ToastEvent =
  | { type: "show"; toast: ToastItem }
  | { type: "dismiss"; id: string };

type Listener = (event: ToastEvent) => void;

const DEFAULT_DURATION = 6000;
const DEFAULT_POSITION: ToastPosition = "bottom-right";

const listeners = new Set<Listener>();

export function subscribeToasts(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function emit(event: ToastEvent): void {
  for (const listener of listeners) listener(event);
}

/**
 * Raise a toast, and return its id so it can be dismissed or replaced later.
 *
 * The short form covers the common case — a message, and a kind that defaults
 * to an error, since API failures are what most callers are reporting:
 *
 *     toast(getErrorMessage(error));
 *     toast("Saved", "success");
 *
 * The object form adds a title, an action, a position and a lifetime:
 *
 *     toast({
 *       title: "Part deleted",
 *       message: "Part 2 and its questions are gone.",
 *       kind: "success",
 *       action: { label: "Undo", onClick: restore },
 *     });
 */
export function toast(message: string, kind?: ToastKind): string;
export function toast(options: ToastOptions): string;
export function toast(
  messageOrOptions: string | ToastOptions,
  kind: ToastKind = "error",
): string {
  const options: ToastOptions =
    typeof messageOrOptions === "string"
      ? { message: messageOrOptions, kind }
      : messageOrOptions;

  const item: ToastItem = {
    ...options,
    id: options.id ?? crypto.randomUUID(),
    kind: options.kind ?? "info",
    duration: options.duration ?? DEFAULT_DURATION,
    position: options.position ?? DEFAULT_POSITION,
  };

  emit({ type: "show", toast: item });
  return item.id;
}

/** Take back a toast early — the pending one whose outcome has now arrived,
 *  or anything left sticky with `duration: 0`. */
export function dismissToast(id: string): void {
  emit({ type: "dismiss", id });
}

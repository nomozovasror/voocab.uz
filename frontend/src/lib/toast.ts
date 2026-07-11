/**
 * Minimal, dependency-free toast bus. Anything can `toast(...)` (including
 * non-React code like the query client's error handlers); the <Toaster/>
 * component subscribes and renders. Kept tiny on purpose — no context threading.
 */

export type ToastKind = "error" | "success" | "info";

export interface ToastItem {
  id: string;
  kind: ToastKind;
  message: string;
}

type Listener = (toast: ToastItem) => void;

const listeners = new Set<Listener>();

export function subscribeToasts(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Emit a toast. Defaults to an error, the most common case for API failures. */
export function toast(message: string, kind: ToastKind = "error"): void {
  const item: ToastItem = { id: crypto.randomUUID(), kind, message };
  for (const listener of listeners) listener(item);
}

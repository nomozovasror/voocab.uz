import {
  createContext,
  use,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { setBackendErrorHandler } from "@/lib/api";
import { checkHealth } from "@/connection/health";

/**
 * - `online`      — backend reachable; the app runs normally.
 * - `offline`     — backend unreachable (network error / 5xx / health fail);
 *                   the full-screen gate takes over.
 * - `reconnected` — just came back; a brief "Connected" confirmation before we
 *                   auto-restore, so a game in progress isn't yanked instantly.
 */
export type ConnectionStatus = "online" | "offline" | "reconnected";

const OFFLINE_POLL_MS = 3000;
const RECONNECTED_HOLD_MS = 3000;

interface ConnectionContextValue {
  status: ConnectionStatus;
  /** Dismiss the reconnected confirmation immediately and restore the app. */
  resume: () => void;
}

const ConnectionContext = createContext<ConnectionContextValue | null>(null);

export function ConnectionProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<ConnectionStatus>("online");
  // A single-flight guard so overlapping triggers don't stack health probes.
  const checkingRef = useRef(false);

  const verify = useCallback(async () => {
    if (checkingRef.current) return;
    checkingRef.current = true;
    try {
      const healthy = await checkHealth();
      setStatus((prev) => {
        if (healthy) {
          // Only celebrate a real recovery; a healthy probe while already
          // online is a no-op.
          return prev === "offline" ? "reconnected" : prev;
        }
        // Unhealthy: drop to offline unless we're mid-reconnect animation.
        return prev === "reconnected" ? prev : "offline";
      });
    } finally {
      checkingRef.current = false;
    }
  }, []);

  // The api client calls this on a network error / 5xx — verify before gating,
  // so a one-off blip that recovers instantly doesn't flash the gate.
  useEffect(() => {
    setBackendErrorHandler(() => void verify());
    return () => setBackendErrorHandler(null);
  }, [verify]);

  // On app open, confirm the backend is actually reachable.
  useEffect(() => {
    void verify();
  }, [verify]);

  // While offline, keep probing until it comes back.
  useEffect(() => {
    if (status !== "offline") return;
    const id = setInterval(() => void verify(), OFFLINE_POLL_MS);
    return () => clearInterval(id);
  }, [status, verify]);

  // After showing "Connected", auto-restore the app.
  useEffect(() => {
    if (status !== "reconnected") return;
    const id = setTimeout(() => setStatus("online"), RECONNECTED_HOLD_MS);
    return () => clearTimeout(id);
  }, [status]);

  const resume = useCallback(() => setStatus("online"), []);

  return (
    <ConnectionContext value={{ status, resume }}>{children}</ConnectionContext>
  );
}

export function useConnection(): ConnectionContextValue {
  const ctx = use(ConnectionContext);
  if (!ctx) {
    throw new Error("useConnection must be used within a ConnectionProvider");
  }
  return ctx;
}

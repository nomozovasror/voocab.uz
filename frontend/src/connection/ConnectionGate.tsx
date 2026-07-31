import { useConnection } from "@/connection/ConnectionContext";
import { ConnectionGateScreen } from "@/connection/ConnectionGateScreen";

/**
 * Wraps the whole app (above the router). While the backend is reachable it's
 * transparent; when it's not, it replaces everything with the full-screen gate,
 * which blocks navigation until the connection is restored.
 */
export function ConnectionGate({ children }: { children: React.ReactNode }) {
  const { status } = useConnection();
  if (status === "online") return <>{children}</>;
  return <ConnectionGateScreen />;
}

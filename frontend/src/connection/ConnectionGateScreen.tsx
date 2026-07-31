import { useState } from "react";
import { WifiOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { TypingRescue } from "@/features/typing-rescue/TypingRescue";
import { useConnection } from "@/connection/ConnectionContext";

/**
 * Full-screen takeover shown while the backend is unreachable. Mounted above
 * the router, so navigation is impossible until the connection returns.
 *
 * Starts as a big "server is down" message; the game is opt-in. When the user
 * chooses to play, the message shrinks to a compact banner and the game takes
 * over. Auto-restores once the API is back.
 */
export function ConnectionGateScreen() {
  const { status, resume } = useConnection();
  const [expanded, setExpanded] = useState(false);
  const reconnected = status === "reconnected";

  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center overflow-y-auto bg-background px-4 py-8">
      <div className="flex w-full max-w-2xl flex-1 flex-col items-center justify-center gap-6">
        {!expanded ? (
          <div
            className="flex flex-col items-center gap-6 text-center"
            style={{ animation: "tr-fade-in 0.4s ease-out" }}
          >
            <div className="space-y-4">
              <div className="mx-auto flex size-16 items-center justify-center rounded-2xl bg-primary/10">
                <WifiOff className="size-8 text-primary" />
              </div>
              <h1 className="text-3xl font-semibold text-balance text-foreground sm:text-4xl">
                The server stepped out for a cup of tea ☕
              </h1>
              <p className="text-lg text-muted-foreground">
                It’ll be back in a moment.
              </p>
            </div>

            {reconnected ? (
              <div className="flex items-center gap-3">
                <span className="font-medium text-primary">Back online ✅</span>
                <Button onClick={resume}>Continue</Button>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-4">
                <p
                  className="font-mono text-sm text-muted-foreground"
                  aria-live="polite"
                >
                  Reconnecting… we’ll bring things back automatically.
                </p>
                <Button
                  variant="outline"
                  size="lg"
                  onClick={() => setExpanded(true)}
                >
                  Play a game while you wait
                </Button>
              </div>
            )}
          </div>
        ) : (
          <>
            {/* Compact connection banner */}
            <div className="flex w-full items-center justify-between gap-3 rounded-lg border border-border bg-background/60 px-4 py-2 text-sm">
              <span className="flex items-center gap-2 text-muted-foreground">
                <WifiOff className="size-4" />
                {reconnected
                  ? "Back online ✅"
                  : "Server unavailable — reconnecting…"}
              </span>
              {reconnected ? (
                <Button size="sm" onClick={resume}>
                  Continue
                </Button>
              ) : (
                <button
                  onClick={() => setExpanded(false)}
                  className="text-muted-foreground underline underline-offset-2 transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                >
                  Hide
                </button>
              )}
            </div>

            <TypingRescue />
          </>
        )}
      </div>
    </div>
  );
}

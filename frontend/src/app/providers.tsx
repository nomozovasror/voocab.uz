import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "@/lib/query-client";
import { ThemeProvider } from "@/theme/ThemeProvider";
import { AuthProvider } from "@/auth/AuthProvider";
import { ConnectionProvider } from "@/connection/ConnectionContext";
import { Toaster } from "@/components/ui/toaster";

/** Single place that composes all app-wide context providers. */
export function AppProviders({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <ConnectionProvider>
          <AuthProvider>{children}</AuthProvider>
        </ConnectionProvider>
        <Toaster />
      </ThemeProvider>
    </QueryClientProvider>
  );
}

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { setUnauthorizedHandler } from "@/lib/api";
import { AUTH_ME_KEY } from "@/auth/useCurrentUser";

/**
 * Wires the central API client's 401 handling into app state: when any request
 * is rejected as unauthenticated (an expired/invalid session), we clear the
 * cached user and hard-redirect to /login. A full navigation (rather than
 * router push) is deliberate — it lives above the router and guarantees a clean
 * slate for a session that just went away.
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();

  useEffect(() => {
    setUnauthorizedHandler(() => {
      queryClient.setQueryData(AUTH_ME_KEY, null);
      if (!window.location.pathname.startsWith("/login")) {
        window.location.assign("/login");
      }
    });
    return () => setUnauthorizedHandler(null);
  }, [queryClient]);

  return <>{children}</>;
}

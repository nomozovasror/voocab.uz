import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { User } from "@/auth/types";

/**
 * Auth state, backed by the backend session cookie (httpOnly — never touched
 * from JS). `/api/auth/me` returns the current user, or 401 when logged out.
 * We model "logged out" as `null` data (via `expected401`) so a 401 here is a
 * normal state, not an error, and doesn't trigger the global redirect/toast.
 */

export const AUTH_ME_KEY = ["auth", "me"] as const;

export function fetchCurrentUser(): Promise<User | null> {
  return api.get<User | null>("/api/auth/me", { expected401: true });
}

export function useCurrentUser() {
  const { data, isLoading, isError } = useQuery({
    queryKey: AUTH_ME_KEY,
    queryFn: fetchCurrentUser,
    staleTime: 60_000,
    retry: false,
    // A network failure on the probe shouldn't pop a global toast.
    meta: { suppressGlobalError: true },
  });

  return { user: data ?? null, isLoading, isError };
}

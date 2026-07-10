import { useQuery, useQueryClient } from "@tanstack/react-query";

/**
 * Auth state, backed by the backend session cookies (httpOnly — never touched
 * from JS). `/api/auth/me` returns the current user or 401; we model "logged
 * out" as `null` data so components can branch on it.
 */

export interface Me {
  id: string;
  display_name: string;
  email: string | null;
  avatar_url: string | null;
}

export const AUTH_ME_KEY = ["auth", "me"] as const;

async function fetchMe(): Promise<Me | null> {
  const res = await fetch("/api/auth/me");
  if (res.status === 401) return null;
  if (!res.ok) throw new Error(`auth/me failed: ${res.status}`);
  return (await res.json()) as Me;
}

export function useAuth() {
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: AUTH_ME_KEY,
    queryFn: fetchMe,
    staleTime: 60_000,
    retry: false,
  });

  /** Full-page navigation to the backend, which 302-redirects out to Telegram. */
  const login = () => {
    window.location.href = "/api/auth/telegram/start";
  };

  const logout = async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    await queryClient.invalidateQueries({ queryKey: AUTH_ME_KEY });
  };

  return { user: data ?? null, isLoading, login, logout };
}

import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { apiUrl } from "@/config";
import { api } from "@/lib/api";
import { AUTH_ME_KEY } from "@/auth/useCurrentUser";

/** Login (Telegram redirect) and logout actions. */
export function useAuthActions() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  /**
   * Full-page navigation to the backend, which 302-redirects out to Telegram
   * and (after the OIDC round-trip) back to the app with the session cookie set.
   * Must be a real navigation, not a fetch, so the browser follows the redirect.
   */
  const login = () => {
    window.location.href = apiUrl("/api/auth/telegram/start");
  };

  const logout = async () => {
    try {
      await api.post("/api/auth/logout");
    } finally {
      // Optimistically drop the cached user, then refetch to confirm, and land
      // on the login page. `finally` so a failed request still clears local state.
      queryClient.setQueryData(AUTH_ME_KEY, null);
      await queryClient.invalidateQueries({ queryKey: AUTH_ME_KEY });
      navigate("/login", { replace: true });
    }
  };

  /** Dev only: passwordless login against the gated backend endpoint. The UI
   *  only exposes this in Vite dev builds; the backend only serves it when
   *  DEV_LOGIN_ENABLED (and non-secure cookies). */
  const devLogin = async () => {
    await api.post("/api/auth/dev-login");
    await queryClient.invalidateQueries({ queryKey: AUTH_ME_KEY });
    navigate("/", { replace: true });
  };

  return { login, logout, devLogin };
}

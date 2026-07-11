import { Navigate, Outlet, useLocation } from "react-router-dom";
import { PageLoader } from "@/components/ui/spinner";
import { useCurrentUser } from "@/auth/useCurrentUser";

/**
 * Gate for protected routes. Used as a pathless layout route wrapping the
 * children that need a session:
 *  - while the auth probe is in flight → a loader (no flash of the login page),
 *  - logged out → redirect to /login, remembering where we came from,
 *  - logged in → render the nested route.
 */
export function RequireAuth() {
  const { user, isLoading } = useCurrentUser();
  const location = useLocation();

  if (isLoading) return <PageLoader />;

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <Outlet />;
}

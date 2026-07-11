import { Navigate, useLocation, useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PageLoader } from "@/components/ui/spinner";
import { useCurrentUser } from "@/auth/useCurrentUser";
import { useAuthActions } from "@/auth/useAuthActions";

interface FromState {
  from?: { pathname?: string };
}

/**
 * Login screen. The backend owns the whole OIDC + session flow; this page just
 * kicks it off and reflects auth state:
 *  - probe in flight → loader,
 *  - already signed in → bounce to where the user was headed (or home),
 *  - signed out → the Telegram button.
 */
export default function LoginPage() {
  const { user, isLoading } = useCurrentUser();
  const { login } = useAuthActions();
  const location = useLocation();
  const [params] = useSearchParams();
  const loginError = params.get("login") === "error";

  if (isLoading) return <PageLoader />;

  if (user) {
    const to = (location.state as FromState | null)?.from?.pathname ?? "/";
    return <Navigate to={to} replace />;
  }

  return (
    <div className="mx-auto max-w-md space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold text-foreground">Sign in</h1>
        <p className="text-muted-foreground">
          Use your Telegram account to sign in to voocab.
        </p>
      </div>

      {loginError && (
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive"
        >
          Sign-in didn’t complete. Please try again.
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Welcome</CardTitle>
          <CardDescription>
            Continue with Telegram to create or access your account.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={login} size="lg" className="w-full">
            Sign in with Telegram
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

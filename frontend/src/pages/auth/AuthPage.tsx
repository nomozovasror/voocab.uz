import { useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { UserAvatar } from "@/auth/UserAvatar";
import { useAuth } from "@/auth/useAuth";

/**
 * Minimal auth screen. The backend owns the whole OIDC + session flow; this
 * page just reflects `useAuth` state and triggers login/logout. (After a
 * successful login the backend redirects to the home page, where the header
 * already shows the account menu — this page is the manual entry point.)
 */
export default function AuthPage() {
  const { user, isLoading, login, logout } = useAuth();
  const [params] = useSearchParams();
  const loginError = params.get("login") === "error";

  return (
    <div className="mx-auto max-w-md space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold text-foreground">Sign in</h1>
        <p className="text-muted-foreground">
          Use your Telegram account to sign in to voocab.
        </p>
      </div>

      {loginError && !user && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          Sign-in didn’t complete. Please try again.
        </div>
      )}

      <Card>
        {isLoading ? (
          <CardContent className="py-10 text-center text-muted-foreground">
            Loading…
          </CardContent>
        ) : user ? (
          <>
            <CardHeader>
              <CardTitle>You’re signed in</CardTitle>
              <CardDescription>Your voocab session is active.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center gap-3">
                <UserAvatar user={user} className="size-12 text-lg" />
                <div className="min-w-0">
                  <div className="truncate font-medium text-foreground">
                    {user.display_name}
                  </div>
                  <div className="truncate text-sm text-muted-foreground">
                    {user.email ?? "No email on file"}
                  </div>
                </div>
              </div>
              <Button
                variant="outline"
                onClick={() => void logout()}
                className="w-full"
              >
                Sign out
              </Button>
            </CardContent>
          </>
        ) : (
          <>
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
          </>
        )}
      </Card>
    </div>
  );
}

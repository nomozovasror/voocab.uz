import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { UserAvatar } from "@/auth/UserAvatar";
import { useCurrentUser } from "@/auth/useCurrentUser";
import { useAuthActions } from "@/auth/useAuthActions";

/**
 * Protected placeholder. Rendered under RequireAuth, so `user` is always
 * present here — it doubles as a smoke test that the session survives a reload.
 */
export default function ProfilePage() {
  const { user } = useCurrentUser();
  const { logout } = useAuthActions();

  if (!user) return null;

  return (
    <div className="mx-auto max-w-md space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold text-foreground">Profile</h1>
        <p className="text-muted-foreground">Your voocab account.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Signed in</CardTitle>
          <CardDescription>Your session is active.</CardDescription>
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
      </Card>
    </div>
  );
}

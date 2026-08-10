import { Suspense } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { ArrowLeft, Bell } from "lucide-react";
import { Logo } from "@/components/Logo";
import { UserAvatar } from "@/auth/UserAvatar";
import { useCurrentUser } from "@/auth/useCurrentUser";
import {
  StudioBreadcrumbProvider,
  StudioBreadcrumbs,
} from "@/components/studio/breadcrumbs";

/**
 * Studio's own layout/navigation (brief §3.10 / §10 — authoring lives under
 * /studio/* with a distinct chrome from the main app, same codebase + auth).
 * Deliberately simpler than <Layout>: no floating islands, a persistent
 * top bar with tabs + a way back to the main app.
 */
export function StudioLayout() {
  const { user } = useCurrentUser();
  const navigate = useNavigate();

  return (
    // h-svh (not min-h-svh): the dashboard is a one-screen app view, so the
    // shell must be *bounded* by the viewport — otherwise its 1fr grid rows
    // grow with their content and the board spills past the fold.
    <StudioBreadcrumbProvider>
    <div className="flex h-svh flex-col bg-background">
      <header className="sticky top-0 z-30 w-full flex-none border-b border-border bg-background/90 backdrop-blur-md">
        <div className="mx-auto flex h-14 w-full max-w-[1500px] items-center gap-4 px-4 sm:px-6">
          <div className="flex items-center gap-2">
            <NavLink to="/" className="group flex items-center gap-2">
              <Logo animate="hover" className="size-6" />
              <span className="text-body font-semibold text-foreground">
                voocab
              </span>
            </NavLink>
            <span className="text-muted-foreground">Studio</span>
          </div>

          <span className="h-4 w-px shrink-0 bg-border" aria-hidden />
          <StudioBreadcrumbs />


          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={() => navigate("/")}
              aria-label="Back to app"
              title="Back to app"
              className="flex size-7 items-center justify-center rounded-full border border-foreground/10 text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              <ArrowLeft className="size-3.5" />
            </button>
            <button
              type="button"
              aria-label="Notifications"
              title="Notifications"
              className="flex size-7 items-center justify-center rounded-full border border-foreground/10 text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              <Bell className="size-3.5" />
            </button>
            {user && (
              <NavLink to="/profile" aria-label="Account">
                <UserAvatar user={user} className="size-7 text-xs" />
              </NavLink>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-[1500px] flex-1 min-h-0 flex-col overflow-y-auto px-4 py-4 sm:px-6">
        <Suspense
          fallback={
            <div className="flex min-h-64 items-center justify-center text-muted-foreground">
              Loading…
            </div>
          }
        >
          <Outlet />
        </Suspense>
      </main>
    </div>
    </StudioBreadcrumbProvider>
  );
}

import { Suspense } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { ArrowLeft, Plus } from "lucide-react";
import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Studio's own layout/navigation (brief §3.10 / §10 — authoring lives under
 * /studio/* with a distinct chrome from the main app, same codebase + auth).
 * Deliberately simpler than <Layout>: no floating islands, a persistent
 * top bar with a way back to the main app.
 */
export function StudioLayout() {
  return (
    <div className="flex min-h-svh flex-col bg-background">
      <header className="sticky top-0 z-30 w-full border-b border-border bg-background/90 backdrop-blur-md">
        <div className="mx-auto flex h-14 w-full max-w-5xl items-center justify-between gap-4 px-4 sm:px-6">
          <div className="flex items-center gap-4">
            <NavLink to="/" className="flex items-center gap-2">
              <Logo className="size-6" />
              <span className="text-base font-semibold text-foreground">
                voocab
              </span>
            </NavLink>
            <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium tracking-wide text-primary uppercase">
              Studio
            </span>
          </div>

          <nav className="flex items-center gap-1">
            <NavLink
              to="/studio"
              end
              className={({ isActive }) =>
                cn(
                  "rounded-full px-3 py-1.5 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-foreground/5 hover:text-foreground",
                )
              }
            >
              My materials
            </NavLink>
            <Button asChild size="sm" className="ml-2">
              <NavLink to="/studio/materials/new">
                <Plus className="size-4" />
                New listening
              </NavLink>
            </Button>
            <Button asChild variant="ghost" size="sm" className="ml-2">
              <NavLink to="/">
                <ArrowLeft className="size-4" />
                Back to app
              </NavLink>
            </Button>
          </nav>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 sm:px-6">
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
  );
}

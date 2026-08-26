import { Suspense } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { Logo } from "@/components/Logo";
import { PageLoader } from "@/components/ui/spinner";
import { RouteProgress } from "@/components/ui/route-progress";
import { UserMenu } from "@/components/layout/UserMenu";
import {
  HeaderCentreProvider,
  useHeaderCentreState,
} from "@/components/layout/header-center";
import { ThemeSwitcher } from "@/theme/ThemeSwitcher";
import { useCurrentUser } from "@/auth/useCurrentUser";
import { useScrolled } from "@/hooks/use-scrolled";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { to: "/reading", label: "Reading" },
  { to: "/listening", label: "Listening" },
  { to: "/dictation", label: "Dictation" },
  { to: "/vocabulary", label: "Vocabulary" },
];

export function Layout() {
  const scrolled = useScrolled();
  const { user, isLoading } = useCurrentUser();
  // The middle of the header is held clear when a page has something of its
  // own arriving there (see components/layout/header-center.tsx).
  const centre = useHeaderCentreState();

  // Each group is its own floating island — transparent at the top, frosted
  // glass once scrolled. A shared height keeps the three islands aligned.
  const pill = cn(
    "flex h-12 items-center rounded-2xl border px-4 transition-[background-color,border-color,box-shadow,backdrop-filter] duration-300",
    scrolled
      ? "border-border bg-background/70 shadow-sm backdrop-blur-md supports-[backdrop-filter]:bg-background/60"
      : "border-transparent bg-transparent",
  );

  return (
    <HeaderCentreProvider value={centre.value}>
    <div className="flex min-h-svh flex-col">
      <RouteProgress />
      <header className="sticky top-0 z-30 w-full px-4 pt-3 sm:px-6 lg:px-8">
        {/* Three islands on one rail. The rail is wider than the content at the
            top and snaps to the container width once scrolled. */}
        <div
          className={cn(
            "mx-auto grid w-full grid-cols-[1fr_auto_1fr] items-center gap-3 transition-[max-width] duration-300",
            scrolled ? "max-w-7xl" : "max-w-[85rem]",
          )}
        >
          {/* Brand — the "voocab" wordmark is the Home link. */}
          <div className={cn(pill, "gap-2 justify-self-start")}>
            <NavLink to="/" className="group flex items-center gap-2">
              <Logo animate="hover" className="size-6" />
              <span className="text-base font-semibold text-foreground">
                voocab
              </span>
            </NavLink>
          </div>

          {/* Primary nav, centered. Active item gets a soft glass chip.

              It gives way when a page has something arriving in the middle —
              lifting out through the top of the header, which is the only
              direction that reads as being pushed rather than as blinking
              out. Moved rather than unmounted: it has to come back down when
              the page lets go, and something that was removed can't. */}
          <nav
            aria-hidden={centre.claimed}
            className={cn(
              pill,
              "hidden gap-1 px-2 justify-self-center md:flex",
              // `translate`, not `transform`: Tailwind v4 writes -translate-y-*
              // to the individual `translate` property, so a transition naming
              // `transform` animates nothing and the nav jumps out while only
              // its opacity fades.
              "transition-[translate,opacity] duration-300 ease-out motion-reduce:transition-none",
              // A short lift, not a launch: 32px puts it behind the header's own top
              // edge, and the fade finishes the job. Sending it further only
              // makes it travel faster to cover the distance in the same
              // 300ms, which reads as a flinch.
              centre.claimed && "pointer-events-none -translate-y-8 opacity-0",
            )}
          >
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                tabIndex={centre.claimed ? -1 : undefined}
                className={({ isActive }) =>
                  cn(
                    "rounded-full px-3 py-1.5 text-xs font-medium tracking-wide uppercase transition-colors",
                    isActive
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:bg-foreground/5 hover:text-foreground",
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          {/* Actions */}
          <div className={cn(pill, "gap-2 justify-self-end")}>
            <ThemeSwitcher />
            {/* Reflect session: signed-in users get an account menu, everyone
                else a Sign in button. `isLoading` avoids a flash of the wrong
                one on first paint. */}
            {isLoading ? (
              <div className="size-7 animate-pulse rounded-full bg-foreground/10" />
            ) : user ? (
              <UserMenu user={user} />
            ) : (
              <NavLink
                to="/login"
                className="rounded-full bg-linear-to-b from-primary to-primary/80 px-4 py-1.5 text-sm font-medium text-primary-foreground shadow-[0_0_24px_-6px_var(--primary)] transition-shadow hover:shadow-[0_0_28px_-4px_var(--primary)] focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                Sign in
              </NavLink>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6 lg:px-8">
        {/* Dead for the routes as configured: react-router's route-level
            `lazy:` resolves inside the router rather than by suspending, so
            nothing below ever reaches here. Kept as the boundary of last
            resort — a page that later adopts React.lazy or use() would
            otherwise suspend all the way to the React root and blank the
            whole app, header included. Cold loads are covered by each
            route's HydrateFallback, in-page waits by the page's own
            skeleton, and the gap between the two by <RouteProgress/>. */}
        <Suspense fallback={<PageLoader />}>
          <Outlet />
        </Suspense>
      </main>
    </div>
    </HeaderCentreProvider>
  );
}

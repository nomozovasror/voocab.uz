import { Suspense } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { Logo } from "@/components/Logo";
import { UserMenu } from "@/components/layout/UserMenu";
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

  // Each group is its own floating island — transparent at the top, frosted
  // glass once scrolled. A shared height keeps the three islands aligned.
  const pill = cn(
    "flex h-12 items-center rounded-2xl border px-4 transition-[background-color,border-color,box-shadow,backdrop-filter] duration-300",
    scrolled
      ? "border-border bg-background/70 shadow-sm backdrop-blur-md supports-[backdrop-filter]:bg-background/60"
      : "border-transparent bg-transparent",
  );

  return (
    <div className="flex min-h-svh flex-col">
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

          {/* Primary nav, centered. Active item gets a soft glass chip. */}
          <nav
            className={cn(pill, "hidden gap-1 px-2 justify-self-center md:flex")}
          >
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  cn(
                    "rounded-full px-3 py-1.5 text-xs font-medium tracking-wider uppercase transition-colors",
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

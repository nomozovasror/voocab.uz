import { Suspense } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { ThemeSwitcher } from "@/theme/ThemeSwitcher";
import { useScrolled } from "@/hooks/use-scrolled";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { to: "/", label: "Home", end: true },
  { to: "/reading", label: "Reading" },
  { to: "/listening", label: "Listening" },
  { to: "/dictation", label: "Dictation" },
  { to: "/profile", label: "Profile" },
];

export function Layout() {
  const scrolled = useScrolled();

  // Each nav group is a floating pill that turns to frosted glass on scroll.
  const pill = cn(
    "flex items-center rounded-2xl border px-4 py-2 transition-[background-color,border-color,box-shadow,backdrop-filter] duration-300",
    scrolled
      ? "border-border bg-background/70 shadow-sm backdrop-blur-md supports-[backdrop-filter]:bg-background/60"
      : "border-transparent bg-transparent",
  );

  return (
    <div className="flex min-h-svh flex-col">
      <header className="sticky top-0 z-30 w-full px-4 pt-3 sm:px-6 lg:px-8">
        <div className="mx-auto flex w-full max-w-7xl items-center gap-3">
          {/* Brand + primary nav */}
          <div className={cn(pill, "gap-5")}>
            <NavLink to="/" className="flex items-center gap-2">
              <img src="/voocab.svg" alt="" className="size-6" />
              <span className="text-base font-semibold text-foreground">
                voocab
              </span>
            </NavLink>

            <span aria-hidden className="text-lg text-muted-foreground/40">
              /
            </span>

            <nav className="hidden items-center gap-6 md:flex">
              {NAV_ITEMS.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    cn(
                      "text-xs font-medium tracking-wider uppercase transition-colors",
                      isActive
                        ? "text-foreground"
                        : "text-muted-foreground hover:text-foreground",
                    )
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
          </div>

          {/* Actions */}
          <div className={cn(pill, "ml-auto gap-2")}>
            <ThemeSwitcher />
            <NavLink
              to="/auth"
              className="rounded-full bg-linear-to-b from-primary to-primary/80 px-4 py-1.5 text-sm font-medium text-primary-foreground shadow-[0_0_24px_-6px_var(--primary)] transition-shadow hover:shadow-[0_0_28px_-4px_var(--primary)] focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              Sign in
            </NavLink>
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

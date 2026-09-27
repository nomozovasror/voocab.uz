import { Suspense } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { Logo } from "@/components/Logo";
import { PageLoader } from "@/components/ui/spinner";
import { RouteProgress } from "@/components/ui/route-progress";
import { UserMenu } from "@/components/layout/UserMenu";
import { Footer } from "@/components/layout/Footer";
import {
  HeaderCentreProvider,
  useHeaderCentreState,
} from "@/components/layout/header-center";
import {
  HeaderTaskProvider,
  useHeaderTaskState,
} from "@/components/layout/header-task";
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
  // ...and all three islands go over to a page that fills the window and
  // cannot scroll (see components/layout/header-task.tsx).
  const task = useHeaderTaskState();

  // Each group is its own floating island — transparent at the top, frosted
  // glass once scrolled. A shared height keeps the three islands aligned.
  //
  // `pointer-events-auto` puts back what the header gives up — see the note
  // on <header> below. It is on the pill rather than on each island because
  // the islands ARE the pills, and a fourth one added later would otherwise
  // be silently unclickable.
  // Settled once the page has moved under them — or straight away for a page
  // that has taken the islands over. `useScrolled` can never fire on the
  // reading take screen: the document does not move, the two panes do. Its
  // islands would have sat transparent for the whole paper, which is a row
  // of loose controls floating on the background rather than the three pills
  // the rest of the app has.
  const settled = scrolled || task.active;
  const pill = cn(
    "pointer-events-auto flex h-12 items-center rounded-2xl border px-4 transition-[background-color,border-color,box-shadow,backdrop-filter] duration-300",
    settled
      ? "border-border bg-background/70 shadow-sm backdrop-blur-md supports-[backdrop-filter]:bg-background/60"
      : "border-transparent bg-transparent",
  );

  return (
    <HeaderCentreProvider value={centre.value}>
      <HeaderTaskProvider value={task.value}>
        <div className="flex min-h-svh flex-col">
          <RouteProgress />
          {/*
        `pointer-events-none`, and this is load-bearing.

        The header is a full-width box sixty pixels tall sitting above the
        page at `z-header`, and a transparent box is still a hit target: every
        click between the islands was landing on the header and going nowhere.
        That is invisible until a page docks a control into the middle of the
        band — the practice player, the catalogue's search field — at which
        point none of its buttons can be pressed.

        The islands take their clicks back through `pill` above.
      */}
          <header className="pointer-events-none sticky top-0 z-30 w-full px-4 pt-3 sm:px-6 lg:px-8">
            {/* Three islands on one rail. The rail is wider than the content at the
            top and snaps to the container width once scrolled. */}
            <div
              className={cn(
                "mx-auto grid w-full grid-cols-[1fr_auto_1fr] items-center gap-3 transition-[max-width] duration-300",
                scrolled ? "max-w-7xl" : "max-w-[85rem]",
              )}
            >
              {/* Brand — the "voocab" wordmark is the Home link.

              Given up entirely in task mode. A paper that fills the window
              has one thing worth putting where the reader's eye already
              goes for "out of here", and it is the way out of the paper —
              not the way to the home page. */}
              <div className={cn(pill, "gap-2 justify-self-start")}>
                {task.active ? (
                  <div
                    ref={task.value.binds.left}
                    className="flex items-center"
                  />
                ) : (
                  <NavLink to="/" className="group flex items-center gap-2">
                    <Logo animate="hover" className="size-6" />
                    <span className="text-base font-semibold text-foreground">
                      voocab
                    </span>
                  </NavLink>
                )}
              </div>

              {/* Primary nav, centered. Active item gets a soft glass chip.

              It gives way when a page has something arriving in the middle —
              lifting out through the top of the header, which is the only
              direction that reads as being pushed rather than as blinking
              out. Moved rather than unmounted: it has to come back down when
              the page lets go, and something that was removed can't. */}
              {/* The middle island is the page's tools in task mode, and the
              app's navigation otherwise. Not the nav hiding and something
              else landing on top of it — that is `header-center`, and it is
              for a control that TRAVELS. This one is simply a different
              island for as long as the paper is open. */}
              {task.active ? (
                <div
                  ref={task.value.binds.centre}
                  className={cn(
                    pill,
                    "hidden gap-1 px-2 justify-self-center md:flex",
                  )}
                />
              ) : (
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
                    centre.claimed &&
                      "pointer-events-none -translate-y-8 opacity-0",
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
              )}

              {/* Actions.

              One trigger, not two. The theme used to sit out here beside the
              account and the pair of them made this island wide enough to
              crowd the middle of the bar — which is where pages dock the
              control they are actually working with. It has moved inside the
              account menu; a visitor with no account menu still gets it, as
              an icon. */}
              <div className={cn(pill, "gap-2 justify-self-end")}>
                {/* Whatever the page is counting, to the LEFT of the account —
                the middle island is spoken for by the tools, and a clock
                belongs next to the thing it is about to interrupt rather
                than among the controls it is not part of. */}
                {/* `empty:hidden`, or the island keeps the parent's `gap-2`
                for a slot with nothing in it — which is how the account
                menu ended up sitting eight pixels off the right edge of
                its own pill on every task page that fills the other two
                islands and not this one. */}
                {task.active && (
                  <div
                    ref={task.value.binds.right}
                    className="flex items-center empty:hidden"
                  />
                )}
                {/* Reflect session: signed-in users get an account menu, everyone
                else a Sign in button. `isLoading` avoids a flash of the wrong
                one on first paint. */}
                {isLoading ? (
                  <div className="size-7 animate-pulse rounded-full bg-foreground/10" />
                ) : user ? (
                  <UserMenu user={user} />
                ) : (
                  <>
                    <ThemeSwitcher />
                    <NavLink
                      to="/login"
                      className="rounded-full bg-linear-to-b from-primary to-primary/80 px-4 py-1.5 text-sm font-medium text-primary-foreground shadow-[0_0_24px_-6px_var(--primary)] transition-shadow hover:shadow-[0_0_28px_-4px_var(--primary)] focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                    >
                      Sign in
                    </NavLink>
                  </>
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
          <Footer />
        </div>
      </HeaderTaskProvider>
    </HeaderCentreProvider>
  );
}

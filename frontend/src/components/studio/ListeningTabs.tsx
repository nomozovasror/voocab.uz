import { useLayoutEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { cn } from "@/lib/utils";
import { useStudioListening } from "@/features/studio/queries";
import { useMyCollections } from "@/features/listening/queries";

/**
 * The listening studio's own header: one title, one line of totals, and the
 * two halves of authoring as tabs.
 *
 * Materials and collections were two pages that only knew about each other
 * through a sentence of prose ("your listening materials · collections"). A
 * link inside a paragraph is not somewhere anybody looks for the other half
 * of what they are doing — and the studio's chrome is a breadcrumb trail
 * rather than a nav, so that sentence was the only route in. Two tabs say
 * both halves exist before either is opened.
 *
 * **One control, not two buttons.** The two labels sit in a single sunken
 * track with a lit pill under whichever is current, and the pill TRAVELS
 * between them. Two separate pills, one of them shaded, is a pair of buttons
 * where one happens to be on; a pill that moves is one switch with two
 * positions — which is what this is, and it also says, in the fifth of a
 * second it takes to slide, that these two views are the same page.
 *
 * The pill is **measured, not written down** (unlike the take screen's
 * player, where the geometry is fixed because it is read mid-transition).
 * Here the two widths depend on the labels AND on counts that arrive later:
 * `Collections 12` is wider than `Collections`, and a hard-coded track would
 * be wrong the first time somebody made a twelfth. A ResizeObserver keeps it
 * honest through the count landing, a font loading and the window changing.
 *
 * **They stay two routes.** The tab is a link, not a piece of local state:
 * an author deep in a collection wants to send somebody the address of it,
 * and the back button has to mean what it means everywhere else. What is
 * shared is this header, so the two pages cannot drift into looking like two
 * different features.
 *
 * **Both counts are always shown, on both tabs**, and they are the page's
 * only totals. A count that appears only once you are on the tab makes the
 * tab a door with nothing written on it — and the number is the thing an
 * author is deciding on. They are withheld while loading rather than drawn
 * as 0: the studio's rule everywhere is that a fabricated zero is worse than
 * a missing figure.
 */
export type StudioListeningTab = "materials" | "collections";

const TABS: Array<{ id: StudioListeningTab; label: string; to: string }> = [
  { id: "materials", label: "Materials", to: "/studio/listening" },
  { id: "collections", label: "Collections", to: "/studio/collections" },
];

export function StudioListeningHeader({
  active,
}: {
  active: StudioListeningTab;
}) {
  // Cached queries, both of which the page under this header is likely to be
  // using anyway — so the second tab's count costs one small request once per
  // visit and nothing after it.
  const materials = useStudioListening();
  const collections = useMyCollections();

  const counts: Record<StudioListeningTab, number | null> = {
    materials: materials.data?.total ?? null,
    collections: collections.data?.length ?? null,
  };

  // Where the lit pill sits. Null until the first measure, and the pill is
  // invisible until then — a pill that animates in from zero width on the
  // first paint is a control introducing itself, which is not what a tab bar
  // is for.
  const trackRef = useRef<HTMLDivElement>(null);
  const tabRefs = useRef<Partial<Record<StudioListeningTab, HTMLAnchorElement>>>(
    {},
  );
  const [pill, setPill] = useState<{ x: number; w: number } | null>(null);

  useLayoutEffect(() => {
    const track = trackRef.current;
    const tab = tabRefs.current[active];
    if (!track || !tab) return;

    const measure = () => {
      const a = tab.getBoundingClientRect();
      const b = track.getBoundingClientRect();
      setPill({ x: a.left - b.left, w: a.width });
    };
    measure();

    // The labels change width when the counts land, and again when the font
    // does. Measuring once would leave the pill under where the tab used to
    // be, which is worse than not having one.
    const observer = new ResizeObserver(measure);
    observer.observe(track);
    observer.observe(tab);
    return () => observer.disconnect();
  }, [active, counts.materials, counts.collections]);

  return (
    // One row, held apart: the page's name at one end and the two halves of
    // it at the other. There is no third thing in it — a line of totals used
    // to sit here and it was printing the numbers the tabs already carry,
    // which is the same fact twice and one of them always slightly stale.
    <div className="mb-6 flex flex-wrap items-center justify-between gap-x-4 gap-y-3">
      <h1 className="text-2xl font-medium tracking-wide text-foreground">
        Listening
      </h1>

      <nav aria-label="Listening studio">
        <div
          ref={trackRef}
          className="relative flex rounded-full bg-surface-sunken p-1"
        >
          {/* Under the labels, never over them: it is the ground the current
              one stands on. Transform and width only — both composited, and
              neither re-lays-out the page behind a control that sits above
              a shelf. */}
          <span
            aria-hidden
            className={cn(
              "absolute top-1 bottom-1 left-0 rounded-full bg-primary/15",
              "transition-[transform,width,opacity] duration-base ease-out motion-reduce:transition-none",
              pill ? "opacity-100" : "opacity-0",
            )}
            style={{
              transform: `translateX(${pill?.x ?? 0}px)`,
              width: pill?.w ?? 0,
            }}
          />

          {TABS.map((tab) => {
            const count = counts[tab.id];
            const current = active === tab.id;
            return (
              <NavLink
                key={tab.id}
                to={tab.to}
                ref={(el) => {
                  if (el) tabRefs.current[tab.id] = el;
                  else delete tabRefs.current[tab.id];
                }}
                aria-current={current ? "page" : undefined}
                className={cn(
                  "relative rounded-full px-4 py-1.5 text-xs whitespace-nowrap",
                  "transition-colors duration-base",
                  "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                  current
                    ? "text-primary"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {tab.label}
                {count != null && (
                  <span className="ml-2 tabular-nums opacity-60">{count}</span>
                )}
              </NavLink>
            );
          })}
        </div>
      </nav>
    </div>
  );
}

/**
 * The frame both tabs live in — a layout route, and that is the point.
 *
 * The header used to be rendered by each page, which meant crossing between
 * them destroyed one copy and built another: the lit pill could only fade in
 * at its new position, and a pill that teleports is two buttons again. Owned
 * by a route ABOVE both pages, it is one element that survives the
 * navigation, so the pill slides while the panel under it changes — which is
 * the whole claim these two tabs make, that this is one page with two views.
 *
 * Only the two list routes are inside it. An editor is not a view of this
 * page — it is somewhere you went from it — and a tab bar over it would
 * offer to switch away from unsaved work.
 */
export function StudioListeningTabsLayout() {
  const { pathname } = useLocation();
  const active: StudioListeningTab = pathname.startsWith("/studio/collections")
    ? "collections"
    : "materials";

  return (
    <div className="mx-auto w-full max-w-[56.25rem] font-mono">
      <StudioListeningHeader active={active} />
      <Outlet />
    </div>
  );
}

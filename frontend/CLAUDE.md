# Frontend conventions

Feature-specific rules live nearer the code:
`src/features/listening/`, `src/pages/listening/`, `src/pages/studio/`,
`src/components/layout/` each carry their own `CLAUDE.md`.

## Preferences default to off

`src/lib/preferences.ts` holds the reader's small on/off choices, in
`localStorage` beside the theme — these are about this browser, not the
account, and none is worth a column, a migration and a round trip.

**Every one defaults to off.** A preference exists because somebody wanted
the behaviour; one that is on before anybody asked is not a preference, it is
a behaviour with a switch attached. `hoverPreview` (`voocab-hover-preview`)
is the first: with it off the practice page's cards stay on the reader's own
statistics and the list is a list.

Wire a preference by *withholding the handler*, not by checking the flag
inside it — `onPreview={followList ? showPreview : undefined}` — so there is
no path left by which the behaviour can happen while the preference is off.

The settings page that turns these on is not built yet. Flip one by hand:
`localStorage.setItem("voocab-hover-preview", "on")`.

## Loading states

Three of the four pieces are structural and need no remembering:

- **Route progress** — `<RouteProgress/>` sits in both layouts, so every
  route present and future is covered. Route-level `lazy:` leaves the old
  page on screen while the next chunk downloads; this is the only thing that
  says so.
- **`HydrateFallback`** — comes from the `page()` helper in
  `src/app/router.tsx`. `lazy:` appears exactly once in the codebase, inside
  that helper. **Register new routes with `...page(() => import(...))`**;
  writing `lazy:` by hand loses the fallback and a cold load renders a blank
  page, header included.
- **Reduced motion** — one global rule in `globals.css` disables
  `animate-pulse`, so any new skeleton inherits it.

The fourth is a habit. When a page-level wait deserves a skeleton:

- **Build it from the real component's class strings, never from measured
  pixels.** That is the only way the two can't drift, and how the non-obvious
  mismatches get caught — the audio control's track is a 24px line box rather
  than the 4px bar it looks like, because the range input is `inline-block`
  on a text baseline.
- **Put a bar that stands in for TEXT inside the real element** (`<h1>`,
  `<p>`) as `inline-block h-[0.8em]`, so the element's own line-height sets
  the row. A block bar in an `items-baseline` row has no baseline and drags
  the row out.
- **No `loader-deferred`** on skeletons, unlike every other loader here. That
  delay exists because `LogoLoader` *replaces* the page and has a reflow to
  hide; a shape-matched skeleton has none, and over a 300ms wait a 250ms
  delay plus a 200ms fade is a blank page with extra steps.
- **Measure it in the browser** — skeleton and loaded, same `top` and same
  `height`. Reasoning about heights is how you end up 6px out per row.
- Reserve space for controls that don't depend on the data but live inside
  the loaded branch, or they shove everything sideways when they appear.

`PageLoader` (the brand mark) is still right where there is no shape to
match: `RequireAuth` guards *any* route, so it cannot know what it is waiting
for, and the two `<Suspense>` fallbacks are boundaries of last resort that
never fire for route-level `lazy:`.

Reference implementations:
`src/features/listening/components/PaperSkeleton.tsx` and `DashboardSkeleton`
in `src/pages/studio/StudioDashboardPage.tsx`.

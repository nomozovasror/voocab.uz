# The header

## Nothing shows through it, and nothing else goes in it

The header is three floating islands with gaps between them, and page content
scrolling up passes through those gaps half-drawn. The fix is
`HeaderGround.tsx`: a **fixed, empty, 60px band** in the page's own colour,
rendered by the page.

**Solid, not a pane**, and this was got wrong once: frosting the whole band
turned three floating islands into one continuous bar and took the design's
language with it. The band is not a surface — it is the page, stopping.

**The glass belongs to whatever docks in it, and the ground makes room for
it.** Frosted glass over an opaque colour is an opaque colour, so a docked
control that wants to be glass gets a window: the ground stops short on both
sides of it and the paper shows through, with the pane covering the window by
about twelve pixels all round so nothing is exposed at the edges or under its
rounded corners. `HeaderGround` takes that window as an `opening`; zero
without one, which is every page but the one that docks.

Fixed because it holds no content and should hold no space — 60px is the
header's own height, which at rest the header already occupies in the flow.
It is per page rather than in `Layout` only because the home page paints a
star field behind everything and a pane across the top would frost the stars.

**The band is not somewhere a page puts things.** It is already contested by
the brand island, the account island, the app's nav, and — on the take screen
— the player that docks into the middle. At 1024px that leaves about 680px
between the two islands, and the docked player takes 448 of it. A page that
also pinned its own title row across the same band runs the title under one
pill and its counter under the other. The take screen did exactly that, and
the answer was not to shuffle it sideways: the title row went back into the
flow and scrolls away, and the one figure that had to survive — how much is
answered — moved to the strip along the bottom, beside the squares it
summarises.

**One trigger per island.** The theme used to be a second control beside the
account menu, and between them the right island was wide enough that the
docked player had to overlap it to get a usable width. It now lives in the
account menu as a submenu (`ThemeSwitcher.tsx`); a signed-out visitor, who
has no account menu, still gets it as an icon. The account name waits for
`lg` for the same reason. What is protected is not tidiness — it is the
middle of the bar, where the control someone is working with goes.

**The header does not take clicks; its islands do.** `<header>` is a
full-width box sixty pixels tall at `z-header`, and a transparent box is
still a hit target — every click between the islands was landing on it and
going nowhere, and once a page docked a control into the band none of that
control's buttons could be pressed. So the header is `pointer-events-none`
and the `pill` class puts it back, which is also what makes a fourth island
impossible to add and forget.

A page that docks a control into the header's middle claims it with
`useClaimHeaderCentre` and lets `position: sticky` carry the control there —
nothing is re-parented, because an element that is re-parented *arrives*, and
arriving is a cut. Such a control takes `z-sticky` like the ground and wins
on document order, being inside `<main>` and therefore later.

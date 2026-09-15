# The listening studio

## One page with two tabs

`/studio/listening` and `/studio/collections` are two routes sharing a header
(`components/studio/ListeningTabs.tsx`): `Listening` at one end of one row,
the two halves of authoring as tabs at the other. The tabs are IN that row
rather than under it — a row of pills on its own line reads as a filter over
the page below, which is the one thing they are not — and held to the far
edge, because against the title they read as part of it.

**One control, not two buttons.** The two labels sit in a single sunken track
with a lit pill under whichever is current, and the pill TRAVELS between
them. Two separate pills, one of them shaded, is a pair of buttons where one
happens to be on; a pill that moves is one switch with two positions.

- **The header is a layout route** (`StudioListeningTabsLayout`), not a
  component each page renders. That is what makes the slide possible at all:
  rendered per page, the bar was destroyed and rebuilt on every crossing, so
  the pill could only fade in at its new position — and a pill that
  teleports is two buttons again. Only the two list routes are inside it; an
  editor is not a view of this page.
- The pill is **measured, not written down** (unlike the take screen's
  player, whose geometry is fixed because it is read mid-transition). The
  widths depend on the labels AND on counts that arrive later — `Collections
  12` is wider than `Collections` — so a ResizeObserver keeps it honest
  through the count landing, a font loading and the window changing. It is
  invisible until the first measure: a pill animating in from zero width is a
  control introducing itself.
- **Only the panel animates on a crossing** (`.studio-panel` in
  `globals.css`): entrance only, six pixels and a fifth of a second. The
  header must not be inside it, or the entrance would drag the sliding pill
  along with it. There is no exit — the outgoing panel is gone the instant
  React swaps the route, and keeping the old tree alive for a frame nobody
  would see is a lot of machinery for nothing.

**The counts on the tabs are the page's only totals.** A line of them used to
sit at the end of the header (`2 collections · 0 materials`), printing the
same numbers the tabs carry, in a second place that could disagree with the
first.

- **They stay two routes.** The tab is a link, not local state — an author
  deep in a collection sends somebody its address, and the back button has to
  mean what it means everywhere else. What is shared is the header, so the
  two pages cannot drift into looking like two features.
- **Both counts show on both tabs**, and are withheld rather than drawn as 0
  while loading. A door with nothing written on it is not a tab.
- The tabs replaced a sentence of prose (`your listening materials ·
  collections`). A link inside a paragraph is not where anybody looks for the
  other half of what they are doing, and the studio's chrome is a breadcrumb
  trail rather than a nav — so that sentence was the only route in.
- The trail follows the hierarchy the tabs claim: `studio / listening /
  collections / <title>`. A crumb landing somewhere the header does not admit
  exists is worse than no crumb.

## The author's collections are a shelf, not a list

They are already books to a learner (`CollectionCover` is shared, so there is
one implementation of one cover), and an author who lays out a course as rows
and then meets it as a shelf has to learn the same shelf twice.

- **A card is the cover and nothing else.** Every card is then exactly one
  portrait rectangle, so rows are level with nothing measured, clamped or
  reserved. The strip of meta that used to sit underneath repeated the title
  off the cover, wrapped its count onto a second line in a narrow column, and
  carried a publishing warning that made one card taller than its neighbours.
- The cover carries the title at the top and **one line across the foot** —
  how much is in it on the left, whether it is out on the right, on the
  title's own left margin. `Empty` rather than `0 materials`: a zero beside a
  word is a measurement, and this is a state to act on.
- **That foot line is what fixes the column count at four.** It has to hold a
  count and a plate side by side on one row, and at five across a 900px page
  the line is wider than the book: `2 materials` wrapped onto two rows and
  took the count off the plate's baseline, which is the foot no longer being
  a line at all. The type is a notch down from the body size and the count
  truncates rather than wraps — a clipped word is the lesser of the two, and
  the number is read first anyway. A column width here is a constraint on
  the type, not a free choice.
- **No byline.** In the studio the author is always the same person, so a
  name would be the same word on every book. The learner's shelf keeps its
  byline, where it distinguishes.
- The status plate is **half-transparent black** (`COVER_INK.plate`), not a
  colour of its own: the stock under it is one of thirteen hues, and a fixed
  background would have to be chosen against each — darkening whatever is
  there reads on all thirteen and survives a fourteenth. `Draft` prints amber
  rather than the accent, because the accent is purple under Dracula, where
  "your move" would stop being the colour that means it.
- **Nothing on the shelf is an instruction.** The server's `blocker`, and the
  count of items a learner cannot see yet, are things to ACT on, so they live
  on the collection's own page beside the Publish button that acts on them.
- **Naming is asked for in a dialog** (`NewCollectionDialog`); creating one
  takes a title and nothing else — a create form demanding the contents up
  front is a form nobody could fill in. One field is not a page, and not a
  book either: in a book-width column the title does not fit, and the tile would
  have to stop being a book to hold it. Once named the author is put straight
  into the collection, because naming a course is not what they came to do.
- The new-collection tile is **first on the shelf**, keeping the shelf's
  ratio. The gap where the next book goes is where the author's eye already
  is, and a create control above a shelf that grows walks off the page.

## The collection editor is two panes

`collections/StudioCollectionEditorPage.tsx`. What is in the course and what
could go in it are one decision, made by comparing them — and stacked, which
is how this page began, the comparison is a scroll: an author adding the
fourth paper cannot see the three they already chose. Side by side, the gap
between the panes is the point.

- **The picker keeps its own scroll** (`PICKER_H`, 25rem), dressed in
  `scrollbar-quiet` — the app's own treatment for a kept native scroll,
  already on the audio editor and the listening sidebar. Invisible at rest,
  there when reached for, and the gutter reserved either way so arriving at
  it never reflows the rows. A library of two hundred must never make the
  page taller than the screen, or the collection is left alone at the top of
  a very tall column.
- **The chips are the catalogue's `scope`**, which already means "a material
  holding that part" in SQL — so they narrow the QUERY, not the page. There
  is deliberately no "not added" chip beside them: membership here is local
  and unsaved, so filtering by it would empty pages the server still counts
  as full. A row already in the collection says so on its own button, and
  stays visible while it says it — a list that removes what you just clicked
  makes the next click land on something else.
- **Dragging is the gesture for an order**, because a sequence is a spatial
  idea and arrow buttons make it arithmetic. The reorder happens on hover,
  not on drop: the list under the cursor is the list being made. The handle
  is a BUTTON and the arrow keys move the row it holds — drag alone is a
  reorder nobody without a mouse can do, on the one control here where
  position is the whole point.
- **The cover IS the header** (`CollectionBanner`), not an illustration in
  it. As a 104px thumbnail beside the title the two never agreed: a portrait
  book is 144px tall and a title with a line under it is about fifty, so the
  row was a tall thing next to a short thing with air either side of both —
  and shrinking the book to match makes it a swatch, since a cover is
  recognised by its colour and its pattern. A full-width band at 150px keeps
  both: the author knows the course before they read the name, and the name,
  the state and the controls are printed on it, which is where a book's
  title is anyway.
- **The pattern is the book's own, TILED** — a row of SVGs each at
  `aspect-[156/214]`, full height, clipped by the band. It was stretched
  first (`preserveAspectRatio="none"`) and a non-uniform scale is exactly
  what a circle cannot survive: the dots came out flat ellipses and the arcs
  squashed ovals, which is a different pattern wearing the same name.
  Tiling repeats the figure at the book's own ratio, so a circle stays a
  circle. No measuring — the aspect ratio does the arithmetic and a fixed
  count wide enough for the widest band means the extras are simply cut off;
  each SVG clips its own overflow, so nothing bleeds between tiles. Still
  the book's figures, never a second set cut for a landscape box: that is
  eight more ways for a cover to come out wrong, and the two sets would
  drift the first time either was touched.
- **The pattern is quieter on the band than on the book**
  (`PATTERN_OPACITY`), and that is the whole of what makes a header readable
  on it. A pattern is one step lighter than its stock by design, so a line
  of type crossing a band or a wave loses exactly the letters that land on
  it. A scrim over the art was tried first and it worked by making the band
  DARK — the colour went with it, and the colour is the recognition. Fading
  the figure leaves the stock at full strength: same book, same hue, a
  texture rather than a picture, which is all a background has to be. The
  opacity is on the figure alone and never on the stock.
- **Controls on the cover are half-transparent black** (`COVER_INK.action`),
  the same argument as the status plate: thirteen stocks, and a button with
  a colour of its own would have to be chosen against each. Live `Publish`
  is a fixed amber rather than `--primary`, which is purple under Dracula —
  a button on a surface that never follows the theme cannot be the one thing
  on it that does.
- **Nothing on the band is an instruction.** The band says what IS — name,
  size, runtime, state, when it was saved. What has to be DONE about it, the
  blocker or the drafts a learner cannot see, is a line under the band, and
  only when there is something to say.
- **`↻ Cover` writes a new `cover_seed`** and the book changes on the shelf,
  in here, and on the learner's page at once. It is the only thing about a
  collection's cover an author can change, and it exists because a generated
  cover nobody chose can still be one nobody wants.

**Everything saves itself, and one line under the title says so.** Title and
summary on blur; the order a beat (700ms) after the last move. It was an
explicit `Save order` button, on the argument that a save per move would
publish half-finished sequences to anybody reading — the debounce answers
that, and an editor where one of three things must be saved by hand is an
editor that loses work.

- The debounce depends on the STABLE halves of the query objects
  (`mutation.mutate`, `query.refetch`). Depending on the objects re-arms the
  timer on every unrelated re-render, which is a debounce that can be starved
  into never firing.
- The last payload sent is remembered, so a server that returns a different
  list than it was sent — it drops duplicates and anything deleted since —
  cannot leave the page dirty and loop.
- **A save that WITHDRAWS the collection still speaks.** Emptying a published
  one un-publishes it, and a flag that changes itself quietly is a flag the
  author hears about from a learner.
- The save line is under the FIELDS it describes and nowhere near the panes:
  over a column of rows it reads as being about the rows. Its row is held
  open when empty, or the first save would push both panes down.
- **Delete moved into the `⋯` menu.** A destructive control beside Publish is
  a destructive control at arm's length from the one an author presses on
  purpose.

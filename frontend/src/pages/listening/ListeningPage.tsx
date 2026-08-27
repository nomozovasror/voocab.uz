import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Headphones } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useClaimHeaderCentre } from "@/components/layout/header-center";
import { useDebounced } from "@/hooks/use-debounced";
import { PREFERENCES, usePreference } from "@/lib/preferences";
import { useMediaQuery } from "@/hooks/use-media-query";
import { useRevealOnScroll } from "@/hooks/use-reveal-on-scroll";
import { SkeletonBlock } from "@/components/ui/skeleton";
import { getErrorMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  PRACTICE_PAGE,
  useCollections,
  useNextUp,
  usePracticeCatalogue,
  usePracticeStats,
} from "@/features/listening/queries";
import {
  DIFFICULTY_LABEL,
  DIFFICULTY_ORDER,
  EMPTY_FILTERS,
  QUESTION_TYPE_ORDER,
  catalogueParams,
  filterOptions,
  isNarrowed,
  toggle,
} from "@/features/listening/practice";
import type {
  CourseCovers,
  CourseLength,
  CourseStatus,
  ListMode,
  PracticeFilterState,
  Scope,
  SortKey,
} from "@/features/listening/practice";
import type {
  DifficultyBand,
  QuestionGroupType,
} from "@/features/listening/types";
import { QUESTION_TYPE_LABEL } from "@/features/listening/parts";
import {
  FilterChips,
  ListHeader,
  SearchField,
} from "@/features/listening/components/PracticeControls";
import {
  PracticeRow,
  PracticeRowSkeleton,
} from "@/features/listening/components/PracticeRow";
import { PracticeAside } from "@/features/listening/components/PracticeAside";
import {
  NextUp,
  NextUpSkeleton,
} from "@/features/listening/components/NextUp";
import { CollectionList } from "@/features/listening/components/CollectionList";

/** How long the pointer has to rest on a row before the cards answer it, and
 *  how long they wait before turning back once it leaves. Module constants so
 *  the callbacks that read them can have empty dependency lists and mean it.
 *
 *  300ms is long enough that a pointer travelling down the page — or crossing
 *  the list on its way somewhere else entirely — never sets the cards going,
 *  and short enough that stopping on a row still feels like it was noticed.
 *  Deliberately far longer than the 120 on the way out: arriving is a question
 *  the reader might not be asking, leaving is one they have already answered. */
const HOVER_IN = 300;
const HOVER_OUT = 120;

/** How long the search field waits for the typing to stop before it asks the
 *  server. Long enough to swallow the gaps inside a word, short enough that
 *  finishing one and looking up finds the answer already there. */
const SEARCH_SETTLE = 250;

/** Air above and below the statistics column: between it and the underside
 *  of the controls it hangs from, and between its own bottom and the bottom
 *  of the window. Module constants so the effect that reads them can have an
 *  honest dependency list. */
const PANEL_GAP = 8;
const BOTTOM_GAP = 16;

/**
 * What there is to practise, and where the reader is weak.
 *
 * Two columns, and the split is the argument: the list is the page, and the
 * panel beside it exists to make one choice in that list better. It leads
 * with the single sentence a learner can act on ("Part 3, 58%") and carries
 * the button that acts on it; everything under that is the working.
 *
 * The row used to answer "how long is it and did I do it". It now answers
 * "and is it hard" — measured over everybody's answers rather than declared
 * by whoever wrote it (app/services/difficulty.py). That number is the whole
 * reason the page can be browsed rather than scrolled.
 *
 * Nothing here fabricates a figure. A material nobody has answered enough of
 * is `New` and not "50%", a part the reader has barely touched draws a dash
 * and not a zero, and a learner with no history at all gets a sentence about
 * where to start instead of a panel of noughts.
 */
export default function ListeningPage() {
  const stats = usePracticeStats();
  const nextUp = useNextUp();

  // One value rather than a useState per control: every one of them narrows
  // the same list, "clear filters" has to put all of them back at once, and
  // the panel beside the list reaches in to set the scope. A setter each would
  // be one more place for those to drift every time a filter is added — which
  // is exactly what happened when type and difficulty arrived.
  const [filters, setFilters] = useState<PracticeFilterState>(EMPTY_FILTERS);
  // Order is not a filter — it changes what the list looks like, not what is
  // in it — so it is its own state and "Clear filters" leaves it alone. A
  // reader who asked for easiest-first did not ask for that to be undone by
  // dropping a part chip.
  const [sort, setSort] = useState<SortKey>("newest");
  // Which of the two lists is showing. Not part of `filters`, because it does
  // not narrow a list — it changes which list there is, and "Clear filters"
  // has no business putting somebody back on the other one.
  const [mode, setMode] = useState<ListMode>("materials");
  // The courses list's own filter. Its own state rather than a field on
  // `filters` for the same reason `mode` is: "Clear filters" belongs to the
  // catalogue, and it has no business reaching into the other list.
  const [status, setStatus] = useState<CourseStatus>("all");
  const [covers, setCovers] = useState<CourseCovers>("all");
  const [length, setLength] = useState<CourseLength>("all");
  const change = useCallback(
    (next: Partial<PracticeFilterState>) =>
      setFilters((prev) => ({ ...prev, ...next })),
    [],
  );
  // The two multi-selects flip a value inside the updater, where `prev` is
  // the current list. Written as `toggle(filters.bands, band)` at the call
  // site it read the array off the render that drew the chip, so two clicks
  // in one batch both started from the same list and the first was dropped —
  // which is exactly what selecting Easy and New in quick succession did.
  const toggleBand = useCallback(
    (band: DifficultyBand) =>
      setFilters((prev) => ({ ...prev, bands: toggle(prev.bands, band) })),
    [],
  );
  const toggleType = useCallback(
    (type: QuestionGroupType) =>
      setFilters((prev) => ({ ...prev, types: toggle(prev.types, type) })),
    [],
  );
  const clearFilters = () => setFilters(EMPTY_FILTERS);
  const setScope = useCallback(
    (scope: Scope) => change({ scope }),
    [change],
  );

  // The controls, as a query. Everything below reads a PAGE of an answer the
  // server worked out — which is the whole of what changed here: filtering a
  // list of thirty is filtering thirty rows out of a thousand.
  //
  // The typed query is held back and the rest is not, and the asymmetry is
  // the point: a chip is one decision and deserves an immediate answer,
  // while "riverside" typed at speed is nine, eight of them questions nobody
  // finished asking. The field itself still shows every keystroke — it reads
  // `filters.query`, not this.
  const settledQuery = useDebounced(filters.query, SEARCH_SETTLE);
  const params = useMemo(
    () => catalogueParams({ ...filters, query: settledQuery }, sort),
    [filters, settledQuery, sort],
  );
  // The same query the courses list itself runs, built the same way so the
  // two share one cache entry rather than fetching twice. This copy exists
  // for what the list cannot hand upwards: the filter row's facet counts and
  // the search field's count, both of which live above it.
  const collectionParams = useMemo(() => {
    if (mode !== "courses") return {};
    const next: Record<string, string> = {};
    if (settledQuery.trim()) next.q = settledQuery.trim();
    if (status !== "all") next.status = status;
    if (covers !== "all") next.covers = covers;
    if (length !== "all") next.length = length;
    return next;
  }, [mode, settledQuery, status, covers, length]);
  const collections = useCollections(collectionParams, {
    enabled: mode === "courses",
  });

  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isPlaceholderData,
  } = usePracticeCatalogue(params);

  // Every page so far, flattened. The pages are the cache's business and the
  // list's business is rows.
  const visible = useMemo(
    () => data?.pages.flatMap((page) => page.items) ?? [],
    [data],
  );
  // What the courses list found, for the field's own announcement. That list
  // holds its own rows; this page only needs the number.
  const coursesTotal = collections.data?.pages[0]?.total ?? 0;
  // Off the first page, because every page carries the same answer: these
  // describe the library, not what came back.
  const head = data?.pages[0];
  const total = head?.total ?? 0;
  const hiddenDone = head?.done_hidden ?? 0;
  const typeOptions = useMemo(
    () =>
      filterOptions(
        head?.types ?? [],
        QUESTION_TYPE_ORDER,
        QUESTION_TYPE_LABEL,
      ),
    [head],
  );
  const bandOptions = useMemo(
    () => filterOptions(head?.bands ?? [], DIFFICULTY_ORDER, DIFFICULTY_LABEL),
    [head],
  );

  const narrowed = isNarrowed(filters);
  // Whether the list on screen — whichever one it is — has been narrowed. The
  // two modes have different filters, and the suggestion block is gated on
  // this in both: it answers "what should I do", and a filter is somebody
  // saying what they want to do.
  const listNarrowed =
    mode === "courses"
      ? filters.query.trim() !== "" ||
        status !== "all" ||
        covers !== "all" ||
        length !== "all"
      : narrowed;

  // --- The field's journey to the header -----------------------------------
  //
  // One element, and it travels: `position: sticky` carries it up the page
  // under its own steam and stops it at the same height as the header's
  // islands. Nothing is re-parented and nothing is duplicated — a copy
  // appearing where another disappears is a cut, and a cut is what this
  // looked like before.
  //
  // All that is left to JS is noticing the moment it lands, so it can put on
  // the island's frosted dress and tell the header's nav to get out of the
  // way. A zero-height sentinel immediately above it is what says so: once
  // that has passed under the header's top edge, the field below it has
  // nowhere further to rise.
  const landingMark = useRef<HTMLDivElement | null>(null);
  // One moment, not two: the field reaching the underside of the header.
  //
  // Everything happens from there — the nav starts lifting out, and the field
  // starts narrowing and frosting — so the last stretch of the climb and the
  // change of dress overlap instead of queueing. Told to shrink only once it
  // had stopped, it travelled, halted, and *then* changed, which is three
  // events where there should be one movement.
  const [docked, setDocked] = useState(false);
  // Only where there is a middle to land in. Below `md` the nav is hidden and
  // the two remaining pills leave no room between them, so the field scrolls
  // away with the rest of the page.
  const hasIsland = useMediaQuery("(min-width: 48rem)");
  const inHeader = docked && hasIsland;

  useEffect(() => {
    const mark = landingMark.current;
    if (!mark || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      ([entry]) => setDocked(!entry.isIntersecting),
      // The controls pin when this mark reaches the top of the window, so
      // firing 48px before that is what makes the change of dress overlap
      // with the last of the climb rather than queue behind it.
      { threshold: 0, rootMargin: "-48px 0px 0px 0px" },
    );
    observer.observe(mark);
    return () => observer.disconnect();
  }, []);

  useClaimHeaderCentre(inHeader);

  // Roving focus down the list. Real DOM focus moves rather than a highlight
  // being drawn, so a screen reader reads the row it lands on and Enter is
  // the link's own Enter — nothing here reimplements activation.
  const rowRefs = useRef<Array<HTMLAnchorElement | null>>([]);
  const focusRow = useCallback((i: number) => {
    const rows = rowRefs.current.filter(Boolean);
    if (rows.length === 0) return;
    const clamped = Math.max(0, Math.min(i, rows.length - 1));
    rows[clamped]?.focus();
  }, []);

  const onListKeyDown = (e: React.KeyboardEvent<HTMLOListElement>) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const rows = rowRefs.current.filter(Boolean);
    const at = rows.indexOf(document.activeElement as HTMLAnchorElement);
    if (at === -1) return;
    e.preventDefault();
    focusRow(at + (e.key === "ArrowDown" ? 1 : -1));
  };

  // The row the reader is pointing at — or has arrow-keyed onto, which is the
  // same question asked with a keyboard. Held here rather than in the aside
  // because the rows report it and the aside reads it, and the two are on
  // opposite sides of the page.
  //
  // The id rather than the material: the catalogue refetches, and a held
  // object would go on describing a row that had since changed.
  // Whether the cards follow the list at all. Off unless the reader has
  // asked for it: the swap answers real questions without a click, and it is
  // also movement at the edge of vision every time the pointer crosses the
  // list on its way somewhere else. Which of those it is depends on the
  // person, and a thing that moves without being asked defaults to not.
  //
  // Off, `onPreview` is simply not handed to the rows — one branch rather
  // than a check in each of the four places a preview can start, so there is
  // no path by which the panel can move while this is off.
  const [followList] = usePreference(PREFERENCES.hoverPreview);

  const [previewId, setPreviewId] = useState<string | null>(null);
  const preview = useMemo(
    () => visible.find((m) => m.id === previewId) ?? null,
    [visible, previewId],
  );

  // Both edges of the hover are on a timer, and each delay is doing a
  // different job.
  //
  // Arriving: the card waits before it turns. A pointer on its way down the
  // page crosses four rows to get to the fifth, and a card that answered each
  // of them would be four flashes of something nobody asked about. The wait
  // is what makes the change a reply to a question rather than a reflex.
  //
  // Leaving: the card waits before it turns back. It carries links, and the
  // only way to reach one is to move the pointer off the row and across to
  // the card — cleared on the spot, it would swap back to the statistics
  // while the pointer was still travelling, and every link in it would be
  // decoration.
  const handover = useRef<number | undefined>(undefined);
  const holdPreview = useCallback(() => {
    window.clearTimeout(handover.current);
  }, []);
  const showPreview = useCallback((id: string | null) => {
    window.clearTimeout(handover.current);
    handover.current = window.setTimeout(() => setPreviewId(id), HOVER_IN);
  }, []);
  const releasePreview = useCallback((delay = 0) => {
    window.clearTimeout(handover.current);
    handover.current = window.setTimeout(() => setPreviewId(null), delay);
  }, []);
  useEffect(() => () => window.clearTimeout(handover.current), []);

  // Turned off in another tab while a card was describing a row, the card
  // would otherwise sit there describing it forever — the handlers that would
  // have put it back are the ones that just went away.
  useEffect(() => {
    if (followList) return;
    window.clearTimeout(handover.current);
    setPreviewId(null);
  }, [followList]);

  // --- Where the page's ceiling is -----------------------------------------
  //
  // The controls are one sticky block, and everything below has to know how
  // tall it is: the statistics column hangs from its underside, and its own
  // scroll region is the window minus that.
  //
  // Measured rather than written down. The field's height is fixed, but the
  // chip row wraps to a second line on a narrow window — which is exactly the
  // window where a number typed in here being 36px short would put the top of
  // the column behind the filters.
  const chromeRef = useRef<HTMLDivElement | null>(null);
  const [chromeH, setChromeH] = useState(0);

  useEffect(() => {
    const el = chromeRef.current;
    if (!el) return;
    const measure = () => setChromeH(el.getBoundingClientRect().height);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Only where the column is beside the list. Stacked under it on a narrow
  // screen it is the last thing on the page, and a height cap there would be
  // a scrollbar inside a scrollbar for no reason at all.
  const beside = useMediaQuery("(min-width: 64rem)");
  const asideTop = chromeH + PANEL_GAP;

  // --- Fetching the next page ----------------------------------------------
  //
  // A sentinel below the last row, watched by an observer, rather than a
  // "Load more" button or a scroll handler. The button is a click that adds
  // nothing to the decision; the scroll handler runs on every frame of every
  // scroll to answer a question that is only interesting at the very bottom.
  //
  // `rootMargin` asks for the next page 400px before the sentinel is on
  // screen, which is about one row of travel at reading speed — enough that
  // the rows are usually there before the reader arrives, and not so much
  // that opening the page fetches three pages nobody scrolled to.
  const bottom = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = bottom.current;
    if (!el || !hasNextPage || typeof IntersectionObserver === "undefined") {
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        // `isFetchingNextPage` is checked inside the callback rather than in
        // the dependency list: it changes twice per page, and re-running this
        // effect on it would tear the observer down and rebuild it mid-fetch.
        if (entry.isIntersecting && !isFetchingNextPage) void fetchNextPage();
      },
      { rootMargin: "400px 0px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  // Rows fade and grow into place as they cross the fold. Off entirely where
  // the reader has asked for less motion — not merely instant, off: the point
  // of the effect is the movement, and without it the only thing left would be
  // rows that are invisible until half of them is on screen.
  const stillness = useMediaQuery("(prefers-reduced-motion: reduce)");
  const revealRef = useRevealOnScroll(!stillness);

  // Nothing in the catalogue at all, as against nothing to show.
  //
  // Three conditions, and the third is the one that took a bug to find:
  // `done_hidden` has to be zero too. A learner who has sat everything there
  // is has no filters on and a total of nought, and telling them the library
  // is empty — with an invitation to go and write one — is the page losing
  // track of a catalogue they have just worked through. That case belongs to
  // the "you have sat all of these" panel below.
  const empty =
    !isLoading && !isError && !narrowed && total === 0 && hiddenDone === 0;

  return (
    <div className="mx-auto w-full max-w-6xl pb-16">
      {/*
        A course/collection block belongs above this heading: when a learner
        is inside somebody's course, the current lesson leads the page and the
        catalogue becomes the thing underneath it. Not built — but the page is
        laid out so it can be inserted here without any of the below moving,
        which is the whole of what "leaving room" means.
      */}
      {/* The page's title is the nav item that got here and the field below
          it; printing "Listening" again under a header that already says so
          spends the first screenful on a word nobody read. It stays for
          anything that can't see the header — a screen reader arriving at
          the main region needs to be told what the region is. */}
      <h1 className="sr-only">Listening</h1>

      {/*
        Search and the filters sit above both columns and centred, rather than
        at the head of the list. Neither belongs to the list: they are how you
        arrive at one, and on a narrow screen — where the columns stack and
        everything below is the list — putting them inside it would say the
        opposite.

        The field takes a fixed, readable width; the chip row takes exactly as
        much as its chips need, so it stays a row of controls rather than a
        rule across the page.
      */}
      {/* Zero-height, and the whole of the scroll detection: when this has
          gone under the header's top edge, the field below it has arrived. */}
      <div ref={landingMark} aria-hidden className="h-0" />

      {/*
        The controls stick to the top as one block, and the list goes UNDER
        them. That is the point of the background on it: the band is painted
        in the page's own colour and sits over the rows, so a row travelling
        up the page stops existing at the filters instead of sliding on into
        the header and showing through the gaps between its islands.

        Sticky rather than fixed: the block keeps its space in the flow, so
        nothing below it moves when it takes off, and the browser does the
        travelling. `top-0` with the padding inside, rather than `top-3` — the
        twelve pixels above the field have to be part of the cover, or the
        rows would show through them.

        Below `md` none of this happens: there is no island to land in, so the
        controls scroll away with the page — see `hasIsland`.

        The negative margin widens the cover by a pixel or sixteen past the
        content it hides, which is what the page's own gutter is for. A row
        lifted a fraction by the reveal animation is wider than the column it
        sits in, and a cover cut to the column exactly would let its corners
        out.
      */}
      <div
        ref={chromeRef}
        className="z-sticky -mx-4 bg-background px-4 pt-3 pb-6 md:sticky md:top-0"
      >
        {/* The field shrinks into the header's row of islands as it arrives —
            one element changing size, not one appearing where another
            vanishes. `max-width` is what narrows (672px → 384px), so it stays
            centred on the same axis the whole way and lands centred between
            the brand and the account pills. */}
        <div
          className={cn(
            "mx-auto w-full transition-[max-width] duration-300 ease-out motion-reduce:transition-none",
            // Wider than the nav it replaced, and wider still where there is
            // room: at `md` the brand and account pills leave about 350px
            // between them, and a field that overlapped them would be a field
            // sitting on top of the account menu.
            inHeader ? "max-w-sm lg:max-w-xl" : "max-w-2xl",
          )}
        >
          <SearchField
            value={filters.query}
            onChange={(query) => change({ query })}
            onDown={() => focusRow(0)}
            count={mode === "courses" ? coursesTotal : total}
            landed={inHeader}
            mode={mode}
          />
        </div>

        <div className="mt-4 flex justify-center">
          <FilterChips
            filters={filters}
            onChange={change}
            mode={mode}
            onMode={setMode}
            status={status}
            onStatus={setStatus}
            covers={covers}
            onCovers={setCovers}
            length={length}
            onLength={setLength}
            // Off the first page, like the catalogue's own facets: every page
            // carries the same answer, because these describe the library
            // rather than what came back.
            coverOptions={collections.data?.pages[0]?.covers ?? []}
            lengthOptions={collections.data?.pages[0]?.lengths ?? []}
            onToggleBand={toggleBand}
            onToggleType={toggleType}
            typeOptions={typeOptions}
            bandOptions={bandOptions}
          />
        </div>
      </div>

      <div className="grid gap-x-8 gap-y-6 lg:grid-cols-[minmax(0,1fr)_19rem] lg:items-start">
        {/*
          Two rules here keep the search field where the reader put it when a
          search from the header cuts sixteen rows down to three.

          `min-h-svh` is the floor: without a screen's worth of height under
          the controls the document becomes shorter than the scroll position,
          there is nothing left to be scrolled to, and a field stuck to the
          top has to fall back into the page. svh rather than vh because on a
          phone the address bar makes vh a promise the viewport doesn't keep.

          `overflow-anchor: none` is the other half, and it is the one that
          actually bit: Chrome anchors the scroll position to a node that is
          on screen, and when the rows it had chosen were the ones filtered
          away it gave up and went to the top of the document — taking the
          field with it, mid-word. Excluding the list from anchoring leaves
          the browser to clamp the scroll, which it does without moving
          anything the reader is looking at.
        */}
        <div className="min-h-svh min-w-0 [overflow-anchor:none]">
          {/*
            Above both lists, because it is about neither of them. A learner
            works from the catalogue and from their courses, and "what now"
            has one answer and should have one place — hidden on the courses
            tab, somebody carrying on a course would find the way back to it
            only by leaving the tab their courses are on.

            Outside the loading and error branches for the same reason: it is
            its own request, and the one useful thing on the page while the
            list is still arriving.
          */}
          {!listNarrowed &&
            (nextUp.isLoading ? (
              <NextUpSkeleton />
            ) : nextUp.data ? (
              <NextUp data={nextUp.data} />
            ) : null)}

          {mode === "courses" ? (
            /* The other list. It gets the same column and the same treatment
               — one field above it, one rule between rows — because the
               control that got here is a switch and not a link: the page did
               not change, the list did. */
            <CollectionList
              query={settledQuery}
              status={status}
              covers={covers}
              length={length}
              revealRef={stillness ? undefined : revealRef}
            />
          ) : isError ? (
            <div className="mt-6 rounded-xl border border-dashed border-border px-5 py-12 text-center">
              <p className="text-sm text-muted-foreground">
                {getErrorMessage(error) ||
                  "Couldn't load the listening materials."}
              </p>
              <Button
                variant="outline"
                size="sm"
                className="mt-4"
                onClick={() => void refetch()}
              >
                Try again
              </Button>
            </div>
          ) : isLoading ? (
            <>
              <ListHeader
                count={0}
                filtered={false}
                loading
                sort={sort}
                onSort={setSort}
                onClear={clearFilters}
              />
              <SkeletonBlock label="Loading materials">
                <ol>
                  {Array.from({ length: 6 }, (_, i) => (
                    <PracticeRowSkeleton key={i} />
                  ))}
                </ol>
              </SkeletonBlock>
            </>
          ) : empty ? (
            <div className="mt-6 flex flex-col items-center gap-2 rounded-xl border border-border-subtle py-16 text-center">
              <Headphones
                className="size-6 text-muted-foreground/60"
                aria-hidden
              />
              <p className="text-sm text-muted-foreground">
                Nothing to practise yet.
              </p>
              <Link
                to="/studio/listening/new"
                className="text-sm text-primary transition-colors hover:underline"
              >
                Write one in the studio
              </Link>
            </div>
          ) : (
            <>
              {/*
                Only over an unnarrowed list, and that is the rule rather than
                a detail. A suggestion answers "what should I do"; a filter is
                somebody saying what they want to do. Leaving the block up
                over a search for "map labelling" is the page talking over the
                reader — and worse, recommending materials that the filter
                they just set would have excluded.

                It is inside the loaded branch and above the header, where the
                list's own first row would be, so the eye meets it on the way
                down rather than having to come back up for it.
              */}
              <ListHeader
                count={total}
                filtered={narrowed}
                hiddenDone={hiddenDone}
                sort={sort}
                onSort={setSort}
                onClear={clearFilters}
              />
              {visible.length === 0 ? (
                // A filter that matched nothing is a state the reader put the
                // page in, so it says which one and offers the way back out —
                // not a shrug about there being no materials, when there are
                // plenty a chip away.
                <div className="rounded-xl border border-dashed border-border px-5 py-12 text-center">
                  {/* The one case worth telling apart, because it is the one
                      the page put the reader in rather than the reader
                      putting themselves in: everything that matched, they
                      have already sat. "No materials match these filters"
                      over a catalogue they have worked through would read as
                      the page having lost them. */}
                  {hiddenDone > 0 ? (
                    <>
                      <p className="text-sm text-foreground">
                        You have sat all of these already.
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {hiddenDone} done material
                        {hiddenDone === 1 ? "" : "s"} match, and done ones are
                        put away by default.
                      </p>
                      <Button
                        variant="outline"
                        size="sm"
                        className="mt-4"
                        onClick={() => change({ showDone: true })}
                      >
                        Show them
                      </Button>
                    </>
                  ) : (
                    <>
                      <p className="text-sm text-foreground">
                        No materials match these filters.
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        Nothing here answers to all of them at once.
                      </p>
                      <Button
                        variant="outline"
                        size="sm"
                        className="mt-4"
                        onClick={clearFilters}
                      >
                        Clear filters
                      </Button>
                    </>
                  )}
                </div>
              ) : (
                <ol
                  // Dimmed while the answer to a new filter is in flight.
                  // The rows underneath are the PREVIOUS filter's — kept on
                  // purpose, so the page doesn't collapse to skeletons on
                  // every chip — and this is what stops them being read as
                  // the answer to the question just asked.
                  className={cn(
                    "transition-opacity duration-fast",
                    isPlaceholderData && "opacity-50",
                  )}
                  onKeyDown={onListKeyDown}
                  // One handler on the list rather than one per row for the
                  // leaving half: the pointer crossing between two rows never
                  // leaves the list, so the aside doesn't flicker back to the
                  // statistics on the way past.
                  onMouseLeave={
                    followList ? () => releasePreview(HOVER_OUT) : undefined
                  }
                  onBlur={
                    followList
                      ? (e) => {
                          if (!e.currentTarget.contains(e.relatedTarget)) {
                            releasePreview();
                          }
                        }
                      : undefined
                  }
                >
                  {visible.map((m, i) => (
                    <PracticeRow
                      key={m.id}
                      material={m}
                      innerRef={(el) => {
                        rowRefs.current[i] = el;
                      }}
                      revealRef={stillness ? undefined : revealRef}
                      onPreview={followList ? showPreview : undefined}
                    />
                  ))}
                </ol>
              )}

              {/* The bottom of the list, and what happens there.

                  A skeleton row while the next page is in flight rather than
                  a spinner: it is the shape of what is arriving, in the place
                  it will arrive, so the list grows instead of flashing
                  something else at the reader.

                  The sentinel is a bare div under it, with height. A
                  zero-height element at the very end of a document can sit
                  permanently inside a 400px rootMargin and fire again the
                  moment each page lands; a real one is somewhere the reader
                  has to travel towards. */}
              {isFetchingNextPage && (
                <ol aria-hidden>
                  <PracticeRowSkeleton />
                  <PracticeRowSkeleton />
                </ol>
              )}
              {hasNextPage && (
                <div ref={bottom} aria-hidden className="h-8" />
              )}
              {/* Nothing announced while more is loading — "30 materials" the
                  instant before it becomes 60 is a screen reader being
                  interrupted to be told a number that is about to change. */}
              {!hasNextPage && visible.length > 0 && total > PRACTICE_PAGE && (
                <p className="py-6 text-center text-xs text-muted-foreground">
                  That&apos;s all {total} of them.
                </p>
              )}
            </>
          )}
        </div>

        {/*
          Sticky, and only where there is room to be: below the fold on a
          narrow screen the panel sits under the list, which is the right
          order to read them in when they can't be read side by side.

          It hangs from the underside of the controls and reaches to just
          short of the bottom of the window; taller than that and it scrolls
          itself. The scrollbar lives in the twelve pixels of padding hanging
          off the right-hand edge, out in the page's gutter — so the cards
          keep the column's full width whether it is there or not, and the
          bar arriving never moves a word of the text it belongs to. What it
          looks like is in globals.css: nothing at all until the pointer is
          on the column (`scrollbar-quiet`).
        */}
        <aside
          // The hold-and-release on the column itself is what lets somebody
          // reach a link inside a card that is describing a row. With the
          // cards not following the list there is nothing to hold.
          onMouseEnter={followList ? holdPreview : undefined}
          onMouseLeave={followList ? () => releasePreview() : undefined}
          style={
            beside
              ? {
                  top: asideTop,
                  // svh, not vh: on a phone the address bar makes vh a
                  // promise the viewport doesn't keep — and this is a floor
                  // the last card sits on.
                  maxHeight: `calc(100svh - ${asideTop + BOTTOM_GAP}px)`,
                }
              : undefined
          }
          className="scrollbar-quiet lg:sticky lg:-mr-3 lg:overflow-y-auto lg:pr-3"
        >
          <PracticeAside
            stats={stats.data}
            statsLoading={stats.isLoading}
            preview={preview}
            onPractisePart={setScope}
          />
        </aside>
      </div>
    </div>
  );
}

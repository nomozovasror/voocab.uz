import { useCallback, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useDebounced } from "@/hooks/use-debounced";
import { getErrorMessage } from "@/lib/api";
import {
  PRACTICE_PAGE,
  usePracticeCatalogue,
  usePracticeStats,
} from "@/features/paper/queries";
import { catalogueParams, EMPTY_FILTERS } from "@/features/listening/practice";
import { READING } from "@/features/paper/skill";
import {
  ListHeader,
  SearchField,
} from "@/features/listening/components/PracticeControls";
import {
  PracticeRow,
  PracticeRowSkeleton,
} from "@/features/listening/components/PracticeRow";
import { PracticeAside } from "@/features/listening/components/PracticeAside";

/**
 * What a learner can read, and what they have done with it.
 *
 * The same catalogue the listening page shows, about the other paper: the
 * same server query (`/api/reading/practice`, which is `/api/listening/
 * practice` mounted a second time), the same rows, the same sidebar. What it
 * does not yet have is the listening page's three list modes — courses and
 * drills — which arrive with reading's collections and drills.
 */
export default function ReadingPage() {
  const [query, setQuery] = useState("");
  // Sat papers are put away by default — the list answers "what shall I
  // practise next" — and the header says how many that hid. Without the
  // switch beside it that line is a fact the reader cannot act on.
  const [showDone, setShowDone] = useState(false);
  const debounced = useDebounced(query, 250);
  const [preview, setPreview] = useState<string | null>(null);

  const params = useMemo(
    // The same shape the listening page sends, so the one server-side filter
    // (`_catalogue_where`) reads both the same way — see services/CLAUDE.md
    // on a filter being added in two places or not at all.
    () =>
      catalogueParams(
        { ...EMPTY_FILTERS, query: debounced, showDone },
        "newest",
      ),
    [debounced, showDone],
  );

  const catalogue = usePracticeCatalogue(READING.id, params);
  const stats = usePracticeStats(READING.id);

  const rows = useMemo(
    () => catalogue.data?.pages.flatMap((page) => page.items) ?? [],
    [catalogue.data],
  );
  const total = catalogue.data?.pages[0]?.total ?? 0;
  const hiddenDone = catalogue.data?.pages[0]?.done_hidden ?? 0;

  const previewed = useMemo(
    () => rows.find((row) => row.id === preview) ?? null,
    [rows, preview],
  );

  // The last row registers itself with an observer; crossing it asks for the
  // next page. The same rule the listening list follows — a button nobody
  // presses is a page nobody reaches the bottom of.
  const observer = useRef<IntersectionObserver | null>(null);
  const lastRow = useCallback(
    (el: HTMLAnchorElement | null) => {
      observer.current?.disconnect();
      if (!el || !catalogue.hasNextPage || catalogue.isFetchingNextPage) return;
      observer.current = new IntersectionObserver(([entry]) => {
        if (entry.isIntersecting) void catalogue.fetchNextPage();
      });
      observer.current.observe(el);
    },
    [catalogue],
  );

  return (
    <div className="mx-auto w-full max-w-[1500px] pb-24">
      <div className="mx-auto max-w-2xl pt-4">
        <SearchField
          value={query}
          onChange={setQuery}
          count={total}
          mode="materials"
        />
      </div>

      <div className="mt-6 flex flex-col gap-6 lg:flex-row">
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex justify-end">
            <button
              type="button"
              onClick={() => setShowDone((on) => !on)}
              aria-pressed={showDone}
              className="rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors duration-fast hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none aria-pressed:text-primary"
            >
              {showDone ? "Hide done" : "Show done"}
            </button>
          </div>
          <ListHeader
            count={total}
            filtered={debounced.trim() !== ""}
            loading={catalogue.isLoading}
            hiddenDone={hiddenDone}
            sort="newest"
            onSort={() => {}}
            onClear={() => setQuery("")}
          />

          {catalogue.isError && (
            <p className="mt-6 text-sm text-destructive">
              {getErrorMessage(catalogue.error) ??
                "Couldn't load the reading materials."}
            </p>
          )}

          {catalogue.isLoading ? (
            <ul className="mt-2 space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <PracticeRowSkeleton key={i} />
              ))}
            </ul>
          ) : rows.length === 0 ? (
            <Empty
              searching={debounced.trim() !== ""}
              hiddenDone={hiddenDone}
              onShowDone={() => setShowDone(true)}
            />
          ) : (
            <ul className="mt-2 space-y-2">
              {rows.map((material, index) => (
                <PracticeRow
                  key={material.id}
                  basePath={READING.basePath}
                  partWord="Passage"
                  material={material}
                  innerRef={
                    index === rows.length - 1 ? lastRow : undefined
                  }
                  onPreview={setPreview}
                />
              ))}
              {catalogue.isFetchingNextPage &&
                Array.from({ length: Math.min(PRACTICE_PAGE, 3) }).map(
                  (_, i) => <PracticeRowSkeleton key={`more-${i}`} />,
                )}
            </ul>
          )}
        </div>

        <PracticeAside
          basePath={READING.basePath}
          stats={stats.data}
          statsLoading={stats.isLoading}
          preview={previewed}
          onPractisePart={() => {}}
        />
      </div>
    </div>
  );
}

/** Nothing to show, and WHICH nothing it is.
 *
 *  Three states that look alike and are not: a search that matched nothing, a
 *  library with nothing in it, and a library whose every paper this reader has
 *  already sat. Only the last two look identical on screen, and saying "no
 *  reading papers published yet" over three the reader finished last week is
 *  the page contradicting the line directly above it. */
function Empty({
  searching,
  hiddenDone,
  onShowDone,
}: {
  searching: boolean;
  hiddenDone: number;
  onShowDone: () => void;
}) {
  if (searching) {
    return (
      <p className="mt-10 text-center text-sm text-muted-foreground">
        Nothing matched that.
      </p>
    );
  }
  if (hiddenDone > 0) {
    return (
      <div className="mt-10 flex flex-col items-center gap-3 text-center">
        <p className="text-sm text-muted-foreground">
          You have sat everything here.
        </p>
        <Button size="sm" variant="secondary" onClick={onShowDone}>
          Show the {hiddenDone} you have done
        </Button>
      </div>
    );
  }
  return (
    <div className="mt-10 flex flex-col items-center gap-3 text-center">
      <READING.icon className="size-7 text-muted-foreground" aria-hidden />
      <p className="text-sm text-muted-foreground">
        No reading papers published yet.
      </p>
      <Button asChild size="sm">
        <Link to={`${READING.studioPath}/new`}>Write one</Link>
      </Button>
    </div>
  );
}

import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, Check, Library } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { getErrorMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import { fmtClock } from "@/lib/time";
import { useRememberedChoice } from "@/lib/preferences";
import { useCollection } from "@/features/listening/queries";
import { useMediaQuery } from "@/hooks/use-media-query";
import { useRevealOnScroll } from "@/hooks/use-reveal-on-scroll";
import {
  describeTask,
  formatSpent,
  partLabel,
} from "@/features/listening/practice";
import { AuthorAvatar } from "@/features/listening/components/AuthorTag";
import { CollectionCover } from "@/features/listening/components/CollectionBook";
import {
  LessonList,
  LessonListSkeleton,
} from "@/features/listening/components/LessonList";
import { LessonGrid } from "@/features/listening/components/LessonGrid";
import type {
  CollectionDetail,
  PracticeMaterial,
} from "@/features/listening/types";

/**
 * One collection, opened.
 *
 * The materials are the catalogue's own — same measured difficulty, same
 * history, same byline — because a collection is a different route to the
 * same papers, not a different kind of thing. What this page adds is the two
 * facts the catalogue cannot carry: the ORDER somebody put them in, and where
 * the reader is in it.
 *
 * **The order is a recommendation, not a lock.** Any lesson can be sat at any
 * time; the numbers are the author's suggestion about what to do when, which
 * is why the list says so out loud and why "next" is the first UNSAT lesson
 * rather than one past the last done one.
 *
 * There is no enrolment and nothing to join. Progress is counted from attempts
 * they had already made, so the page is safe to wander into and safe to
 * abandon, and it is still correct months later without anybody having pressed
 * a button on it.
 */

/** Where a collection stops being a list and starts being a map.
 *
 *  Thirty is about a screenful of rows. Below it a list reads in one go and
 *  every title is legible; above it the reader is scrolling past titles to
 *  find a shape, which is the grid's job. Only the DEFAULT — whichever they
 *  pick is remembered. */
const GRID_FROM = 30;

const VIEWS = ["list", "grid"] as const;
type View = (typeof VIEWS)[number];

export default function CollectionPage() {
  const { id } = useParams<{ id: string }>();
  const { data, isLoading, isError, error, refetch } = useCollection(id);

  const stillness = useMediaQuery("(prefers-reduced-motion: reduce)");
  const revealRef = useRevealOnScroll(!stillness);

  const total = data?.items.length ?? 0;
  // Per collection, not one setting for all of them. A course of six and a
  // course of two hundred want different views, and a choice made on one is
  // not a statement about the other — remembered globally, picking `list` on
  // a short course would open the next 200-lesson one as a list too.
  const [view, setView] = useRememberedChoice<View>(
    `voocab-collection-view:${id ?? ""}`,
    total > GRID_FROM ? "grid" : "list",
    VIEWS,
  );

  return (
    <div className="mx-auto w-full max-w-6xl pb-16">
      {/* Back to where they came from, first thing. A page reached from one
          place should say so — the header's nav says "Listening" is a
          section, not that this is inside it. */}
      <Link
        to="/listening"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" aria-hidden />
        All listening
      </Link>

      {isError ? (
        <div className="mt-8 rounded-xl border border-dashed border-border px-5 py-12 text-center">
          <p className="text-sm text-muted-foreground">
            {getErrorMessage(error) || "Couldn't load this collection."}
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
        <CollectionSkeleton />
      ) : data ? (
        <div className="mt-4 grid gap-x-10 gap-y-8 lg:grid-cols-[minmax(0,1fr)_18rem] lg:items-start">
          <div className="min-w-0">
            <Header collection={data} />
            <ActionBar collection={data} />

            {data.items.length === 0 ? (
              // Published with nothing a learner may see. Publishing an empty
              // collection is refused, so reaching this means every material
              // in it has been withdrawn since — rare, and still something the
              // page has to be able to say without looking broken.
              <p className="mt-8 rounded-xl border border-dashed border-border px-5 py-12 text-center text-sm text-muted-foreground">
                Nothing in this collection is published yet.
              </p>
            ) : (
              <>
                <div className="mt-7 flex items-center justify-between gap-4">
                  <p className="text-xs text-muted-foreground">
                    <span className="tabular-nums text-foreground">
                      {total}
                    </span>{" "}
                    material{total === 1 ? "" : "s"} · in suggested order
                  </p>
                  <ViewToggle view={view} onChange={setView} />
                </div>

                {view === "grid" ? (
                  <LessonGrid
                    items={data.items}
                    nextId={data.progress.next_material_id}
                  />
                ) : (
                  <LessonList
                    items={data.items}
                    nextId={data.progress.next_material_id}
                    revealRef={stillness ? undefined : revealRef}
                  />
                )}
              </>
            )}
          </div>

          <Aside collection={data} />
        </div>
      ) : null}
    </div>
  );
}

// --- Header -----------------------------------------------------------------

function Header({ collection }: { collection: CollectionDetail }) {
  return (
    // Cover and text are the same height, and both are pinned top and bottom
    // — two tidy rectangles rather than a picture with text spilling past it.
    // The byline is pushed to the foot with `mt-auto`, which is what makes the
    // two bottoms line up whatever the summary's length turns out to be.
    <header className="flex gap-6">
      <div className="w-26 shrink-0">
        <CollectionCover
          id={collection.id}
          title={collection.title}
          className="shadow-[0_6px_14px_rgba(0,0,0,0.36)]"
        />
      </div>

      <div className="flex h-36 min-w-0 flex-1 flex-col">
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Library className="size-3.5" aria-hidden />
          Collection
        </p>
        <h1 className="mt-1 truncate text-2xl font-semibold text-foreground">
          {collection.title}
        </h1>
        {collection.summary && (
          <p className="mt-2 line-clamp-2 max-w-prose text-sm leading-relaxed text-muted-foreground">
            {collection.summary}
          </p>
        )}
        {collection.author && (
          // "By", not "put together by". An author may have written every
          // material in it or gathered other people's; "put together by" only
          // covers the second. "By" is true of both, and every material in the
          // list carries its own byline anyway.
          <p className="mt-auto flex items-center gap-2 text-xs text-muted-foreground">
            <AuthorAvatar author={collection.author} />
            By {collection.author.display_name}
          </p>
        )}
      </div>
    </header>
  );
}

// --- The one action ---------------------------------------------------------

function ActionBar({ collection }: { collection: CollectionDetail }) {
  const { done, total, next_material_id } = collection.progress;
  const next = useMemo(
    () => collection.items.find((m) => m.id === next_material_id) ?? null,
    [collection.items, next_material_id],
  );
  const index = next ? collection.items.indexOf(next) + 1 : 0;
  const finished = total > 0 && done === total;

  if (total === 0) return null;

  // Its own row under the header rather than inside it. In the header it
  // competed with the title for the eye and left the text block ragged; on
  // its own the heading stays a heading and the action is unmistakably the
  // action.
  return (
    <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-3 rounded-xl bg-surface-sunken px-3.5 py-3">
      {finished ? (
        <>
          <p className="flex min-w-0 flex-1 items-center gap-2 text-sm text-foreground">
            <Check className="size-4 shrink-0 text-correct" aria-hidden />
            All {total} done
            {collection.stats.first_try_avg_pct !== null && (
              <span className="text-muted-foreground">
                · Average{" "}
                <span className="tabular-nums">
                  {collection.stats.first_try_avg_pct}%
                </span>{" "}
                on first try
              </span>
            )}
          </p>
          <Button asChild variant="outline" size="sm">
            <Link to="/listening/statistics">
              See your results
              <ArrowRight className="size-3.5" aria-hidden />
            </Link>
          </Button>
        </>
      ) : next ? (
        <>
          <Button asChild>
            <Link to={`/listening/${next.id}`}>
              {done === 0 ? "Start" : "Continue"}
              <ArrowRight className="size-4" aria-hidden />
            </Link>
          </Button>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm text-foreground">
              <span className="text-muted-foreground tabular-nums">
                {index} ·{" "}
              </span>
              {next.title}
            </p>
            <p className="truncate text-xs text-muted-foreground">
              <Meta material={next} />
            </p>
          </div>
        </>
      ) : null}
    </div>
  );
}

function Meta({ material: m }: { material: PracticeMaterial }) {
  return (
    <>
      {[
        partLabel(m),
        describeTask(m)?.label,
        `${m.question_count} question${m.question_count === 1 ? "" : "s"}`,
        m.duration_ms != null ? fmtClock(m.duration_ms) : null,
      ]
        .filter(Boolean)
        .join(" · ")}
    </>
  );
}

// --- List / grid ------------------------------------------------------------

function ViewToggle({
  view,
  onChange,
}: {
  view: View;
  onChange: (view: View) => void;
}) {
  return (
    <div
      role="group"
      aria-label="How to show the materials"
      className="flex items-center gap-0.5 rounded-full bg-surface-sunken p-0.5"
    >
      {VIEWS.map((value) => (
        <Button
          key={value}
          type="button"
          variant="ghost"
          size="xs"
          aria-pressed={view === value}
          onClick={() => onChange(value)}
          className={cn(
            "rounded-full px-2.5 text-xs capitalize",
            view === value
              ? "bg-primary/15 text-primary hover:bg-primary/20 hover:text-primary"
              : "text-muted-foreground hover:bg-surface-hover hover:text-foreground",
          )}
        >
          {value}
        </Button>
      ))}
    </div>
  );
}

// --- The column beside it ---------------------------------------------------

function Aside({ collection }: { collection: CollectionDetail }) {
  const { done, total } = collection.progress;
  const { first_try_avg_pct, best_avg_pct, time_spent_ms } = collection.stats;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  return (
    <aside className="flex flex-col gap-4 lg:sticky lg:top-16">
      <section
        aria-label="Your progress"
        className="rounded-xl border border-border-subtle bg-card/50 p-4"
      >
        <p className="text-xs text-muted-foreground">Your progress</p>
        <div
          className="mt-2.5 h-1 overflow-hidden rounded-full bg-foreground/10"
          role="progressbar"
          aria-valuenow={done}
          aria-valuemin={0}
          aria-valuemax={total}
          aria-label={`${done} of ${total} done`}
        >
          <div
            className="h-full rounded-full bg-correct transition-[width] duration-slow ease-out motion-reduce:transition-none"
            style={{ width: `${pct}%` }}
          />
        </div>
        <p className="mt-2 text-lg text-foreground">
          <span className="tabular-nums">{done}</span>{" "}
          <span className="text-sm text-muted-foreground">
            of <span className="tabular-nums">{total}</span> done
          </span>
        </p>
      </section>

      {/* Only once they have sat something in it. A panel of dashes beside a
          course nobody has opened is four ways of saying "nothing yet", and
          the progress card above already says it once. */}
      {done > 0 && (
        <section
          aria-label="Your results in this collection"
          className="rounded-xl border border-border-subtle bg-card/50 p-4"
        >
          <p className="text-xs text-muted-foreground">In this collection</p>
          <dl className="mt-3 space-y-2 text-sm">
            <Stat label="First-try average" value={pctOrDash(first_try_avg_pct)} />
            {/* Absent until something has been sat twice: with no retries it
                is the first-try average under a second name. */}
            {best_avg_pct !== null && (
              <Stat label="Best average" value={`${best_avg_pct}%`} />
            )}
            <Stat
              label="Time spent"
              value={time_spent_ms > 0 ? formatSpent(time_spent_ms) : "—"}
            />
            <Stat label="Left to sit" value={String(total - done)} />
          </dl>
        </section>
      )}
    </aside>
  );
}

/** A dash, never a zero. Nothing measured is not a measurement of nothing —
 *  the same rule the sidebar on the practice page follows. */
function pctOrDash(value: number | null): string {
  return value === null ? "—" : `${value}%`;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="tabular-nums text-foreground">{value}</dd>
    </div>
  );
}

// --- Waiting ----------------------------------------------------------------

/**
 * The page, waiting.
 *
 * Built from the real page's own class strings and on the same two-column
 * grid, so nothing moves sideways when the collection lands.
 */
function CollectionSkeleton() {
  return (
    <SkeletonBlock label="Loading collection">
      <div className="mt-4 grid gap-x-10 gap-y-8 lg:grid-cols-[minmax(0,1fr)_18rem] lg:items-start">
        <div className="min-w-0">
          <header className="flex gap-6">
            <div className="w-26 shrink-0">
              <svg
                viewBox="0 0 156 214"
                className="block h-auto w-full rounded-l-sm rounded-r-md"
                aria-hidden
              >
                <rect width={156} height={214} className="fill-foreground/10" />
              </svg>
            </div>
            <div className="flex h-36 min-w-0 flex-1 flex-col">
              <p className="text-xs">
                <Skeleton className="inline-block h-[0.8em] w-20" />
              </p>
              <h1 className="mt-1 text-2xl font-semibold">
                <Skeleton className="inline-block h-[0.8em] w-72 max-w-full" />
              </h1>
              <p className="mt-2 text-sm leading-relaxed">
                <Skeleton className="inline-block h-[0.8em] w-full max-w-lg" />
              </p>
              <p className="mt-auto flex items-center gap-2 text-xs">
                <Skeleton className="size-5 rounded-full" />
                <Skeleton className="inline-block h-[0.8em] w-40" />
              </p>
            </div>
          </header>

          <div className="mt-5 h-16 rounded-xl bg-surface-sunken" />

          <div className="mt-7 flex items-center justify-between gap-4">
            <p className="text-xs">
              <Skeleton className="inline-block h-[0.8em] w-48" />
            </p>
            <Skeleton className="h-7 w-28 rounded-full" />
          </div>
          <LessonListSkeleton />
        </div>

        <aside className="flex flex-col gap-4">
          <div className="rounded-xl border border-border-subtle bg-card/50 p-4">
            <p className="text-xs">
              <Skeleton className="inline-block h-[0.8em] w-24" />
            </p>
            <div className="mt-2.5 h-1 rounded-full bg-foreground/10" />
            <p className="mt-2 text-lg">
              <Skeleton className="inline-block h-[0.8em] w-28" />
            </p>
          </div>
        </aside>
      </div>
    </SkeletonBlock>
  );
}

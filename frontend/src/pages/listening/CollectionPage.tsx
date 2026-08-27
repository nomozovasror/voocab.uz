import { Link, useParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, Check, Library } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { getErrorMessage } from "@/lib/api";
import { useCollection } from "@/features/listening/queries";
import { useMediaQuery } from "@/hooks/use-media-query";
import { useRevealOnScroll } from "@/hooks/use-reveal-on-scroll";
import { AuthorAvatar } from "@/features/listening/components/AuthorTag";
import {
  PracticeRow,
  PracticeRowSkeleton,
} from "@/features/listening/components/PracticeRow";
import type { CollectionDetail } from "@/features/listening/types";

/**
 * One collection, opened.
 *
 * The rows are the catalogue's own — same measured difficulty, same history,
 * same byline — because a collection is a different route to the same
 * materials, not a different kind of thing. What this page adds is the two
 * facts the catalogue cannot carry: the ORDER somebody put them in, and where
 * the reader is in it.
 *
 * There is no enrolment and nothing to join. Progress is counted from
 * attempts they had already made, so this page is safe to wander into and
 * safe to abandon, and it is still correct months later without anybody
 * having pressed a button on it.
 */
export default function CollectionPage() {
  const { id } = useParams<{ id: string }>();
  const { data, isLoading, isError, error, refetch } = useCollection(id);

  const stillness = useMediaQuery("(prefers-reduced-motion: reduce)");
  const revealRef = useRevealOnScroll(!stillness);

  return (
    <div className="mx-auto w-full max-w-3xl pb-16">
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
        <>
          <Header collection={data} />
          {data.items.length === 0 ? (
            // Published with nothing a learner may see. The API refuses to
            // publish an empty collection, so reaching this means the author
            // has withdrawn every material in it since — rare, and still
            // something the page has to be able to say without looking
            // broken.
            <p className="mt-8 rounded-xl border border-dashed border-border px-5 py-12 text-center text-sm text-muted-foreground">
              Nothing in this collection is published yet.
            </p>
          ) : (
            <ol className="mt-6">
              {data.items.map((m, i) => (
                <PracticeRow
                  key={m.id}
                  material={m}
                  index={i + 1}
                  revealRef={stillness ? undefined : revealRef}
                />
              ))}
            </ol>
          )}
        </>
      ) : null}
    </div>
  );
}

function Header({ collection }: { collection: CollectionDetail }) {
  const { done, total, next_material_id } = collection.progress;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  const finished = total > 0 && done === total;

  return (
    <header className="mt-4">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Library className="size-3.5" aria-hidden />
        Collection
      </div>
      <h1 className="mt-1 text-2xl font-semibold text-foreground">
        {collection.title}
      </h1>
      {collection.summary && (
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          {collection.summary}
        </p>
      )}

      {collection.author && (
        <p className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
          <AuthorAvatar author={collection.author} />
          Put together by {collection.author.display_name}
        </p>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-4">
        <div className="min-w-48 flex-1">
          <div
            className="h-1.5 overflow-hidden rounded-full bg-foreground/10"
            role="progressbar"
            aria-valuenow={done}
            aria-valuemin={0}
            aria-valuemax={total}
            aria-label={`${done} of ${total} done`}
          >
            {/* Green, not the accent. Yellow means "this is the action"
                everywhere else here, and a progress bar is a report. */}
            <div
              className="h-full rounded-full bg-correct transition-[width] duration-slow ease-out motion-reduce:transition-none"
              style={{ width: `${pct}%` }}
            />
          </div>
          <p className="mt-1.5 text-xs text-muted-foreground">
            <span className="tabular-nums text-foreground">{done}</span> of{" "}
            <span className="tabular-nums">{total}</span> done
          </p>
        </div>

        {/* One button, and what it says depends on where they are. "Continue"
            goes to the first material they have NOT sat, in order — not the
            nearest one, because the order is somebody's judgement about what
            to do when, and that judgement is the whole reason this is a
            collection rather than a filter. */}
        {finished ? (
          <p className="flex items-center gap-1.5 text-sm text-correct">
            <Check className="size-4" aria-hidden />
            You&apos;ve finished this one.
          </p>
        ) : next_material_id ? (
          <Button asChild>
            <Link to={`/listening/${next_material_id}`}>
              {done === 0 ? "Start" : "Continue"}
              <ArrowRight className="size-4" aria-hidden />
            </Link>
          </Button>
        ) : null}
      </div>
    </header>
  );
}

/**
 * The page, waiting.
 *
 * Built from the real page's own class strings, and the rows are the
 * catalogue's own skeleton — this page borrows that component for the loaded
 * state too, so borrowing it here is what stops the two drifting apart.
 */
function CollectionSkeleton() {
  return (
    <SkeletonBlock label="Loading collection">
      <header className="mt-4">
        <div className="flex items-center gap-2 text-xs">
          <Skeleton className="size-3.5 rounded" />
          <Skeleton className="inline-block h-[0.8em] w-20" />
        </div>
        <h1 className="mt-1 text-2xl font-semibold">
          <Skeleton className="inline-block h-[0.8em] w-72 max-w-full" />
        </h1>
        <p className="mt-2 text-sm leading-relaxed">
          <Skeleton className="inline-block h-[0.8em] w-full max-w-lg" />
        </p>
        <p className="mt-3 flex items-center gap-2 text-xs">
          <Skeleton className="size-5 rounded-full" />
          <Skeleton className="inline-block h-[0.8em] w-40" />
        </p>
        <div className="mt-5 flex flex-wrap items-center gap-4">
          <div className="min-w-48 flex-1">
            <div className="h-1.5 rounded-full bg-foreground/10" />
            <p className="mt-1.5 text-xs">
              <Skeleton className="inline-block h-[0.8em] w-24" />
            </p>
          </div>
          <Skeleton className="h-8 w-24 rounded-lg" />
        </div>
      </header>
      <ol className="mt-6">
        {Array.from({ length: 4 }, (_, i) => (
          <PracticeRowSkeleton key={i} />
        ))}
      </ol>
    </SkeletonBlock>
  );
}

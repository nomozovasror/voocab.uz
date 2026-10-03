import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { vocabularyApi, wordListKey } from "@/features/vocabulary/api";
import { CefrSpread } from "@/features/vocabulary/components/CefrSpread";
import { CefrTag } from "@/features/vocabulary/components/CefrTag";
import {
  BackLink,
  ListProgress,
  ListToggle,
} from "@/features/vocabulary/components/WordListControls";
import { formatCount } from "@/features/vocabulary/wordLists";

/**
 * One Word list: why it is worth learning, how big and how hard it is, a
 * dozen of its words so the learner can judge the level themselves, and —
 * last, small, and required by the licence — whose list it is.
 */
export default function VocabularyListPage() {
  const { key = "" } = useParams();
  const { data, isPending, error } = useQuery({
    queryKey: wordListKey(key),
    queryFn: () => vocabularyApi.listDetail(key),
    retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 2,
  });

  if (isPending) return <ListSkeleton />;

  if (!data) {
    const missing = error instanceof ApiError && error.status === 404;
    return (
      <div className="mx-auto w-full max-w-2xl pb-24 pt-2">
        <BackLink />
        <p className="mt-4 text-sm text-destructive">
          {missing ? "There is no such word list." : "This word list couldn't be loaded."}
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-2xl pb-24 pt-2">
      <BackLink />

      <header className="mt-2 flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold text-foreground">{data.title}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{data.description}</p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <ListToggle
            listKey={data.key}
            title={data.title}
            active={data.active}
            size="default"
          />
        </div>
      </header>

      <section aria-label="Size and levels" className="mt-6">
        <p className="mb-3 text-sm text-muted-foreground">
          <span className="font-medium tabular-nums text-foreground">
            {formatCount(data.word_count)}
          </span>{" "}
          words
        </p>
        <CefrSpread counts={data.cefr} />
      </section>

      {data.started && (
        <section aria-label="Your progress" className="mt-6">
          <ListProgress
            title={data.title}
            owned={data.owned}
            total={data.word_count}
          />
        </section>
      )}

      <section aria-labelledby="samples-heading" className="mt-8">
        <h2 id="samples-heading" className="mb-2 text-sm font-medium text-foreground">
          Some of the words
        </h2>
        <ul className="divide-y divide-border rounded-xl border border-border">
          {data.samples.map((w) => (
            <li key={`${w.lemma}-${w.pos}`} className="px-4 py-3">
              <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <span className="font-medium text-foreground">{w.lemma}</span>
                {w.pos && (
                  <span className="text-xs text-muted-foreground italic">{w.pos}</span>
                )}
                <CefrTag level={w.cefr} />
              </p>
              {w.definition_en && (
                <p className="mt-0.5 text-sm text-muted-foreground">{w.definition_en}</p>
              )}
              {w.meaning_uz && (
                <p lang="uz" className="mt-0.5 text-sm text-foreground">
                  {w.meaning_uz}
                </p>
              )}
            </li>
          ))}
        </ul>
      </section>

      <footer className="mt-10 text-xs text-muted-foreground">
        {data.attribution}
        {data.licence_url && (
          <>
            {" "}
            <a
              href={data.licence_url}
              target="_blank"
              rel="noreferrer noopener"
              className="underline underline-offset-2 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              Licence
            </a>
          </>
        )}
      </footer>
    </div>
  );
}

/** Built from the page's own class strings — see `frontend/CLAUDE.md`. */
function ListSkeleton() {
  return (
    <SkeletonBlock
      label="Loading word list"
      className="mx-auto w-full max-w-2xl pb-24 pt-2"
    >
      <span className="inline-flex items-center gap-1 text-xs">
        <Skeleton className="inline-block h-[0.8em] w-20" />
      </span>
      <header className="mt-2 flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold">
            <Skeleton className="inline-block h-[0.8em] w-56" />
          </h1>
          <p className="mt-1 text-sm">
            <Skeleton className="inline-block h-[0.8em] w-80 max-w-full" />
          </p>
        </div>
        <Skeleton className="h-8 w-16 rounded-lg" />
      </header>
      <section className="mt-6">
        <p className="mb-3 text-sm">
          <Skeleton className="inline-block h-[0.8em] w-24" />
        </p>
        <Skeleton className="h-8 w-full rounded-md" />
      </section>
      <section className="mt-8">
        <h2 className="mb-2 text-sm font-medium">
          <Skeleton className="inline-block h-[0.8em] w-32" />
        </h2>
        <ul className="divide-y divide-border rounded-xl border border-border">
          {Array.from({ length: 6 }, (_, i) => (
            <li key={i} className="px-4 py-3">
              <p>
                <Skeleton className="inline-block h-[1em] w-24" />
              </p>
              <p className="mt-0.5 text-sm">
                <Skeleton className="inline-block h-[0.8em] w-72 max-w-full" />
              </p>
              <p className="mt-0.5 text-sm">
                <Skeleton className="inline-block h-[0.8em] w-40" />
              </p>
            </li>
          ))}
        </ul>
      </section>
    </SkeletonBlock>
  );
}

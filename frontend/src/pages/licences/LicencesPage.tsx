import { ExternalLink } from "lucide-react";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { getErrorMessage } from "@/lib/api";
import { useLicences } from "@/features/lexicon/queries";
import type { LicenceSource } from "@/features/lexicon/types";

/**
 * "Data sources and licences" — public, generated from what
 * `source_id`/`licence`/`frequency_source` actually sit in the database
 * (`brief-lexicon.md` §9), never a hand-written list of rows. See
 * `app.services.lexicon_licences` for the registry this reads.
 */
export default function LicencesPage() {
  const { data, isLoading, isError, error } = useLicences();

  return (
    <div className="mx-auto w-full max-w-2xl">
      <h1 className="text-2xl font-medium tracking-wide text-foreground">
        Data sources and licences
      </h1>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
        Voocab's vocabulary is built in part from third-party word lists and
        a sense inventory, each under its own licence. This page lists
        exactly what this deployment's dictionary is actually built from —
        it is generated from the database, not written by hand.
      </p>

      <div className="mt-8 space-y-3 font-mono">
        {isLoading ? (
          <SkeletonBlock label="Loading data sources" className="space-y-3">
            <SourceCardSkeleton />
            <SourceCardSkeleton />
          </SkeletonBlock>
        ) : isError ? (
          <p className="rounded-lg border border-dashed border-border px-5 py-10 text-center text-sm text-muted-foreground">
            {getErrorMessage(error) || "Couldn't load the licences page."}
          </p>
        ) : !data || data.sources.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border px-5 py-10 text-center text-sm text-muted-foreground">
            Nothing to attribute yet.
          </p>
        ) : (
          data.sources.map((source) => (
            <SourceCard key={source.key} source={source} />
          ))
        )}
      </div>
    </div>
  );
}

function SourceCard({ source }: { source: LicenceSource }) {
  return (
    <div className="rounded-lg bg-card/70 px-5 py-4">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-medium text-foreground">{source.title}</h2>
        <span className="shrink-0 tabular-nums text-xs text-muted-foreground">
          {source.count.toLocaleString()} {source.count === 1 ? "entry" : "entries"}
        </span>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">{source.authors}</p>
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        <a
          href={source.licence_url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 rounded-full bg-foreground/8 px-2 py-0.5 text-foreground/80 transition-colors hover:text-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          {source.licence_name}
          <ExternalLink className="size-3" aria-hidden />
        </a>
        <a
          href={source.source_url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          Source
          <ExternalLink className="size-3" aria-hidden />
        </a>
      </div>
    </div>
  );
}

function SourceCardSkeleton() {
  return (
    <div className="rounded-lg bg-card/70 px-5 py-4" aria-hidden>
      <div className="flex items-baseline justify-between gap-3">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-3 w-16" />
      </div>
      <Skeleton className="mt-2 h-3 w-52" />
      <div className="mt-3 flex gap-4">
        <Skeleton className="h-5 w-24 rounded-full" />
        <Skeleton className="h-3 w-14" />
      </div>
    </div>
  );
}

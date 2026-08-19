import { Link } from "react-router-dom";
import { Check, Headphones } from "lucide-react";
import { cn } from "@/lib/utils";
import { fmtClock, timeAgo } from "@/lib/time";
import { PageLoader } from "@/components/ui/spinner";
import { usePracticeCatalogue } from "@/features/listening/queries";
import type { PracticeMaterial } from "@/features/listening/types";

/**
 * What there is to practise.
 *
 * This used to be the author's material list wearing a learner's heading: it
 * showed you your own unfinished drafts, labelled them "private", and offered
 * a Practice button that opened a paper with no questions on it. Whether a
 * material is public is a fact about publishing, not something a candidate
 * needs told; what they need is how long it is and whether they have done it.
 *
 * So each row answers three questions before it is clicked — how many
 * questions, how long the recording runs, and how you did last time — and the
 * score, where there is one, is the link back to that review.
 */
export default function ListeningPage() {
  const { data, isLoading, isError } = usePracticeCatalogue();

  return (
    <div className="mx-auto max-w-3xl pb-16">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 pt-2 pb-6">
        <h1 className="flex-1 text-lg font-semibold text-foreground">
          listening
        </h1>
        {data && data.length > 0 && (
          <span className="font-mono text-xs tabular-nums text-muted-foreground">
            {data.filter((m) => m.attempts > 0).length} of {data.length} done
          </span>
        )}
      </div>

      {isLoading ? (
        <PageLoader />
      ) : isError ? (
        <p className="text-sm text-destructive">
          couldn&apos;t load the listening materials.
        </p>
      ) : !data || data.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-border py-16 text-center">
          <Headphones className="size-6 text-muted-foreground/50" aria-hidden />
          <p className="text-sm text-muted-foreground">
            nothing to practise yet.
          </p>
          <Link
            to="/studio/listening/new"
            className="text-xs text-primary transition-colors hover:underline"
          >
            write one in the studio
          </Link>
        </div>
      ) : (
        <ol className="divide-y divide-border border-y border-border">
          {data.map((m) => (
            <Row key={m.id} material={m} />
          ))}
        </ol>
      )}
    </div>
  );
}

function Row({ material: m }: { material: PracticeMaterial }) {
  const done = m.attempts > 0 && m.best_score !== null;
  const pct =
    done && m.question_count > 0
      ? Math.round((m.best_score! / m.question_count) * 100)
      : null;

  return (
    <li className="group flex items-center gap-4 py-3">
      {/* Whether it has been sat, in the leftmost column, so the eye can run
          down one edge to find what is left. */}
      <span
        aria-hidden
        className={cn(
          "flex size-5 shrink-0 items-center justify-center rounded-full border",
          done
            ? "border-primary/40 bg-primary/10 text-primary"
            : "border-border text-transparent",
        )}
      >
        <Check className="size-3" />
      </span>

      <div className="min-w-0 flex-1">
        <Link
          to={`/listening/${m.id}`}
          className="truncate font-medium text-foreground transition-colors group-hover:text-primary"
        >
          {m.title}
        </Link>
        <p className="mt-0.5 font-mono text-xs text-muted-foreground tabular-nums">
          {m.question_count} question{m.question_count === 1 ? "" : "s"}
          {m.part_count > 1 && ` · ${m.part_count} parts`}
          {m.duration_ms != null && ` · ${fmtClock(m.duration_ms)}`}
          {m.attempts > 1 && ` · ${m.attempts} attempts`}
          {m.last_attempt_at && ` · ${timeAgo(m.last_attempt_at)}`}
        </p>
      </div>

      {/* The score IS the way back to the review — a separate "see result"
          link beside a number that already says it would be two things to
          read where the page has one thing to say. */}
      {done && m.last_attempt_id ? (
        <Link
          to={`/listening/attempts/${m.last_attempt_id}`}
          title="Your last result"
          className="shrink-0 rounded-md px-2 py-1 text-right font-mono text-xs tabular-nums transition-colors hover:bg-foreground/8"
        >
          <span className="text-primary">
            {m.best_score}
            <span className="text-muted-foreground">/{m.question_count}</span>
          </span>
          {pct !== null && (
            <span className="ml-2 text-muted-foreground">{pct}%</span>
          )}
        </Link>
      ) : (
        <Link
          to={`/listening/${m.id}`}
          className="shrink-0 rounded-md px-3 py-1.5 text-xs text-muted-foreground transition-colors group-hover:bg-primary group-hover:text-primary-foreground"
        >
          start
        </Link>
      )}
    </li>
  );
}

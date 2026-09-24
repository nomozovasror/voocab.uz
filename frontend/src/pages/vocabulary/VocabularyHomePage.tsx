import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { toast } from "@/lib/toast";
import { getErrorMessage } from "@/lib/api";
import { localTimeZone, timeUntil } from "@/lib/time";
import { practiceSummaryKey, vocabularyApi } from "@/features/vocabulary/api";
import type { VocabularySettings } from "@/features/vocabulary/types";

const MINUTES_OPTIONS: VocabularySettings["daily_minutes"][] = [5, 10, 15, 20];

/**
 * The practice module's home — not the word list, and that distinction is
 * the whole reason `/vocabulary` and `/vocabulary/words` are two routes now
 * rather than one. A list is something you consult; this is the door into a
 * spaced-repetition habit, and the one number that matters on it is what is
 * due TODAY, not how many words exist in total (that is `totals.total`, and
 * it is printed smaller, on purpose).
 *
 * ## Where the queue is built
 *
 * `Start` does not itself call `POST /practice/session` — the practice page
 * does, on mount. Building the queue twice (once to preview a count here,
 * once for real on the next screen) would be two different plans of a
 * budget that shrinks as it is spent, and the two could disagree about how
 * many words fit today. This screen only ever reads `summary`, which is the
 * cheap, side-effect-free half of the same arithmetic.
 */
export default function VocabularyHomePage() {
  const tz = localTimeZone();
  const qc = useQueryClient();
  const navigate = useNavigate();

  const { data, isPending, isError } = useQuery({
    queryKey: practiceSummaryKey(tz),
    queryFn: () => vocabularyApi.practiceSummary(tz),
  });

  const updateMinutes = useMutation({
    mutationFn: (minutes: VocabularySettings["daily_minutes"]) =>
      vocabularyApi.updateSettings(minutes),
    // Patched at once so the picker answers the tap, then re-planned: the
    // minutes are the input to every other number on this page, and a
    // patch alone left the old budget's count — and a hidden Start button —
    // on screen for up to a minute after 5 became 20.
    onSuccess: (settings) => {
      qc.setQueryData(practiceSummaryKey(tz), (was) =>
        was ? { ...was, daily_minutes: settings.daily_minutes } : was,
      );
      void qc.invalidateQueries({ queryKey: practiceSummaryKey(tz) });
    },
    onError: (e) => toast(getErrorMessage(e)),
  });

  if (isPending) return <HomeSkeleton />;

  if (isError || !data) {
    return (
      <div className="mx-auto w-full max-w-xl py-16">
        <h1 className="text-2xl font-semibold text-foreground">Vocabulary</h1>
        <p className="mt-2 text-sm text-destructive">
          Your practice couldn&apos;t be loaded.
        </p>
      </div>
    );
  }

  // Nothing saved at all — not "nothing due today", which is an ordinary and
  // even a good state to be in, but no words to practise full stop. The
  // brief's own line for this: point them at where words come from rather
  // than showing a due count of zero, which reads as "you're all caught up"
  // on a module nobody has ever used.
  if (data.totals.total === 0) return <Empty />;

  const planned = data.planned_reviews + data.planned_new;

  return (
    <div className="mx-auto w-full max-w-xl pb-24 pt-2">
      <header className="pb-6">
        <h1 className="text-2xl font-semibold text-foreground">Vocabulary</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          The words you saved, practised the way that actually keeps them.
        </p>
      </header>

      <section className="rounded-2xl border border-border bg-card px-6 py-10 text-center">
        {planned > 0 ? (
          <>
            <p className="text-5xl font-bold tabular-nums text-foreground">
              {planned}
            </p>
            <p className="mt-1.5 text-sm text-muted-foreground">
              {planned === 1 ? "word" : "words"} waiting today
            </p>
            <Button
              type="button"
              size="lg"
              onClick={() => navigate("/vocabulary/practice")}
              className="mt-6 gap-1.5 px-6"
            >
              <Play className="size-4" aria-hidden />
              Start
            </Button>
          </>
        ) : (
          // The budget is spent, or there is nothing overdue and no time
          // left to buy new ones — either way there is truthfully nothing to
          // do, and a Start button that opens an empty session is worse than
          // no button.
          <>
            <p className="text-lg font-medium text-foreground">
              All caught up
            </p>
            <p className="mt-1.5 text-sm text-muted-foreground">
              {data.next_due_at
                ? `Next review ${timeUntil(data.next_due_at)}.`
                : "Nothing scheduled yet — save a few more words."}
            </p>
          </>
        )}
      </section>

      <dl className="mt-6 grid grid-cols-3 gap-3">
        <Total label="Total" value={data.totals.total} />
        <Total label="Learning" value={data.totals.learning} />
        <Total label="Mastered" value={data.totals.mastered} />
      </dl>

      <div className="mt-6 flex items-center justify-between gap-4 rounded-xl border border-border px-4 py-3">
        <div>
          <p className="text-sm text-foreground">Daily practice</p>
          <p className="text-xs text-muted-foreground">
            How much time this buys in new words each day.
          </p>
        </div>
        <MinutesPicker
          value={data.daily_minutes}
          onChange={(minutes) => updateMinutes.mutate(minutes)}
          busy={updateMinutes.isPending}
        />
      </div>

      <Link
        to="/vocabulary/words"
        className="mt-6 block text-center text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        All words ({data.totals.total})
      </Link>
    </div>
  );
}

function Total({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-border px-3 py-3 text-center">
      <p className="text-xl font-semibold tabular-nums text-foreground">
        {value}
      </p>
      <p className="text-xs text-muted-foreground">{label}</p>
    </div>
  );
}

/** Five/ten/fifteen/twenty, as a row of pills rather than a `<select>` — four
 *  options are a control you can see the whole of at once, and a native
 *  dropdown hides three of them behind a click for no reason here. */
function MinutesPicker({
  value,
  onChange,
  busy,
}: {
  value: number;
  onChange: (minutes: VocabularySettings["daily_minutes"]) => void;
  busy: boolean;
}) {
  return (
    <div
      role="group"
      aria-label="Daily practice time, in minutes"
      className="flex gap-1 rounded-full border border-border bg-surface-sunken p-1"
    >
      {MINUTES_OPTIONS.map((minutes) => {
        const on = value === minutes;
        return (
          <button
            key={minutes}
            type="button"
            disabled={busy}
            aria-pressed={on}
            onClick={() => onChange(minutes)}
            className={cn(
              "rounded-full px-2.5 py-1 text-xs font-medium tabular-nums transition-colors duration-fast focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-50",
              on
                ? "bg-primary/20 text-primary"
                : "text-muted-foreground hover:bg-surface-hover hover:text-foreground",
            )}
          >
            {minutes}
          </button>
        );
      })}
    </div>
  );
}

/** No saved words at all. Named after the thing that fills it, the same rule
 *  the list page's own empty state follows — pointing at the review page
 *  rather than describing the emptiness, because a learner who has never
 *  saved a word does not yet know that page exists. */
function Empty() {
  return (
    <div className="mx-auto w-full max-w-xl pb-24 pt-2">
      <header className="pb-6">
        <h1 className="text-2xl font-semibold text-foreground">Vocabulary</h1>
      </header>
      <div className="rounded-xl border border-dashed border-border px-5 py-10 text-center">
        <p className="text-sm text-muted-foreground">
          There is nothing to practise yet. Sit a reading passage, and the
          words worth learning from it are waiting on the review page
          afterwards — save a few, and they land here.
        </p>
        <Link
          to="/reading"
          className="mt-4 inline-flex items-center gap-1.5 text-sm text-primary transition-colors hover:underline"
        >
          <BookOpen className="size-3.5" aria-hidden />
          Find a passage
        </Link>
      </div>
    </div>
  );
}

/** The page's shape, held open while the summary loads. Built from the real
 *  layout's own class strings — see `frontend/CLAUDE.md`. */
function HomeSkeleton() {
  return (
    <SkeletonBlock
      label="Loading your practice"
      className="mx-auto w-full max-w-xl pb-24 pt-2"
    >
      <header className="pb-6">
        <h1 className="text-2xl font-semibold">
          <Skeleton className="inline-block h-[0.8em] w-32" />
        </h1>
        <p className="mt-1 text-sm">
          <Skeleton className="inline-block h-[0.8em] w-72 max-w-full" />
        </p>
      </header>
      <section className="rounded-2xl border border-border bg-card px-6 py-10 text-center">
        <p className="text-5xl font-bold">
          <Skeleton className="mx-auto inline-block h-[0.8em] w-16" />
        </p>
        <p className="mt-1.5 text-sm">
          <Skeleton className="mx-auto inline-block h-[0.8em] w-28" />
        </p>
        <Skeleton className="mx-auto mt-6 h-9 w-28 rounded-lg" />
      </section>
      <div className="mt-6 grid grid-cols-3 gap-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="rounded-xl border border-border px-3 py-3 text-center">
            <p className="text-xl">
              <Skeleton className="mx-auto inline-block h-[0.8em] w-8" />
            </p>
            <p className="text-xs">
              <Skeleton className="mx-auto mt-1 inline-block h-[0.8em] w-14" />
            </p>
          </div>
        ))}
      </div>
      <div className="mt-6 h-[3.75rem] rounded-xl border border-border" />
    </SkeletonBlock>
  );
}

import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, Play, Settings } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { localTimeZone, timeUntil } from "@/lib/time";
import { practiceSummaryKey, vocabularyApi } from "@/features/vocabulary/api";
import { MODE_LABEL } from "@/features/vocabulary/status";
import type { PracticeMode } from "@/features/vocabulary/types";

const MODES: PracticeMode[] = ["auto", "recognise", "recall", "produce"];

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
 * cheap, side-effect-free half of the same arithmetic — now once per `mode`
 * the picker below is set to, for the same reason.
 *
 * ## Stage 2 moved daily minutes to Settings
 *
 * Stage 1 put the minutes picker here. The spec's own list of what this
 * screen shows (mode picker, the set-aside line, a link to Settings) does
 * not mention it, and Settings' screen 6 lists it as one of its three
 * fields — so it now lives there and only there, rather than in two places
 * that would have to agree.
 */
export default function VocabularyHomePage() {
  const tz = localTimeZone();
  const navigate = useNavigate();
  // Not persisted: the whole point of "bugun faqat yozish" (the brief's own
  // example, spec §7) is a choice about TODAY, not a standing preference —
  // that one lives in Settings' `exercise_types` instead.
  const [mode, setMode] = useState<PracticeMode>("auto");

  const { data, isPending, isError } = useQuery({
    queryKey: practiceSummaryKey(tz, mode),
    queryFn: () => vocabularyApi.practiceSummary(tz, mode),
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
      <header className="flex items-start justify-between gap-4 pb-6">
        <div>
          <h1 className="text-2xl font-semibold text-foreground">Vocabulary</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            The words you saved, practised the way that actually keeps them.
          </p>
        </div>
        <Link
          to="/vocabulary/settings"
          aria-label="Vocabulary settings"
          title="Settings"
          className="flex size-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors duration-fast hover:bg-surface-hover hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          <Settings className="size-4" aria-hidden />
        </Link>
      </header>

      <ModePicker value={mode} onChange={setMode} />

      <section className="mt-4 rounded-2xl border border-border bg-card px-6 py-10 text-center">
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
              onClick={() =>
                navigate(
                  mode === "auto"
                    ? "/vocabulary/practice"
                    : `/vocabulary/practice?mode=${mode}`,
                )
              }
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

      {/* Said rather than hidden — a word that has been set aside and will
       *  come back in three weeks is not a word that vanished, and the spec
       *  is explicit that nothing here should read as a silent forget. */}
      {data.set_aside > 0 && (
        <Link
          to="/vocabulary/words?status=suspended"
          className="mt-4 block rounded-xl border border-border px-4 py-3 text-sm text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
        >
          {data.set_aside} {data.set_aside === 1 ? "word" : "words"} set aside
        </Link>
      )}

      <Link
        to="/vocabulary/words"
        className="mt-6 block text-center text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        All words ({data.totals.total})
      </Link>
    </div>
  );
}

/** Mixed · Recognise · Fill the gap · Write — a row of pills exactly like
 *  stage 1's minutes picker, and for the same reason: four options are a
 *  control you can see the whole of at once. `role="radiogroup"` rather
 *  than `role="group"` (unlike the minutes picker) because these four are
 *  genuinely mutually exclusive alternatives, not four independent
 *  toggles. */
function ModePicker({
  value,
  onChange,
}: {
  value: PracticeMode;
  onChange: (mode: PracticeMode) => void;
}) {
  return (
    <div
      role="radiogroup"
      aria-label="What to practise today"
      className="flex gap-1 rounded-full border border-border bg-surface-sunken p-1"
    >
      {MODES.map((mode) => {
        const on = value === mode;
        return (
          <button
            key={mode}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onChange(mode)}
            className={cn(
              "flex-1 rounded-full px-2.5 py-1.5 text-xs font-medium transition-colors duration-fast focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
              on
                ? "bg-primary/20 text-primary"
                : "text-muted-foreground hover:bg-surface-hover hover:text-foreground",
            )}
          >
            {MODE_LABEL[mode]}
          </button>
        );
      })}
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
      <header className="flex items-start justify-between gap-4 pb-6">
        <div>
          <h1 className="text-2xl font-semibold">
            <Skeleton className="inline-block h-[0.8em] w-32" />
          </h1>
          <p className="mt-1 text-sm">
            <Skeleton className="inline-block h-[0.8em] w-72 max-w-full" />
          </p>
        </div>
        <Skeleton className="size-8 shrink-0 rounded-lg" />
      </header>
      <Skeleton className="h-9 w-full rounded-full" />
      <section className="mt-4 rounded-2xl border border-border bg-card px-6 py-10 text-center">
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
    </SkeletonBlock>
  );
}

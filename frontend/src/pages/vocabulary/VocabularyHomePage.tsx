import { useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, Headphones, Play, Settings } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { localTimeZone, timeUntil } from "@/lib/time";
import { armAudioUnlock } from "@/features/vocabulary/audio";
import {
  practiceSummaryKey,
  vocabularyApi,
  wordListsKey,
} from "@/features/vocabulary/api";
import {
  WordListCards,
  WordListCardsSkeleton,
} from "@/features/vocabulary/components/WordListCards";

/**
 * The practice module's home — not the word list, and that distinction is
 * the whole reason `/vocabulary` and `/vocabulary/words` are two routes now
 * rather than one. A list is something you consult; this is the door into a
 * spaced-repetition habit, and the one number that matters on it is what is
 * due TODAY.
 *
 * ## The fixes brief's own shape for this screen (F1)
 *
 * Today's amount, a Start button, a short progress row (total / learning /
 * mastered — stage 1's brief asks for it and stage 2 does not take it away),
 * the "N words set aside" line, and links to the words list and Settings.
 * Nothing else — no mode picker (that was a
 * per-session override the addendum's single manual choice in Settings has
 * superseded, per B4/F1) and no daily minutes (moved to Settings in stage 2
 * already, and the brief's own list of what this screen shows still doesn't
 * mention it).
 *
 * ## Where the queue is built
 *
 * `Start` does not itself call `POST /practice/session` — the practice page
 * does, on mount. This screen only ever reads `summary`, the cheap,
 * side-effect-free half of the same arithmetic.
 */
export default function VocabularyHomePage() {
  const tz = localTimeZone();
  const navigate = useNavigate();

  // The Start press unlocks the audio element for iOS Safari, so the listen
  // card that follows can play without a gesture of its own.
  useEffect(() => armAudioUnlock(), []);

  const { data, isPending, isError } = useQuery({
    queryKey: practiceSummaryKey(tz),
    queryFn: () => vocabularyApi.practiceSummary(tz),
  });

  // Whether a manual exercise type is what's making today's amount zero —
  // read to tell "you've cleared everything" apart from "you asked for just
  // one task and nothing is at that rung yet" (F2). Shares the settings
  // page's own cache key, so this never fires an extra request once that
  // page has been visited.
  const { data: settings } = useQuery({
    queryKey: ["vocabulary", "settings"],
    queryFn: () => vocabularyApi.settings(),
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
  //
  // "Nothing saved" is not enough on its own: a learner who has started a
  // Word list owns no saved word yet and still has today's new words waiting
  // (the list items become words when answered).
  const planned = data.planned_reviews + data.planned_new;
  if (data.totals.total === 0 && planned === 0) return <Empty />;
  const manualEmpty = planned === 0 && settings?.exercise_types != null;

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
        ) : manualEmpty ? (
          // The learner picked one task in Settings and nothing is at that
          // rung of the ladder right now — never "All caught up", which
          // would read as nothing left to learn at all (F2).
          <p className="text-sm text-muted-foreground">
            No words are ready for this yet.
          </p>
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

      {/* Independent of today's amount on purpose: it plays whatever is in
       *  rotation, so it is offered whether or not anything is due. Named
       *  "On the go" and nothing else (not "Listen", which is an exercise). */}
      <Link
        to="/vocabulary/on-the-go"
        className="mt-4 flex items-center gap-3 rounded-xl border border-border px-4 py-3 transition-colors hover:border-primary/40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        <Headphones className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        <span>
          <span className="block text-sm text-foreground">On the go</span>
          <span className="block text-xs text-muted-foreground">
            Your words, played one after another. No screen needed.
          </span>
        </span>
      </Link>

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

      <WordListsSection />

      <Link
        to="/vocabulary/words"
        className="mt-6 block text-center text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        All words ({data.totals.total})
      </Link>
    </div>
  );
}

/** Ready-made lists a learner can start from. Subscribing adds no words —
 *  see the module's CLAUDE.md. Renders nothing when the lists cannot be
 *  loaded: the practice home must not be taken down by a shelf beside it. */
function WordListsSection() {
  const { data, isPending, isError } = useQuery({
    queryKey: wordListsKey,
    queryFn: () => vocabularyApi.lists(),
  });
  if (isError || (data && data.length === 0)) return null;
  return (
    <section aria-labelledby="word-lists-heading" className="mt-8">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2
          id="word-lists-heading"
          className="text-sm font-medium text-foreground"
        >
          Word lists
        </h2>
        <Link
          to="/vocabulary/lists"
          className="rounded text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          About the lists
        </Link>
      </div>
      {isPending ? (
        <WordListCardsSkeleton />
      ) : (
        <WordListCards lists={data} />
      )}
    </section>
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
          There is nothing to practise yet. Start a word list below, or sit a
          reading passage and save the words worth learning from its review
          page — either way they land here.
        </p>
        <Link
          to="/reading"
          className="mt-4 inline-flex items-center gap-1.5 text-sm text-primary transition-colors hover:underline"
        >
          <BookOpen className="size-3.5" aria-hidden />
          Find a passage
        </Link>
      </div>
      <WordListsSection />
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
    </SkeletonBlock>
  );
}

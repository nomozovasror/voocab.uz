import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { toast } from "@/lib/toast";
import { getErrorMessage } from "@/lib/api";
import { localTimeZone, timeUntil } from "@/lib/time";
import { GapField } from "@/features/paper/components/GapField";
import { CefrTag } from "@/features/vocabulary/components/CefrTag";
import { meanings } from "@/features/vocabulary/meaning";
import { pickJoke, type SessionStats } from "@/features/vocabulary/jokes";
import { practiceSummaryKey, vocabularyApi } from "@/features/vocabulary/api";
import type {
  PracticeAnswer,
  PracticeItem,
} from "@/features/vocabulary/types";

/** One answered turn, kept for the end screen's stats and joke. A word
 *  answered twice in one session (it came back after an Again) appears here
 *  twice — `sessionStats` below is what collapses that back to "one word,
 *  two attempts" rather than counting it as two words. */
interface Turn {
  item: PracticeItem;
  result: PracticeAnswer;
}

/**
 * The practice session, then its end screen — one component, because the
 * queue that drives the first half is also the source of the second half's
 * stats, and splitting them into two routes would mean passing that queue
 * through router state or refetching a session that has already been spent.
 *
 * ## The queue lives here, not on the server
 *
 * `POST /practice/session` is called once, on mount, and its `items` become
 * local state that this page mutates directly: popping the front off on
 * every answer, pushing the same item back onto the END when the server
 * says `returns_this_session`. The server is never asked "what's next" a
 * second time — it doesn't know either, because the queue's own order past
 * the first requeue is a client-side fact, not something FSRS decides.
 *
 * ## Calm, on purpose
 *
 * One word. No sidebar, no timer visible, no list of what's coming. The
 * brief's word for this screen is "tinch" (calm) and the take screen right
 * next door is the opposite of that by design — a forty-question paper with
 * a navigator strip and a clock. This has neither, because there is nothing
 * here to navigate between; there is one word, and then there is the next
 * one.
 */
export default function VocabularyPracticePage() {
  const tz = localTimeZone();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const exit = () => navigate("/vocabulary");

  const { data, isPending, isError } = useQuery({
    queryKey: ["vocabulary", "practice", "session", tz],
    queryFn: () => vocabularyApi.practiceSession(tz),
    // Never served from a previous mount's cache: reloading this page is
    // meant to re-plan, not resume a stale plan from ten minutes ago that
    // may no longer reflect what's due.
    staleTime: 0,
    gcTime: 0,
  });

  // `null` while the session hasn't landed yet; `[]` once every item — the
  // ones the server sent, plus every requeue — has been answered. Those are
  // two different reasons to render nothing further, kept as one variable
  // because the render logic already has to ask "do we have a current
  // item?" and null vs. empty both answer "no".
  const [queue, setQueue] = useState<PracticeItem[] | null>(null);
  const [totalCount, setTotalCount] = useState(0);
  const [answeredCount, setAnsweredCount] = useState(0);
  const [given, setGiven] = useState("");
  const [result, setResult] = useState<PracticeAnswer | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  // Wall-clock, not a React state value: resetting it must never itself
  // cause a render, and reading it happens only once, at submit.
  const shownAt = useRef(Date.now());

  useEffect(() => {
    if (data && queue === null) {
      setQueue(data.items);
      setTotalCount(data.items.length);
      shownAt.current = Date.now();
    }
  }, [data, queue]);

  // Esc exits from anywhere on this page, focus or no focus — the field
  // itself also handles it while typing (see below), but a learner who has
  // clicked the source-material link or is mid-reveal with the field blurred
  // still needs a way out that doesn't depend on where the pointer last was.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        exit();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const ended = queue !== null && queue.length === 0;

  // Once the queue is spent, the numbers this session made stale — due
  // count, totals, next review — are refetched under the SAME key the home
  // screen reads, so going back there shows what just happened rather than
  // what was true when this page opened.
  useEffect(() => {
    if (ended) void qc.invalidateQueries({ queryKey: practiceSummaryKey(tz) });
  }, [ended, tz, qc]);

  const { data: freshSummary } = useQuery({
    queryKey: practiceSummaryKey(tz),
    queryFn: () => vocabularyApi.practiceSummary(tz),
    enabled: ended,
  });

  const answer = useMutation({
    mutationFn: vocabularyApi.practiceAnswer,
    onSuccess: (res) => setResult(res),
    onError: (e) => toast(getErrorMessage(e)),
  });

  const current = queue?.[0] ?? null;

  function submit() {
    if (!current || answer.isPending) return;
    answer.mutate({
      word_id: current.word_id,
      context_id: current.context_id,
      direction: current.direction,
      exercise_type: current.exercise_type,
      given,
      elapsed_ms: Date.now() - shownAt.current,
    });
  }

  function advance() {
    if (!current || !result || !queue) return;
    setTurns((was) => [...was, { item: current, result }]);
    const rest = queue.slice(1);
    // The wrong-answer requeue, spelled out where the whole session can see
    // it: the client appends, the server has already rescheduled the card
    // either way (see the spec's §4). `returns_this_session` is exactly
    // `rating === Again`, and nothing else moves a word to the back.
    const next = result.returns_this_session ? [...rest, current] : rest;
    if (result.returns_this_session) setTotalCount((t) => t + 1);
    setAnsweredCount((c) => c + 1);
    setGiven("");
    setResult(null);
    shownAt.current = Date.now();
    setQueue(next);
  }

  if (isPending || queue === null) return <SessionSkeleton />;

  if (isError || !data) {
    return (
      <div className="mx-auto w-full max-w-xl py-16 text-center">
        <p className="text-sm text-destructive">
          Your session couldn&apos;t be built.
        </p>
        <Link
          to="/vocabulary"
          className="mt-3 inline-block text-sm text-primary hover:underline"
        >
          Back to Vocabulary
        </Link>
      </div>
    );
  }

  if (ended) {
    return (
      <EndScreen
        turns={turns}
        nextDueAt={freshSummary?.next_due_at ?? null}
        onExit={exit}
      />
    );
  }

  // Not reachable via the home screen, which hides Start once nothing is
  // due — but the URL is typeable, and the budget can also run out between
  // opening the home screen and pressing Start.
  if (!current) {
    return (
      <div className="mx-auto w-full max-w-xl py-16 text-center">
        <p className="text-sm text-muted-foreground">
          Nothing to practise right now.
        </p>
        <Link
          to="/vocabulary"
          className="mt-3 inline-block text-sm text-primary hover:underline"
        >
          Back to Vocabulary
        </Link>
      </div>
    );
  }

  const position = Math.min(answeredCount + 1, totalCount);
  const prompt = current.prompt;
  const tone = !result
    ? "border-border"
    : result.verdict === "correct"
      ? "border-correct text-correct"
      : result.verdict === "close"
        ? "border-warning text-warning"
        : "border-incorrect text-incorrect";

  return (
    <div className="mx-auto flex min-h-[70vh] w-full max-w-xl flex-col justify-center py-10">
      <div className="flex-1">
        {prompt.kind === "definition" && prompt.definition && (
          // The fallback prompt — no usable example sentence, so the gap
          // stands beside the word's own meaning instead. See the spec's
          // §5: still a `recall` exercise, just without the sentence.
          <p className="text-center text-sm text-muted-foreground italic">
            {prompt.definition}
          </p>
        )}
        <p
          className={cn(
            "text-xl leading-relaxed text-foreground",
            prompt.kind === "definition"
              ? "mt-4 text-center"
              : "text-center sm:text-left",
          )}
        >
          {prompt.before}
          <GapField
            // A fresh key per turn — including a requeued repeat of the same
            // word — so the input remounts and `autoFocus` fires again
            // rather than the browser leaving focus wherever it landed on
            // the previous item.
            key={`${current.word_id}-${answeredCount}`}
            autoFocus
            // What the learner actually typed, kept on screen after
            // grading rather than overwritten with the right answer — the
            // take screen's own completion gap does the same (see
            // `FormCompletionGroup`): the field says what you wrote, its
            // colour says whether that was right, and the correct answer
            // is printed in the reveal panel below rather than substituted
            // into the box you typed in.
            value={given}
            onChange={(e) => setGiven(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                if (result) advance();
                else submit();
              } else if (e.key === "Escape") {
                // Stopped here, or the document listener exits a second
                // time and Back has to be pressed twice to leave.
                e.preventDefault();
                e.stopPropagation();
                exit();
              }
            }}
            disabled={answer.isPending || Boolean(result)}
            placeholder={prompt.cue}
            aria-label={`Type the missing word. It starts with ${prompt.cue}.`}
            tone={tone}
            className="mx-1 w-40"
          />
          {prompt.after}
        </p>
      </div>

      {result && <Reveal result={result} />}

      <p className="mt-10 text-center text-xs tabular-nums text-muted-foreground">
        {position} / {totalCount}
      </p>
    </div>
  );
}

/** What one answer reveals — never sent with the prompt, always after.
 *  Order follows the brief exactly: verdict and the answer itself, then the
 *  word's usual sense, Uzbek under it, `Here: …` only where the passage's
 *  sense genuinely differs (see `meaning.ts`), then the way back to where
 *  it was met. */
function Reveal({ result }: { result: PracticeAnswer }) {
  const sense = meanings(result.word);
  const verdictLabel =
    result.verdict === "correct"
      ? "Correct"
      : result.verdict === "close"
        ? "Close"
        : "Not quite";
  const verdictTone =
    result.verdict === "correct"
      ? "text-correct"
      : result.verdict === "close"
        ? "text-warning"
        : "text-incorrect";

  return (
    <div className="mt-6 rounded-xl border border-border bg-card px-5 py-4">
      <p className={cn("text-sm font-semibold", verdictTone)}>
        {verdictLabel}
        <span className="ml-1.5 font-normal text-muted-foreground">
          — {result.answer}
        </span>
      </p>
      <p className="mt-2.5 flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
        <span className="text-base font-semibold text-foreground">
          {result.word.lemma}
        </span>
        {result.word.pos && (
          <span className="text-xs text-muted-foreground italic">
            {result.word.pos}
          </span>
        )}
        <CefrTag level={result.word.cefr_level} />
      </p>
      <p className="mt-1 text-sm text-foreground">{sense.uz}</p>
      <p className="text-xs text-muted-foreground">{sense.en}</p>
      {sense.here && (
        <p className="mt-1.5 border-l-2 border-border pl-2">
          <span className="block text-sm text-foreground">
            <span className="text-muted-foreground">Here: </span>
            {sense.here.uz}
          </span>
          <span className="block text-xs text-muted-foreground">
            {sense.here.en}
          </span>
        </p>
      )}
      {result.word.material_id && result.word.material_title && (
        <Link
          to={`/reading/${result.word.material_id}`}
          className="mt-2 inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          <BookOpen className="size-3" aria-hidden />
          {result.word.material_title}
        </Link>
      )}
      <p className="mt-3 text-xs text-muted-foreground">
        Enter for the next word · Esc to stop
      </p>
    </div>
  );
}

/** Distinct words this session touched, and the shape `jokes.ts` and the end
 *  screen's stat line both need — collapsed from `turns`, where a word that
 *  came back after an Again appears twice. */
function summarise(turns: Turn[]): SessionStats & {
  newCount: number;
  reviewedCount: number;
} {
  const firstSeenNew = new Map<string, boolean>();
  const wrongCounts = new Map<string, number>();

  for (const { item, result } of turns) {
    if (!firstSeenNew.has(item.word_id)) {
      firstSeenNew.set(item.word_id, item.is_new);
    }
    if (result.verdict === "wrong") {
      wrongCounts.set(item.lemma, (wrongCounts.get(item.lemma) ?? 0) + 1);
    }
  }

  let newCount = 0;
  let reviewedCount = 0;
  for (const isNew of firstSeenNew.values()) {
    if (isNew) newCount += 1;
    else reviewedCount += 1;
  }

  let hardest: string | null = null;
  let hardestCount = 0;
  for (const [lemma, count] of wrongCounts) {
    if (count > hardestCount) {
      hardest = lemma;
      hardestCount = count;
    }
  }

  return {
    total: firstSeenNew.size,
    struggled: wrongCounts.size,
    hardest,
    newCount,
    reviewedCount,
  };
}

/**
 * The end screen: one dry joke, then the small numbers.
 *
 * The brief is explicit about the joke's target — never the learner, only
 * the words or the app itself — which is why `jokes.ts` takes session
 * shapes (how many struggled, which one struggled most) rather than
 * anything that could read as a verdict on the person who just sat here.
 */
function EndScreen({
  turns,
  nextDueAt,
  onExit,
}: {
  turns: Turn[];
  nextDueAt: string | null;
  onExit: () => void;
}) {
  const stats = useMemo(() => summarise(turns), [turns]);
  // Picked once per visit to this screen, not once per render — `pickJoke`
  // draws from a pool at random, and re-rolling it on an unrelated re-render
  // (the summary query landing a moment later) would change the joke under
  // a reader mid-sentence.
  const joke = useMemo(
    () => pickJoke(stats),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [stats.total, stats.struggled, stats.hardest],
  );

  if (stats.total === 0) {
    return (
      <div className="mx-auto w-full max-w-xl py-20 text-center">
        <p className="text-sm text-muted-foreground">
          Nothing to practise right now.
        </p>
        <Button type="button" onClick={onExit} className="mt-4">
          Back to Vocabulary
        </Button>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-xl py-20 text-center">
      <p className="text-xl leading-relaxed text-foreground">{joke}</p>

      <dl className="mt-8 flex items-center justify-center gap-8">
        <EndStat label="new" value={stats.newCount} />
        <EndStat label="reviewed" value={stats.reviewedCount} />
      </dl>

      <p className="mt-6 text-sm text-muted-foreground">
        Next session {timeUntil(nextDueAt)}.
      </p>

      <Button type="button" onClick={onExit} className="mt-8">
        Done
      </Button>
    </div>
  );
}

function EndStat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <p className="text-2xl font-semibold tabular-nums text-foreground">
        {value}
      </p>
      <p className="text-xs text-muted-foreground">{label}</p>
    </div>
  );
}

/** Held open while the session builds. One centred bar for the sentence,
 *  one for the progress line — the shape of a screen that has almost
 *  nothing on it to begin with. */
function SessionSkeleton() {
  return (
    <SkeletonBlock
      label="Building your session"
      className="mx-auto flex min-h-[70vh] w-full max-w-xl flex-col justify-center py-10"
    >
      <div className="flex-1 text-center">
        <p className="text-xl">
          <Skeleton className="mx-auto inline-block h-[0.8em] w-64 max-w-full" />
        </p>
      </div>
      <p className="mt-10 text-center text-xs">
        <Skeleton className="mx-auto inline-block h-[0.8em] w-10" />
      </p>
    </SkeletonBlock>
  );
}

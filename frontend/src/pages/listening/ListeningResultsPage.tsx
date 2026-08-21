import { useMemo, useRef } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { ArrowLeft, Check, RotateCcw, Volume2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { fmtClock } from "@/lib/time";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { mediaUrl } from "@/features/listening/api";
import { useAttempt, useTakeMaterial } from "@/features/listening/queries";
import {
  PartChips,
  QuestionPaper,
} from "@/features/listening/components/QuestionPaper";
import {
  AudioSkeleton,
  PaperSkeleton,
} from "@/features/listening/components/PaperSkeleton";
import {
  TakeAudio,
  type TakeAudioHandle,
} from "@/features/listening/components/TakeAudio";
import { questionNumbersShort, sorted } from "@/features/listening/numbering";
import { PRACTICE } from "@/features/listening/take-config";
import { usePartSpy } from "@/features/listening/use-part-spy";
import type { AttemptResult, QuestionResult } from "@/features/listening/types";

/**
 * What one attempt came to — on the paper it was sat on.
 *
 * The questions are fetched back from the same take endpoint that drew them
 * in the first place, and drawn by the same component, because a review has
 * to put the candidate back in front of what they were looking at. Told any
 * other way — a list of "18 ✗ C" — a letter answer means nothing at all: C is
 * a place on a map or a line in a box, and printing the letter alone is
 * printing the storage format.
 *
 * Two requests, in sequence, because the attempt is what says which material
 * to ask for. The compact list below is not a loading state but a fallback:
 * an attempt outlives the material's visibility, and a review of a paper that
 * has since been unpublished should still show what was answered.
 *
 * The URL is the attempt, which is what makes the page survive a reload. The
 * submit hands its result over through navigation state so nothing is fetched
 * twice on the way in; arriving any other way, it asks by id and gets an
 * identical object, because one function on the server answers both.
 */
export default function ListeningResultsPage() {
  const { attemptId } = useParams<{ attemptId: string }>();
  const location = useLocation();
  const seed = (location.state as { result?: AttemptResult } | null)?.result;
  const { data, isLoading, isError } = useAttempt(attemptId, seed);
  const { data: material, isError: paperGone } = useTakeMaterial(
    data?.material_id,
  );
  const audio = useRef<TakeAudioHandle>(null);

  const parts = useMemo(
    () => (material ? sorted(material.parts) : []),
    [material],
  );
  const activePart = usePartSpy(parts);

  const byQuestion = useMemo(() => {
    const map: Record<string, QuestionResult> = {};
    for (const r of data?.results ?? []) map[r.question_id] = r;
    return map;
  }, [data]);

  const given = useMemo(() => {
    const map: Record<string, string> = {};
    for (const r of data?.results ?? []) map[r.question_id] = r.given_answer;
    return map;
  }, [data]);

  if (isLoading) return <ResultsSkeleton />;
  if (isError || !data) {
    return (
      <div className="mx-auto max-w-3xl space-y-4 py-10">
        <p className="text-sm text-destructive">couldn&apos;t load this result.</p>
        <Link
          to="/listening"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          back to listening
        </Link>
      </div>
    );
  }

  const pct =
    data.total_questions > 0
      ? Math.round((data.score / data.total_questions) * 100)
      : 0;

  return (
    <div className="mx-auto max-w-3xl pb-24">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 pt-2 pb-4">
        <Link
          to="/listening"
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" />
          listening
        </Link>
        <h1 className="min-w-0 flex-1 truncate text-lg font-semibold text-foreground">
          {data.material_title}
        </h1>
        <Link
          to={`/listening/${data.material_id}`}
          className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-foreground/8 hover:text-foreground"
        >
          <RotateCcw className="size-3.5" />
          take it again
        </Link>
      </div>

      <div className="flex items-baseline gap-3 rounded-lg border border-border bg-card px-5 py-4">
        <span className="font-mono text-4xl leading-none font-bold text-primary tabular-nums">
          {data.score}
        </span>
        <span className="font-mono text-sm text-muted-foreground">
          / {data.total_questions}
        </span>
        <span className="ml-auto font-mono text-sm text-muted-foreground tabular-nums">
          {pct}%
        </span>
      </div>

      {data.audio_url && (
        <div className="sticky top-[3.75rem] z-20 -mx-1 mt-4 bg-background/90 px-1 py-2 backdrop-blur-md">
          <TakeAudio
            ref={audio}
            src={mediaUrl(data.audio_url)}
            durationMs={data.duration_ms}
            // Nothing is being measured any more, so nothing is restricted.
            config={PRACTICE}
          />
          {material && <PartChips parts={parts} active={activePart} />}
        </div>
      )}

      {material ? (
        <div className="mt-6">
          <QuestionPaper
            material={material}
            answers={given}
            results={byQuestion}
            onReplay={(start, end) => audio.current?.playRange(start, end)}
            onPlayPart={
              data.audio_url
                ? (start, end) => audio.current?.playRange(start, end)
                : undefined
            }
            disabled
          />
          <Transcripts results={data.results} />
        </div>
      ) : paperGone ? (
        <CompactList data={data} onReplay={(s, e) => audio.current?.playRange(s, e)} />
      ) : (
        // Neither yet. The paper is still coming — and this page always waits
        // for it, because the attempt has to arrive first to say which
        // material to ask for. Showing the compact fallback in the meantime
        // would flash a whole different page and then replace it.
        <SkeletonBlock label="Loading the paper" className="mt-6">
          <PaperSkeleton />
        </SkeletonBlock>
      )}
    </div>
  );
}

/** What was actually said, question by question.
 *
 *  Kept apart from the paper rather than printed beside each gap. On the
 *  paper an answer is a word in a box; the transcript is a sentence, and
 *  threading sentences through a form or across a map would take the layout
 *  apart to say something the candidate reads afterwards, in order, once. */
function Transcripts({ results }: { results: QuestionResult[] }) {
  const withText = results.filter((r) => r.transcript && r.transcript.length);
  if (!withText.length) return null;
  return (
    <section className="mt-12">
      <h2 className="mb-4 border-b border-border pb-2 text-xs tracking-[0.14em] text-muted-foreground uppercase">
        where the answers are said
      </h2>
      <ol className="divide-y divide-border">
        {withText.map((r) => (
          <li key={r.question_id} className="flex gap-3 py-2.5">
            <span
              className={cn(
                "w-9 shrink-0 pt-0.5 text-right font-mono text-xs tabular-nums",
                r.is_correct ? "text-success" : "text-destructive",
              )}
            >
              {questionNumbersShort(r.number, r.marks ?? 1)}
            </span>
            <p className="min-w-0 flex-1 text-xs leading-relaxed text-muted-foreground">
              {r.transcript!.map((line) => line.text).join(" ")}
            </p>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** The fallback: everything the attempt knows, without the paper. Reached
 *  when the material can no longer be fetched — unpublished since, most
 *  likely. Worse than the marked paper, and much better than an error. */
function CompactList({
  data,
  onReplay,
}: {
  data: AttemptResult;
  onReplay: (startMs: number | null, endMs: number | null) => void;
}) {
  return (
    <ol className="mt-6 divide-y divide-border">
      {data.results.map((r) => {
        const say = (v: string) =>
          r.answered_by === "letters"
            ? v
                .split(",")
                .map((x) => x.trim().toUpperCase())
                .filter(Boolean)
                .join(" and ")
            : v.trim();
        return (
          <li key={r.question_id} className="flex flex-wrap gap-x-3 gap-y-1 py-3">
            <span className="w-9 shrink-0 pt-0.5 text-right font-mono text-xs text-muted-foreground tabular-nums">
              {questionNumbersShort(r.number, r.marks ?? 1)}
            </span>
            <span
              aria-hidden
              className={cn(
                "mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full",
                r.is_correct
                  ? "bg-success/15 text-success"
                  : "bg-destructive/15 text-destructive",
              )}
            >
              {r.is_correct ? <Check className="size-3" /> : <X className="size-3" />}
            </span>

            <div className="min-w-0 flex-1">
              <p className="text-sm">
                <span
                  className={cn(
                    "font-medium",
                    r.is_correct ? "text-success" : "text-destructive",
                    !r.given_answer.trim() && "text-muted-foreground italic",
                  )}
                >
                  {say(r.given_answer) || "left blank"}
                </span>
                {!r.is_correct && r.correct_answers.length > 0 && (
                  <span className="ml-2 text-muted-foreground">
                    →{" "}
                    {r.answered_by === "letters"
                      ? say(r.correct_answers.join(","))
                      : r.correct_answers.join(" / ")}
                  </span>
                )}
              </p>
              {r.transcript && r.transcript.length > 0 && (
                <p className="mt-1 border-l-2 border-border pl-2 text-xs leading-relaxed text-muted-foreground">
                  {r.transcript.map((line) => line.text).join(" ")}
                </p>
              )}
            </div>

            {data.audio_url && r.replay_start_ms != null && (
              <button
                type="button"
                onClick={() => onReplay(r.replay_start_ms, r.replay_end_ms)}
                title={`Hear where answer ${r.number} is said`}
                aria-label={`Hear where answer ${r.number} is said`}
                className="flex h-6 shrink-0 items-center gap-1.5 self-start rounded-md px-1.5 font-mono text-xs text-muted-foreground transition-colors hover:bg-foreground/8 hover:text-primary"
              >
                <Volume2 className="size-3.5" aria-hidden />
                {fmtClock(r.replay_start_ms ?? 0)}
              </button>
            )}
          </li>
        );
      })}
    </ol>
  );
}

/**
 * The review's shape while the attempt loads. Reached on a reload of the URL;
 * arriving from a submit skips it entirely, because the result travels with
 * the navigation.
 */
function ResultsSkeleton() {
  return (
    <SkeletonBlock label="Loading result" className="mx-auto max-w-3xl pb-24">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 pt-2 pb-4">
        <Link
          to="/listening"
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" />
          listening
        </Link>
        <h1 className="min-w-0 flex-1 truncate text-lg font-semibold">
          <Skeleton className="inline-block h-[0.85em] w-64 max-w-full" />
        </h1>
        <span className="text-xs">
          <Skeleton className="inline-block h-[0.9em] w-24" />
        </span>
      </div>

      {/* The score card, which is the first thing anyone looks for. */}
      <div className="flex items-baseline gap-3 rounded-lg border border-border bg-card px-5 py-4">
        <Skeleton className="h-8 w-10" />
        <Skeleton className="h-4 w-12" />
        <Skeleton className="ml-auto h-4 w-10" />
      </div>

      <div className="sticky top-[3.75rem] z-20 -mx-1 mt-4 bg-background/90 px-1 py-2 backdrop-blur-md">
        <AudioSkeleton />
      </div>

      <div className="mt-6">
        <PaperSkeleton />
      </div>
    </SkeletonBlock>
  );
}

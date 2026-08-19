import { useRef } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { ArrowLeft, Check, RotateCcw, Volume2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { fmtClock } from "@/lib/time";
import { questionNumbersShort } from "@/features/listening/numbering";
import { PageLoader } from "@/components/ui/spinner";
import { mediaUrl } from "@/features/listening/api";
import { useAttempt } from "@/features/listening/queries";
import {
  TakeAudio,
  type TakeAudioHandle,
} from "@/features/listening/components/TakeAudio";
import { PRACTICE } from "@/features/listening/take-config";
import type { AttemptResult } from "@/features/listening/types";

/**
 * What one attempt came to.
 *
 * Minimal on purpose — the score, the answers, and the moment each one was
 * said. The full review this will grow into (the question as it was printed,
 * the transcript around it, why the accepted answers are the accepted ones)
 * needs no more from the server: the endpoint behind this page already sends
 * all of it, so growing the screen never means reopening the backend.
 *
 * The URL is the attempt, which is what makes this page survive a reload. The
 * submit hands its result over through navigation state so nothing is fetched
 * twice on the way in; arriving any other way, it asks for the attempt by id
 * and gets the identical object, because one function on the server answers
 * both.
 */
export default function ListeningResultsPage() {
  const { attemptId } = useParams<{ attemptId: string }>();
  const location = useLocation();
  const seed = (location.state as { result?: AttemptResult } | null)?.result;
  const { data, isLoading, isError } = useAttempt(attemptId, seed);
  const audio = useRef<TakeAudioHandle>(null);

  if (isLoading) return <PageLoader />;
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
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 pt-2 pb-6">
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
        <span className="font-mono text-3xl leading-none font-bold text-primary tabular-nums">
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
        </div>
      )}

      <ol className="mt-6 divide-y divide-border">
        {data.results.map((r) => {
          const canHear = data.audio_url && r.replay_start_ms != null;
          // Letters are printed the way the paper prints them. A chosen
          // option stored as "b,d" is two letters, and reading them back as
          // "b,d" in a sentence is reading back the storage format.
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
                {r.is_correct ? (
                  <Check className="size-3" />
                ) : (
                  <X className="size-3" />
                )}
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
                        ? // The key is the whole set — "B and D" is one
                          // answer, not two acceptable ones.
                          say(r.correct_answers.join(","))
                        : r.correct_answers.join(" / ")}
                    </span>
                  )}
                </p>
                {/* The author's transcript across the moment, not the
                    machine's — it has to agree with the answer key. */}
                {r.transcript && r.transcript.length > 0 && (
                  <p className="mt-1 border-l-2 border-border pl-2 text-xs leading-relaxed text-muted-foreground">
                    {r.transcript.map((line) => line.text).join(" ")}
                  </p>
                )}
              </div>

              {canHear && (
                <button
                  type="button"
                  onClick={() =>
                    audio.current?.playRange(r.replay_start_ms, r.replay_end_ms)
                  }
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
    </div>
  );
}

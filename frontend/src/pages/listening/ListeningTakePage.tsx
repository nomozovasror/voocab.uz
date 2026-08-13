import { useCallback, useMemo, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { Play, Loader2, RotateCcw, ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageLoader } from "@/components/ui/spinner";
import { toast } from "@/lib/toast";
import { getErrorMessage } from "@/lib/api";
import { mediaUrl } from "@/features/listening/api";
import { useTakeMaterial, useSubmitAttempt } from "@/features/listening/queries";
import { ChoiceGroup } from "@/features/listening/components/ChoiceGroup";
import { questionSpan } from "@/features/listening/numbering";
import { FormCompletionGroup } from "@/features/listening/components/FormCompletionGroup";
import type {
  AttemptResult,
  MaterialTake,
  QuestionResult,
  TakePart,
} from "@/features/listening/types";

function fmt(ms: number): string {
  const s = ms / 1000;
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

/** Where each group's numbering starts, by group id.
 *
 *  Questions are stored numbered 1..N inside their own group; what the
 *  candidate reads runs across the whole material, so a part of "Questions
 *  1–6" followed by "Questions 7–10" is one walk of the tree in order.
 *  Worked out here rather than sent, because it is the same walk the editor
 *  does — one rule in two places beats two numbers that can disagree.
 *
 *  What accumulates is numbers, not questions: a "Choose TWO letters" is
 *  printed as *Questions 23 and 24* and takes both. */
function groupNumbering(material: MaterialTake): Map<string, number> {
  const startAt = new Map<string, number>();
  let seen = 0;
  for (const part of material.parts
    .slice()
    .sort((a, b) => a.order_index - b.order_index)) {
    for (const group of part.question_groups
      .slice()
      .sort((a, b) => a.order_index - b.order_index)) {
      startAt.set(group.id, seen + 1);
      seen += group.questions.length * questionSpan(group.config.answers_per_question);
    }
  }
  return startAt;
}

export default function ListeningTakePage() {
  const { id } = useParams<{ id: string }>();
  const { data: material, isLoading, isError } = useTakeMaterial(id);
  const submitMut = useSubmitAttempt(id ?? "");

  const audioRef = useRef<HTMLAudioElement>(null);
  const pauseTimer = useRef<number | undefined>(undefined);

  // question_id -> given_answer. correct_answers never enters this state or
  // any prop before submit — the /take payload has no such field, and the
  // only place answers appear is the POST /attempts RESPONSE below.
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [result, setResult] = useState<AttemptResult | null>(null);

  const allQuestionIds = useMemo(() => {
    const ids: string[] = [];
    for (const part of material?.parts ?? []) {
      for (const group of part.question_groups) {
        for (const q of group.questions) ids.push(q.id);
      }
    }
    return ids;
  }, [material]);

  const startNumbers = useMemo(
    () => (material ? groupNumbering(material) : new Map<string, number>()),
    [material],
  );

  const resultsByQuestion = useMemo(() => {
    if (!result) return undefined;
    const map: Record<string, QuestionResult> = {};
    for (const r of result.results) map[r.question_id] = r;
    return map;
  }, [result]);

  /** Plays a stretch of the recording and stops at its end. Used both for a
   *  part and, after grading, for replaying the moment a single answer was
   *  said — the same behaviour either way, so it lives in one place. */
  const playRange = useCallback((startMs: number | null, endMs: number | null) => {
    const audio = audioRef.current;
    if (!audio) return;
    window.clearTimeout(pauseTimer.current);
    audio.currentTime = (startMs ?? 0) / 1000;
    void audio.play();
    if (startMs != null && endMs != null) {
      pauseTimer.current = window.setTimeout(
        () => audio.pause(),
        Math.max(0, endMs - startMs),
      );
    }
  }, []);

  const playPart = (part: TakePart) =>
    playRange(part.audio_start_ms, part.audio_end_ms);

  const onSubmit = () => {
    const payload = {
      answers: allQuestionIds.map((question_id) => ({
        question_id,
        given_answer: answers[question_id] ?? "",
      })),
    };
    submitMut.mutate(payload, {
      onSuccess: (data) => setResult(data),
      onError: (e) => toast(getErrorMessage(e)),
    });
  };

  const tryAgain = () => {
    setResult(null);
    setAnswers({});
  };

  if (!id) return null;
  if (isLoading) return <PageLoader />;
  if (isError || !material) {
    return (
      <div className="mx-auto max-w-3xl space-y-4">
        <p className="text-sm text-destructive">
          Couldn&apos;t load this listening material.
        </p>
        <Button asChild variant="outline">
          <Link to="/listening">
            <ArrowLeft className="size-4" />
            Back to listening
          </Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0 space-y-1">
          <Link
            to="/listening"
            className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-3.5" />
            Listening
          </Link>
          <h1 className="truncate text-2xl font-semibold text-foreground">
            {material.title}
          </h1>
        </div>
      </div>

      {material.audio_url && (
        <Card>
          <CardHeader>
            <CardTitle>Audio</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <audio
              ref={audioRef}
              controls
              src={mediaUrl(material.audio_url)}
              className="w-full"
            />
            {material.parts.length > 1 && (
              <div className="flex flex-wrap gap-2">
                {material.parts
                  .slice()
                  .sort((a, b) => a.order_index - b.order_index)
                  .map((part) => (
                    <Button
                      key={part.id}
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => playPart(part)}
                    >
                      <Play className="size-3.5" />
                      Play {part.title}
                      {part.audio_start_ms != null && part.audio_end_ms != null
                        ? ` (${fmt(part.audio_start_ms)}–${fmt(part.audio_end_ms)})`
                        : ""}
                    </Button>
                  ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {material.parts
        .slice()
        .sort((a, b) => a.order_index - b.order_index)
        .map((part) => (
          <Card key={part.id}>
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle>{part.title}</CardTitle>
              {material.audio_url && material.parts.length === 1 && (
                <Button type="button" variant="outline" size="sm" onClick={() => playPart(part)}>
                  <Play className="size-3.5" />
                  Play this part
                </Button>
              )}
            </CardHeader>
            <CardContent className="space-y-6">
              {part.question_groups
                .slice()
                .sort((a, b) => a.order_index - b.order_index)
                .map((group) => {
                  const shared = {
                    group,
                    answers,
                    onChange: (qid: string, value: string) =>
                      setAnswers((prev) => ({ ...prev, [qid]: value })),
                    startNumber: startNumbers.get(group.id) ?? 1,
                    results: resultsByQuestion,
                    disabled: !!result,
                  };
                  // Anything that isn't multiple choice is rendered as a
                  // form: it is the only other type there is, and a type
                  // this build doesn't know about is better shown as its
                  // template than left out of the paper entirely.
                  return group.type === "multiple_choice" ? (
                    <ChoiceGroup
                      key={group.id}
                      {...shared}
                      onReplay={playRange}
                    />
                  ) : (
                    <FormCompletionGroup
                      key={group.id}
                      {...shared}
                      onReplay={playRange}
                    />
                  );
                })}
            </CardContent>
          </Card>
        ))}

      {/* Announce the outcome for screen-reader users the moment it's known. */}
      <div role="status" aria-live="polite" className="sr-only">
        {result &&
          `Result: ${result.score} out of ${result.total_questions} correct.`}
      </div>

      {result ? (
        <Card>
          <CardContent className="flex items-center justify-between py-4">
            <p className="text-lg font-semibold text-foreground">
              Score: {result.score} / {result.total_questions}
            </p>
            <Button variant="outline" onClick={tryAgain}>
              <RotateCcw className="size-4" />
              Try again
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="flex justify-end">
          <Button onClick={onSubmit} disabled={submitMut.isPending}>
            {submitMut.isPending && <Loader2 className="size-4 animate-spin" />}
            Submit answers
          </Button>
        </div>
      )}
    </div>
  );
}

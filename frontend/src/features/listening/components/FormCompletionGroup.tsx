import { useMemo } from "react";
import { Volume2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { FormLayout } from "@/features/listening/components/FormLayout";
import { parseTemplateLayout } from "@/features/listening/form-syntax";
import { rubricSentence } from "@/features/listening/rubric";
import type { QuestionResult, TakeQuestionGroup } from "@/features/listening/types";

interface FormCompletionGroupProps {
  group: TakeQuestionGroup;
  answers: Record<string, string>;
  onChange: (questionId: string, value: string) => void;
  results?: Record<string, QuestionResult>;
  /** Replays the moment this answer is said. Only ever called after grading:
   *  the timings aren't in the take payload until then. */
  onReplay?: (startMs: number | null, endMs: number | null) => void;
  disabled?: boolean;
}

export function FormCompletionGroup({
  group,
  answers,
  onChange,
  results,
  onReplay,
  disabled,
}: FormCompletionGroupProps) {
  const rubric = rubricSentence(group.config.answer_rubric, group.word_limit);

  const byNumber = useMemo(() => {
    const map = new Map<number, (typeof group.questions)[number]>();
    for (const q of group.questions) map.set(q.number, q);
    return map;
  }, [group.questions]);

  // Same parse the editor previews with, so what the author saw is what the
  // candidate sits — layout can't drift between the two.
  const blocks = useMemo(
    () => parseTemplateLayout(group.config.template),
    [group.config.template],
  );

  return (
    <div className="space-y-3">
      <p className="text-sm text-foreground">{group.instructions}</p>
      {rubric && <p className="text-xs text-muted-foreground">{rubric}</p>}

      <div className="rounded-lg border border-border bg-background p-4">
        <FormLayout
          blocks={blocks}
          renderGap={(n) => {
            const question = byNumber.get(n);
            // A token with no question behind it can only come from a
            // template we didn't author; show the gap rather than pretend.
            if (!question) return <span className="text-muted-foreground">{`{{${n}}}`}</span>;
            const result = results?.[question.id];
            const graded = result !== undefined;
            return (
              <span className="mx-1 inline-flex items-baseline gap-1 align-baseline">
                <span aria-hidden className="text-xs font-semibold text-muted-foreground">
                  {n}
                </span>
                <input
                  type="text"
                  className={cn(
                    "w-32 rounded-md border border-border bg-background px-2 py-0.5 text-sm text-foreground placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                    graded &&
                      (result.is_correct
                        ? "border-success text-success"
                        : "border-destructive text-destructive"),
                  )}
                  value={answers[question.id] ?? ""}
                  onChange={(e) => onChange(question.id, e.target.value)}
                  disabled={disabled}
                  aria-label={`Answer ${n}`}
                  aria-invalid={graded && !result.is_correct}
                />
                {graded && !result.is_correct && (
                  <span className="text-xs text-muted-foreground">
                    (accepted: {result.correct_answers.join(", ")})
                  </span>
                )}
                {/* Only where the author marked it — a review that offered
                    replay on every gap and played the wrong moment on half of
                    them would be worse than not offering it. */}
                {graded && onReplay && result.replay_start_ms != null && (
                  <button
                    type="button"
                    onClick={() =>
                      onReplay(result.replay_start_ms, result.replay_end_ms)
                    }
                    title="Hear where this answer is said"
                    aria-label={`Hear where answer ${n} is said`}
                    className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-foreground/8 hover:text-primary"
                  >
                    <Volume2 className="size-3.5" aria-hidden />
                    hear it
                  </button>
                )}
              </span>
            );
          }}
        />
      </div>
    </div>
  );
}

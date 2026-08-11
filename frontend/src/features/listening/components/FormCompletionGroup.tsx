import { useMemo } from "react";
import { cn } from "@/lib/utils";
import { FormLayout } from "@/features/listening/components/FormLayout";
import { parseTemplateLayout } from "@/features/listening/form-syntax";
import type { QuestionResult, TakeQuestionGroup } from "@/features/listening/types";

interface FormCompletionGroupProps {
  group: TakeQuestionGroup;
  answers: Record<string, string>;
  onChange: (questionId: string, value: string) => void;
  results?: Record<string, QuestionResult>;
  disabled?: boolean;
}

export function FormCompletionGroup({
  group,
  answers,
  onChange,
  results,
  disabled,
}: FormCompletionGroupProps) {
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
      {group.word_limit != null && (
        <p className="text-xs text-muted-foreground">
          Write no more than {group.word_limit}{" "}
          {group.word_limit === 1 ? "word" : "words"} for each answer.
        </p>
      )}

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
              </span>
            );
          }}
        />
      </div>
    </div>
  );
}

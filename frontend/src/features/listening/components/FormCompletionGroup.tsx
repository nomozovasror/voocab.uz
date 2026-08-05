import { Fragment, useMemo } from "react";
import { cn } from "@/lib/utils";
import type { QuestionResult, TakeQuestionGroup } from "@/features/listening/types";

const TOKEN_RE = /\{\{(\d+)\}\}/g;

/** Split a form-completion template into alternating text/gap-number parts,
 *  e.g. "Name: {{1}}\nPhone: {{2}}" -> ["Name: ", "1", "\nPhone: ", "2", ""].
 *  Whitespace (including newlines) is preserved verbatim by the caller via
 *  `whitespace-pre-wrap` — we don't trim or reflow anything here. */
function splitTemplate(template: string): string[] {
  return template.split(TOKEN_RE);
}

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

  const parts = useMemo(() => splitTemplate(group.config.template), [group.config.template]);

  return (
    <div className="space-y-3">
      <p className="text-sm text-foreground">{group.instructions}</p>
      {group.word_limit != null && (
        <p className="text-xs text-muted-foreground">
          Write no more than {group.word_limit}{" "}
          {group.word_limit === 1 ? "word" : "words"} for each answer.
        </p>
      )}

      <div className="rounded-lg border border-border bg-background p-4 font-mono text-sm leading-8 whitespace-pre-wrap text-foreground">
        {parts.map((part, i) => {
          // Odd indices are the captured {{N}} token numbers (see split regex).
          if (i % 2 === 1) {
            const n = Number(part);
            const question = byNumber.get(n);
            if (!question) return <Fragment key={i}>{`{{${part}}}`}</Fragment>;
            const result = results?.[question.id];
            const graded = result !== undefined;
            return (
              <span key={i} className="inline-flex items-baseline gap-1 align-baseline">
                <span
                  aria-hidden
                  className="text-xs font-semibold text-muted-foreground"
                >
                  {n}
                </span>
                <input
                  type="text"
                  className={cn(
                    "mx-0.5 w-32 rounded-md border border-border bg-background px-2 py-0.5 font-sans text-sm text-foreground placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
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
          }
          return <Fragment key={i}>{part}</Fragment>;
        })}
      </div>
    </div>
  );
}

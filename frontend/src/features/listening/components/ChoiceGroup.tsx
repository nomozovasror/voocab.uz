import { cn } from "@/lib/utils";
import { optionLetter } from "@/features/listening/mcq";
import { questionNumbers } from "@/features/listening/numbering";
import type {
  QuestionResult,
  TakeQuestion,
  TakeQuestionGroup,
} from "@/features/listening/types";

/**
 * A multiple-choice group, as the candidate sits it.
 *
 * The selection travels as the chosen option letters, comma-separated — "b",
 * or "a,c" — which is the same string the server grades and stores. Nothing
 * here knows which option is right until the attempt comes back graded: the
 * take payload carries the option text and how many to pick, and there is no
 * field in it that could carry more.
 */

interface ChoiceGroupProps {
  group: TakeQuestionGroup;
  /** question id -> the chosen letters, comma-separated. */
  answers: Record<string, string>;
  onChange: (questionId: string, value: string) => void;
  /** The number this group's first question carries on the page. */
  startNumber: number;
  results?: Record<string, QuestionResult>;
  disabled?: boolean;
}

function chosenLetters(value: string | undefined): Set<string> {
  return new Set(
    (value ?? "")
      .split(",")
      .map((letter) => letter.trim().toLowerCase())
      .filter(Boolean),
  );
}

export function ChoiceGroup({
  group,
  answers,
  onChange,
  startNumber,
  results,
  disabled,
}: ChoiceGroupProps) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-foreground">{group.instructions}</p>

      {group.questions
        .slice()
        .sort((a, b) => a.number - b.number)
        .map((question, index) => (
          <ChoiceQuestion
            key={question.id}
            question={question}
            // A "choose two" occupies two of the numbers down the side, so
            // the next question starts two later — the same walk the editor
            // and the server do.
            number={startNumber + index * (question.select_count ?? 1)}
            chosen={chosenLetters(answers[question.id])}
            onChange={(letters) =>
              onChange(question.id, [...letters].join(","))
            }
            result={results?.[question.id]}
            disabled={disabled}
          />
        ))}
    </div>
  );
}

function ChoiceQuestion({
  question,
  number,
  chosen,
  onChange,
  result,
  disabled,
}: {
  question: TakeQuestion;
  number: number;
  chosen: Set<string>;
  onChange: (letters: string[]) => void;
  result?: QuestionResult;
  disabled?: boolean;
}) {
  const options = question.options ?? [];
  const selectCount = question.select_count ?? 1;
  const several = selectCount > 1;
  const graded = result !== undefined;
  // The answer key, once it is allowed to exist here — never before grading.
  const key = new Set(
    graded ? result.correct_answers.map((l) => l.trim().toLowerCase()) : [],
  );

  const pick = (letter: string) => {
    if (!several) {
      onChange([letter]);
      return;
    }
    // Kept in the options' own order, so what is submitted reads the way the
    // question does however it was clicked.
    const next = new Set(chosen);
    if (next.has(letter)) next.delete(letter);
    else next.add(letter);
    onChange(options.map((_o, i) => optionLetter(i)).filter((l) => next.has(l)));
  };

  return (
    <fieldset
      className="space-y-1.5"
      aria-invalid={graded && !result.is_correct}
    >
      <legend className="mb-1 text-sm text-foreground">
        <span className="mr-2 font-semibold tabular-nums text-muted-foreground">
          {questionNumbers(number, selectCount)}
        </span>
        {question.prompt}
      </legend>

      {several && (
        <p className="text-xs text-muted-foreground">
          Choose {selectCount} letters.
        </p>
      )}

      {options.map((text, index) => {
        const letter = optionLetter(index);
        const picked = chosen.has(letter);
        const isKey = key.has(letter);
        return (
          <label
            key={letter}
            className={cn(
              "flex cursor-pointer items-baseline gap-2 rounded-md border px-2.5 py-1.5 text-sm transition-colors",
              // Before grading, only what the candidate chose is coloured.
              // After it, the answer leads: every right option is marked
              // whether or not they found it, and a wrong pick is marked as
              // theirs.
              graded && isKey
                ? "border-success bg-success/10 text-success"
                : graded && picked
                  ? "border-destructive bg-destructive/10 text-destructive"
                  : picked
                    ? "border-primary bg-primary/10 text-foreground"
                    : "border-border text-foreground hover:border-foreground/30",
              disabled && "cursor-default",
            )}
          >
            <input
              type={several ? "checkbox" : "radio"}
              name={question.id}
              checked={picked}
              onChange={() => pick(letter)}
              disabled={disabled}
              className="sr-only"
            />
            <span
              aria-hidden
              className={cn(
                "flex size-5 shrink-0 items-center justify-center self-center border text-[11px] font-semibold",
                several ? "rounded-[4px]" : "rounded-full",
                graded && isKey
                  ? "border-success"
                  : graded && picked
                    ? "border-destructive"
                    : picked
                      ? "border-primary"
                      : "border-border",
              )}
            >
              {letter}
            </span>
            {text}
          </label>
        );
      })}
    </fieldset>
  );
}

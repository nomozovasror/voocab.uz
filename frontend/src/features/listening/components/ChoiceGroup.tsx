import { Volume2 } from "lucide-react";
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
 *
 * "How many to pick" is a limit, not a suggestion. A question that says
 * choose two and lets you tick four is marked wrong for a reason the
 * candidate never sees — grading is an exact set match — so the extra ticks
 * are refused here instead, with the tally saying why. Refused rather than
 * silently dropping an earlier answer: this is someone sitting a test, and an
 * answer disappearing from under them because they clicked elsewhere is worse
 * than a click that does nothing.
 */

interface ChoiceGroupProps {
  group: TakeQuestionGroup;
  /** question id -> the chosen letters, comma-separated. */
  answers: Record<string, string>;
  onChange: (questionId: string, value: string) => void;
  /** The number this group's first question carries on the page. */
  startNumber: number;
  results?: Record<string, QuestionResult>;
  /** Playing back the moment the answer is given, once the attempt has been
   *  marked. Only where the author marked one — see below. */
  onReplay?: (startMs: number | null, endMs: number | null) => void;
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
  onReplay,
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
            onReplay={onReplay}
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
  onReplay,
  disabled,
}: {
  question: TakeQuestion;
  number: number;
  chosen: Set<string>;
  onChange: (letters: string[]) => void;
  result?: QuestionResult;
  onReplay?: (startMs: number | null, endMs: number | null) => void;
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

  // Only in the way once the question is answered in full, so it never
  // blocks a first click.
  const full = several && chosen.size >= selectCount;

  const pick = (letter: string) => {
    if (!several) {
      onChange([letter]);
      return;
    }
    const next = new Set(chosen);
    if (next.has(letter)) next.delete(letter);
    else if (next.size >= selectCount) return;
    else next.add(letter);
    // Kept in the options' own order, so what is submitted reads the way the
    // question does however it was clicked.
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
          Choose {selectCount} letters — {chosen.size} of {selectCount} chosen
          {full && !graded && ". Unpick one to change your answer."}
        </p>
      )}

      {options.map((text, index) => {
        const letter = optionLetter(index);
        const picked = chosen.has(letter);
        const isKey = key.has(letter);
        // Not disabled on the way to being answered — only once the question
        // is full and this option isn't part of the answer. It stays
        // readable; it just stops responding until something is unpicked.
        const spent = full && !picked && !graded;
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
              (disabled || spent) && "cursor-default",
              spent && "opacity-45 hover:border-border",
            )}
          >
            <input
              type={several ? "checkbox" : "radio"}
              name={question.id}
              checked={picked}
              onChange={() => pick(letter)}
              disabled={disabled || spent}
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

      {/* Only where the author marked one. A choice question is often
          answered from the whole of what was said rather than from one
          phrase in it, so most of them will never have a moment to point at
          — and a "hear it" that played the wrong seconds would be worse
          than no "hear it" at all. */}
      {graded && onReplay && result.replay_start_ms != null && (
        <button
          type="button"
          onClick={() => onReplay(result.replay_start_ms, result.replay_end_ms)}
          title="Hear where this answer is given"
          aria-label={`Hear where the answer to question ${number} is given`}
          className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-foreground/8 hover:text-primary"
        >
          <Volume2 className="size-3.5" aria-hidden />
          hear it
        </button>
      )}
    </fieldset>
  );
}

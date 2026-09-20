import { cn } from "@/lib/utils";
import { FlagQuestion } from "@/features/listening/components/FlagQuestion";
import { Q_ANCHOR } from "@/features/paper/take-focus";
import type {
  QuestionResult,
  TakeQuestion,
  TakeQuestionGroup,
} from "@/features/paper/types";

/**
 * A true/false/not-given set, as the candidate sits it.
 *
 * The three words come down on the GROUP, in `config.options`, exactly as
 * matching's box does — and for the same reason: the paper prints them once
 * above the whole set. What is different is where they came from. They are
 * not something an author wrote: the server derives them from the group's
 * TYPE, so the words on screen and the words grading compares against cannot
 * be two different lists (see `FIXED_CHOICE_OPTIONS`).
 *
 * The answer travels as the word, not as a letter, because the word is what
 * the answer key prints and what a candidate writes on the real paper. That
 * is also why this is graded as WRITTEN rather than as a choice: it goes
 * through `grade_answer` like a gap-fill, and "true" and "TRUE" are one
 * answer after normalization.
 *
 * One control per NUMBER, like everywhere else on this paper.
 */

interface FixedChoiceGroupProps {
  group: TakeQuestionGroup;
  /** question id -> the chosen word. */
  answers: Record<string, string>;
  onChange: (questionId: string, value: string) => void;
  /** The number this group's first statement carries on the page. */
  startNumber: number;
  results?: Record<string, QuestionResult>;
  disabled?: boolean;
  /** Only while the paper is being sat — see QuestionPaper. */
  flagged?: Set<string>;
  onFlag?: (questionId: string) => void;
}

export function FixedChoiceGroup({
  group,
  answers,
  onChange,
  startNumber,
  results,
  disabled,
  flagged,
  onFlag,
}: FixedChoiceGroupProps) {
  const options = group.config.options ?? [];

  return (
    <div className="space-y-3">
      <p className="text-sm text-foreground">{group.instructions}</p>

      <div className="space-y-1.5">
        {group.questions
          .slice()
          .sort((a, b) => a.number - b.number)
          .map((question, index) => (
            <Statement
              key={question.id}
              question={question}
              number={startNumber + index}
              options={options}
              chosen={(answers[question.id] ?? "").trim().toUpperCase()}
              onChange={(word) => onChange(question.id, word)}
              result={results?.[question.id]}
              disabled={disabled}
              flagged={flagged?.has(question.id) ?? false}
              onFlag={onFlag ? () => onFlag(question.id) : undefined}
            />
          ))}
      </div>
    </div>
  );
}

function Statement({
  question,
  number,
  options,
  chosen,
  onChange,
  result,
  disabled,
  flagged,
  onFlag,
}: {
  question: TakeQuestion;
  number: number;
  options: string[];
  chosen: string;
  onChange: (word: string) => void;
  result?: QuestionResult;
  disabled?: boolean;
  flagged?: boolean;
  onFlag?: () => void;
}) {
  const graded = result !== undefined;
  const key = graded
    ? result.correct_answers[0]?.trim().toUpperCase()
    : undefined;

  return (
    <fieldset
      {...{ [Q_ANCHOR]: question.id }}
      className="flex flex-wrap items-center gap-x-2 gap-y-1 py-0.5"
      aria-invalid={graded && !result.is_correct}
    >
      <legend className="sr-only">Question {number}</legend>
      <span
        aria-hidden
        className="w-6 shrink-0 text-sm font-semibold tabular-nums text-muted-foreground"
      >
        {number}
      </span>
      {/* A floor under the statement, not `min-w-0`.
          The three words are `shrink-0` and take about two hundred pixels,
          and with the statement free to shrink to nothing the row kept them
          company by squeezing the QUESTION into a third of the pane — three
          cramped lines beside one comfortable row of buttons, while the
          multiple-choice group next to it gives its options the full width
          for the same act of picking one of several.

          With a floor, the row wraps instead: wide enough and the words sit
          beside the statement as before; too narrow and they drop to their
          own line and the sentence gets all of it. */}
      <span className="min-w-[20rem] flex-1 text-base text-foreground">
        {question.prompt}
      </span>
      {onFlag && (
        <FlagQuestion
          number={String(number)}
          flagged={!!flagged}
          onToggle={onFlag}
        />
      )}

      {/* The words themselves, not initials. "T / F / NG" is shorthand a
          candidate has to expand in their head, and the sheet they will sit
          the real test on prints the words. */}
      <div className="flex shrink-0 flex-wrap items-center gap-1">
        {options.map((word) => {
          const picked = chosen === word;
          const isKey = graded && key === word;
          return (
            <label
              key={word}
              className={cn(
                "flex h-7 cursor-pointer items-center justify-center rounded-full border px-2.5 text-xs font-semibold tracking-caps transition-colors",
                "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring",
                // Before grading only the pick is coloured; after it the
                // answer leads, whether or not they found it — the same four
                // states matching draws.
                isKey
                  ? "border-success bg-success/10 text-success"
                  : graded && picked
                    ? "border-destructive bg-destructive/10 text-destructive"
                    : picked
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border text-muted-foreground hover:border-border-strong",
                disabled && "cursor-default",
              )}
            >
              <input
                type="radio"
                name={question.id}
                data-question={question.id}
                checked={picked}
                onChange={() => onChange(word)}
                disabled={disabled}
                className="sr-only"
              />
              <span aria-hidden>{word}</span>
              <span className="sr-only">
                Question {number}, {word}
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

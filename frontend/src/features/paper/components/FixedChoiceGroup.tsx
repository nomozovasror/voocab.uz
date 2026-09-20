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
      <p className="text-[0.875em] text-foreground">{group.instructions}</p>

      <div>
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
      className="border-b border-border py-2.5 last:border-b-0"
      aria-invalid={graded && !result.is_correct}
    >
      <legend className="sr-only">Question {number}</legend>

      {/* The statement, across the width it needs. The three words used to
          sit beside it and take about two hundred pixels of a six-hundred
          pixel pane, so the QUESTION was squeezed into a third of the row
          and wrapped to three cramped lines — while the multiple-choice
          group directly below gave its options the full width for the same
          act of picking one of several. Question first, answer under it, the
          way every other group on this paper reads. */}
      <div className="flex items-baseline gap-3">
        <span
          aria-hidden
          className="w-6 shrink-0 text-right text-[0.875em] font-semibold tabular-nums text-muted-foreground"
        >
          {number}
        </span>
        <span className="min-w-0 flex-1 text-[1em] leading-snug text-foreground">
          {question.prompt}
        </span>
        {onFlag && (
          <FlagQuestion
            number={String(number)}
            flagged={!!flagged}
            onToggle={onFlag}
          />
        )}
      </div>

      {/* One control rather than three loose pills, and the columns are
          EQUAL: "NOT GIVEN" is twice the width of "NO", and left to size
          themselves the three made a ragged edge down a list of six
          statements. Indented to the statement's own left edge, so the
          answer sits under the question it belongs to rather than under its
          number. */}
      <div
        className="mt-2 ml-9 inline-grid gap-0.5 rounded-lg bg-surface-sunken p-0.5"
        style={{
          gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))`,
        }}
      >
        {options.map((word) => {
          const picked = chosen === word;
          const isKey = graded && key === word;
          return (
            <label
              key={word}
              className={cn(
                "flex h-7 cursor-pointer items-center justify-center rounded-md px-3 text-[0.75em] font-semibold tracking-caps transition-colors",
                "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring",
                // Before grading only the pick is coloured; after it the
                // answer leads, whether or not they found it — the same four
                // states matching draws.
                isKey
                  ? "bg-correct/15 text-correct"
                  : graded && picked
                    ? "bg-incorrect/15 text-incorrect"
                    : picked
                      ? "bg-primary/15 text-primary"
                      : "text-muted-foreground hover:text-foreground",
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

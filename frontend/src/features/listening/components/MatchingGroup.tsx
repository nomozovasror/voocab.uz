import { Volume2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { matchLetter } from "@/features/listening/matching";
import type {
  QuestionResult,
  TakeQuestion,
  TakeQuestionGroup,
} from "@/features/listening/types";

/**
 * A matching group, as the candidate sits it.
 *
 * The box comes down on the GROUP — it is printed once above the whole set —
 * and each question is one item answered from it. The answer travels as the
 * chosen letter, which is the same string the server grades and stores, and
 * the same one a multiple-choice answer of one letter travels as.
 *
 * Nothing here knows which letter is right until the attempt comes back
 * graded: the take payload carries the box and the items, and there is no
 * field in it that could carry more.
 *
 * Unlike multiple choice, nothing is capped. A "choose two" that lets you tick
 * four is marked wrong for a reason the candidate never sees, so the extra
 * ticks are refused there. Here every item is graded on its own letter, so a
 * candidate who puts A against two items is simply right about one of them and
 * wrong about the other — which is what the real paper does, and stopping them
 * would be telling them one of the two is wrong.
 */

interface MatchingGroupProps {
  group: TakeQuestionGroup;
  /** question id -> the chosen letter. */
  answers: Record<string, string>;
  onChange: (questionId: string, value: string) => void;
  /** The number this group's first item carries on the page. */
  startNumber: number;
  results?: Record<string, QuestionResult>;
  /** Playing back the moment the answer is given, once the attempt has been
   *  marked. Only where the author marked one. */
  onReplay?: (startMs: number | null, endMs: number | null) => void;
  disabled?: boolean;
}

export function MatchingGroup({
  group,
  answers,
  onChange,
  startNumber,
  results,
  onReplay,
  disabled,
}: MatchingGroupProps) {
  const options = group.config.options ?? [];

  return (
    <div className="space-y-3">
      <p className="text-sm text-foreground">{group.instructions}</p>
      {/* The paper's own NB line, and only when it is true — printed on a set
          where each letter is used once, it would be a lie the candidate
          plans around. */}
      {group.config.allow_reuse && (
        <p className="text-xs text-muted-foreground">
          NB You may use any letter more than once.
        </p>
      )}

      <ul className="space-y-1 rounded-lg border border-border bg-background p-3">
        {options.map((text, index) => (
          <li key={index} className="flex items-baseline gap-2 text-sm">
            <span
              aria-hidden
              className="flex size-5 shrink-0 items-center justify-center self-center rounded-full border border-border text-[11px] font-semibold text-muted-foreground"
            >
              {matchLetter(index).toUpperCase()}
            </span>
            <span className="text-foreground">{text}</span>
          </li>
        ))}
      </ul>

      <div className="space-y-1.5">
        {group.questions
          .slice()
          .sort((a, b) => a.number - b.number)
          .map((question, index) => (
            <MatchingItem
              key={question.id}
              question={question}
              // One item is one number: the arithmetic a "choose two" forces
              // on multiple choice has nothing to do here.
              number={startNumber + index}
              options={options}
              chosen={(answers[question.id] ?? "").trim().toLowerCase()}
              onChange={(letter) => onChange(question.id, letter)}
              result={results?.[question.id]}
              onReplay={onReplay}
              disabled={disabled}
            />
          ))}
      </div>
    </div>
  );
}

function MatchingItem({
  question,
  number,
  options,
  chosen,
  onChange,
  result,
  onReplay,
  disabled,
}: {
  question: TakeQuestion;
  number: number;
  options: string[];
  chosen: string;
  onChange: (letter: string) => void;
  result?: QuestionResult;
  onReplay?: (startMs: number | null, endMs: number | null) => void;
  disabled?: boolean;
}) {
  const graded = result !== undefined;
  // The answer, once it is allowed to exist here — never before grading.
  const key = graded ? result.correct_answers[0]?.trim().toLowerCase() : undefined;

  return (
    <fieldset
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
      <span className="min-w-0 flex-1 text-sm text-foreground">
        {question.prompt}
      </span>

      <div className="flex shrink-0 flex-wrap items-center gap-1">
        {options.map((_text, index) => {
          const letter = matchLetter(index);
          const picked = chosen === letter;
          const isKey = graded && key === letter;
          return (
            <label
              key={letter}
              className={cn(
                "flex size-7 cursor-pointer items-center justify-center rounded-full border text-xs font-semibold transition-colors",
                // Before grading, only what the candidate chose is coloured.
                // After it, the answer leads: the right letter is marked
                // whether or not they found it, and a wrong pick is marked as
                // theirs.
                isKey
                  ? "border-success bg-success/10 text-success"
                  : graded && picked
                    ? "border-destructive bg-destructive/10 text-destructive"
                    : picked
                      ? "border-primary bg-primary/10 text-foreground"
                      : "border-border text-muted-foreground hover:border-foreground/30",
                disabled && "cursor-default",
              )}
            >
              <input
                type="radio"
                name={question.id}
                checked={picked}
                onChange={() => onChange(letter)}
                disabled={disabled}
                className="sr-only"
              />
              <span aria-hidden>{letter.toUpperCase()}</span>
              <span className="sr-only">
                Question {number}, option {letter.toUpperCase()}
              </span>
            </label>
          );
        })}
      </div>

      {/* Only where the author marked it — a review that offered replay on
          every item and played the wrong moment on half of them would be
          worse than not offering it. */}
      {graded && onReplay && result.replay_start_ms != null && (
        <button
          type="button"
          onClick={() => onReplay(result.replay_start_ms, result.replay_end_ms)}
          title="Hear where this answer is given"
          aria-label={`Hear where the answer to question ${number} is given`}
          className="inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-foreground/8 hover:text-primary"
        >
          <Volume2 className="size-3.5" aria-hidden />
          hear it
        </button>
      )}
    </fieldset>
  );
}

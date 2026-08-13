import { useEffect, useRef } from "react";
import { CornerUpLeft, Plus, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { ToolbarButton } from "@/features/listening/components/BuilderTools";
import { questionNumbers } from "@/features/listening/numbering";
import {
  addOption,
  answerSummary,
  newChoiceQuestion,
  newOption,
  optionLetter,
  patchOption,
  removeOption,
  toggleCorrect,
  type ChoiceQuestion,
} from "@/features/listening/mcq";

/**
 * The multiple-choice builder.
 *
 * Same sheet as the form builder — one bordered card holding the questions in
 * order, controls that appear on hover, a row of tools underneath — because
 * an author moving between the two inside one part should not have to learn a
 * second editor. What differs is only what a question is made of.
 *
 * A question is drawn the way it is printed: the number, the question, and
 * the options lettered beneath it. Marking the answer is done on the letter
 * itself rather than through a separate control, so the sheet says which
 * option is right in the same place the candidate will read it — round
 * markers where one answer is wanted, square where several are, borrowed
 * from the radio and checkbox they will actually be.
 *
 * How many answers are wanted is the group's, set once above this card
 * (ChoiceGroupEditor) rather than per question. It arrives here as `wanted`
 * and does three things: it decides the marker shape, it caps what clicking
 * an option can mark, and it is what an unfinished key is short of.
 */

interface ChoiceBuilderProps {
  questions: ChoiceQuestion[];
  /** Applied against the latest list, not the one this render was built from
   *  — see FormBuilder's note; holding Enter on an option is enough to land
   *  two edits between renders. */
  onChange: (edit: (current: ChoiceQuestion[]) => ChoiceQuestion[]) => void;
  /** The number the first question of this group carries on the page. */
  startNumber: number;
  /** How many options each question wants marked — the group's setting. */
  wanted: number;
  /** Question ids with something still missing, flagged so the block can be
   *  found without reading the list underneath. */
  flagged?: Set<string>;
  /** The phrase currently selected in the transcript, if any — offered as
   *  something to drop into a question or an option. */
  transcriptSelection?: string;
  extraTools?: React.ReactNode;
}

export function ChoiceBuilder({
  questions,
  onChange,
  startNumber,
  wanted,
  flagged,
  transcriptSelection,
  extraTools,
}: ChoiceBuilderProps) {
  // Inputs are registered by key so the caret can be put where the edit
  // implies it should go: into the option a press of Enter just created,
  // into the question a press of "+ question" just added.
  const inputs = useRef(new Map<string, HTMLInputElement>());
  const pendingFocus = useRef<string | null>(null);
  const register = (key: string) => (el: HTMLInputElement | null) => {
    if (el) inputs.current.set(key, el);
    else inputs.current.delete(key);
  };

  useEffect(() => {
    const key = pendingFocus.current;
    if (!key) return;
    pendingFocus.current = null;
    const el = inputs.current.get(key);
    if (!el) return;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  });

  const patchQuestion = (
    questionId: string,
    edit: (question: ChoiceQuestion) => ChoiceQuestion,
  ) =>
    onChange((current) =>
      current.map((q) => (q.id === questionId ? edit(q) : q)),
    );

  const addQuestion = () => {
    const question = newChoiceQuestion();
    pendingFocus.current = `prompt#${question.id}`;
    onChange((current) => [...current, question]);
  };

  /** Adds an option and puts the caret in it. The option is minted here
   *  rather than inside the edit so there is something to focus — the edit
   *  runs against the latest question and reports nothing back. */
  const appendOption = (questionId: string) => {
    const option = newOption();
    pendingFocus.current = `option#${option.id}`;
    patchQuestion(questionId, (question) => addOption(question, option));
  };

  return (
    <div>
      <div className="divide-y divide-border rounded-lg border border-border bg-card">
        {questions.map((question, index) => (
          <QuestionBlock
            key={question.id}
            question={question}
            number={startNumber + index * wanted}
            wanted={wanted}
            flagged={flagged?.has(question.id)}
            transcriptSelection={transcriptSelection}
            register={register}
            // The only question in a group can't be removed: a group with no
            // questions is not a thing the API will store, and deleting the
            // group is the thing the author actually means.
            onRemove={
              questions.length > 1
                ? () =>
                    onChange((current) =>
                      current.filter((q) => q.id !== question.id),
                    )
                : undefined
            }
            onPrompt={(prompt) =>
              patchQuestion(question.id, (q) => ({ ...q, prompt }))
            }
            onToggleCorrect={(optionId) =>
              patchQuestion(question.id, (q) =>
                toggleCorrect(q, optionId, wanted),
              )
            }
            onOptionText={(optionId, text) =>
              patchQuestion(question.id, (q) => patchOption(q, optionId, text))
            }
            onRemoveOption={(optionId) =>
              patchQuestion(question.id, (q) => removeOption(q, optionId))
            }
            onAddOption={() => appendOption(question.id)}
          />
        ))}
      </div>

      <div className="mt-2.5 flex flex-wrap items-center justify-center gap-1.5">
        <ToolbarButton
          onClick={addQuestion}
          icon={<Plus className="size-3.5" aria-hidden />}
          label="question"
          title="Add a question at the end"
        />
        {extraTools}
      </div>
    </div>
  );
}

interface QuestionBlockProps {
  question: ChoiceQuestion;
  number: number;
  wanted: number;
  flagged?: boolean;
  transcriptSelection?: string;
  register: (key: string) => (el: HTMLInputElement | null) => void;
  onRemove?: () => void;
  onPrompt: (prompt: string) => void;
  onToggleCorrect: (optionId: string) => void;
  onOptionText: (optionId: string, text: string) => void;
  onRemoveOption: (optionId: string) => void;
  onAddOption: () => void;
}

function QuestionBlock({
  question,
  number,
  wanted,
  flagged,
  transcriptSelection,
  register,
  onRemove,
  onPrompt,
  onToggleCorrect,
  onOptionText,
  onRemoveOption,
  onAddOption,
}: QuestionBlockProps) {
  // Which field the author was last in, so a phrase taken from the transcript
  // lands where they were working. Selecting words in the left pane blurs
  // whatever was focused here, so "where the caret is" has to be remembered
  // rather than looked up.
  const lastField = useRef<HTMLInputElement | null>(null);
  const remember = (e: React.FocusEvent<HTMLInputElement>) => {
    lastField.current = e.currentTarget;
  };

  /** Drops the selected transcript words into the field last worked in.
   *  Typed through execCommand rather than assigned, so the browser's own
   *  undo keeps the change and the caret ends up after it. */
  const takeFromTranscript = () => {
    const field = lastField.current;
    if (!field || !transcriptSelection) return;
    field.focus();
    document.execCommand("insertText", false, transcriptSelection);
  };

  // Progress towards what the group asks for, and only where there is
  // progress to make: in an ordinary single-answer group the marker itself
  // already says everything, and "1 of 1" beside every question would be
  // noise on every line.
  const tally =
    wanted > 1 ? `${question.correct.length} of ${wanted} marked` : null;

  // The number gutter is wider when a question owns a range ("23 and 24"),
  // and everything under the prompt lines up with the prompt either way.
  const gutter = wanted > 1 ? "w-16" : "w-6";
  const indent = wanted > 1 ? "pl-[4.5rem]" : "pl-8";

  return (
    <div
      className={cn(
        "group/question relative px-3 py-2.5 transition-colors",
        flagged && "bg-destructive/5",
      )}
    >
      <div className="flex items-baseline gap-2">
        {/* The numbers this question occupies, not its position in the list:
            a "choose two" is printed as "23 and 24" and takes both. */}
        <span
          className={cn(
            "shrink-0 text-xs tabular-nums text-muted-foreground",
            gutter,
          )}
        >
          {questionNumbers(number, wanted)}.
        </span>
        <input
          type="text"
          ref={register(`prompt#${question.id}`)}
          value={question.prompt}
          onChange={(e) => onPrompt(e.target.value)}
          onFocus={remember}
          placeholder="question text"
          aria-label={`Question ${questionNumbers(number, wanted)}`}
          className="min-w-0 flex-1 border-b border-transparent bg-transparent pr-7 pb-0.5 text-sm text-foreground placeholder:text-muted-foreground/50 hover:border-border focus:border-primary focus:outline-none"
        />
        {onRemove && (
          <button
            type="button"
            onClick={onRemove}
            aria-label={`Remove question ${questionNumbers(number, wanted)}`}
            title="Remove this question"
            className="absolute top-2 right-2 flex size-7 items-center justify-center rounded-md bg-card text-muted-foreground opacity-0 shadow-sm transition-opacity group-hover/question:opacity-100 hover:text-destructive focus-visible:opacity-100"
          >
            <X className="size-3.5" aria-hidden />
          </button>
        )}
      </div>

      {tally && (
        <div className={cn("mt-1", indent)}>
          <span
            className={cn(
              "text-[11px]",
              question.correct.length === wanted
                ? "text-muted-foreground"
                : "text-warning",
            )}
          >
            {tally}
          </span>
        </div>
      )}

      <ul className={cn("mt-1.5 space-y-0.5", indent)}>
        {question.options.map((option, index) => {
          const letter = optionLetter(index);
          const correct = question.correct.includes(option.id);
          return (
            <li key={option.id} className="group/option flex items-center gap-2">
              <button
                type="button"
                onClick={() => onToggleCorrect(option.id)}
                aria-pressed={correct}
                aria-label={
                  correct
                    ? `${letter} is a correct answer — press to unmark`
                    : `Mark ${letter} as a correct answer`
                }
                title={
                  correct ? "Correct — press to unmark" : "Mark as correct"
                }
                className={cn(
                  "flex size-5 shrink-0 items-center justify-center border text-[11px] font-semibold transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                  // Round for one answer, square for several: the same shapes
                  // the candidate will be given, so the author is looking at
                  // the question rather than at a setting.
                  wanted === 1 ? "rounded-full" : "rounded-[4px]",
                  correct
                    ? "border-success/50 bg-success/15 text-success"
                    : "border-border text-muted-foreground hover:border-foreground/30 hover:text-foreground",
                )}
              >
                {letter}
              </button>
              <input
                type="text"
                ref={register(`option#${option.id}`)}
                value={option.text}
                onChange={(e) => onOptionText(option.id, e.target.value)}
                onFocus={remember}
                onKeyDown={(e) => {
                  if (e.key !== "Enter") return;
                  e.preventDefault();
                  onAddOption();
                }}
                placeholder="option"
                aria-label={`Option ${letter} of question ${number}`}
                className="min-w-0 flex-1 border-b border-transparent bg-transparent pb-0.5 text-sm text-foreground placeholder:text-muted-foreground/50 hover:border-border focus:border-primary focus:outline-none"
              />
              {/* Two is the fewest a question can have; below that there is
                  nothing to choose between. */}
              {question.options.length > 2 && (
                <button
                  type="button"
                  onClick={() => onRemoveOption(option.id)}
                  aria-label={`Remove option ${letter}`}
                  title="Remove this option"
                  className="flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-opacity group-hover/option:opacity-100 hover:text-destructive focus-visible:opacity-100"
                >
                  <X className="size-3.5" aria-hidden />
                </button>
              )}
            </li>
          );
        })}
      </ul>

      <div
        className={cn(
          "mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1",
          indent,
        )}
      >
        <button
          type="button"
          onClick={onAddOption}
          className="text-[11px] text-muted-foreground transition-colors hover:text-foreground"
        >
          + option
        </button>

        {/* Only once there is something to take. Shown always it would be a
            disabled control on every question, explaining itself to nobody. */}
        {transcriptSelection && (
          <button
            type="button"
            // Keeps the transcript selection alive: a plain click would
            // collapse it before there was anything to read.
            onMouseDown={(e) => e.preventDefault()}
            onClick={takeFromTranscript}
            title={`Put “${transcriptSelection}” into the last field you were in`}
            className="flex items-center gap-1 text-[11px] text-primary transition-colors hover:text-primary/80"
          >
            <CornerUpLeft className="size-3" aria-hidden />
            from transcript
          </button>
        )}

        <span
          className={cn(
            "ml-auto text-[11px] tabular-nums",
            question.correct.length > 0
              ? "text-success"
              : "text-muted-foreground/70",
          )}
        >
          {answerSummary(question)}
        </span>
      </div>
    </div>
  );
}

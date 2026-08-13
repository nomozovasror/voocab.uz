import { useEffect, useRef } from "react";
import { CircleAlert, CornerUpLeft, Plus, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatClock } from "@/features/studio/format";
import { ToolbarButton } from "@/features/listening/components/BuilderTools";
import {
  questionNumbers,
  questionNumbersShort,
} from "@/features/listening/numbering";
import {
  addOption,
  answerSummary,
  editOption,
  newChoiceQuestion,
  newOption,
  optionLetter,
  patchOption,
  removeOption,
  toggleCorrect,
  type ChoiceIssue,
  type ChoiceOption,
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
 *
 * Marking an option right and saying where it is said are ONE action. The
 * author presses the letter, the transcript asks which line, and the answer
 * to that question settles both — because they are the same decision. "This
 * is the right answer" and "because of this sentence" arrive together in the
 * author's head, and asking for them separately meant a second control on
 * every answer and a state, right-but-unlinked, that publishing then had to
 * refuse. The moment shows at the end of the row afterwards, as a reading
 * rather than a button.
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
  /** The one thing still missing from each question, by question id. Shown
   *  on the question it is about. */
  issues?: Map<string, ChoiceIssue>;
  /** The phrase currently selected in the transcript, if any — offered as
   *  something to drop into a question or an option. */
  transcriptSelection?: string;
  /** Marking where the answer is said, the same way a gap does it: the page
   *  owns the transcript, so it takes the phrases to look for and hands back
   *  a range. Absent while there is no recording to mark against. */
  onMarkAudio?: (
    answers: string[],
    apply: (range: { startMs: number; endMs: number }) => void,
  ) => void;
  extraTools?: React.ReactNode;
}

export function ChoiceBuilder({
  questions,
  onChange,
  startNumber,
  wanted,
  issues,
  transcriptSelection,
  onMarkAudio,
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
            issue={issues?.get(question.id)}
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
            onChooseCorrect={(option) => {
              // Already right: pressing it again takes it back, which is the
              // only way out of a wrong press.
              if (question.correct.includes(option.id)) {
                patchQuestion(question.id, (q) =>
                  toggleCorrect(q, option.id, wanted),
                );
                return;
              }
              // Nothing to mark against — no recording, or none that
              // decoded. The letter still does what it always did rather
              // than doing nothing at all.
              if (!onMarkAudio) {
                patchQuestion(question.id, (q) =>
                  toggleCorrect(q, option.id, wanted),
                );
                return;
              }
              onMarkAudio([option.text.trim()], (range) =>
                patchQuestion(question.id, (q) =>
                  editOption(
                    toggleCorrect(q, option.id, wanted),
                    option.id,
                    (o) => ({
                      ...o,
                      replayStartMs: range.startMs,
                      replayEndMs: range.endMs,
                    }),
                  ),
                ),
              );
            }}
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
  issue?: ChoiceIssue;
  transcriptSelection?: string;
  register: (key: string) => (el: HTMLInputElement | null) => void;
  onRemove?: () => void;
  onPrompt: (prompt: string) => void;
  /** Pressing an option's letter: the one gesture that makes it the answer
   *  and records where that answer is given. */
  onChooseCorrect: (option: ChoiceOption) => void;
  onOptionText: (optionId: string, text: string) => void;
  onRemoveOption: (optionId: string) => void;
  onAddOption: () => void;
}

function QuestionBlock({
  question,
  number,
  wanted,
  issue,
  transcriptSelection,
  register,
  onRemove,
  onPrompt,
  onChooseCorrect,
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

  const settled = question.correct.length === wanted;

  return (
    <div
      className={cn(
        "group/question relative px-3 py-2.5 transition-colors",
        issue && "bg-destructive/5",
      )}
    >
      <div className="flex items-center gap-2">
        {/* The numbers this question occupies, not its position in the list:
            a "choose two" is printed as "23–24" and takes both. */}
        <span className="shrink-0 text-sm tabular-nums text-muted-foreground">
          {questionNumbersShort(number, wanted)}.
        </span>
        <input
          type="text"
          ref={register(`prompt#${question.id}`)}
          value={question.prompt}
          onChange={(e) => onPrompt(e.target.value)}
          onFocus={remember}
          placeholder="question text"
          aria-label={`Question ${questionNumbers(number, wanted)}`}
          className="min-w-0 flex-1 border-b border-transparent bg-transparent pb-0.5 text-base text-foreground placeholder:text-muted-foreground/50 hover:border-border focus:border-primary focus:outline-none"
        />
        {/* In the flow rather than floating over the input's right edge,
            where it sat on top of whatever had been typed. Its space is held
            whether or not it is showing, so nothing shifts on hover. */}
        {onRemove && (
          <button
            type="button"
            onClick={onRemove}
            aria-label={`Remove question ${questionNumbers(number, wanted)}`}
            title="Remove this question"
            className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-opacity group-hover/question:opacity-100 hover:text-destructive focus-visible:opacity-100"
          >
            <X className="size-4" aria-hidden />
          </button>
        )}
      </div>

      {/* Flush left, under the number rather than under the prompt: the
          letters are what the candidate reads down, and indenting them to
          the question text pushed the whole answer key into the middle of
          the card. */}
      <ul className="mt-2 space-y-1">
        {question.options.map((option, index) => {
          const letter = optionLetter(index);
          const correct = question.correct.includes(option.id);
          const marked = option.replayStartMs != null;
          return (
            <li key={option.id} className="group/option flex items-center gap-2">
              <button
                type="button"
                onClick={() => onChooseCorrect(option)}
                aria-pressed={correct}
                aria-label={
                  correct
                    ? `${letter} is a correct answer — press to unmark`
                    : `Mark ${letter} as a correct answer and say where it is given`
                }
                title={
                  correct
                    ? "Correct — press to unmark"
                    : "Mark as correct, then click the line where it is given"
                }
                className={cn(
                  "flex size-6 shrink-0 items-center justify-center border text-xs font-semibold transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
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
                className="min-w-0 flex-1 border-b border-transparent bg-transparent pb-0.5 text-base text-foreground placeholder:text-muted-foreground/50 hover:border-border focus:border-primary focus:outline-none"
              />
              {/* When the answer is given, read out at the end of the row.
                  Not a control: it was settled by the press that made this
                  the answer, and there is nothing here to press that the
                  letter doesn't already do.

                  A right option with no time is a state only work from
                  before this could be in — those get the word instead, and
                  pressing the letter twice puts it right. */}
              {correct && (
                <span
                  className={cn(
                    "shrink-0 text-xs tabular-nums",
                    marked ? "text-primary" : "text-warning",
                  )}
                >
                  {marked ? formatClock(option.replayStartMs ?? 0) : "unlinked"}
                </span>
              )}

              {/* Two is the fewest a question can have; below that there is
                  nothing to choose between. Its space is held either way, so
                  the times above stay in one column. */}
              <span className="flex size-6 shrink-0 items-center justify-center">
                {question.options.length > 2 && (
                  <button
                    type="button"
                    onClick={() => onRemoveOption(option.id)}
                    aria-label={`Remove option ${letter}`}
                    title="Remove this option"
                    className="flex size-6 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-opacity group-hover/option:opacity-100 hover:text-destructive focus-visible:opacity-100"
                  >
                    <X className="size-3.5" aria-hidden />
                  </button>
                )}
              </span>
            </li>
          );
        })}
        {/* The next option, drawn as one but a size down: it lines up with
            the letters above it without competing with them for the eye.
            Dashed rather than solid, and the label says what pressing it
            does — a lettered box that looked exactly like the others would
            read as an option someone forgot to fill in.
            The answer rides on the same line: both are about the key, and
            two half-empty rows in a row is a gap for no reason. */}
        <li className="flex items-center gap-2 pt-0.5">
          <button
            type="button"
            onClick={onAddOption}
            title="Add an option"
            className="group/add flex min-w-0 items-center gap-2 text-left"
          >
            <span
              className={cn(
                "flex size-5 shrink-0 items-center justify-center border border-dashed border-border text-muted-foreground transition-colors group-hover/add:border-primary group-hover/add:text-primary",
                wanted === 1 ? "rounded-full" : "rounded-[4px]",
              )}
            >
              <Plus className="size-3" aria-hidden />
            </span>
            <span className="text-sm text-muted-foreground/60 transition-colors group-hover/add:text-foreground">
              add an option
            </span>
          </button>

          {/* Already the report for an unfinished key — "1 of 2 marked" is
              the whole of what an issue about the answer would say — so a
              flagged one is coloured rather than described again. */}
          <span
            className={cn(
              "ml-auto shrink-0 pl-2 text-xs tabular-nums",
              issue?.kind === "answer"
                ? "text-destructive"
                : settled
                  ? "text-success"
                  : question.correct.length > 0
                    ? "text-warning"
                    : "text-muted-foreground/70",
            )}
          >
            {answerSummary(question, wanted)}
          </span>
        </li>
      </ul>

      {/* What the card can't already show — see `selfEvident`. On the
          question rather than under the group's toolbar, which is where the
          whole list used to sit: further from question 1 than anything else
          on screen, and naming the question because from down there it had
          to. */}
      {issue && !issue.selfEvident && (
        <p className="mt-2 flex items-start gap-1.5 text-xs text-destructive">
          <CircleAlert className="mt-0.5 size-3 shrink-0" aria-hidden />
          {issue.detail}
        </p>
      )}

      {/* Only once there is something to take, so most questions end at the
          options and this row isn't there at all. */}
      {transcriptSelection && (
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">

          <button
            type="button"
            // Keeps the transcript selection alive: a plain click would
            // collapse it before there was anything to read.
            onMouseDown={(e) => e.preventDefault()}
            onClick={takeFromTranscript}
            title={`Put “${transcriptSelection}” into the last field you were in`}
            className="flex items-center gap-1 text-xs text-primary transition-colors hover:text-primary/80"
          >
            <CornerUpLeft className="size-3" aria-hidden />
            from transcript
          </button>
        </div>
      )}
    </div>
  );
}

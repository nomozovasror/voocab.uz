import { useMemo } from "react";
import { CircleAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import { ChoiceBuilder } from "@/features/listening/components/ChoiceBuilder";
import { GroupHeader } from "@/features/listening/components/GroupHeader";
import { questionRangeLabel } from "@/features/listening/numbering";
import {
  ANSWER_COUNTS,
  choiceIssues,
  type ChoiceQuestion,
} from "@/features/listening/mcq";

/**
 * One multiple-choice group: its header, its instruction line, and the
 * questions under it.
 *
 * The counterpart of QuestionFormEditor, and deliberately its twin down to
 * the spacing — the two sit one above the other inside a part. The one thing
 * missing here is the answer-length row: how long an answer may be is not a
 * question you can ask about a letter.
 *
 * In its place, how many letters the candidate picks. It sits on the same
 * line as the instructions because it is the same statement — "Choose the
 * correct letter, A, B or C" against "Choose TWO letters, A–E" — and asking
 * it per question, as this used to, let a group be built whose heading and
 * questions disagreed.
 */

interface ChoiceGroupEditorProps {
  questions: ChoiceQuestion[];
  /** Applied against the latest list — see ChoiceBuilder's note. */
  onChange: (edit: (current: ChoiceQuestion[]) => ChoiceQuestion[]) => void;
  instructions: string;
  onInstructionsChange: (v: string) => void;
  /** How many options each question in this group wants marked. */
  answersPerQuestion: number;
  onAnswersPerQuestionChange: (v: number) => void;
  /** The number the first question of this group carries on the page. */
  startNumber: number;
  /** Set while a publish attempt is blocked on this group, so everything
   *  unfinished is marked even if the author hadn't looked yet. */
  showIssues?: boolean;
  transcriptSelection?: string;
  disabled?: boolean;
  extraTools?: React.ReactNode;
  onMoveUp?: () => void;
  onMoveDown?: () => void;
  onDelete?: () => void;
  canMoveUp?: boolean;
  canMoveDown?: boolean;
}

/** Whether the author has started this question. An untouched one is not a
 *  mistake — every group begins as a page of them — so it stays unmarked
 *  until either it has been written into or publishing asks for all of it. */
function isStarted(question: ChoiceQuestion): boolean {
  return (
    question.prompt.trim() !== "" ||
    question.options.some((option) => option.text.trim() !== "")
  );
}

export function ChoiceGroupEditor({
  questions,
  onChange,
  instructions,
  onInstructionsChange,
  answersPerQuestion,
  onAnswersPerQuestionChange,
  startNumber,
  showIssues,
  transcriptSelection,
  disabled,
  extraTools,
  onMoveUp,
  onMoveDown,
  onDelete,
  canMoveUp,
  canMoveDown,
}: ChoiceGroupEditorProps) {
  const issues = useMemo(
    () => choiceIssues(questions, startNumber - 1, answersPerQuestion),
    [questions, startNumber, answersPerQuestion],
  );

  const shown = useMemo(() => {
    if (showIssues) return issues;
    const started = new Set(
      questions.filter(isStarted).map((question) => question.id),
    );
    return issues.filter((issue) => started.has(issue.questionId));
  }, [issues, questions, showIssues]);

  const flagged = useMemo(
    () => new Set(shown.map((issue) => issue.questionId)),
    [shown],
  );

  // `inert` rather than only dimming and blocking the pointer: without it
  // everything in here stays tabbable, so a keyboard can walk into a section
  // that looks — and, for a mouse, is — switched off.
  return (
    <div inert={disabled} className={cn(disabled && "opacity-40")}>
      <GroupHeader
        range={questionRangeLabel(
          startNumber - 1,
          questions.length * answersPerQuestion,
        )}
        count={questions.length}
        typeLabel="Multiple choice"
        onMoveUp={onMoveUp}
        onMoveDown={onMoveDown}
        onDelete={onDelete}
        canMoveUp={canMoveUp}
        canMoveDown={canMoveDown}
      />

      {/* Both are the same statement — what the candidate is told to do —
          so they sit on one line, the same height, and the count reads as
          part of the instruction rather than as a stray setting beside it. */}
      <div className="mb-3 flex flex-wrap items-stretch gap-2">
        <input
          type="text"
          value={instructions}
          onChange={(e) => onInstructionsChange(e.target.value)}
          placeholder={
            answersPerQuestion === 1
              ? "Choose the correct letter, A, B or C."
              : `Choose ${WORD[answersPerQuestion] ?? answersPerQuestion} letters, A–E.`
          }
          aria-label="Instructions"
          className="h-10 min-w-0 flex-1 rounded-md border border-border bg-transparent px-3 text-sm text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:outline-none"
        />
        <AnswerCount
          value={answersPerQuestion}
          onChange={onAnswersPerQuestionChange}
        />
      </div>

      <ChoiceBuilder
        questions={questions}
        onChange={onChange}
        startNumber={startNumber}
        wanted={answersPerQuestion}
        flagged={flagged}
        transcriptSelection={transcriptSelection}
        extraTools={extraTools}
      />

      {shown.length > 0 && (
        <ul className="mt-2 space-y-1">
          {shown.map((issue) => (
            <li
              key={issue.questionId}
              className="flex items-start gap-1.5 text-xs text-destructive"
            >
              <CircleAlert className="mt-0.5 size-3 shrink-0" aria-hidden />
              {issue.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** "TWO", the way the rubric writes it. Only as far as the control goes. */
const WORD: Record<number, string> = { 2: "TWO", 3: "THREE" };

/** How many letters this group's questions each ask for.
 *
 *  Numbers rather than "one / several", because "several" is not what the
 *  paper says and not what the candidate needs: the instruction line names a
 *  number, and so does the count of checkboxes they are allowed to tick.
 *
 *  The word sits inside the same border as the numbers rather than floating
 *  to their left, where it belonged to nothing and left the pair looking
 *  like two controls that had drifted together. */
function AnswerCount({
  value,
  onChange,
}: {
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Answers per question"
      className="flex h-10 shrink-0 items-center gap-1 rounded-md border border-border pr-1 pl-3"
    >
      <span className="mr-1 text-xs text-muted-foreground">Answers</span>
      {ANSWER_COUNTS.map((count) => (
        <button
          key={count}
          type="button"
          onClick={() => onChange(count)}
          aria-pressed={value === count}
          title={
            count === 1
              ? "One correct answer per question"
              : `${count} correct answers per question, all of which must be picked`
          }
          className={cn(
            "flex size-8 items-center justify-center rounded text-sm tabular-nums transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
            value === count
              ? "bg-primary/15 font-medium text-primary"
              : "text-muted-foreground hover:bg-foreground/6 hover:text-foreground",
          )}
        >
          {count}
        </button>
      ))}
    </div>
  );
}

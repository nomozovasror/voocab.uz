import { useMemo } from "react";
import { CircleAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import { ChoiceBuilder } from "@/features/listening/components/ChoiceBuilder";
import { GroupHeader } from "@/features/listening/components/GroupHeader";
import { questionRangeLabel } from "@/features/listening/numbering";
import { choiceIssues, type ChoiceQuestion } from "@/features/listening/mcq";

/**
 * One multiple-choice group: its header, its instruction line, and the
 * questions under it.
 *
 * The counterpart of QuestionFormEditor, and deliberately its twin down to
 * the spacing — the two sit one above the other inside a part. The one thing
 * missing here is the answer-length row: how long an answer may be is not a
 * question you can ask about a letter.
 */

interface ChoiceGroupEditorProps {
  questions: ChoiceQuestion[];
  /** Applied against the latest list — see ChoiceBuilder's note. */
  onChange: (edit: (current: ChoiceQuestion[]) => ChoiceQuestion[]) => void;
  instructions: string;
  onInstructionsChange: (v: string) => void;
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
    () => choiceIssues(questions, startNumber - 1),
    [questions, startNumber],
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
        range={questionRangeLabel(startNumber - 1, questions.length)}
        count={questions.length}
        typeLabel="Multiple choice"
        onMoveUp={onMoveUp}
        onMoveDown={onMoveDown}
        onDelete={onDelete}
        canMoveUp={canMoveUp}
        canMoveDown={canMoveDown}
      />

      <input
        type="text"
        value={instructions}
        onChange={(e) => onInstructionsChange(e.target.value)}
        placeholder="Choose the correct letter, A, B or C."
        aria-label="Instructions"
        className="mb-3 w-full rounded-md border border-border bg-transparent px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:outline-none"
      />

      <ChoiceBuilder
        questions={questions}
        onChange={onChange}
        startNumber={startNumber}
        flagged={flagged}
        transcriptSelection={transcriptSelection}
        extraTools={extraTools}
      />

      {shown.length > 0 && (
        <ul className="mt-2 space-y-1">
          {shown.map((issue) => (
            <li
              key={issue.questionId}
              className="flex items-start gap-1.5 text-[11px] text-destructive"
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

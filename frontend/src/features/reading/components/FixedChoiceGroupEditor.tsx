import { useMemo } from "react";
import { Plus, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { GroupHeader } from "@/features/listening/components/GroupHeader";
import { questionRangeLabel } from "@/features/paper/numbering";
import { newId } from "@/features/paper/form-syntax";
import type { MatchItem } from "@/features/paper/matching";
import {
  FIXED_CHOICE_OPTIONS,
  QUESTION_TYPE_LABEL,
} from "@/features/paper/question-types";
import type { FixedChoiceType } from "@/features/paper/types";

/**
 * A true/false/not-given set, or its yes/no twin.
 *
 * The simplest group in the editor, and deliberately so: there is no box to
 * write, no options to order and no letters to hand out. The author writes
 * statements and says which of three words each one is, and the three words
 * are the type's — the same constant the server grades against, so what is on
 * screen cannot drift from what marks the paper.
 *
 * It reuses `MatchItem` rather than inventing a row of its own. The shape is
 * the same — a prompt and one answer — and the difference is only what the
 * answer IS: an option id there, and here the word itself, because the word
 * is what the answer key prints and what the candidate submits.
 */

interface FixedChoiceGroupEditorProps {
  type: FixedChoiceType;
  items: MatchItem[];
  onItemsChange: (edit: (current: MatchItem[]) => MatchItem[]) => void;
  instructions: string;
  onInstructionsChange: (v: string) => void;
  /** The number the first statement of this group carries on the page. */
  startNumber: number;
  /** Set while a publish attempt is blocked on this group, so everything
   *  unfinished is marked even if the author hadn't looked yet. */
  showIssues?: boolean;
  disabled?: boolean;
  extraTools?: React.ReactNode;
  onMoveUp?: () => void;
  onMoveDown?: () => void;
  onDelete?: () => void;
  canMoveUp?: boolean;
  canMoveDown?: boolean;
}

/** The instruction line each of the two is printed under, offered as the
 *  placeholder so an author who types nothing still sees what belongs there. */
const RUBRIC: Record<FixedChoiceType, string> = {
  true_false_not_given:
    "Do the following statements agree with the information given in the passage?",
  yes_no_not_given:
    "Do the following statements agree with the claims of the writer?",
};

export function newStatement(): MatchItem {
  return {
    id: newId(),
    prompt: "",
    answer: null,
    replayStartMs: null,
    replayEndMs: null,
  };
}

export function FixedChoiceGroupEditor({
  type,
  items,
  onItemsChange,
  instructions,
  onInstructionsChange,
  startNumber,
  showIssues,
  disabled,
  extraTools,
  onMoveUp,
  onMoveDown,
  onDelete,
  canMoveUp,
  canMoveDown,
}: FixedChoiceGroupEditorProps) {
  const options = FIXED_CHOICE_OPTIONS[type];

  /** Only the statements the author has actually started, unless publishing
   *  has asked for all of them — the same rule every other builder here
   *  follows, because an untouched group is not a mistake. */
  const flagged = useMemo(() => {
    const out = new Set<string>();
    for (const item of items) {
      const started = item.prompt.trim() !== "" || item.answer !== null;
      if (!showIssues && !started) continue;
      if (item.prompt.trim() === "" || item.answer === null) out.add(item.id);
    }
    return out;
  }, [items, showIssues]);

  return (
    <div inert={disabled} className={cn(disabled && "opacity-40")}>
      <GroupHeader
        range={questionRangeLabel(startNumber - 1, items.length)}
        count={items.length}
        typeLabel={QUESTION_TYPE_LABEL[type]}
        onMoveUp={onMoveUp}
        onMoveDown={onMoveDown}
        onDelete={onDelete}
        canMoveUp={canMoveUp}
        canMoveDown={canMoveDown}
      />

      <div className="mb-3 flex flex-wrap items-stretch gap-2">
        <input
          type="text"
          value={instructions}
          onChange={(e) => onInstructionsChange(e.target.value)}
          placeholder={RUBRIC[type]}
          aria-label="Instructions"
          className="h-10 min-w-0 flex-1 rounded-md border border-border bg-transparent px-3 text-sm text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:outline-none"
        />
      </div>

      <ol className="space-y-2">
        {items.map((item, index) => (
          <li
            key={item.id}
            className={cn(
              "flex flex-wrap items-center gap-2 rounded-md border px-3 py-2",
              flagged.has(item.id) ? "border-destructive/60" : "border-border",
            )}
          >
            <span className="w-7 shrink-0 text-xs tabular-nums text-muted-foreground">
              {startNumber + index}
            </span>
            <input
              type="text"
              value={item.prompt}
              onChange={(e) =>
                onItemsChange((current) =>
                  current.map((row) =>
                    row.id === item.id ? { ...row, prompt: e.target.value } : row,
                  ),
                )
              }
              placeholder="The statement to be judged"
              aria-label={`Statement ${startNumber + index}`}
              className="h-9 min-w-0 flex-1 rounded-md border border-border bg-transparent px-3 text-sm text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:outline-none"
            />
            {/* One control per answer, not a select: three options is few
                enough to show, and showing them is what makes the key
                readable down the column at a glance. */}
            <div className="flex shrink-0 gap-1">
              {options.map((word) => (
                <button
                  key={word}
                  type="button"
                  aria-pressed={item.answer === word}
                  onClick={() =>
                    onItemsChange((current) =>
                      current.map((row) =>
                        row.id === item.id
                          ? { ...row, answer: row.answer === word ? null : word }
                          : row,
                      ),
                    )
                  }
                  className={cn(
                    "rounded-md border px-2 py-1 text-xs transition-colors duration-fast focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                    item.answer === word
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border text-muted-foreground hover:text-foreground",
                  )}
                >
                  {word}
                </button>
              ))}
            </div>
            <button
              type="button"
              aria-label={`Remove statement ${startNumber + index}`}
              onClick={() =>
                onItemsChange((current) =>
                  current.filter((row) => row.id !== item.id),
                )
              }
              className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors duration-fast hover:text-destructive focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              <Trash2 className="size-3.5" aria-hidden />
            </button>
          </li>
        ))}
      </ol>

      <div className="mt-2 flex items-center gap-2">
        <button
          type="button"
          onClick={() => onItemsChange((current) => [...current, newStatement()])}
          className="flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground transition-colors duration-fast hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          <Plus className="size-3.5" aria-hidden />
          Add a statement
        </button>
        {extraTools}
      </div>
    </div>
  );
}

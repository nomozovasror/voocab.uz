import { useMemo } from "react";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";
import { GroupHeader } from "@/features/listening/components/GroupHeader";
import { MatchingBuilder } from "@/features/listening/components/MatchingBuilder";
import { questionRangeLabel } from "@/features/paper/numbering";
import {
  matchingIssues,
  type MatchItem,
  type MatchOption,
} from "@/features/paper/matching";

/**
 * One matching group: its header, its instruction line, and the box and items
 * under it.
 *
 * Deliberately the twin of ChoiceGroupEditor down to the spacing — the two sit
 * one above the other inside a part. Where multiple choice puts "how many
 * letters" beside the instructions, this puts whether a letter may answer more
 * than one item, for the same reason: it is part of the same statement. A real
 * paper prints it as an NB line directly under the rubric, and asking it per
 * question would let a group be built whose heading and questions disagreed.
 */

interface MatchingGroupEditorProps {
  options: MatchOption[];
  items: MatchItem[];
  onOptionsChange: (edit: (current: MatchOption[]) => MatchOption[]) => void;
  onItemsChange: (edit: (current: MatchItem[]) => MatchItem[]) => void;
  onRemoveOption: (optionId: string) => void;
  instructions: string;
  onInstructionsChange: (v: string) => void;
  allowReuse: boolean;
  onAllowReuseChange: (v: boolean) => void;
  /** The number the first item of this group carries on the page. */
  startNumber: number;
  /** Set while a publish attempt is blocked on this group, so everything
   *  unfinished is marked even if the author hadn't looked yet. */
  showIssues?: boolean;
  transcriptSelection?: string;
  onMarkAudio?: (
    answers: string[],
    apply: (range: { startMs: number; endMs: number }) => void,
  ) => void;
  disabled?: boolean;
  extraTools?: React.ReactNode;
  onMoveUp?: () => void;
  onMoveDown?: () => void;
  onDelete?: () => void;
  canMoveUp?: boolean;
  canMoveDown?: boolean;
}

export function MatchingGroupEditor({
  options,
  items,
  onOptionsChange,
  onItemsChange,
  onRemoveOption,
  instructions,
  onInstructionsChange,
  allowReuse,
  onAllowReuseChange,
  startNumber,
  showIssues,
  transcriptSelection,
  onMarkAudio,
  disabled,
  extraTools,
  onMoveUp,
  onMoveDown,
  onDelete,
  canMoveUp,
  canMoveDown,
}: MatchingGroupEditorProps) {
  const issues = useMemo(
    () => matchingIssues(options, items, startNumber - 1, allowReuse),
    [options, items, startNumber, allowReuse],
  );

  /** Only the ones about work the author has actually started, unless
   *  publishing has asked for all of it. An untouched group is not a mistake
   *  — every group begins as a page of them. */
  const shown = useMemo(() => {
    if (showIssues) return issues;
    const started = new Set(
      items
        .filter((item) => item.prompt.trim() !== "" || item.answer !== null)
        .map((item) => item.id),
    );
    const anythingWritten =
      started.size > 0 || options.some((option) => option.text.trim() !== "");
    return issues.filter((issue) =>
      issue.itemId === null ? anythingWritten : started.has(issue.itemId),
    );
  }, [issues, items, options, showIssues]);

  // `inert` rather than only dimming and blocking the pointer: without it
  // everything in here stays tabbable, so a keyboard can walk into a section
  // that looks — and, for a mouse, is — switched off.
  return (
    <div inert={disabled} className={cn(disabled && "opacity-40")}>
      <GroupHeader
        range={questionRangeLabel(startNumber - 1, items.length)}
        count={items.length}
        typeLabel="Matching"
        onMoveUp={onMoveUp}
        onMoveDown={onMoveDown}
        onDelete={onDelete}
        canMoveUp={canMoveUp}
        canMoveDown={canMoveDown}
      />

      {/* Both are the same statement — what the candidate is told to do — so
          they sit on one line and share a height. */}
      <div className="mb-3 flex flex-wrap items-stretch gap-2">
        <input
          type="text"
          value={instructions}
          onChange={(e) => onInstructionsChange(e.target.value)}
          placeholder="What does the speaker say about each place? Choose your answers from the box."
          aria-label="Instructions"
          className="h-10 min-w-0 flex-1 rounded-md border border-border bg-transparent px-3 text-sm text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:outline-none"
        />
        <ReuseToggle value={allowReuse} onChange={onAllowReuseChange} />
      </div>

      <MatchingBuilder
        options={options}
        items={items}
        onOptionsChange={onOptionsChange}
        onItemsChange={onItemsChange}
        onRemoveOption={onRemoveOption}
        startNumber={startNumber}
        allowReuse={allowReuse}
        issues={shown}
        transcriptSelection={transcriptSelection}
        onMarkAudio={onMarkAudio}
        extraTools={extraTools}
      />
    </div>
  );
}

/** Whether one option may answer more than one item.
 *
 *  One switch, not a pair of buttons. Multiple choice's neighbouring control
 *  offers 1, 2 or 3 and needs three of them; this has two states, and drawn
 *  the same way it needed a word to label it — at which point "Letters",
 *  "once" and "reused" were three words side by side and the label read as a
 *  third option that happened never to be selected.
 *
 *  So the label is the switch. It says the thing a real paper prints under
 *  the rubric, and ticking it is what puts that line on the candidate's page.
 */
function ReuseToggle({
  value,
  onChange,
}: {
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={value}
      onClick={() => onChange(!value)}
      title={
        value
          ? "The paper says: NB You may use any letter more than once"
          : "Each option answers one question"
      }
      className={cn(
        "flex h-10 shrink-0 items-center gap-2 rounded-md border px-3 text-sm transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
        value
          ? "border-primary/40 bg-primary/10 text-primary"
          : "border-border text-muted-foreground hover:bg-foreground/4 hover:text-foreground",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "flex size-4 shrink-0 items-center justify-center rounded-[4px] border transition-colors",
          value ? "border-primary bg-primary/20" : "border-border",
        )}
      >
        {value && <Check className="size-3" aria-hidden />}
      </span>
      reuse letters
    </button>
  );
}

import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { QuestionTypeChoices } from "@/features/listening/components/QuestionTypeChoices";
import type { QuestionGroupType } from "@/features/paper/types";

/**
 * What a group is, asked once, before there is anything in it.
 *
 * It stands where the group will stand, in the part it belongs to, because
 * the answer depends on which part that is: Part 1 is a completion task and
 * is never asked at all, Part 2 leads with the map that only it labels.
 * Asking in the dialog before the editor opened would have meant asking once
 * for a whole test and getting it wrong for three quarters of it.
 *
 * This is the question asked of a group added mid-edit. The same question for
 * a material's opening groups is asked by EditorSetup, before the editor is
 * any use at all — both draw their cards from QuestionTypeChoices.
 *
 * Dashed, like the empty states elsewhere in the studio: nothing has been
 * written here yet, and the block is a place for something rather than the
 * something itself.
 */

interface GroupTypeChooserProps {
  types: QuestionGroupType[];
  onChoose: (type: QuestionGroupType) => void;
  /** Dropping the group without choosing. Always offered — a part with no
   *  groups left has its own way back in. */
  onRemove: () => void;
  disabled?: boolean;
}

export function GroupTypeChooser({
  types,
  onChoose,
  onRemove,
  disabled,
}: GroupTypeChooserProps) {
  return (
    <div
      inert={disabled}
      className={cn(
        "group/chooser relative rounded-lg border border-dashed border-border p-4",
        disabled && "opacity-40",
      )}
    >
      <div className="mb-3 flex items-baseline gap-2">
        <h4 className="text-sm font-medium text-foreground">
          What kind of questions?
        </h4>
        <button
          type="button"
          onClick={onRemove}
          aria-label="Remove this group"
          title="Remove this group"
          className="ml-auto flex size-6 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-opacity group-hover/chooser:opacity-100 hover:text-destructive focus-visible:opacity-100"
        >
          <X className="size-3.5" aria-hidden />
        </button>
      </div>

      <QuestionTypeChoices types={types} onChoose={onChoose} />
    </div>
  );
}

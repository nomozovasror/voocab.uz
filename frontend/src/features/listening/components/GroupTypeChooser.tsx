import { ListChecks, Rows3, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  QUESTION_TYPE_BLURB,
  QUESTION_TYPE_LABEL,
} from "@/features/listening/parts";
import type { QuestionGroupType } from "@/features/listening/types";

/**
 * What a group is, asked once, before there is anything in it.
 *
 * It stands where the group will stand, in the part it belongs to, because
 * the answer depends on which part that is: Part 1 is a completion task and
 * is never asked at all, Part 2 has no map labelling to offer yet. Asking in
 * the dialog before the editor opened would have meant asking once for a
 * whole test and getting it wrong for three quarters of it.
 *
 * Dashed, like the empty states elsewhere in the studio: nothing has been
 * written here yet, and the block is a place for something rather than the
 * something itself.
 */

const TYPE_ICON: Record<QuestionGroupType, LucideIcon> = {
  form_completion: Rows3,
  multiple_choice: ListChecks,
};

interface GroupTypeChooserProps {
  types: QuestionGroupType[];
  onChoose: (type: QuestionGroupType) => void;
  /** Dropping the group without choosing. Always offered — a part with no
   *  groups left has its own way back in. */
  onRemove: () => void;
  /** What this part is known for that isn't built yet, so a short list of
   *  choices reads as "not yet" rather than "not allowed". */
  note?: string;
  disabled?: boolean;
}

export function GroupTypeChooser({
  types,
  onChoose,
  onRemove,
  note,
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

      <div className="grid gap-3 sm:grid-cols-2">
        {types.map((type) => {
          const Icon = TYPE_ICON[type];
          return (
            <button
              key={type}
              type="button"
              onClick={() => onChoose(type)}
              className="flex items-start gap-3 rounded-lg border border-border px-4 py-3 text-left transition-colors hover:border-primary hover:bg-foreground/[0.03] focus-visible:border-primary focus-visible:outline-none"
            >
              <Icon className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
              <span className="min-w-0">
                <span className="block text-sm text-foreground">
                  {QUESTION_TYPE_LABEL[type]}
                </span>
                <span className="mt-1 block text-[11px] text-muted-foreground">
                  {QUESTION_TYPE_BLURB[type]}
                </span>
              </span>
            </button>
          );
        })}
      </div>

      {note && (
        <p className="mt-3 text-[11px] text-muted-foreground">{note}</p>
      )}
    </div>
  );
}

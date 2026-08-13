import { ListChecks, Rows3, SquarePlus } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { QUESTION_TYPE_LABEL } from "@/features/listening/parts";
import type { QuestionGroupType } from "@/features/listening/types";

/**
 * The row of controls under a builder, and the one control both builders
 * share.
 *
 * They live here rather than in either builder because the row has to look
 * the same in both: a part can hold a form and a set of multiple-choice
 * questions one after another, and two different-looking toolbars would make
 * that read as two different tools.
 */

export function ToolbarButton({
  onClick,
  icon,
  label,
  title,
}: {
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/60 hover:bg-foreground/5 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
    >
      {icon}
      {label}
    </button>
  );
}

const TYPE_ICON: Record<QuestionGroupType, LucideIcon> = {
  form_completion: Rows3,
  multiple_choice: ListChecks,
};

/** Adds a group after this one. The type is chosen on the way in rather than
 *  switched afterwards: it decides what the whole block is, and an empty
 *  group is nothing to lose by deleting and adding the other kind.
 *
 *  `types` is what this part may be given (features/listening/parts.ts) —
 *  Part 1 is a completion task and nothing else, so there it is one button
 *  rather than a menu with one thing in it. */
export function AddGroupButton({
  types,
  onAdd,
}: {
  types: QuestionGroupType[];
  onAdd: (type: QuestionGroupType) => void;
}) {
  const trigger = (onClick?: () => void) => (
    <button
      type="button"
      onClick={onClick}
      title="Add another group of questions after this one"
      className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/60 hover:bg-foreground/5 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
    >
      <SquarePlus className="size-3.5" aria-hidden />
      question group
    </button>
  );

  if (types.length <= 1) {
    const only = types[0] ?? "form_completion";
    return trigger(() => onAdd(only));
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>{trigger()}</DropdownMenuTrigger>
      <DropdownMenuContent align="center" className="w-52">
        {types.map((type) => {
          const Icon = TYPE_ICON[type];
          return (
            <DropdownMenuItem key={type} onClick={() => onAdd(type)}>
              <Icon aria-hidden />
              {QUESTION_TYPE_LABEL[type]}
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

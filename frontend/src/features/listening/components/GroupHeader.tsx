import {
  ChevronDown,
  ChevronUp,
  EllipsisVertical,
  Trash2,
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

/**
 * The line that opens a question group: the run of numbers it covers, how
 * many questions that is, and what kind they are.
 *
 * One header for both builders, because the two are the same object to the
 * author — "Questions 7–10, multiple choice" reads the same whichever it is,
 * and a part that mixes them should not look like two different screens
 * stacked.
 */

interface GroupHeaderProps {
  /** "Questions 7–10". Empty while the group has nothing in it yet. */
  range: string;
  count: number;
  typeLabel: string;
  onMoveUp?: () => void;
  onMoveDown?: () => void;
  onDelete?: () => void;
  /** Both ends of the stack: the menu still opens, the move that can't
   *  happen is simply greyed. */
  canMoveUp?: boolean;
  canMoveDown?: boolean;
}

export function GroupHeader({
  range,
  count,
  typeLabel,
  onMoveUp,
  onMoveDown,
  onDelete,
  canMoveUp,
  canMoveDown,
}: GroupHeaderProps) {
  const hasMenu = !!(onMoveUp || onMoveDown || onDelete);

  return (
    <div className="mb-2 flex items-center gap-x-2.5 gap-y-1">
      {/* A group with no questions has no run to name. "New group" says what
          it is without claiming a range that would read backwards. */}
      <h4 className="min-w-0 truncate text-sm font-medium text-foreground">
        {range || "New group"}
      </h4>
      {/* The three of them travel together on the right. They used to be
          loose children of a wrapping row, so a narrow pane could break the
          line between the chip and the menu and leave the menu adrift on the
          next one — or off the end of it. */}
      <div className="ml-auto flex shrink-0 items-center gap-2.5">
        <span className="hidden text-[11px] tabular-nums text-muted-foreground sm:inline">
          {count} {count === 1 ? "question" : "questions"}
        </span>
        <span className="rounded-full bg-primary/12 px-2 py-0.5 text-[11px] text-primary">
          {typeLabel}
        </span>

        {hasMenu && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                title="Group actions"
                aria-label="Group actions"
                className="flex size-7 shrink-0 items-center justify-center rounded-md border border-border text-muted-foreground transition-colors hover:bg-foreground/8 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                <EllipsisVertical className="size-4" aria-hidden />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44">
              <DropdownMenuItem onClick={onMoveUp} disabled={!canMoveUp}>
                <ChevronUp aria-hidden />
                Move up
              </DropdownMenuItem>
              <DropdownMenuItem onClick={onMoveDown} disabled={!canMoveDown}>
                <ChevronDown aria-hidden />
                Move down
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" onClick={onDelete}>
                <Trash2 aria-hidden />
                Delete group
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
    </div>
  );
}

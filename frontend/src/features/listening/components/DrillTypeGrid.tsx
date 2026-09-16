import {
  QUESTION_TYPE_BLURB,
  QUESTION_TYPE_ICON,
  QUESTION_TYPE_LABEL,
} from "@/features/listening/parts";
import { QUESTION_TYPE_ORDER } from "@/features/listening/practice";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { DrillType, QuestionGroupType } from "@/features/listening/types";

/**
 * The Drills tab's front page: every kind of task, and what there is of it.
 *
 * A grid of cards rather than a list of all 470 drills, because the question
 * somebody arrives with is "what can I practise", not "which of these 470".
 * The count on the card is the answer to the first one and the way into the
 * second.
 *
 * Everything a card says about a task type — its name, what it is, its mark —
 * is read from the canonical tables in `parts.ts`, the same three the editor's
 * chooser and the catalogue row read. An author who built a map-labelling
 * group and a learner looking for one should be looking at the same icon.
 */

const GRID = "mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3";

export function DrillTypeGrid({
  types,
  loading,
  onPick,
}: {
  types: DrillType[];
  loading: boolean;
  onPick: (type: QuestionGroupType) => void;
}) {
  if (loading) {
    return (
      <div className={GRID} aria-hidden>
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-[6.5rem] rounded-xl" />
        ))}
      </div>
    );
  }

  // In the canonical table's order, not by count, so a card keeps its place
  // from one visit to the next — a grid that reorders itself as the library
  // grows is a grid nobody learns. A type with nothing in it is not drawn at
  // all, the same rule the filter menus apply.
  const byValue = new Map(types.map((t) => [t.value, t]));
  const shown = QUESTION_TYPE_ORDER.map((value) => byValue.get(value)).filter(
    (t): t is DrillType => t !== undefined && t.exercises > 0,
  );

  if (shown.length === 0) {
    return (
      <div className="mt-6 rounded-xl border border-dashed border-border px-5 py-12 text-center">
        <p className="text-sm text-muted-foreground">
          There is nothing to drill yet — a drill needs a material whose
          answers have been marked in the recording.
        </p>
      </div>
    );
  }

  return (
    <div className={GRID}>
      {shown.map((type) => (
        <DrillTypeCard key={type.value} type={type} onPick={onPick} />
      ))}
    </div>
  );
}

function DrillTypeCard({
  type,
  onPick,
}: {
  type: DrillType;
  onPick: (type: QuestionGroupType) => void;
}) {
  const Icon = QUESTION_TYPE_ICON[type.value];
  const finished = type.done >= type.exercises && type.exercises > 0;
  return (
    <button
      type="button"
      onClick={() => onPick(type.value)}
      className={cn(
        "group flex flex-col items-start gap-1 rounded-xl border border-border-subtle bg-surface p-4 text-left",
        "transition-colors hover:border-border hover:bg-surface-hover",
        "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
      )}
    >
      <span className="flex items-center gap-2">
        <Icon className="size-4 text-muted-foreground" aria-hidden />
        <span className="text-sm font-medium text-foreground">
          {QUESTION_TYPE_LABEL[type.value]}
        </span>
      </span>
      <span className="text-xs text-muted-foreground">
        {QUESTION_TYPE_BLURB[type.value]}
      </span>
      <span className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
        <span className="tabular-nums text-foreground">{type.exercises}</span>
        {type.exercises === 1 ? "drill" : "drills"}
        <span aria-hidden className="text-border">·</span>
        <span className="tabular-nums">{type.questions}</span>
        questions
      </span>
      {/* Progress is green, never the accent — the accent means "this is the
          action", and how far somebody has got is a report. */}
      {type.done > 0 && (
        <span
          className={cn(
            "text-xs tabular-nums",
            finished ? "text-correct" : "text-muted-foreground",
          )}
        >
          {finished ? "All done" : `${type.done} done`}
        </span>
      )}
    </button>
  );
}

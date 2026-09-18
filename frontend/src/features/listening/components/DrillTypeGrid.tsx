import { TASK_FAMILIES, familyIcon } from "@/features/listening/practice";
import type { TaskFamily } from "@/features/listening/practice";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { DrillType } from "@/features/listening/types";

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

/** One card: a family, and what the library holds of it.
 *
 *  The server counts per TYPE, because that is what a question group has. The
 *  folding happens here, where the families are — a card covering two types
 *  carries the sum of both, and because families never share a type the sums
 *  cannot double-count. */
interface Card extends TaskFamily {
  exercises: number;
  questions: number;
  done: number;
}

/** Whether a card answers what was typed. Over the NAME and the description,
 *  not the materials underneath: on this screen the reader is choosing a kind
 *  of task, and "map" should find labelling without them having to know which
 *  books contain one. Every whitespace-separated term must appear, the same
 *  rule the studio's own search follows. */
function matches(card: Card, terms: string[]): boolean {
  // The member types' own names are searched too, so "diagram" still finds
  // the card that swallowed diagram labelling.
  const hay = `${card.label} ${card.blurb} ${card.types.join(" ")}`
    .toLowerCase()
    .replace(/_/g, " ");
  return terms.every((term) => hay.includes(term));
}

export function DrillTypeGrid({
  types,
  loading,
  query,
  onPick,
}: {
  types: DrillType[];
  loading: boolean;
  /** The same field that searches the other two lists. */
  query: string;
  onPick: (key: string) => void;
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
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const byValue = new Map(types.map((t) => [t.value, t]));
  const shown = TASK_FAMILIES.map((family) => {
    const counted = family.types
      .map((type) => byValue.get(type))
      .filter((t): t is DrillType => t !== undefined);
    return {
      ...family,
      exercises: counted.reduce((n, t) => n + t.exercises, 0),
      questions: counted.reduce((n, t) => n + t.questions, 0),
      done: counted.reduce((n, t) => n + t.done, 0),
    };
  }).filter((card) => card.exercises > 0 && matches(card, terms));

  if (shown.length === 0) {
    return (
      <div className="mt-6 rounded-xl border border-dashed border-border px-5 py-12 text-center">
        {/* Three different facts, said differently. A search that found
            nothing is a state the reader put the page in, a part with no
            tasks of any kind is a fact about the paper, and an empty library
            is a fact about the library. */}
        <p className="text-sm text-muted-foreground">
          {terms.length > 0
            ? "No kind of question matches that."
            : types.length > 0
              ? "No tasks of any kind in that part."
              : "There is nothing to practise yet — a drill needs a material whose answers have been marked in the recording."}
        </p>
      </div>
    );
  }

  return (
    <div className={GRID}>
      {shown.map((card) => (
        <DrillTypeCard key={card.key} card={card} onPick={onPick} />
      ))}
    </div>
  );
}

function DrillTypeCard({
  card,
  onPick,
}: {
  card: Card;
  onPick: (key: string) => void;
}) {
  const Icon = familyIcon(card);
  const finished = card.done >= card.exercises && card.exercises > 0;
  return (
    <button
      type="button"
      onClick={() => onPick(card.key)}
      className={cn(
        "group flex flex-col items-start gap-1 rounded-xl border border-border-subtle bg-surface p-4 text-left",
        "transition-colors hover:border-border hover:bg-surface-hover",
        "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
      )}
    >
      <span className="flex items-center gap-2">
        <Icon className="size-4 text-muted-foreground" aria-hidden />
        <span className="text-sm font-medium text-foreground">
          {card.label}
        </span>
      </span>
      <span className="text-xs text-muted-foreground">
        {card.blurb}
      </span>
      <span className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
        <span className="tabular-nums text-foreground">{card.exercises}</span>
        {card.exercises === 1 ? "exercise" : "exercises"}
        <span aria-hidden className="text-border">·</span>
        <span className="tabular-nums">{card.questions}</span>
        questions
      </span>

      {/* How far through this kind they are, said the same way whether they
          have started it or not: "0 of 23" is a fact and an empty space is a
          card that has stopped paying attention. Green, never the accent —
          the accent means "this is the action" and a progress bar is a
          report. */}
      <span className="mt-2 w-full">
        <span className="flex items-center justify-between text-xs">
          <span
            className={cn(
              "tabular-nums",
              finished ? "text-correct" : "text-muted-foreground",
            )}
          >
            {finished ? "All done" : `${card.done} of ${card.exercises} done`}
          </span>
          {card.done > 0 && !finished && (
            <span className="tabular-nums text-muted-foreground">
              {Math.round((card.done / card.exercises) * 100)}%
            </span>
          )}
        </span>
        <span
          aria-hidden
          className="mt-1 block h-1 overflow-hidden rounded-full bg-border-subtle"
        >
          <span
            className="block h-full rounded-full bg-correct transition-[width] duration-base"
            style={{
              width: `${Math.round((card.done / Math.max(1, card.exercises)) * 100)}%`,
            }}
          />
        </span>
      </span>
    </button>
  );
}

import { Link } from "react-router-dom";
import { Check } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { fmtClock } from "@/lib/time";
import type { PracticeDrill } from "@/features/listening/types";

/**
 * The exercises of one kind, as a list.
 *
 * `LessonList`'s shape — a rail of numbered stops down the left, done ones
 * ticked and faded, the next one lit — for the same reason the grid borrowed
 * the course grid's: a reader who has learned to read one of these has
 * learned to read both.
 *
 * With one honest difference, and it is worth writing down. A course's order
 * is somebody's JUDGEMENT about what to do when, which is what its rail draws.
 * This order is the list's own — newest first — and nobody laid it out. So the
 * rail here is a position rather than a curriculum: the numbers exist because
 * they are the SAME numbers the grid draws, so square 183 and row 183 are the
 * same exercise and switching views does not lose your place. Nothing in this
 * list claims a suggested order, and `Next` means only "the first you have not
 * done".
 */

type Status = "done" | "next" | "todo";

function statusOf(d: PracticeDrill, nextId: string | null): Status {
  if (d.attempts > 0) return "done";
  return d.group_id === nextId ? "next" : "todo";
}

/**
 * One stop on the rail: the marker, and the line joining it to its
 * neighbours.
 *
 * Two halves rather than one line, so the first and last stops can drop the
 * half that would run off the end — a rail continuing past the last exercise
 * suggests one that isn't there. The upper half is coloured by the PREVIOUS
 * stop, because the segment between two markers belongs to the ground already
 * covered.
 */
function Rail({
  status,
  index,
  first,
  last,
  afterDone,
}: {
  status: Status;
  index: number;
  first: boolean;
  last: boolean;
  afterDone: boolean;
}) {
  return (
    <div className="relative flex w-8 shrink-0 flex-col items-center self-stretch">
      <span
        aria-hidden
        className={cn(
          "w-px flex-1",
          first ? "bg-transparent" : afterDone ? "bg-correct/40" : "bg-border",
        )}
      />
      <span
        aria-hidden
        className={cn(
          // Wider than the course's, because these run to three digits where
          // a course runs to two: 188 in a 20px circle is not a number.
          "my-1 flex h-5 min-w-6 shrink-0 items-center justify-center rounded-full px-1 text-xs tabular-nums",
          status === "done" && "bg-correct/20 text-correct",
          status === "next" && "bg-primary text-primary-foreground",
          status === "todo" && "border border-border text-muted-foreground",
        )}
      >
        {status === "done" ? (
          <Check className="size-3" strokeWidth={3} />
        ) : (
          index
        )}
      </span>
      <span
        aria-hidden
        className={cn(
          "w-px flex-1",
          last
            ? "bg-transparent"
            : status === "done"
              ? "bg-correct/40"
              : "bg-border",
        )}
      />
    </div>
  );
}

function DrillRow({
  drill: d,
  index,
  status,
  first,
  last,
  afterDone,
  revealRef,
}: {
  drill: PracticeDrill;
  index: number;
  status: Status;
  first: boolean;
  last: boolean;
  afterDone: boolean;
  revealRef?: (el: HTMLLIElement | null) => void;
}) {
  const done = status === "done";
  // First-try, not best: the number beside an exercise measures the reader,
  // and a record is what a card is for.
  const pct =
    d.first_score !== null && d.question_count > 0
      ? Math.round((d.first_score / d.question_count) * 100)
      : null;

  return (
    <li ref={revealRef} className="flex items-stretch">
      <Rail
        status={status}
        index={index}
        first={first}
        last={last}
        afterDone={afterDone}
      />
      <Link
        to={`/listening/drills/${d.group_id}`}
        className={cn(
          "my-0.5 flex min-w-0 flex-1 items-center gap-4 rounded-lg px-3 py-2.5 transition-colors duration-fast",
          "hover:bg-surface-hover focus-visible:bg-surface-hover focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
          status === "next" && "bg-surface-sunken",
        )}
      >
        <div className="min-w-0 flex-1">
          <p
            className={cn(
              "flex min-w-0 items-center gap-2 truncate text-sm",
              done ? "text-muted-foreground" : "text-foreground",
            )}
          >
            <span className="truncate">{d.material_title}</span>
            {status === "next" && (
              <span className="shrink-0 rounded-full bg-primary/15 px-2 py-0.5 text-xs font-medium text-primary">
                Next
              </span>
            )}
          </p>
          <p
            className={cn(
              "mt-0.5 truncate text-xs",
              done ? "text-muted-foreground/60" : "text-muted-foreground",
            )}
          >
            {[
              // The numbers the paper prints, first — they are what tells two
              // maps out of the same book apart.
              `Questions ${d.first_number}–${d.last_number}`,
              `Part ${d.part_number}`,
              // The CLIP's length, which is the promise the row makes about
              // how long this will take.
              d.clip_ms != null ? fmtClock(d.clip_ms) : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>

        {/* Never blank. An empty column beside a row reads as data that
            failed to load; "Not done" is the same fact said on purpose.

            One column where the course row has two: a drill carries no
            difficulty band. There is no projection for one and no sort that
            needs it — see the note in `drills.py`. */}
        <span
          className={cn(
            "w-24 shrink-0 text-right text-xs tabular-nums",
            done ? "text-foreground" : "text-muted-foreground",
          )}
        >
          {pct !== null ? (
            <>
              {pct}%
              <span className="text-muted-foreground">
                {" · "}
                {d.attempts} {d.attempts === 1 ? "try" : "tries"}
              </span>
            </>
          ) : (
            "Not done"
          )}
        </span>
      </Link>
    </li>
  );
}

export function DrillRows({
  items,
  nextId,
  revealRef,
}: {
  items: PracticeDrill[];
  nextId: string | null;
  revealRef?: (el: HTMLLIElement | null) => void;
}) {
  return (
    <ol className="mt-2">
      {items.map((d, i) => (
        <DrillRow
          key={d.group_id}
          drill={d}
          index={i + 1}
          status={statusOf(d, nextId)}
          first={i === 0}
          last={i === items.length - 1}
          afterDone={i > 0 && items[i - 1].attempts > 0}
          revealRef={revealRef}
        />
      ))}
    </ol>
  );
}

/** The list, waiting. The rail is drawn for real — its width and rhythm are
 *  what the loaded rows sit against, and a placeholder without it would shift
 *  every row sideways when the data lands. */
export function DrillRowsSkeleton() {
  return (
    <ol className="mt-2">
      {[0, 1, 2, 3, 4].map((i) => (
        <li key={i} className="flex items-stretch">
          <div className="relative flex w-8 shrink-0 flex-col items-center self-stretch">
            <span className={cn("w-px flex-1", i === 0 ? "" : "bg-border")} />
            <span className="my-1 h-5 min-w-6 shrink-0 rounded-full border border-border" />
            <span className={cn("w-px flex-1", i === 4 ? "" : "bg-border")} />
          </div>
          <div className="my-0.5 min-w-0 flex-1 px-3 py-2.5">
            <p className="text-sm">
              <Skeleton className="inline-block h-[0.8em] w-56 max-w-full" />
            </p>
            <p className="mt-0.5 text-xs">
              <Skeleton className="inline-block h-[0.8em] w-64 max-w-full" />
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}

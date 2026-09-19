import { Link } from "react-router-dom";
import { Check } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { fmtClock } from "@/lib/time";
import {
  DIFFICULTY_CLASS,
  DIFFICULTY_LABEL,
  describeTask,
  difficultyTitle,
  partLabel,
} from "@/features/listening/practice";
import type { PracticeMaterial } from "@/features/paper/types";

/**
 * A collection's materials, as a route through them.
 *
 * The catalogue's row answers "what is this and have I done it". Here the
 * question is different — where am I in a sequence somebody laid out — so the
 * row is different: a rail of connected stops down the left, done ones faded,
 * the next one lit.
 *
 * **The order is a recommendation, not a lock.** Anything can be sat at any
 * time, and the numbers are the author's suggestion about what to do when. The
 * next lesson is therefore the first UNSAT one rather than "done + 1": a
 * reader who skipped lesson four and sat lesson five is on lesson four, and a
 * page that counted instead of looking would send them somewhere they had
 * already been.
 */

type Status = "done" | "next" | "todo";

function statusOf(m: PracticeMaterial, nextId: string | null): Status {
  if (m.attempts > 0) return "done";
  return m.id === nextId ? "next" : "todo";
}

/**
 * One stop on the rail: the marker, and the line joining it to its
 * neighbours.
 *
 * The line is two halves rather than one, so the first and last stops can
 * drop the half that would run off the end of the list — a rail that
 * continues past the last lesson suggests a lesson that isn't there. The
 * upper half is coloured by the PREVIOUS stop, because the segment between
 * two markers belongs to the ground already covered.
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
    <div className="relative flex w-6 shrink-0 flex-col items-center self-stretch">
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
          "my-1 flex size-5 shrink-0 items-center justify-center rounded-full text-xs tabular-nums",
          status === "done" && "bg-correct/20 text-correct",
          // The one accent on this page, on the one thing to do next.
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

export function LessonRow({
  basePath,
  material: m,
  index,
  status,
  first,
  last,
  afterDone,
  revealRef,
}: {
  /** Where this paper's materials live. See `LessonList`. */
  basePath: string;
  material: PracticeMaterial;
  index: number;
  status: Status;
  first: boolean;
  last: boolean;
  afterDone: boolean;
  revealRef?: (el: HTMLLIElement | null) => void;
}) {
  const task = describeTask(m);
  const part = partLabel(m);
  const done = status === "done";
  // First-try, not best: the number beside a lesson is a measurement of the
  // reader, and a record is what the catalogue row is for.
  const pct =
    m.first_score !== null && m.question_count > 0
      ? Math.round((m.first_score / m.question_count) * 100)
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
        to={`${basePath}/${m.id}`}
        className={cn(
          "my-0.5 flex min-w-0 flex-1 items-center gap-4 rounded-lg px-3 py-2.5 transition-colors duration-fast",
          "hover:bg-surface-hover focus-visible:bg-surface-hover focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
          // The next one is lit; the done ones fade. Attention goes to the
          // thing left to do rather than to the wall of ticks above it.
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
            <span className="truncate">{m.title}</span>
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
              part,
              task?.label,
              `${m.question_count} question${m.question_count === 1 ? "" : "s"}`,
              m.duration_ms != null ? fmtClock(m.duration_ms) : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>

        {/* Never blank. An empty column beside a row reads as data that
            failed to load; "Not sat" is the same fact said on purpose. */}
        <span
          className={cn(
            "w-20 shrink-0 text-right text-xs tabular-nums",
            done ? "text-foreground" : "text-muted-foreground",
          )}
        >
          {pct !== null ? (
            <>
              {pct}%
              <span className="text-muted-foreground">
                {" · "}
                {m.attempts} {m.attempts === 1 ? "try" : "tries"}
              </span>
            </>
          ) : (
            "Not sat"
          )}
        </span>

        {/* The full word here, not the three-letter form the catalogue uses.
            There the chip is a column down a long list and its width is what
            keeps the edge straight; here it is one item on a row of four and
            there is room to say what it means. */}
        <span
          title={difficultyTitle(m)}
          className={cn(
            "w-16 shrink-0 rounded-full border py-0.5 text-center text-xs font-medium",
            DIFFICULTY_CLASS[m.difficulty.band],
            done && "opacity-60",
          )}
        >
          {DIFFICULTY_LABEL[m.difficulty.band]}
        </span>
      </Link>
    </li>
  );
}

export function LessonList({
  basePath,
  items,
  nextId,
  revealRef,
}: {
  /** Where this paper's materials live — `/listening`, `/reading`. A course
   *  is a sequence through ONE paper, and a lesson row that linked to the
   *  other one would open the wrong take screen. */
  basePath: string;
  items: PracticeMaterial[];
  nextId: string | null;
  revealRef?: (el: HTMLLIElement | null) => void;
}) {
  return (
    <ol className="mt-2">
      {items.map((m, i) => (
        <LessonRow
          key={m.id}
          basePath={basePath}
          material={m}
          index={i + 1}
          status={statusOf(m, nextId)}
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
export function LessonListSkeleton() {
  return (
    <ol className="mt-2">
      {[0, 1, 2, 3].map((i) => (
        <li key={i} className="flex items-stretch">
          <div className="relative flex w-6 shrink-0 flex-col items-center self-stretch">
            <span className={cn("w-px flex-1", i === 0 ? "" : "bg-border")} />
            <span className="my-1 size-5 shrink-0 rounded-full border border-border" />
            <span className={cn("w-px flex-1", i === 3 ? "" : "bg-border")} />
          </div>
          <div className="my-0.5 min-w-0 flex-1 px-3 py-2.5">
            <p className="text-sm">
              <Skeleton className="inline-block h-[0.8em] w-56 max-w-full" />
            </p>
            <p className="mt-0.5 text-xs">
              <Skeleton className="inline-block h-[0.8em] w-72 max-w-full" />
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}

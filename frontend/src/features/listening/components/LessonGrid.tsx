import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import { fmtClock } from "@/lib/time";
import { describeTask, partLabel } from "@/features/listening/practice";
import type { PracticeMaterial } from "@/features/paper/types";

/**
 * A collection's materials as a map of results.
 *
 * A course can hold two hundred papers, and two hundred rows is not something
 * anybody reads — it is something they scroll past. The grid does two things a
 * list cannot: it puts the whole course on one screen, and it colours each
 * cell by how the reader did, so a run of red is visible as a shape before a
 * single title has been read. That is a more useful answer than done/not done,
 * because "where did I struggle" is the question somebody opens a finished
 * course to ask.
 *
 * Coloured by the FIRST attempt, like every other figure here that measures
 * somebody. A grid drawn from best-of would go green as they re-sat things and
 * stop showing where the trouble was.
 */

/** The bands, and what each one means. Deliberately three rather than five:
 *  the grid is read as a shape at a glance, and a shape needs few enough
 *  colours to be one. */
const BANDS = [
  { at: 80, cell: "bg-correct/20 text-correct", label: "80%+" },
  { at: 60, cell: "bg-attention/20 text-attention", label: "60–79%" },
  { at: 0, cell: "bg-incorrect/20 text-incorrect", label: "Under 60%" },
] as const;

function bandFor(pct: number) {
  return BANDS.find((band) => pct >= band.at) ?? BANDS[BANDS.length - 1];
}

function firstTryPct(m: PracticeMaterial): number | null {
  if (m.first_score === null || m.question_count === 0) return null;
  return Math.round((m.first_score / m.question_count) * 100);
}

function describe(m: PracticeMaterial): string {
  const pct = firstTryPct(m);
  return [
    partLabel(m),
    describeTask(m)?.label,
    m.duration_ms != null ? fmtClock(m.duration_ms) : null,
    pct !== null ? `${pct}%` : null,
    m.attempts > 0
      ? `${m.attempts} ${m.attempts === 1 ? "try" : "tries"}`
      : "not sat",
  ]
    .filter(Boolean)
    .join(" · ");
}

export function LessonGrid({
  basePath,
  items,
  nextId,
}: {
  /** Where this paper's materials live — `/listening`, `/reading`. A course
   *  is a sequence through ONE paper, and a lesson that linked to the other
   *  one would open the wrong take screen. */
  basePath: string;
  items: PracticeMaterial[];
  nextId: string | null;
}) {
  const navigate = useNavigate();
  // What the pointer or the keyboard is on. One index rather than a hover
  // flag per cell: only one can be current, and a hundred booleans is a
  // hundred renders.
  const [at, setAt] = useState<number | null>(null);
  const cells = useRef<Array<HTMLButtonElement | null>>([]);

  // Arrow keys move by one and by a row, which means knowing how many fit —
  // and that is a layout fact, so it is measured rather than assumed. Without
  // it, Down would move by a guess and land somewhere the eye didn't follow.
  const grid = useRef<HTMLDivElement | null>(null);
  const [perRow, setPerRow] = useState(1);
  useEffect(() => {
    const el = grid.current;
    if (!el) return;
    const measure = () => {
      const columns = getComputedStyle(el).gridTemplateColumns;
      setPerRow(Math.max(1, columns.split(" ").filter(Boolean).length));
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const move = (from: number, by: number) => {
    const to = Math.max(0, Math.min(from + by, items.length - 1));
    cells.current[to]?.focus();
    setAt(to);
  };

  const current = at !== null ? items[at] : null;

  return (
    <div>
      <div
        ref={grid}
        role="group"
        aria-label="Materials in this collection"
        // An arbitrary value, and one of the few that earns it: `auto-fill`
        // with a `minmax` floor is how a grid fits as many cells as the
        // column allows without anybody deciding how many that is, and there
        // is no utility on the scale that says it. The floor is 36px — small
        // enough that two hundred cells fit on a screen, large enough that a
        // three-digit number still reads.
        className="mt-2 grid grid-cols-[repeat(auto-fill,minmax(2.25rem,1fr))] gap-2"
      >
        {items.map((m, i) => {
          const pct = firstTryPct(m);
          const isNext = m.id === nextId;
          return (
            <button
              key={m.id}
              type="button"
              ref={(el) => {
                cells.current[i] = el;
              }}
              // The accessible name is the whole story, because the number in
              // the cell is meaningless read aloud on its own.
              aria-label={`${i + 1}. ${m.title} — ${describe(m)}`}
              onClick={() => navigate(`${basePath}/${m.id}`)}
              onMouseEnter={() => setAt(i)}
              onMouseLeave={() => setAt((was) => (was === i ? null : was))}
              onFocus={() => setAt(i)}
              onBlur={() => setAt((was) => (was === i ? null : was))}
              onKeyDown={(e) => {
                const by =
                  e.key === "ArrowRight"
                    ? 1
                    : e.key === "ArrowLeft"
                      ? -1
                      : e.key === "ArrowDown"
                        ? perRow
                        : e.key === "ArrowUp"
                          ? -perRow
                          : 0;
                if (by === 0) return;
                e.preventDefault();
                move(i, by);
              }}
              className={cn(
                "flex aspect-square items-center justify-center rounded-md text-xs tabular-nums transition-[scale] duration-fast",
                "hover:scale-110 focus-visible:scale-110 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                isNext
                  ? "bg-primary font-medium text-primary-foreground"
                  : pct !== null
                    ? bandFor(pct).cell
                    : "border border-border text-muted-foreground",
              )}
            >
              {i + 1}
            </button>
          );
        })}
      </div>

      {/* The legend sits under the grid and is read once. It is not sticky:
          three colours and their meanings are learned in a glance and then
          stop being needed, and a key that follows you down two hundred
          cells is a key that has outstayed its use. */}
      <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-muted-foreground">
        {BANDS.map((band) => (
          <span key={band.label} className="flex items-center gap-1.5">
            <span
              aria-hidden
              className={cn("size-3 rounded-sm", band.cell)}
            />
            {band.label}
          </span>
        ))}
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="size-3 rounded-sm border border-border" />
          Not sat
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="size-3 rounded-sm bg-primary" />
          Next
        </span>
      </div>

      {/*
        One readout rather than a floating tooltip on each cell. A tooltip
        chasing the pointer over two hundred targets is two hundred chances to
        flicker, and it covers the very cells somebody is comparing. One line
        is always in the same place, works identically for the keyboard, and
        obscures nothing.

        **Stuck to the bottom of the window**, which is what makes it work at
        two hundred cells rather than at twenty. Sat at the end of the grid it
        was fine on a short course and useless on a long one: the reader
        hovers a cell near the top and the answer is printed a screen and a
        half below them. Sticky, it rides along and is never further away than
        the bottom edge — and it settles into its natural place at the end of
        the grid rather than floating over the page forever.

        It needs its own ground because it now floats over the cells: a
        translucent panel here would print the answer on top of the numbers it
        is describing.

        Its height is held whether or not anything is under the pointer, so
        nothing shifts as the pointer crosses in and out of the grid.
      */}
      <div className="sticky bottom-4 z-raised mt-3 min-h-9 rounded-lg border border-border-subtle bg-card px-3 py-2 text-sm shadow-sm">
        {current ? (
          <p className="truncate">
            <span className="text-muted-foreground tabular-nums">
              {(at ?? 0) + 1} ·{" "}
            </span>
            <span className="text-foreground">{current.title}</span>
            <span className="text-xs text-muted-foreground">
              {" — "}
              {describe(current)}
            </span>
          </p>
        ) : (
          <p className="truncate text-xs text-muted-foreground">
            Point at a square for what it is, or use the arrow keys.
          </p>
        )}
      </div>
    </div>
  );
}

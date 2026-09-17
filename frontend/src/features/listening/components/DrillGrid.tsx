import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import { fmtClock } from "@/lib/time";
import type { PracticeDrill } from "@/features/listening/types";

/**
 * One kind of question as a map of results.
 *
 * `LessonGrid`'s shape, asked of a set of exercises instead of a course, and
 * it earns it harder here: a course holds ten or twenty papers, and multiple
 * choice holds a hundred and eighty-eight drills. A hundred and eighty-eight
 * cards is not something anybody reads, it is something they scroll past.
 * Squares put the whole of a task type on one screen and colour each by how
 * the reader did, so a run of red is a shape before a single title has been
 * read — which is the question somebody opens a task type to ask: not "which
 * of these have I done" but "where am I weak at maps".
 *
 * Coloured by the FIRST attempt, like every other figure that measures
 * somebody. Drawn from best-of it would go green as they re-sat things and
 * stop showing where the trouble was.
 *
 * The bands, the cell size and the sticky readout are deliberately the same
 * as the course grid's rather than chosen again: a reader who has learned to
 * read one of these has learned to read both, and two grids in one app that
 * mean their colours differently is worse than either.
 */

const BANDS = [
  { at: 80, cell: "bg-correct/20 text-correct", label: "80%+" },
  { at: 60, cell: "bg-attention/20 text-attention", label: "60–79%" },
  { at: 0, cell: "bg-incorrect/20 text-incorrect", label: "Under 60%" },
] as const;

function bandFor(pct: number) {
  return BANDS.find((band) => pct >= band.at) ?? BANDS[BANDS.length - 1];
}

function firstTryPct(d: PracticeDrill): number | null {
  if (d.first_score === null || d.question_count === 0) return null;
  return Math.round((d.first_score / d.question_count) * 100);
}

function describe(d: PracticeDrill): string {
  const pct = firstTryPct(d);
  return [
    `Questions ${d.first_number}–${d.last_number}`,
    `Part ${d.part_number}`,
    d.clip_ms != null ? fmtClock(d.clip_ms) : null,
    pct !== null ? `${pct}%` : null,
    d.attempts > 0
      ? `${d.attempts} ${d.attempts === 1 ? "try" : "tries"}`
      : "not done",
  ]
    .filter(Boolean)
    .join(" · ");
}

export function DrillGrid({
  items,
  nextId,
}: {
  items: PracticeDrill[];
  /** The first one they have not done, in the order shown. Not a sequence
   *  anybody laid out — these are not lessons — but "the next one to do" is
   *  still the question the grid is most often opened with. */
  nextId: string | null;
}) {
  const navigate = useNavigate();
  const [at, setAt] = useState<number | null>(null);
  const cells = useRef<Array<HTMLButtonElement | null>>([]);

  // Measured, not assumed: Down has to move by a real row or it lands
  // somewhere the eye did not follow.
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
        aria-label="Exercises of this kind"
        className="mt-2 grid grid-cols-[repeat(auto-fill,minmax(2.25rem,1fr))] gap-2"
      >
        {items.map((d, i) => {
          const pct = firstTryPct(d);
          const isNext = d.group_id === nextId;
          return (
            <button
              key={d.group_id}
              type="button"
              ref={(el) => {
                cells.current[i] = el;
              }}
              // The number in the cell says nothing read aloud on its own, so
              // the accessible name carries the whole row.
              aria-label={`${i + 1}. ${d.material_title} — ${describe(d)}`}
              onClick={() => navigate(`/listening/drills/${d.group_id}`)}
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

      <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-muted-foreground">
        {BANDS.map((band) => (
          <span key={band.label} className="flex items-center gap-1.5">
            <span aria-hidden className={cn("size-3 rounded-sm", band.cell)} />
            {band.label}
          </span>
        ))}
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="size-3 rounded-sm border border-border" />
          Not done
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="size-3 rounded-sm bg-primary" />
          Next
        </span>
      </div>

      {/* One readout, stuck to the bottom of the window. The reasoning is the
          course grid's and it applies more strongly at this many cells: a
          tooltip chasing the pointer over a hundred and eighty targets is a
          hundred and eighty chances to flicker, and it covers the very cells
          being compared. Its height is held so nothing shifts as the pointer
          crosses in and out. */}
      <div className="sticky bottom-4 z-raised mt-3 min-h-9 rounded-lg border border-border-subtle bg-card px-3 py-2 text-sm shadow-sm">
        {current ? (
          <p className="truncate">
            <span className="tabular-nums text-muted-foreground">
              {(at ?? 0) + 1} ·{" "}
            </span>
            <span className="text-foreground">{current.material_title}</span>
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

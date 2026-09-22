import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { timeAgo } from "@/lib/time";
import {
  MISTAKE_LABEL,
  MISTAKE_MEANING,
  formatSpent,
  ordinal,
} from "@/features/listening/practice";
import type { Scope } from "@/features/listening/practice";
import type { LearnerStats, Mistakes, Trend } from "@/features/paper/types";

/**
 * What the reader should do next, and why they are losing the marks they lose.
 *
 * The panel this replaced reported four percentages and a bar chart, and the
 * trouble with all of it was the same: a percentage describes, it doesn't
 * explain. "Part 3: 62%" tells a candidate something they already know — Part
 * 3 is the hard one — and nothing about what to do on Thursday evening. Half
 * its rows were dashes, and the one conclusion it did draw ("your weakest
 * area") was ranking 62% above 66% over a few dozen answers, which is noise
 * wearing a verdict's clothes.
 *
 * What is here instead, in order of how much use it is:
 *
 *   1. the thing they were doing, so carrying on costs one click;
 *   2. what KIND of mistake they make most, which is the only part of a wrong
 *      answer anybody can act on;
 *   3. whether the line is going up;
 *   4. the totals, with first-try before best-of, because sitting a paper
 *      until you score well on it measures memory of that paper.
 */

/** The shell. One definition so the cards can't drift apart. */
function Card({
  children,
  className,
  label,
}: {
  children: React.ReactNode;
  className?: string;
  label?: string;
}) {
  return (
    <section
      aria-label={label}
      className={cn(
        "rounded-2xl border border-border-subtle bg-card/60 px-4 py-2.5",
        className,
      )}
    >
      {children}
    </section>
  );
}

/** A card's title. Sentence case and quiet — the uppercase micro-labels this
 *  replaces (`WEAKEST AREA`, `BY PART`) made the column read as a form. */
function Label({ children }: { children: React.ReactNode }) {
  return <p className="text-xs text-muted-foreground">{children}</p>;
}

interface PracticeStatsProps {
  stats: LearnerStats;
  /** Where this paper's pages live — `/reading`, `/listening`.
   *
   *  Every link out of this column used to be written `/listening/...`,
   *  which was true for as long as there was one paper. On the reading page
   *  the column then showed reading's own figures under links that took the
   *  reader to listening: "See your answers" opened the listening review
   *  with a reading attempt id in it. The numbers were never wrong; every
   *  way out of them was. */
  basePath: string;
  /** What one part of this paper is called, capitalised: `Passage`, `Part`.
   *  A reading page telling somebody to start with Part 1 is naming a thing
   *  a reading paper does not have. */
  partWord: string;
  onBrowsePart: (scope: Scope) => void;
}

export function PracticeStats({
  stats,
  basePath,
  partWord,
  onBrowsePart,
}: PracticeStatsProps) {
  // Nothing sat yet. Every card here is a measurement, so they all go rather
  // than standing empty: "0%" and "0 done" are not encouraging, they are not
  // informative, and they are not even true — nothing has been measured.
  if (stats.materials_done === 0) {
    return (
      <GettingStarted partWord={partWord} onBrowsePart={onBrowsePart} />
    );
  }

  return (
    <div className="space-y-2">
      {stats.resume && (
        <ResumeCard resume={stats.resume} basePath={basePath} />
      )}

      <MistakesCard mistakes={stats.mistakes} basePath={basePath} />

      {/* Absent until there are ten attempts to draw. A line through four
          points is joining up noise and calling it a trend. */}
      {stats.trend && <TrendCard trend={stats.trend} />}

      <Totals stats={stats} basePath={basePath} />
    </div>
  );
}

// --- 1. Your last result ----------------------------------------------------

/**
 * The last thing they sat, framed as a RESULT rather than as a way back in.
 *
 * It used to say "Pick up where you left off", which put a second invitation
 * to carry on next to the one at the top of the page — two "continue" buttons
 * on one screen, and no way to tell which is the right one. The block above
 * the list is what to do next; this column is how it is going.
 *
 * The reframing costs nothing because the card was already a result: the most
 * valuable thing about the last material somebody sat is not sitting it again,
 * it is seeing what they got wrong, and the main action here has always been
 * "See your answers". Only the label was arguing with it.
 *
 * With that settled the column reads in one direction — this result, then
 * what kind of mistakes, then the trend, then the totals — and the page has a
 * side for what to do and a side for how it is going.
 */
function ResumeCard({
  resume,
  basePath,
}: {
  resume: NonNullable<LearnerStats["resume"]>;
  basePath: string;
}) {
  return (
    <Card label="Your last result">
      <Label>Your last result</Label>
      <p className="mt-1 text-sm leading-snug text-foreground">{resume.title}</p>
      <p className="mt-1 text-xs text-muted-foreground">
        {timeAgo(resume.submitted_at)}
        {resume.score_pct !== null && (
          <>
            {" · "}
            <span className="tabular-nums">{resume.score_pct}%</span> on your{" "}
            {ordinal(resume.attempt_number)} try
          </>
        )}
      </p>
      <div className="mt-2.5 flex items-center gap-4 text-sm">
        <Link
          to={`${basePath}/attempts/${resume.attempt_id}`}
          className="inline-flex items-center gap-1 text-primary transition-colors hover:underline"
        >
          See your answers
          <ArrowRight className="size-3.5" aria-hidden />
        </Link>
        <Link
          to={`${basePath}/${resume.material_id}`}
          className="text-muted-foreground transition-colors hover:text-foreground"
        >
          Sit again
        </Link>
      </div>
    </Card>
  );
}

// --- 2. Where the marks go --------------------------------------------------

/**
 * The most valuable card on the page, and the reason the panel was rewritten.
 *
 * A candidate who loses twelve marks to spelling and eight to not hearing the
 * answer at all has two different problems with two different evenings' work
 * behind them. Neither is visible in "62%".
 */
function MistakesCard({
  mistakes,
  basePath,
}: {
  mistakes: Mistakes | null;
  basePath: string;
}) {
  if (!mistakes || mistakes.groups.length === 0) {
    return (
      <Card label="Where you lose marks">
        <Label>Where you lose marks</Label>
        {/* Said in words rather than drawn as a chart of two bars. A pattern
            over four mistakes isn't one, and a panel that draws it anyway is
            teaching the reader to distrust it. */}
        <p className="mt-1 text-xs leading-snug text-muted-foreground">
          Not enough answers yet to spot a pattern. Sit two or three more
          materials and this will fill in.
        </p>
      </Card>
    );
  }

  const [top, ...rest] = mistakes.groups;
  const most = top.count;

  return (
    <Card label="Where you lose marks">
      <Label>Where you lose marks</Label>
      <p className="mt-0.5 text-base leading-tight text-foreground">
        {MISTAKE_LABEL[top.kind]}
      </p>
      <p className="mt-1 text-xs leading-snug text-muted-foreground">
        <span className="tabular-nums">{top.count}</span> of your{" "}
        <span className="tabular-nums">{mistakes.total}</span> mistakes.{" "}
        {MISTAKE_MEANING[top.kind]}
      </p>

      <ul className="mt-2.5 space-y-1 border-t border-border-subtle pt-2.5">
        {[top, ...rest].map((group) => (
          <li key={group.kind} className="flex items-center gap-3 text-xs">
            <span className="min-w-0 flex-1 truncate text-foreground/80">
              {MISTAKE_LABEL[group.kind]}
            </span>
            {/* Bars against the biggest kind rather than against the total:
                the question this list answers is "which of these is the one",
                and proportions of a whole make every slice look small. */}
            <span className="h-1.5 w-12 shrink-0 overflow-hidden rounded-full bg-surface-sunken">
              <span
                className={cn(
                  "block h-full rounded-full",
                  group.kind === top.kind ? "bg-incorrect" : "bg-foreground/40",
                )}
                style={{ width: `${Math.round((group.count / most) * 100)}%` }}
              />
            </span>
            <span className="w-5 shrink-0 text-right tabular-nums text-muted-foreground">
              {group.count}
            </span>
          </li>
        ))}
      </ul>

      <Link
        to={`${basePath}/statistics`}
        className="mt-3 inline-flex items-center gap-1 text-sm text-primary transition-colors hover:underline"
      >
        Review your mistakes
        <ArrowRight className="size-3.5" aria-hidden />
      </Link>
    </Card>
  );
}

// --- 3. Trend ---------------------------------------------------------------

function TrendCard({ trend }: { trend: Trend }) {
  const up = trend.delta_pct > 0;
  const flat = trend.delta_pct === 0;

  return (
    <Card label="Last 10 attempts">
      <Label>Last 10 attempts</Label>
      <div className="mt-1 flex items-baseline justify-between">
        <span className="text-base tabular-nums text-foreground">
          {trend.average_pct}%
        </span>
        {!flat && (
          <span
            className={cn(
              "text-sm tabular-nums",
              up ? "text-correct" : "text-incorrect",
            )}
          >
            {up ? "↑" : "↓"} {Math.abs(trend.delta_pct)}
          </span>
        )}
      </div>
      <Sparkline points={trend.points} up={up || flat} />
      <p className="mt-1.5 text-xs text-muted-foreground">
        <span className="tabular-nums">{trend.from_pct}%</span> →{" "}
        <span className="tabular-nums">{trend.to_pct}%</span> since{" "}
        {timeAgo(trend.since)}
      </p>
    </Card>
  );
}

/**
 * Ten scores as one line.
 *
 * Scaled to the range it actually contains rather than to 0–100: ten attempts
 * between 58% and 74% drawn on a full scale is a flat line, and flat is the
 * one thing this card exists to disprove or confirm. A floor of 20 points
 * keeps a genuinely steady run from being drawn as dramatic.
 */
function Sparkline({ points, up }: { points: number[]; up: boolean }) {
  if (points.length < 2) return null;

  const width = 244;
  const height = 30;
  const pad = 3;
  const low = Math.min(...points);
  const high = Math.max(...points);
  const span = Math.max(high - low, 20);
  const mid = (high + low) / 2;
  const top = mid + span / 2;

  const step = width / (points.length - 1);
  const y = (value: number) =>
    pad + ((top - value) / span) * (height - pad * 2);
  const coords = points.map((value, i) => [i * step, y(value)] as const);
  const line = coords.map(([x, py]) => `${x.toFixed(1)},${py.toFixed(1)}`).join(" ");
  const [lastX, lastY] = coords[coords.length - 1];

  return (
    // Scaled uniformly, not stretched to the card: `preserveAspectRatio="none"`
    // made the line fill the width neatly and drew the end marker as a
    // vertical smear, because a circle in a squashed coordinate system is an
    // ellipse. The viewBox is close enough to the card's width that letting it
    // scale as a whole costs nothing.
    <svg
      className="mt-2 w-full"
      viewBox={`0 0 ${width} ${height}`}
      // Decorative: every number in it is written out above and below.
      aria-hidden
    >
      <polyline
        points={line}
        fill="none"
        className={up ? "stroke-correct" : "stroke-incorrect"}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
      <circle
        cx={lastX}
        cy={lastY}
        r={3}
        className={up ? "fill-correct" : "fill-incorrect"}
      />
    </svg>
  );
}

// --- 4. Totals --------------------------------------------------------------

function Totals({
  stats,
  basePath,
}: {
  stats: LearnerStats;
  basePath: string;
}) {
  return (
    <Card label="Totals">
      <dl className="space-y-1 text-sm">
        {/* First-try leads, and the label says which it is. "Average 72%" was
            ambiguous in the way that matters: three sittings of the same paper
            ending at 95% is memory of that paper, not listening. */}
        <Total
          label="First-try average"
          value={
            stats.first_try_avg_pct === null
              ? null
              : `${stats.first_try_avg_pct}%`
          }
        />
        {/* Absent until something has been sat twice — with no retries it is
            the number above under a second name. */}
        {stats.best_avg_pct !== null && (
          <Total label="Best average" value={`${stats.best_avg_pct}%`} />
        )}
        <Total label="Materials done" value={String(stats.materials_done)} />
        <Total label="Time spent" value={formatSpent(stats.time_spent_ms)} />
      </dl>
      {/* Inside the totals rather than floating under them: as its own block
          it cost a card's worth of gap to say four words, and the column is
          already taller than a short laptop screen. */}
      <Link
        to={`${basePath}/statistics`}
        className="mt-3 block border-t border-border-subtle pt-2.5 text-center text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        Full statistics →
      </Link>
    </Card>
  );
}

function Total({ label, value }: { label: string; value: string | null }) {
  if (value === null) return null;
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium tabular-nums text-foreground">{value}</dd>
    </div>
  );
}

// --- The empty state --------------------------------------------------------

function GettingStarted({
  partWord,
  onBrowsePart,
}: {
  partWord: string;
  onBrowsePart: (scope: Scope) => void;
}) {
  return (
    <div className="space-y-2">
      <Card label="Getting started">
        <p className="text-sm text-foreground">Start with {partWord} 1</p>
        <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
          It&apos;s the most approachable — a short conversation with a form to
          fill in. Sit two or three and you&apos;ll start seeing where your
          marks go.
        </p>
        <Button
          type="button"
          variant="link"
          size="sm"
          onClick={() => onBrowsePart(1)}
          className="mt-2.5 h-auto px-0 text-sm"
        >
          Browse {partWord} 1
          <ArrowRight className="size-3.5" aria-hidden />
        </Button>
      </Card>
      {/* Outside a card and quieter than one: it is a note about what will
          appear here, not a thing to read now. */}
      <p className="px-4 text-xs leading-relaxed text-muted-foreground/70">
        Your progress, common mistakes and trend appear here once you&apos;ve
        sat a few materials.
      </p>
    </div>
  );
}

// --- Waiting ----------------------------------------------------------------

export function PracticeStatsSkeleton() {
  return (
    <SkeletonBlock label="Loading your statistics" className="space-y-2">
      {[3, 5, 4].map((rows, i) => (
        <div
          key={i}
          className="rounded-2xl border border-border-subtle bg-card/60 px-4 py-3"
        >
          <p className="text-xs">
            <Skeleton className="inline-block h-[0.8em] w-28" />
          </p>
          <div className="mt-2 space-y-2">
            {Array.from({ length: rows }, (_, row) => (
              <p key={row} className="text-sm">
                <Skeleton
                  className={cn(
                    "inline-block h-[0.8em]",
                    row === 0 ? "w-40" : "w-full",
                  )}
                />
              </p>
            ))}
          </div>
        </div>
      ))}
    </SkeletonBlock>
  );
}

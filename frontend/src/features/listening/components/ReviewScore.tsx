import { cn } from "@/lib/utils";
import { ordinal } from "@/features/listening/practice";
import type { ReviewRow } from "@/features/listening/review";
import type { AttemptResult } from "@/features/listening/types";

/**
 * What the attempt came to, and what that is worth knowing against.
 *
 * `43%` on its own is a number nobody can act on. It is only a fact once
 * there is something beside it: *2nd try, 52% → 70%* is somebody getting
 * better at a paper, and *average here 61%* is somebody finding out where
 * they stand on it. The score is the same figure in all three readings and
 * only the last two are useful, which is why the context is not a detail
 * tucked under a "more" link.
 *
 * **Four columns, label above and value below** — not a sentence. Run
 * together as prose ("3rd try · first try was 0% / 1 min · average here is
 * 45%") the four facts have to be parsed apart before any of them can be
 * read, and three of the four are numbers, which is exactly the content a
 * table exists for.
 *
 * The first try is printed as a MOVEMENT (`0% → 70%`) rather than as a
 * figure on its own. Two numbers on one line with an arrow between them is
 * one fact — how much better this went — where the same two numbers in two
 * places are an arithmetic problem set for the reader.
 *
 * **Every column is withheld rather than faked.** There is no first-try
 * figure on a first try — the same number under a second name is a panel
 * padding itself out — and no platform average until enough people have
 * answered the paper for one to mean anything, which is the difficulty
 * projection's own threshold and not a second one invented here.
 */
export function ReviewScore({
  data,
  rows,
  onJump,
}: {
  data: AttemptResult;
  rows: ReviewRow[];
  /** Scroll to one question. */
  onJump?: (questionId: string) => void;
}) {
  const pct =
    data.total_questions > 0
      ? Math.round((data.score / data.total_questions) * 100)
      : 0;
  const first = data.first_try_pct;

  return (
    <section
      aria-label="Your result"
      className="rounded-xl border border-border bg-card px-5 py-4"
    >
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
        <p className="flex items-baseline gap-3">
          <span className="font-mono text-4xl leading-none font-bold tabular-nums text-foreground">
            {data.score}
            <span className="text-lg font-normal text-muted-foreground">
              {" / "}
              {data.total_questions}
            </span>
          </span>
          <span className="font-mono text-lg tabular-nums text-muted-foreground">
            {pct}%
          </span>
        </p>

        <dl className="flex flex-wrap gap-x-6 gap-y-2">
          <Stat label="Attempt">{ordinal(data.attempt_no ?? 1)}</Stat>
          {first != null && (
            <Stat
              label="First try"
              // Green only where it IS growth. A retake that went worse is
              // still worth seeing — it is why somebody would try a third
              // time — but colouring it as an achievement would be the page
              // congratulating them on going backwards.
              tone={pct > first ? "up" : undefined}
            >
              {first}% → {pct}%
            </Stat>
          )}
          {data.time_spent_ms != null && (
            <Stat label="Time">{spent(data.time_spent_ms)}</Stat>
          )}
          {data.material_avg_pct != null && (
            <Stat label="Average here">{data.material_avg_pct}%</Stat>
          )}
        </dl>
      </div>

      <QuestionMap rows={rows} onJump={onJump} />
    </section>
  );
}

function Stat({
  label,
  tone,
  children,
}: {
  label: string;
  tone?: "up";
  children: React.ReactNode;
}) {
  return (
    <div className="text-right">
      <dt className="text-xs leading-tight text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          "text-sm leading-tight tabular-nums",
          tone === "up" ? "text-correct" : "text-foreground/80",
        )}
      >
        {children}
      </dd>
    </div>
  );
}

/**
 * How the paper went, question by question.
 *
 * **Two shapes, and the threshold is what makes either of them work.** Up to
 * a dozen questions, a row of bars is the whole paper at a glance: whether
 * the mistakes are scattered or bunched, and how far in they started. Past
 * that the bars are three pixels wide, which is a texture rather than a
 * picture — nobody can tell the ninth from the tenth, and clicking one is
 * aiming at a hairline.
 *
 * So a long paper gets a MAP: numbered squares in a grid, right in green and
 * wrong in red. Same object the take screen's navigator is and the same one a
 * collection's grid is, so it needs no learning — and a number in a box is
 * something a reader can actually aim at, which matters because the map is
 * also the fastest route to a mistake. Scrolling past thirty right answers to
 * find the one that isn't is what it replaces.
 */
const MAP_AT = 12;

function QuestionMap({
  rows,
  onJump,
}: {
  rows: ReviewRow[];
  onJump?: (questionId: string) => void;
}) {
  if (!rows.length) return null;

  if (rows.length <= MAP_AT) {
    return (
      <div className="mt-4 flex gap-1">
        {rows.map((row) => (
          <Cell key={row.result.question_id} row={row} onJump={onJump} bar />
        ))}
      </div>
    );
  }

  return (
    <div className="mt-4">
      <p className="mb-2 text-xs text-muted-foreground">Question map</p>
      {/* `auto-fill` with a floor rather than a fixed column count: a forty
          question paper is four rows on a laptop and eight on a phone, and
          neither is a decision anything here has to make. */}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(1.75rem,1fr))] gap-1">
        {rows.map((row) => (
          <Cell key={row.result.question_id} row={row} onJump={onJump} />
        ))}
      </div>
    </div>
  );
}

/**
 * One question in either shape.
 *
 * A bar and a numbered square are different enough that they are written out
 * separately rather than threaded through one class string with three
 * conditionals — which is how a `rounded-full` ends up on a square.
 */
function Cell({
  row,
  onJump,
  bar,
}: {
  row: ReviewRow;
  onJump?: (questionId: string) => void;
  /** The short-paper shape: a rule with no number in it. */
  bar?: boolean;
}) {
  const right = row.result.is_correct;
  const label = `Question ${row.number} — ${right ? "right" : "wrong"}`;
  const mark = cn(
    "block h-1.5 w-full rounded-full",
    right ? "bg-correct" : "bg-incorrect",
  );

  if (bar) {
    // The mark is 6px tall but the target is the whole row, so a line of
    // hairlines is still something a mouse can land on.
    return onJump ? (
      <button
        type="button"
        onClick={() => onJump(row.result.question_id)}
        title={label}
        aria-label={label}
        className="flex h-4 min-w-0 flex-1 items-center focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card focus-visible:outline-none"
      >
        <span className={mark} />
      </button>
    ) : (
      <span
        title={label}
        aria-label={label}
        className="flex h-1.5 min-w-0 flex-1 items-center"
      >
        <span className={mark} />
      </span>
    );
  }

  const square = cn(
    "flex aspect-square items-center justify-center rounded-md text-xs tabular-nums",
    right ? "bg-correct/20 text-correct" : "bg-incorrect/20 text-incorrect",
  );
  return onJump ? (
    <button
      type="button"
      onClick={() => onJump(row.result.question_id)}
      title={label}
      aria-label={label}
      className={cn(
        square,
        "transition-colors duration-fast hover:brightness-125 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
      )}
    >
      {row.number}
    </button>
  ) : (
    <span title={label} aria-label={label} className={square}>
      {row.number}
    </span>
  );
}

/** How long it took, to the nearest minute — which is all anybody wants from
 *  it. "12 min" is a fact about the sitting; "11 min 43 s" is a stopwatch
 *  reading, and nothing on this page is being timed. */
function spent(ms: number): string {
  const minutes = Math.round(ms / 60_000);
  return minutes < 1 ? "under a minute" : `${minutes} min`;
}

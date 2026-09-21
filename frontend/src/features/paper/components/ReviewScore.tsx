import { cn } from "@/lib/utils";
import { ordinal } from "@/features/listening/practice";
import type { ReviewRow } from "@/features/paper/review";
import type { AttemptResult } from "@/features/paper/types";

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
 * **Two rows: the score against the map, then the context under them.**
 *
 * It was three — a big number on one line, four labelled columns beside it,
 * and the map below with a heading of its own — and on the reading review,
 * where the whole analysis lives in a 670px pane, that card took a third of
 * the column before the first mistake was reached. The mistakes are what
 * the page is for.
 *
 * So the score and the map share a line, which is also the honest pairing:
 * "4 / 14" and the thirteen squares saying WHICH four are the same fact at
 * two magnifications, and reading one against the other is the first thing
 * anybody does here. The heading over the map went with them — a grid of
 * green and red numbered squares needs no label.
 *
 * **The context is one row, and it is still not a sentence.** Every value
 * keeps its own label in front of it, dimmer than the figure, so the four
 * facts stay four facts to be picked out rather than prose to be parsed —
 * which is what the columns were protecting and is the part worth keeping.
 * What they were spending on it was a third row and eight lines of height.
 *
 * The first try is printed as a MOVEMENT (`0% → 70%`) rather than as a
 * figure on its own. Two numbers on one line with an arrow between them is
 * one fact — how much better this went — where the same two numbers in two
 * places are an arithmetic problem set for the reader.
 *
 * **Every figure is withheld rather than faked.** There is no look-up count
 * on a paper nobody looked anything up in, no first-try figure on a first
 * try — the same number under a second name is a panel padding itself out —
 * and no platform average until enough people have answered the paper for
 * one to mean anything, which is the difficulty projection's own threshold
 * and not a second one invented here.
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
      className="rounded-xl border border-border bg-card px-4 py-3"
    >
      <div className="flex items-center gap-5">
        <p className="flex shrink-0 items-baseline gap-2">
          <span className="font-mono text-3xl leading-none font-bold tabular-nums text-foreground">
            {data.score}
            <span className="text-base font-normal text-muted-foreground">
              {" / "}
              {data.total_questions}
            </span>
          </span>
          <span className="font-mono text-base tabular-nums text-muted-foreground">
            {pct}%
          </span>
        </p>
        {/* The map takes what is left, which is what makes the two read as
            one statement rather than as a figure with a diagram under it. */}
        <div className="min-w-0 flex-1">
          <QuestionMap rows={rows} onJump={onJump} />
        </div>
      </div>

      <div className="mt-2.5 flex flex-wrap items-baseline gap-x-4 gap-y-1">
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
        {/* How many of the three this sitting spent. A fact about how the
              paper was worked rather than about how it was marked, and the
              only one of these columns that is: somebody who read nine
              hundred words without reaching for the dictionary once read
              them differently from somebody who spent all three by
              paragraph C.

              Absent at zero, and absent for every listening attempt, which
              is the same absence — there is no dictionary in a recording. */}
        {(data.looked_up?.length ?? 0) > 0 && (
          <Stat label="Looked up">{data.looked_up!.length}</Stat>
        )}
        {data.material_avg_pct != null && (
          <Stat label="Average here">{data.material_avg_pct}%</Stat>
        )}
      </div>
    </section>
  );
}

/** One fact, its label in front of it rather than above it.
 *
 *  Still a label and a value, and that is the part that matters: four
 *  figures run together as prose have to be parsed apart before any of them
 *  can be read. What the row costs instead of the column is nothing —
 *  "Attempt 1st" is as quick to find as "Attempt" over "1st", and it does
 *  not spend a second line of the card to say so. */
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
    <span className="flex items-baseline gap-1.5 text-xs whitespace-nowrap">
      <span className="text-muted-foreground">{label}</span>
      <span
        className={cn(
          "tabular-nums",
          tone === "up" ? "text-correct" : "text-foreground/80",
        )}
      >
        {children}
      </span>
    </span>
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
      <div className="flex gap-1">
        {rows.map((row) => (
          <Cell key={row.result.question_id} row={row} onJump={onJump} bar />
        ))}
      </div>
    );
  }

  return (
    // `auto-fill` with a floor rather than a fixed column count: a forty
    // question paper is two rows in this space and five on a phone, and
    // neither is a decision anything here has to make.
    //
    // No heading over it any more. "Question map" above a grid of green and
    // red numbered squares is a label on something that has already said
    // what it is, and it cost the card a row it did not have.
    <div>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(1.6rem,1fr))] gap-1">
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

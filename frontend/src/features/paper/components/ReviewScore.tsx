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
 * ## Two rows, and both of them full width
 *
 * The score and the context share the first line, on one baseline — the
 * figure on the left where reading starts, the facts that qualify it on the
 * right. The map has the second line to itself.
 *
 * It was one line for the score and the map together, with the context
 * under them. That put the map in whatever width the score left over, which
 * is a different width on every paper and never the one the squares wanted:
 * fourteen of them in half a pane came out as a stripe with a gap after it.
 *
 * **The context is a row, and it is still not a sentence.** Every value
 * keeps its own label in front of it, dimmer than the figure, so the four
 * facts stay four facts to be picked out rather than prose to be parsed.
 * That is what a column of labels was protecting; what it was spending on
 * it was a third row.
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
      className="rounded-xl border border-border bg-card px-5 py-4"
    >
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <p className="flex items-baseline gap-2.5 font-mono tabular-nums">
          <span className="text-[2rem] leading-none text-foreground">
            {data.score}
          </span>
          <span className="text-[1.05rem] text-muted-foreground">
            / {data.total_questions}
          </span>
          <span className="text-[1.05rem] text-muted-foreground">{pct}%</span>
        </p>

        <dl className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
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
              only one of these that is: somebody who read nine hundred words
              without reaching for the dictionary once read them differently
              from somebody who spent all three by paragraph C.

              Absent at zero, and absent for every listening attempt, which
              is the same absence — there is no dictionary in a recording. */}
          {(data.looked_up?.length ?? 0) > 0 && (
            <Stat label="Looked up">{data.looked_up!.length}</Stat>
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
    <span className="flex items-baseline gap-1.5 font-sans text-[0.8rem] whitespace-nowrap">
      <dt className="text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          "tabular-nums",
          tone === "up" ? "text-correct" : "text-foreground/80",
        )}
      >
        {children}
      </dd>
    </span>
  );
}

/**
 * How the paper went, question by question — the whole width of the card,
 * every time.
 *
 * `repeat(N, 1fr)` rather than a floor and `auto-fill`: the squares divide
 * the width they are given instead of being packed into it at some fixed
 * size, so thirteen questions and forty questions both reach from edge to
 * edge and neither leaves the ragged gap that a packed row leaves whenever
 * the count and the width disagree. The map is a picture of the paper, and
 * a picture with an empty quarter reads as missing data.
 *
 * Twenty across is the only number in here, and it is a ceiling rather than
 * a width: a row of forty in half a pane is squares too narrow to carry two
 * digits, and twenty is what a printed answer sheet does with the same
 * problem. Past it the map takes as many rows as it needs and then divides
 * the questions EVENLY between them — 26 is two rows of thirteen, not
 * twenty and a ragged six. A last row that stops a third of the way across
 * is the same missing-data look the fixed cell size was leaving, moved down
 * a line.
 *
 * Which also removes the special case: one row is the same arithmetic with
 * the answer 1.
 *
 * The squares lose a little height once there is more than one row, because
 * two rows at the full height is a map taller than it is interesting.
 *
 * **Numbered, always.** There was a second shape for short papers — a row
 * of bars with no numbers, on the argument that up to a dozen the pattern
 * is the whole point. It is not: the map is the fastest route to a mistake,
 * and a bar you cannot name is one you have to count along to. One shape
 * means a passage and a full test look like the same object, which they
 * are.
 */
const PER_ROW = 20;

function QuestionMap({
  rows,
  onJump,
}: {
  rows: ReviewRow[];
  onJump?: (questionId: string) => void;
}) {
  if (!rows.length) return null;
  const lines = Math.ceil(rows.length / PER_ROW);
  const columns = Math.ceil(rows.length / lines);
  return (
    <div
      className="grid gap-1.5"
      style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
    >
      {rows.map((row) => (
        <Cell
          key={row.result.question_id}
          row={row}
          onJump={onJump}
          dense={lines > 1}
        />
      ))}
    </div>
  );
}

function Cell({
  row,
  onJump,
  dense,
}: {
  row: ReviewRow;
  onJump?: (questionId: string) => void;
  dense: boolean;
}) {
  const right = row.result.is_correct;
  const label = `Question ${row.number} — ${right ? "right" : "wrong"}`;
  const square = cn(
    "flex items-center justify-center rounded-md font-mono tabular-nums",
    dense ? "h-[1.6rem] text-[0.66rem]" : "h-8 text-xs",
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
        "transition-[filter] duration-fast hover:brightness-125 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
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

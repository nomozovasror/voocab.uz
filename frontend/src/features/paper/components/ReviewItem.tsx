import { Play } from "lucide-react";
import { cn } from "@/lib/utils";
import { fmtClock } from "@/lib/time";
import { MISTAKE_LABEL } from "@/features/listening/practice";
import {
  markAnswer,
  type QuoteSource,
  type ReviewRow,
} from "@/features/paper/review";
import { matchIndex, matchLabel } from "@/features/paper/matching";
import { questionNumbersShort } from "@/features/paper/numbering";
import { isFixedChoice } from "@/features/paper/types";

/**
 * One question, after it has been marked.
 *
 * ## One skeleton for every task, and only the VALUE changes
 *
 * Number, question, then `You` and `Answer` under each other in a two-column
 * grid. That shape is the same for a multiple choice, a gap-fill, a matching
 * item and a true/false statement — and holding it still is what lets a
 * reader run down forty rows without re-learning the layout at every group
 * boundary.
 *
 * What changes is how the ANSWER reads, because the tasks are answered in
 * four different currencies:
 *
 * - **picked from a box** — the letter as a chip and the option's own WORDS
 *   beside it. "C" is the storage format; *C · outlining some possible
 *   benefits of AI* is the answer. The chip is small and the words are not,
 *   because the words are the part anybody thinks in.
 * - **a "choose TWO"** — one chip per option they picked, green for the one
 *   they got and red for the one they did not, with the ones they MISSED
 *   drawn as outlines on the answer line. Partial credit is invisible in a
 *   score and very visible here, which is the point: one of two right is a
 *   different evening's work from none.
 * - **written in their own words** — no letter, and the kind of wrong
 *   instead: *spelling*, *singular / plural*. On this task the
 *   classification is the most useful thing on the row, because "almost
 *   right" and "never found it" are two different problems wearing the same
 *   red.
 * - **a fixed choice** — the three words in mono, and a LINE underneath
 *   saying why. See below.
 *
 * ## The hint line, which only the fixed choices get
 *
 * Everything else explains itself: you picked C, the answer was B, the
 * passage is beside you. TRUE / FALSE / NOT GIVEN does not, and it is the
 * task candidates lose most — so the row carries one sentence of teaching,
 * chosen by which of the three ways they got it wrong. The page decides
 * which; this draws it.
 *
 * ## Where it was, in the corner
 *
 * The passage is on the other half of the screen, so the row does not quote
 * it: it points. `¶3` in the corner, invisible until the row is under the
 * pointer, and pressing the row goes there. A sentence-long link inside the
 * row ("The answer is in paragraph C") was the same fact taking a whole
 * line, and it pushed the thing the row exists for — what you put, and what
 * was right — further down the page on every one of forty rows.
 *
 * Listening keeps its quote box instead. There the sentence is inside a
 * recording and there is nothing on screen to point at, which is the whole
 * difference between the two papers and the one thing this still draws two
 * ways.
 */
export function ReviewItem({
  row,
  onPlay,
  onGoTo,
  evidence,
  hint,
  onPoint,
  lit,
  anchor,
}: {
  row: ReviewRow;
  /** Seeks to the moment and plays only it. Absent when the recording failed
   *  to load — the text still stands, so the row is drawn either way. */
  onPlay?: (startMs: number | null, endMs: number | null) => void;
  /** Takes the reader to the paragraph the quote came from — the older
   *  route, for a paper the evidence extraction never reached. */
  onGoTo?: (where: QuoteSource) => void;
  /** Where in the passage this row's marks are, said in as little as it
   *  takes — `¶3`, or `¶C` where the book letters its paragraphs — and how
   *  to go there. */
  evidence?: { where: string; onGoTo: () => void };
  /** One line of teaching, under the answers. Only the fixed choices have
   *  one; everything else explains itself. */
  hint?: React.ReactNode;
  /** Pointing at this row, which lights its marks in the passage. Both
   *  directions, because a link that only works one way is one the reader
   *  has to discover the direction of. */
  onPoint?: (on: boolean) => void;
  /** Something in the passage belonging to this row is under the pointer. */
  lit?: boolean;
  anchor: Record<string, string>;
}) {
  const { result } = row;
  const right = result.is_correct;
  const numbers = questionNumbersShort(row.number, row.span);
  const canPlay = onPlay && row.startMs != null;

  return (
    <article
      {...anchor}
      aria-label={`Question ${numbers}`}
      onMouseEnter={onPoint ? () => onPoint(true) : undefined}
      onMouseLeave={onPoint ? () => onPoint(false) : undefined}
      onClick={
        evidence
          ? (e) => {
              // A drag that ends inside the row is somebody copying the
              // question, not asking to be taken somewhere. Without this the
              // passage jumps out from under a selection every time.
              if (window.getSelection()?.toString()) return;
              if ((e.target as HTMLElement).closest("button")) return;
              evidence.onGoTo();
            }
          : undefined
      }
      className={cn(
        "group relative -mx-3 grid scroll-mt-24 grid-cols-[auto_1fr] gap-x-2 rounded-lg border-b border-border/60 px-3 py-3.5 transition-colors duration-fast last:border-b-0",
        evidence && "cursor-pointer",
        onPoint && "hover:bg-surface-hover",
        lit && "bg-surface-hover",
      )}
    >
      {/* As wide as the WIDEST number on this paper, and not a pixel more.
          A fixed column has to be wide enough for "13–14" — a "choose TWO"
          takes five characters — and on a paper whose questions are 1 to 13
          that is thirty pixels of empty gutter down the left of every row,
          taken off the question beside it.
        
          The width comes from the list, in `ch` of THIS span's own type, so
          `2ch` is two digits of the face the digits are actually set in.
          Every row is its own grid and cannot learn the width from its
          neighbours — `--q-number` is how they are told. */}
      <span
        className={cn(
          "w-[var(--q-number,2.5rem)] pt-px text-right text-[0.8rem] whitespace-nowrap tabular-nums",
          right ? "text-correct" : "text-incorrect",
        )}
      >
        {numbers}
      </span>

      <div className="min-w-0">
        {/* What was asked. In the SANS face, because it is the only thing on
            the row that is a sentence — everything under it is an answer,
            and answers are set in mono here the way they are on the paper. */}
        {(row.context?.label || row.context?.line) && (
          <p className="mb-2 pr-8 font-sans text-sm leading-relaxed text-foreground/75">
            {row.context?.label && (
              <span className="text-foreground/90">{row.context.label}</span>
            )}
            {row.context?.label && row.context.line && " — "}
            {row.context?.line}
          </p>
        )}

        <div className="grid grid-cols-[3rem_1fr] items-baseline gap-x-2.5 gap-y-1.5">
          <span className="text-xs text-muted-foreground">You</span>
          <Given row={row} />

          {/* Only where it adds something. Beside a right answer it is the
              same words twice, which reads as the page not knowing they got
              it. */}
          {!right && (
            <>
              <span className="text-xs text-muted-foreground">Answer</span>
              <Answer row={row} />
            </>
          )}

          {hint && (
            <p className="col-start-2 font-sans text-xs leading-relaxed text-muted-foreground">
              {hint}
            </p>
          )}
        </div>
      </div>

      {/* Where it is, not what it says. Hidden until the row is pointed at:
          forty of these at full contrast is a column of markers down the
          edge of a page that is about something else. */}
      {evidence && (
        <button
          type="button"
          onClick={evidence.onGoTo}
          aria-label={`Show where question ${numbers} was answered`}
          className={cn(
            "absolute top-3.5 right-3 rounded text-[0.7rem] tabular-nums transition-colors duration-fast group-hover:text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none focus-visible:text-muted-foreground",
            lit ? "text-muted-foreground" : "text-transparent",
          )}
        >
          {evidence.where} ↖
        </button>
      )}

      {/* Listening's quote: the sentence is inside a recording, so there is
          nothing on screen to point at and the words have to come here. */}
      {!evidence && row.transcript && (
        <div className="col-start-2 mt-2.5 flex items-start gap-3 rounded-lg bg-surface-sunken px-3 py-2.5">
          {onPlay && (
            <button
              type="button"
              disabled={!canPlay}
              onClick={() => onPlay?.(row.startMs, row.endMs)}
              aria-label={`Hear where the answer to question ${row.number} is said`}
              title="Hear this"
              className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-foreground/10 text-primary transition-colors hover:bg-foreground/20 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:pointer-events-none disabled:opacity-40"
            >
              <Play className="size-3" fill="currentColor" aria-hidden />
            </button>
          )}
          <div className="min-w-0 flex-1">
            {row.startMs != null && (
              <p className="text-xs tabular-nums text-muted-foreground">
                {fmtClock(row.startMs)}
                {row.endMs != null && ` — ${fmtClock(row.endMs)}`}
              </p>
            )}
            {row.where && onGoTo && (
              <button
                type="button"
                onClick={() => onGoTo(row.where!)}
                className="text-xs text-primary transition-colors hover:text-primary/80 hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                Paragraph {row.where.label}
              </button>
            )}
            <p className="text-sm leading-relaxed text-foreground/80">
              {markAnswer(row.transcript, result.correct_answers).map(
                (run, i) =>
                  run.hit ? (
                    <mark
                      key={i}
                      className="rounded-sm bg-primary/20 px-1 text-primary"
                    >
                      {run.text}
                    </mark>
                  ) : (
                    <span key={i}>{run.text}</span>
                  ),
              )}
            </p>
          </div>
        </div>
      )}
    </article>
  );
}

/** The letters in a stored answer, in order, lower-cased and without the
 *  blanks a trailing comma leaves. */
function letters(value: string): string[] {
  return value
    .split(",")
    .map((one) => one.trim().toLowerCase())
    .filter(Boolean);
}

/**
 * What they put.
 *
 * Three shapes for the three currencies — see the component's docstring —
 * and one for nothing at all, which is its own kind of answer and reads as
 * one: an empty row would say the page had lost it.
 */
function Given({ row }: { row: ReviewRow }) {
  const { result } = row;
  const right = result.is_correct;
  const given = result.given_answer.trim();

  if (!given)
    return <span className="text-sm text-skipped italic">left blank</span>;

  if (row.byLetter) {
    const picked = letters(given);
    const key = new Set(letters(result.correct_answers.join(",")));
    return (
      <span className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
        {picked.map((letter, i) => (
          <Option
            key={i}
            row={row}
            letter={letter}
            tone={key.has(letter) ? "got" : "missed"}
            // The words only where ONE option was picked. A "choose TWO"
            // answered with two full options runs two sentences across the
            // row and buries which of them was right, which is the one
            // thing that line has to say.
            words={picked.length === 1}
          />
        ))}
        {picked.length > 1 && (
          <span className="text-xs text-muted-foreground">
            {[...key].filter((one) => picked.includes(one)).length} of{" "}
            {key.size} right
          </span>
        )}
      </span>
    );
  }

  return (
    <span className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
      <span
        className={cn(
          "font-mono text-sm",
          isFixedChoice(row.groupType) && "tracking-wide",
          right ? "text-correct" : "text-incorrect",
        )}
      >
        {given}
      </span>
      {/* What KIND of wrong, beside the words rather than off in the margin.
          On a written answer this is the most useful thing on the row. */}
      {result.mistake && !right && (
        <span className="inline-flex items-center gap-1.5 text-[0.7rem] text-muted-foreground">
          <span
            aria-hidden
            className={cn(
              "size-1.5 rounded-full",
              result.mistake === "missed" || result.mistake === "wrong"
                ? "bg-incorrect"
                : "bg-attention",
            )}
          />
          {MISTAKE_LABEL[result.mistake]}
        </span>
      )}
    </span>
  );
}

/** What it should have been. Every accepted variant for a written answer,
 *  because "10km" and "10 km" both counting is a fact about the marking
 *  worth seeing; every right option for a lettered one, with the ones they
 *  did not pick drawn as outlines. */
function Answer({ row }: { row: ReviewRow }) {
  const { result } = row;
  if (row.byLetter) {
    const picked = new Set(letters(result.given_answer));
    const key = letters(result.correct_answers.join(","));
    return (
      <span className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
        {key.map((letter, i) => (
          <Option
            key={i}
            row={row}
            letter={letter}
            tone={picked.has(letter) ? "got" : "outline"}
            words={key.length === 1}
          />
        ))}
      </span>
    );
  }
  return (
    <span
      className={cn(
        "font-mono text-sm text-correct",
        isFixedChoice(row.groupType) && "tracking-wide",
      )}
    >
      {result.correct_answers.join(" · ")}
    </span>
  );
}

/**
 * One option: its letter as a chip, and — where there is room for it to mean
 * anything — the words the chip stands for.
 *
 * Drawn in the box's own alphabet, so matching headings reads `iv` where
 * everything else reads `D`. Taken from `matchLabel` rather than from the
 * stored string, which is what keeps the chip and the paper agreeing about
 * which option this is.
 */
function Option({
  row,
  letter,
  tone,
  words,
}: {
  row: ReviewRow;
  letter: string;
  tone: "got" | "missed" | "outline";
  words: boolean;
}) {
  const index = matchIndex(letter, row.labels);
  const text = index >= 0 ? row.options[index] : undefined;

  // Not a letter this box has. A drill cut out of a paper, a group whose
  // options were edited under an answer already given, or a client that
  // sent words where the paper wanted a letter — whatever the cause, it is
  // what the learner put, so it is printed as what it is. A chip around it
  // would be the page dressing a stray value as an option that exists.
  if (index < 0) {
    return (
      <span
        className={cn(
          "font-mono text-sm",
          tone === "missed" ? "text-incorrect" : "text-correct",
        )}
      >
        {letter}
      </span>
    );
  }

  // A roman numeral stays lowercase — `vii` is how the paper prints it —
  // and a letter is capitalised.
  const shown = matchLabel(index, row.labels);
  return (
    <span className="inline-flex items-baseline gap-2">
      <span
        className={cn(
          "inline-flex min-w-[1.15rem] shrink-0 justify-center rounded px-1 py-px text-center font-mono text-[0.7rem]",
          tone === "got" && "bg-correct/20 text-correct",
          tone === "missed" && "bg-incorrect/20 text-incorrect",
          // Never picked, and the outline says so: a chip with nothing
          // inside it, which is what a missed option is.
          tone === "outline" &&
            "text-correct ring-1 ring-correct/50 ring-inset",
        )}
      >
        {row.labels === "roman" ? shown : shown.toUpperCase()}
      </span>
      {words && text && (
        <span
          className={cn(
            "font-sans text-sm leading-snug",
            tone === "missed" ? "text-incorrect/90" : "text-correct/90",
          )}
        >
          {text}
        </span>
      )}
    </span>
  );
}

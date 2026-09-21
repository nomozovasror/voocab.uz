import { CornerLeftUp, Play } from "lucide-react";
import { cn } from "@/lib/utils";
import { fmtClock } from "@/lib/time";
import { MISTAKE_LABEL } from "@/features/listening/practice";
import {
  markAnswer,
  sayAnswer,
  type QuoteSource,
  type ReviewRow,
} from "@/features/paper/review";
import { questionNumbersShort } from "@/features/paper/numbering";

/**
 * One question, after it has been marked.
 *
 * Three rows, and the order is the argument: where you were, what you put,
 * and what was actually said. Anything that breaks that order breaks the
 * page — the version this replaced threaded `(accepted: Preston, preston)`
 * into the middle of the form's own sentence, which left "junction of Mill
 * Street and 3 test (accepted: Preston, preston) Avenue" on screen and no
 * way to read either the question or the answer out of it.
 *
 * So the form is not redrawn. It is quoted, in one line, with the gap written
 * `___` — enough to be recognised and never enough to take the layout apart.
 *
 * ## The transcript is the reason this page exists
 *
 * Knowing you were wrong is worth very little. *Hearing why you missed it* is
 * the whole value of a review, and it is the one thing a score cannot give
 * anybody. A candidate who wrote "windscreen" where the answer was "wing
 * mirror" did not mishear a word — they were pulled by a distractor, and the
 * only thing on any screen that shows them so is the sentence: *"The
 * windscreen was fine, luckily — but the wing mirror is broken."*
 *
 * The answer is marked inside it, and the play button seeks to exactly that
 * stretch. Both are conditional and quietly absent when they can't be had:
 * listening transcripts are optional (the ASR may have failed, the author may
 * have removed it), and a row with no transcript prints the answer and stops.
 * No empty box, no "no transcript available" — a message about a missing
 * feature is a row of the page spent saying nothing.
 *
 * ## On a reading review the evidence is not quoted, it is pointed at
 *
 * The passage is on the other half of the screen. Quoting a sentence out of
 * it into a box under the answer would put the same words on screen twice
 * and, worse, cut them out of the paragraph that gives them their meaning —
 * which is the whole reason somebody who answered NOT GIVEN wrongly needs
 * the text rather than the line.
 *
 * So `evidence` replaces the quote box with a LINK: pointing at the row
 * lights the words in the passage, and pressing it scrolls them into view.
 * The quote box stays for listening, where the sentence is inside a
 * recording and there is nothing on screen to point at.
 */
export function ReviewItem({
  row,
  onPlay,
  onGoTo,
  evidence,
  onPoint,
  lit,
  anchor,
}: {
  row: ReviewRow;
  /** Seeks to the moment and plays only it. Absent when the recording failed
   *  to load — the text still stands, so the row is drawn either way. */
  onPlay?: (startMs: number | null, endMs: number | null) => void;
  /** Takes the reader to the paragraph the quote came from. Reading's
   *  counterpart to the play button, and it is the same argument: the quote
   *  says what the line was, and this is how you go and read around it —
   *  which is exactly what somebody who answered NOT GIVEN wrongly needs to
   *  do. Absent for listening, where there is no paragraph to go to. */
  onGoTo?: (where: QuoteSource) => void;
  /** Where the answer is in the passage beside this row, and how to get
   *  there. Given only where the extraction placed the evidence — see
   *  `seed/read_evidence.py`. Takes the place of the quote box entirely:
   *  with the passage on screen, a copy of one of its sentences in a box is
   *  the same words twice and the paragraph around them lost. */
  evidence?: { label: string; onGoTo: () => void };
  /** Pointing at this row, which lights its evidence in the passage. Both
   *  directions, because a link that only works one way is one the reader
   *  has to discover the direction of. */
  onPoint?: (on: boolean) => void;
  /** Something in the passage belonging to this row is under the pointer. */
  lit?: boolean;
  anchor: Record<string, string>;
}) {
  const { result } = row;
  const right = result.is_correct;
  const given = sayAnswer(
    result.given_answer,
    row.byLetter,
    row.options,
    row.labels,
  ).trim();
  const key = row.byLetter
    ? sayAnswer(
        result.correct_answers.join(","),
        true,
        row.options,
        row.labels,
      )
    : result.correct_answers.join(" / ");
  const canPlay = onPlay && row.startMs != null;

  return (
    <article
      {...anchor}
      aria-label={`Question ${questionNumbersShort(row.number, row.span)}`}
      onMouseEnter={onPoint ? () => onPoint(true) : undefined}
      onMouseLeave={onPoint ? () => onPoint(false) : undefined}
      className={cn(
        "scroll-mt-24 border-t border-border py-4 transition-colors duration-fast",
        // Only where there is something on the other side to be lit BY.
        // A row that highlights itself on hover for no reason is a row
        // that looks clickable and isn't.
        onPoint && "-mx-3 rounded-lg px-3 hover:bg-surface-hover",
        lit && "bg-surface-hover",
      )}
    >
      {/* Where you were: the number, the line it sat in, and — for a wrong
          answer — what kind of wrong. */}
      <header className="flex items-baseline gap-3">
        <span
          className={cn(
            "w-6 shrink-0 text-right text-sm font-semibold tabular-nums",
            right ? "text-correct" : "text-incorrect",
          )}
        >
          {questionNumbersShort(row.number, row.span)}
        </span>
        <p className="min-w-0 flex-1 text-sm text-muted-foreground">
          {row.context?.label && (
            <span className="text-foreground/80">{row.context.label}</span>
          )}
          {row.context?.label && row.context.line && " — "}
          {row.context?.line}
        </p>
        {result.mistake && (
          // A tag rather than a sentence: it is a filing label, and the panel
          // above is where it is explained. Two tones only — the kinds that
          // mean "you didn't hear it" are red, the ones that mean "you heard
          // it and wrote it wrong" are amber, because those are two different
          // evenings' work and the colour should say which.
          <span
            className={cn(
              "shrink-0 rounded-full px-2 py-0.5 text-xs",
              result.mistake === "missed" || result.mistake === "wrong"
                ? "bg-incorrect/10 text-incorrect"
                : "bg-attention/10 text-attention",
            )}
          >
            {MISTAKE_LABEL[result.mistake]}
          </span>
        )}
      </header>

      {/* What you put, and what it should have been — on their OWN line, side
          by side, never inside the question's text. */}
      <div className="mt-2 ml-9 flex flex-wrap items-baseline gap-x-6 gap-y-1 text-base">
        <span className="flex items-baseline gap-2">
          <span className="text-xs text-muted-foreground">You</span>
          <span
            className={cn(
              "border-b-2 pb-px font-mono",
              !given
                ? "border-line-subtle text-skipped italic"
                : right
                  ? "border-correct/40 text-correct"
                  : "border-incorrect/40 text-incorrect",
            )}
          >
            {given || "left blank"}
          </span>
        </span>
        {/* Only where it adds something. Beside a right answer it is the same
            word twice, which reads as the page not knowing they got it. */}
        {!right && key && (
          <span className="flex items-baseline gap-2">
            <span className="text-xs text-muted-foreground">Answer</span>
            <span className="font-mono text-correct">{key}</span>
          </span>
        )}
      </div>

      {/* Where the answer is, on a page that is showing the page it is on.
          A link rather than a quotation — see the module docstring. */}
      {evidence && (
        <p className="mt-2 ml-9">
          <button
            type="button"
            onClick={evidence.onGoTo}
            className="inline-flex items-center gap-1.5 rounded-md text-xs text-primary transition-colors duration-fast hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            <CornerLeftUp className="size-3" aria-hidden />
            {evidence.label}
          </button>
        </p>
      )}

      {!evidence && row.transcript && (
        <div className="mt-2.5 ml-9 flex items-start gap-3 rounded-lg bg-surface-sunken px-3 py-2.5">
          {/* Only where there is a recording behind it. A reading quote has
              nothing to play, and a disabled play button beside it would be a
              control that exists to be greyed out. */}
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
            {/* Where the quote is, in whatever the paper measures place in.
                A recording measures it in time and a page measures it in
                paragraphs, and a row never has both — so they share the
                line rather than reserving two. */}
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
            <p className="text-base leading-relaxed text-foreground/80">
              {markAnswer(row.transcript, result.correct_answers).map(
                (run, i) =>
                  run.hit ? (
                    // The one place yellow appears in a review row, and it
                    // means what it means everywhere else here: this is the
                    // thing. <mark> rather than a span, because it is
                    // literally what the element is for and screen readers
                    // announce it.
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

import { Fragment } from "react";
import { Link } from "react-router-dom";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";
import { fmtClock } from "@/lib/time";
import { Skeleton } from "@/components/ui/skeleton";
import { AuthorTag } from "@/features/listening/components/AuthorTag";
import {
  DIFFICULTY_CLASS,
  DIFFICULTY_SHORT,
  FULL_TEST_PARTS,
  authorSummary,
  describeTask,
  difficultyTitle,
  partLabel,
} from "@/features/listening/practice";
import type { PracticeMaterial } from "@/features/paper/types";

/**
 * One material, as somebody deciding what to practise reads it.
 *
 * Left is what it is — done or not, its name as the author typed it, and one
 * line of what is inside. Right is how hard it is, and underneath, quietly,
 * how the reader did last time. That asymmetry is the design: difficulty is
 * about the material and belongs to everyone, the score is about the reader
 * and belongs to nobody else, so the loud one is the shared fact and the
 * private one is a footnote.
 *
 * The whole row is one link. Not a link plus a "start" button plus a score
 * that led somewhere else — three targets for one decision, which is what
 * this row used to be.
 */

/** The meta line's segments, interpuncted. Built as a list rather than a
 *  template string because two of them carry a component (the task's icon,
 *  the author's avatar) and one is conditional on the material having a
 *  recording at all. */
function MetaLine({
  material: m,
  partWord,
}: {
  material: PracticeMaterial;
  partWord: string;
}) {
  const task = describeTask(m);
  const segments: React.ReactNode[] = [];

  const part = partLabel(m, partWord);
  if (part) segments.push(part);

  // Which test it was cut from. Second, after the part: both say where this
  // sits, and the part is the one the filters above the list are phrased in.
  //
  // Withheld where it IS the title. A listening part the book printed no
  // heading over — most Part 3s — is named by its reference for want of
  // anything else the book said, and printing it again underneath would be
  // the row saying one thing twice.
  if (m.reference && m.reference !== m.title) {
    segments.push(<span className="tabular-nums">{m.reference}</span>);
  }

  if (task) {
    const { Icon, label } = task;
    segments.push(
      <span className="inline-flex items-center gap-1.5">
        <Icon className="size-3.5 shrink-0 opacity-80" aria-hidden />
        {label}
      </span>,
    );
  }

  // Only alongside "Full test", which is a claim about the paper rather than
  // a count. For two or three parts the count IS the label above and saying
  // it twice would be padding.
  if (m.part_count >= FULL_TEST_PARTS) {
    segments.push(`${m.part_count} ${partWord.toLowerCase()}s`);
  }

  segments.push(
    `${m.question_count} question${m.question_count === 1 ? "" : "s"}`,
  );
  if (m.duration_ms != null) segments.push(fmtClock(m.duration_ms));
  if (m.author)
    segments.push(
      <AuthorTag author={m.author} summary={authorSummary(m.author)} />,
    );

  return (
    <p className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-muted-foreground">
      {segments.map((segment, i) => (
        <Fragment key={i}>
          {i > 0 && (
            <span aria-hidden className="opacity-60">
              ·
            </span>
          )}
          {segment}
        </Fragment>
      ))}
    </p>
  );
}

interface PracticeRowProps {
  material: PracticeMaterial;
  /** Where this paper's pages live — `/listening`, `/reading`. Taken rather
   *  than assumed: the row is the same row on both, and the only thing about
   *  it that knows which paper it is showing is where it points. */
  basePath: string;
  /** What one section of this paper is called: "Part", "Passage". */
  partWord?: string;
  /** Its place in the SEQUENCE, where there is one — the third lesson of a
   *  course. Absent in the catalogue, and that absence is the point: there,
   *  the order is "Newest first" and changes with every chip, so a number
   *  beside a title claims a ranking that does not exist and that nobody can
   *  act on. Inside a collection the order is somebody's judgement about what
   *  to do when, and the number is the whole of what makes it a course. */
  index?: number;
  innerRef?: (el: HTMLAnchorElement | null) => void;
  onFocus?: () => void;
  /** Registers the row with the list's one IntersectionObserver, which flips
   *  `data-visible` as it crosses the fold. Absent — when the reader has asked
   *  for reduced motion — the row simply renders. */
  revealRef?: (el: HTMLLIElement | null) => void;
  /** Reports the row as the one being looked at, so the cards beside the list
   *  can describe it. Pointer and keyboard both, because arrow-keying down the
   *  list is the same question asked without a mouse. */
  onPreview?: (id: string | null) => void;
}

export function PracticeRow({
  material: m,
  basePath,
  partWord = "Part",
  index,
  innerRef,
  onFocus,
  revealRef,
  onPreview,
}: PracticeRowProps) {
  const done = m.attempts > 0 && m.best_score !== null;
  const scorePct =
    done && m.question_count > 0
      ? Math.round((m.best_score! / m.question_count) * 100)
      : null;

  return (
    // The rule between rows lifts under the pointer, so the row being read
    // reads as one block rather than as the space between two lines.
    //
    // The row also fades and grows into place as it crosses the fold, and
    // back out as it leaves (reactbits.dev/components/animated-list). Two
    // departures from that original, both because their items are small cards
    // inside a scroll box and these are full-width rows on a page: the scale
    // starts at 0.95 rather than 0.7 — a 800px row growing by 240px reads as
    // a glitch rather than as an entrance — and there are no gradient masks
    // over the ends, which only make sense on a box with its own scrollbar.
    //
    // `data-visible` is set by the observer directly on the element, so
    // scrolling costs no renders. Absent it, the row stays hidden — which is
    // why `revealRef` is what decides whether the classes are here at all.
    <li
      ref={revealRef}
      className={cn(
        // The rule is a pseudo-element inset to the row's own padding, not a
        // border on this box. A border runs the full width of the column,
        // which put its ends twelve pixels outside everything it separates —
        // the number at one end and the difficulty chip at the other both
        // started short of it. Inset, the rule begins exactly under the
        // number and ends exactly under the chip.
        "relative after:absolute after:inset-x-3 after:bottom-0 after:h-px after:bg-border-subtle after:transition-colors after:duration-fast last:after:hidden",
        // It lifts under the pointer, so the row being read is one block
        // rather than the space between two lines.
        "has-[a:hover]:after:bg-transparent has-[a:focus-visible]:after:bg-transparent",
        revealRef &&
          // `scale`, not `transform`: Tailwind v4 writes scale-* to the
          // individual property, and a transition naming `transform` would
          // animate nothing.
          "scale-95 opacity-0 transition-[opacity,scale] delay-100 duration-base ease-out data-[visible=true]:scale-100 data-[visible=true]:opacity-100",
      )}
    >
      <Link
        ref={innerRef}
        to={`${basePath}/${m.id}`}
        onFocus={() => {
          onFocus?.();
          onPreview?.(m.id);
        }}
        onMouseEnter={() => onPreview?.(m.id)}
        className="group/row flex items-start gap-3 rounded-lg px-3 py-3.5 transition-colors duration-fast hover:bg-surface-hover focus-visible:bg-surface-hover focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        <div className="min-w-0 flex-1">
          <span className="flex min-w-0 items-center gap-1.5">
            {/* The count, at the head of the title rather than out in a
                gutter of its own. A column for it indented every title and
                every meta line by its width, which left the row's two lines
                of text starting somewhere the row's own edge wasn't — the
                number now sits in the reading order, and both lines begin at
                the same left edge as each other and as the rule below them.

                The full stop is what makes it a numbered title rather than a
                number that happens to be in front of one — "1 Library
                membership" reads as part of the name, "1." reads as an item
                in a list. It is also why the colour is the title's own:
                greyed, the number looked like it belonged to the meta line
                below and had drifted up a row.

                aria-hidden because the <ol> around these rows already numbers
                them for a screen reader, and hearing "one, one, Library
                membership" is the same fact twice. */}
            {index !== undefined && (
              <span
                aria-hidden
                className="shrink-0 text-base tabular-nums text-foreground"
              >
                {index}.
              </span>
            )}
            {/* The title, then the tick — the order the sentence is read in:
                "Library membership, done" rather than "done, Library
                membership".

                It survives a long title because these are flex items rather
                than text: the title takes what it needs and no more, so on a
                short one the tick sits against the last letter, and on a long
                one the title shrinks to an ellipsis and the tick keeps its
                sixteen pixels at the end of it. Written inline it would have
                been the first thing the ellipsis ate. */}
            <span className="truncate text-base text-foreground">{m.title}</span>
            {/* Nothing at all where it isn't done: an empty circle in every
                other row is a column of holes to read past. */}
            {done && (
              <span
                role="img"
                aria-label="Completed"
                title="You have sat this material"
                className="inline-flex size-4 shrink-0 items-center justify-center rounded-full bg-correct/20 text-correct"
              >
                <Check className="size-3" strokeWidth={3} aria-hidden />
              </span>
            )}
          </span>
          <MetaLine material={m} partWord={partWord} />
        </div>

        {/*
          A column of its own width, and the two things in it centred in it.
          Ragged right edges down a list read as rows that don't line up even
          when every one of them is placed identically — so the chip is a
          fixed width (see `DIFFICULTY_SHORT`) and the figure under it is
          centred on the same axis rather than pushed to the page edge.

          `self-stretch` with `justify-center` is what handles the row that
          has no figure: the chip centres against the whole two-line row
          instead of hanging at the top of it beside nothing.
        */}
        <div className="flex w-24 shrink-0 flex-col items-center justify-center gap-1 self-stretch">
          <span
            title={difficultyTitle(m)}
            className={cn(
              "w-14 rounded-full border py-0.5 text-center text-xs font-medium",
              DIFFICULTY_CLASS[m.difficulty.band],
            )}
          >
            {DIFFICULTY_SHORT[m.difficulty.band]}
          </span>
          {/* Only where there is something to say. A "0% · 0 tries" under
              every untouched row would be a page telling a beginner they have
              failed forty things they have never opened. */}
          {done && (
            <span className="text-xs whitespace-nowrap tabular-nums text-muted-foreground">
              {scorePct !== null && `${scorePct}% · `}
              {m.attempts} {m.attempts === 1 ? "try" : "tries"}
            </span>
          )}
        </div>
      </Link>
    </li>
  );
}

/**
 * The same row, waiting.
 *
 * Built from the real row's own class strings — the bars sit inside the same
 * elements, so the line-heights set the height and the two can't drift apart.
 * See CLAUDE.md: measured pixels are how a skeleton ends up 6px out per row.
 */
export function PracticeRowSkeleton() {
  return (
    <li className="relative after:absolute after:inset-x-3 after:bottom-0 after:h-px after:bg-border-subtle last:after:hidden">
      <div className="flex items-start gap-3 px-3 py-3.5">
        <div className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5">
            <span className="text-base">
              <Skeleton className="inline-block h-[0.8em] w-56 max-w-full" />
            </span>
          </span>
          {/* h-5, because the real meta line holds a 20px avatar and its own
              13px line box is only 17px tall. Left to the text alone the
              skeleton row came out 3px short — invisible on one row and a
              nine-pixel settle by the third. */}
          <p className="mt-1 flex h-5 items-center text-xs">
            <Skeleton className="inline-block h-[0.8em] w-72 max-w-full" />
          </p>
        </div>
        <div className="flex w-24 shrink-0 flex-col items-center justify-center gap-1 self-stretch">
          <Skeleton className="h-6 w-14 rounded-full" />
          <span className="text-xs">
            <Skeleton className="inline-block h-[0.8em] w-20" />
          </span>
        </div>
      </div>
    </li>
  );
}

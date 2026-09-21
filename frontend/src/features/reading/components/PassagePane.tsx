import { cn } from "@/lib/utils";
import type { Passage } from "@/features/paper/types";
import {
  marksIn,
  runsOf,
  type Highlight,
  type MarkColour,
} from "@/features/reading/highlights";
import {
  overlaysIn,
  points,
  WASH as LAYER_WASH,
  type Overlay,
} from "@/features/reading/layers";

/**
 * The text a reading paper is answered from.
 *
 * It is half the screen and it is the half that does not change, which is
 * what makes the two-pane layout right for reading where one scroll is right
 * for listening: a recording plays once through whatever is on screen, and a
 * passage is looked BACK at, sentence by sentence, against the question in
 * hand. A candidate on question 9 wants paragraph C and question 9 in view at
 * the same time, and nothing but two scrolls gives them that.
 *
 * Paragraph letters are printed where the passage has them, in the margin
 * rather than inline: two of Reading's own tasks are answered by naming one
 * ("which paragraph contains the following information"), so the letter has
 * to be findable at a glance down the edge, and it must not read as the first
 * word of the paragraph.
 */

interface PassagePaneProps {
  title: string;
  passage: Passage;
  /** Which part this passage belongs to. Part of every anchor it prints,
   *  because a paper has three passages and each one letters its paragraphs
   *  from A: without it a page carries three elements called `p-C` and every
   *  jump lands on the first of them. */
  partId: string;
  /** Whether to print the passage's own heading above it. False where it is
   *  the only passage on the page — see the comment where it is drawn. */
  showTitle?: boolean;
  /** What the reader marked. Drawn here and nowhere else — the passage is
   *  the only thing on either page there is anything to mark. */
  highlights?: Highlight[];
  /** Clicking a mark asks for it to go. Absent on the review, where the
   *  marks are a record of how the paper was read rather than a tool. */
  onUnmark?: (index: number, offset: number) => void;
  /** A paragraph to draw attention to — the review page points at the one an
   *  answer came from. Null while the paper is being sat: there is nothing to
   *  point at yet, and pointing would be telling. */
  highlight?: string | null;
  /** What the REVIEW has to say about this text: where the answers were,
   *  which words are worth learning, which of those are already saved. One
   *  layer's worth — see `features/reading/layers.ts` on why never four.
   *
   *  Absent while the paper is being sat, and that is not a matter of
   *  tidiness: every one of these is an answer. */
  overlays?: Overlay[];
  /** The overlay `key` currently being pointed at from the other pane, drawn
   *  brighter. One key rather than one overlay, because a question's
   *  evidence can be two sentences and lighting one of them lights half of
   *  why the reader was wrong. */
  lit?: string | null;
  /** Pointing at a mark from THIS side, which lights the row that belongs to
   *  it in the other pane. The hover link works both ways or it is a trick
   *  the reader has to learn the direction of. */
  onPoint?: (key: string | null) => void;
  className?: string;
}

/** How each mark is washed over the prose.
 *
 *  A wash rather than a block, so the words underneath stay the foreground
 *  — a passage with six marks in it has to still read as a passage.
 *
 *  It was a quarter of the colour and that was too little to read as a
 *  highlight at all: against a dark ground a 25% tint of amber is a change
 *  in shade, not a mark, and a reader scanning back through nine hundred
 *  words could not find what they had marked. Two fifths, with the padding
 *  and the small radius of a real marker stroke — which is what carries
 *  most of it, because what says "highlighted" is the shape of the block
 *  around the words rather than the strength of the colour in it. */
const WASH: Record<MarkColour, string> = {
  key: "bg-mark-key/40",
  found: "bg-mark-found/40",
  doubt: "bg-mark-doubt/40",
};

/** What every mark wears, whatever colour it is. `box-decoration-clone` is
 *  the one that matters: a mark that wraps across a line break would
 *  otherwise get its padding and rounding only at the two outer ends, and
 *  the middle lines would run flush into the margin. */
const STROKE =
  "rounded-[0.2em] px-[0.12em] py-[0.05em] [box-decoration-break:clone]";

/** The id a paragraph can be scrolled to by, so the review's "go to
 *  paragraph C" and the letter printed beside it name the same thing. */
export function paragraphId(partId: string, label: string): string {
  return `passage-${partId}-${label}`;
}

/** How one of the reader's own marks is named, so the list beside the
 *  passage and the mark on it agree about which is which. Its own START
 *  rather than the run's, because two touching marks are drawn as one shape
 *  and a key taken from the wrong half would light nothing. */
export function markKey(partId: string, index: number, start: number): string {
  return `${partId}:${index}:${start}`;
}

/** The id the whole passage can be scrolled to by. The take screen brings
 *  the passage pane to it when the reader crosses into the questions that
 *  are answered from it. */
export function passageId(partId: string): string {
  return `passage-${partId}`;
}

export function PassagePane({
  title,
  passage,
  partId,
  showTitle = true,
  highlights,
  onUnmark,
  highlight,
  overlays,
  lit,
  onPoint,
  className,
}: PassagePaneProps) {
  return (
    <article
      id={passageId(partId)}
      aria-label={title}
      className={cn("max-w-prose", className)}
    >
      {/* No heading of its own where there is only one passage on the page.
          It said "Reading Passage 2" under a page already titled with the
          passage's name, beside a meta line already saying which passage of
          which test it is — four lines of the most expensive space on this
          screen spent on one fact, while the prose below them was cut off
          mid-sentence. `showTitle` puts it back for a paper that holds
          three, where the reader does need to know which one they are in. */}
      {showTitle && (
        <h2 className="mb-1 text-lg font-semibold text-foreground">{title}</h2>
      )}
      {passage.subtitle && (
        <p className="mb-5 text-sm leading-relaxed text-muted-foreground">
          {passage.subtitle}
        </p>
      )}

      <div className="space-y-4">
        {passage.paragraphs.map((paragraph, index) => (
          <div
            key={index}
            id={
              paragraph.label ? paragraphId(partId, paragraph.label) : undefined
            }
            className={cn(
              "flex gap-3 rounded-md transition-colors duration-slow",
              highlight &&
                paragraph.label === highlight &&
                "-mx-2 bg-primary/5 px-2 py-1",
            )}
          >
            {/* Only where the book prints one. A letter invented for a
                passage that has none would be a letter no question can
                name. */}
            {paragraph.label && (
              <span
                aria-hidden
                className={cn(
                  "w-4 shrink-0 pt-0.5 text-[0.8em] font-semibold tabular-nums",
                  highlight === paragraph.label
                    ? "text-primary"
                    : "text-muted-foreground",
                )}
              >
                {paragraph.label}
              </span>
            )}
            <p
              // The offsets a selection is measured against are offsets into
              // THIS element's text, so it is the one the page reaches for.
              data-paragraph-index={index}
              // `em`, not `rem`: the size control sets a percentage on the
              // pane, and an absolute size ignores it — which is what the
              // first version of the control did, silently.
              className="min-w-0 flex-1 text-[0.95em] leading-[1.72] text-foreground"
            >
              {/* Two kinds of marking, never both at once.

                  A paragraph carries either what the READER put on it — the
                  take screen, and the review's "My marks" layer, which is
                  the same data drawn the same way — or what the REVIEW has
                  to say about it. Laid over each other they would be two
                  systems of colour in one sentence, which is the thing
                  `layers.ts` exists to prevent one level up. */}
              {overlays
                ? runsOf(
                    paragraph.text,
                    overlaysIn(overlays, partId, index),
                  ).map((run, k) =>
                    run.mark ? (
                      <mark
                        key={k}
                        // What the other pane scrolls to. On the MARK rather
                        // than on the paragraph, because a paragraph is
                        // ninety words and the reader was promised a
                        // sentence — and because a question's evidence can
                        // be in two paragraphs, of which this names the
                        // first drawn.
                        data-overlay={run.mark.key}
                        // And the keys of whatever this mark swallowed, so
                        // two questions whose evidence is the SAME sentence
                        // can both be jumped to. Space-separated for the
                        // `~=` selector that reads it; only question ids are
                        // ever looked up this way, and those have no spaces
                        // in them.
                        data-overlay-also={run.mark.also?.join(" ")}
                        title={run.mark.title || undefined}
                        onMouseEnter={
                          onPoint ? () => onPoint(run.mark!.key) : undefined
                        }
                        onMouseLeave={onPoint ? () => onPoint(null) : undefined}
                        className={cn(
                          "text-foreground transition-colors duration-fast",
                          STROKE,
                          LAYER_WASH[run.mark.tone].rest,
                          points(run.mark, lit ?? null) &&
                            LAYER_WASH[run.mark.tone].lit,
                        )}
                      >
                        {run.text}
                        {/* The number, riding on the end of the mark.
                            Inside the <mark> so it travels with the wash
                            and cannot be separated from it by a line break,
                            and `sup` because that is what a marginal
                            reference is — a teacher's pencil number beside
                            the sentence, not a word in it.

                            `select-none` so copying the passage does not
                            take "Q12" out with it: the text under these
                            marks is the book's, and a reader copying a
                            sentence into their notes should get the
                            sentence. */}
                        {run.mark.labels?.length ? (
                          <sup
                            className={cn(
                              "ml-0.5 text-[0.6em] font-semibold tracking-tight select-none",
                              LAYER_WASH[run.mark.tone].tag,
                            )}
                          >
                            {run.mark.labels.join(" ")}
                          </sup>
                        ) : null}
                      </mark>
                    ) : (
                      <span key={k}>{run.text}</span>
                    ),
                  )
                : runsOf(
                    paragraph.text,
                    marksIn(highlights ?? [], partId, index),
                  ).map((run, k) =>
                    run.mark ? (
                      // `mark` rather than a span: it is literally what the
                      // element is for, and it is what a screen reader announces
                      // as marked text. A click takes it off again — the same
                      // gesture that put it on, which is how every highlighter
                      // in a document works.
                      <mark
                        key={k}
                        title={run.mark.note || undefined}
                        onClick={
                          onUnmark ? () => onUnmark(index, run.at) : undefined
                        }
                        // The reader's own marks join the hover link too,
                        // keyed the way `ReviewMarks` keys its rows: the
                        // merged mark's own start, since two touching marks
                        // are one shape here and must be one row there.
                        // Absent on the take screen, which hands in no
                        // `onPoint` and has no list to light.
                        onMouseEnter={
                          onPoint
                            ? () =>
                                onPoint(markKey(partId, index, run.mark!.start))
                            : undefined
                        }
                        onMouseLeave={onPoint ? () => onPoint(null) : undefined}
                        className={cn(
                          "text-foreground",
                          STROKE,
                          WASH[run.mark.colour ?? "key"],
                          // A note is a mark that says something, and it has to
                          // look like one or the reader cannot tell which of
                          // their own marks they wrote on. An underline rather
                          // than an icon: an icon inside running prose is a
                          // character the sentence did not have.
                          run.mark.note &&
                            "decoration-dotted underline underline-offset-4",
                          onUnmark && "cursor-pointer",
                          lit === markKey(partId, index, run.mark.start) &&
                            "ring-2 ring-foreground/30",
                        )}
                      >
                        {run.text}
                      </mark>
                    ) : (
                      <span key={k}>{run.text}</span>
                    ),
                  )}
            </p>
          </div>
        ))}
      </div>

      {/* The acknowledgement line the book prints under the passage. Kept
          because it is part of the paper, and because a passage with no
          source reads as something the app wrote. */}
      {passage.source && (
        <p className="mt-6 border-t border-border pt-3 text-xs text-muted-foreground">
          {passage.source}
        </p>
      )}
    </article>
  );
}

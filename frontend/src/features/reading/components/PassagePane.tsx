import { cn } from "@/lib/utils";
import type { Passage } from "@/features/paper/types";

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
  /** A paragraph to draw attention to — the review page points at the one an
   *  answer came from. Null while the paper is being sat: there is nothing to
   *  point at yet, and pointing would be telling. */
  highlight?: string | null;
  className?: string;
}

/** The id a paragraph can be scrolled to by, so the review's "go to
 *  paragraph C" and the letter printed beside it name the same thing. */
export function paragraphId(partId: string, label: string): string {
  return `passage-${partId}-${label}`;
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
  highlight,
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
              paragraph.label
                ? paragraphId(partId, paragraph.label)
                : undefined
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
                  "w-4 shrink-0 pt-0.5 text-sm font-semibold tabular-nums",
                  highlight === paragraph.label
                    ? "text-primary"
                    : "text-muted-foreground",
                )}
              >
                {paragraph.label}
              </span>
            )}
            <p className="min-w-0 flex-1 text-[0.95rem] leading-7 text-foreground">
              {paragraph.text}
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

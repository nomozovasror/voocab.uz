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

export function PassagePane({
  title,
  passage,
  highlight,
  className,
}: PassagePaneProps) {
  return (
    <article className={cn("max-w-prose", className)}>
      <header className="mb-5">
        <h2 className="text-lg font-semibold text-foreground">{title}</h2>
        {passage.subtitle && (
          <p className="mt-1 text-sm text-muted-foreground">
            {passage.subtitle}
          </p>
        )}
      </header>

      <div className="space-y-4">
        {passage.paragraphs.map((paragraph, index) => (
          <div
            key={index}
            id={paragraph.label ? `p-${paragraph.label}` : undefined}
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

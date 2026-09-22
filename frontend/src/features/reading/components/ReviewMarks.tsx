import { cn } from "@/lib/utils";
import type { Passage } from "@/features/paper/types";
import {
  marksIn,
  MARK_MEANING,
  MARK_STYLES,
  type Highlight,
  type MarkStyle,
} from "@/features/reading/highlights";

/**
 * What the reader marked while they were reading, listed beside the passage
 * it is marked on.
 *
 * ## Why this exists at all
 *
 * Because every other layer has an analysis next to it and this one did not.
 * With one control governing both halves of the screen, choosing *My marks*
 * used to leave whatever panel happened to be open on the right — the
 * mistakes, talking about something else — which is the page contradicting
 * its own control.
 *
 * And it turns out to be worth having on its own terms. A candidate
 * highlights for two reasons and the two strokes keep them apart
 * (`highlights.ts`); what the strokes cannot do is answer *what did I mark
 * as "come back to this" and never come back to?* Six underlined stretches
 * scattered through nine hundred words are six stretches nobody can count.
 * Grouped by what they MEAN, they are a short list of decisions, and the
 * second group is a list of things the reader knew they were unsure of.
 *
 * ## Read-only, and that is the point
 *
 * The marks are a record of how the paper was worked. Letting them be
 * removed here would let somebody tidy away the evidence of their own
 * reading twenty minutes after making it, which is the one thing this page
 * exists to stop them doing. The take screen is where a mark is a tool; here
 * it is a fact.
 *
 * Notes are printed where there are any, because a note is the only part of
 * a mark the passage itself cannot show — the underline says "there are
 * words attached" and this is where the words are.
 */

/** In the order they are worth reading back: what the reader settled, then
 *  what they did not — which is the group with something left to do in it,
 *  and therefore the one that belongs at the bottom where reading stops. */
const ORDER: MarkStyle[] = MARK_STYLES;

/** The heading's swatch, which is the mark itself at heading size: both are
 *  amber now, so a dot each would be two identical dots labelling two
 *  different groups. */
const INK: Record<MarkStyle, string> = {
  fill: "h-2 w-3.5 rounded-[0.15rem] bg-mark-key/70",
  line: "h-2 w-3.5 rounded-[0.15rem] border-b-2 border-mark-key bg-mark-key/10",
};

export function ReviewMarks({
  marks,
  passages,
  lit,
  onPoint,
  className,
}: {
  marks: Highlight[];
  /** The passages, to cut each mark's own words out of. The mark is offsets
   *  and nothing else — see `highlights.ts` on why it stores no copy of the
   *  text — so the words come from the same place the passage draws them. */
  passages: { id: string; passage?: Passage | null }[];
  lit: string | null;
  onPoint: (key: string | null) => void;
  className?: string;
}) {
  const rows = ORDER.map((colour) => ({
    colour,
    marks: read(marks, passages).filter(
      (one) => (one.mark.style ?? "fill") === colour,
    ),
  })).filter((group) => group.marks.length > 0);

  return (
    <section className={cn("min-w-0", className)}>
      <header className="rounded-xl bg-surface-sunken px-4 py-3">
        <h2 className="text-sm font-semibold text-foreground">
          {marks.length} {marks.length === 1 ? "thing" : "things"} you marked
        </h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Read back as you left them — the passage as you worked it.
        </p>
      </header>

      {rows.map((group) => (
        <div key={group.colour} className="mt-4">
          <h3 className="mb-1 flex items-center gap-2 text-xs tracking-caps text-muted-foreground uppercase">
            <span aria-hidden className={cn("shrink-0", INK[group.colour])} />
            {MARK_MEANING[group.colour]}
          </h3>
          <ul>
            {group.marks.map((one) => (
              <li
                key={one.key}
                onMouseEnter={() => onPoint(one.key)}
                onMouseLeave={() => onPoint(null)}
                className={cn(
                  "rounded-lg border-b border-border/60 px-2 py-2.5 transition-colors duration-fast last:border-b-0",
                  lit === one.key && "bg-surface-hover",
                )}
              >
                <p className="text-xs leading-relaxed text-foreground/80">
                  {one.text}
                </p>
                {one.mark.note && (
                  <p className="mt-1 border-l-2 border-border pl-2 text-xs leading-relaxed text-muted-foreground italic">
                    {one.mark.note}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}

/**
 * Each mark with the words it covers, in the order they stand in the paper.
 *
 * Through `marksIn` rather than over the raw list, so two touching marks are
 * one row here exactly as they are one shape on the passage — and so the key
 * a row hovers by is the key the merged overlay carries. A list that named
 * marks the passage has already merged would light nothing.
 */
function read(
  marks: Highlight[],
  passages: { id: string; passage?: Passage | null }[],
): { key: string; text: string; mark: Highlight }[] {
  const out: { key: string; text: string; mark: Highlight }[] = [];
  for (const part of passages) {
    const paragraphs = part.passage?.paragraphs ?? [];
    for (let index = 0; index < paragraphs.length; index++) {
      for (const mark of marksIn(marks, part.id, index)) {
        const text = (paragraphs[index].text || "").slice(mark.start, mark.end);
        if (!text.trim()) continue;
        out.push({
          key: `${part.id}:${index}:${mark.start}`,
          text,
          mark,
        });
      }
    }
  }
  return out;
}

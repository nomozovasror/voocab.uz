import type { FocusEventHandler } from "react";
import { cn } from "@/lib/utils";
import { ChoiceGroup } from "@/features/listening/components/ChoiceGroup";
import { FormCompletionGroup } from "@/features/listening/components/FormCompletionGroup";
import { MatchingGroup } from "@/features/listening/components/MatchingGroup";
import { groupNumbering, sorted } from "@/features/listening/numbering";
import type {
  MaterialTake,
  QuestionResult,
  TakePart,
} from "@/features/listening/types";

/**
 * The paper: every part, every group, in the author's order.
 *
 * One component for sitting the test and for reading it back afterwards,
 * because they are the same paper. A review that redrew the questions in its
 * own way would be showing a candidate something they never sat — the gap
 * somewhere else in the sentence, the options in a list instead of on the
 * map — and the whole point of the review is to put them back in front of
 * what they were looking at when they got it wrong.
 *
 * What makes it a review rather than a test is the `results` prop. The group
 * components each know how to draw a graded answer: the field in the colour
 * of its verdict, the accepted answers beside it, a button that plays the
 * moment it was said. Handing them results turns the paper into a marked one,
 * and there is nothing else to switch.
 */

interface QuestionPaperProps {
  material: MaterialTake;
  /** question_id -> what was given. Typed answers as text, chosen options as
   *  comma-separated letters — the same shape going in and coming back. */
  answers: Record<string, string>;
  onChange?: (questionId: string, value: string) => void;
  /** Present only after grading. Its presence is what marks the paper. */
  results?: Record<string, QuestionResult>;
  onReplay?: (startMs: number | null, endMs: number | null) => void;
  disabled?: boolean;
  /** The take page measures how long each answer held focus by watching focus
   *  move through here, rather than by every group component reporting it. */
  onFocus?: FocusEventHandler<HTMLDivElement>;
  onBlur?: FocusEventHandler<HTMLDivElement>;
}

export function QuestionPaper({
  material,
  answers,
  onChange,
  results,
  onReplay,
  disabled,
  onFocus,
  onBlur,
}: QuestionPaperProps) {
  const parts = sorted(material.parts);
  const startNumbers = groupNumbering(material);

  return (
    <div className="space-y-10" onFocus={onFocus} onBlur={onBlur}>
      {parts.map((part, i) => (
        // scroll-mt clears the whole sticky block — app header, audio, and
        // the chips that did the jumping — because a jump that lands the
        // part's own heading underneath the bar that sent you there looks
        // like it went somewhere else.
        <section key={part.id} id={`part-${part.id}`} className="scroll-mt-52">
          <h2 className="mb-4 border-b border-border pb-2 text-xs tracking-[0.14em] text-muted-foreground uppercase">
            part {i + 1}
            {part.title && part.title.toLowerCase() !== `part ${i + 1}` && (
              <span className="ml-2 normal-case tracking-normal">
                {part.title}
              </span>
            )}
          </h2>
          <div className="space-y-8">
            {sorted(part.question_groups).map((group) => {
              const shared = {
                group,
                answers,
                onChange: onChange ?? (() => {}),
                startNumber: startNumbers.get(group.id) ?? 1,
                results,
                onReplay,
                disabled,
              };
              // Anything this build doesn't know about is rendered as a
              // form: every group has a template field, so showing it is
              // better than leaving the questions out of the paper entirely.
              return group.type === "multiple_choice" ? (
                <ChoiceGroup key={group.id} {...shared} />
              ) : group.type === "matching" ? (
                <MatchingGroup key={group.id} {...shared} />
              ) : (
                <FormCompletionGroup key={group.id} {...shared} />
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}

/** Jump links along the bottom of the sticky block. Drawn only where there is
 *  more than one part to jump between — a single-part material would be
 *  offering a way back to the page you are on. */
export function PartChips({
  parts,
  active,
}: {
  parts: TakePart[];
  active: string | null;
}) {
  if (parts.length < 2) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {parts.map((part, i) => (
        <a
          key={part.id}
          href={`#part-${part.id}`}
          className={cn(
            "rounded-md px-2 py-1 text-xs transition-colors",
            active === part.id
              ? "bg-primary/12 text-primary"
              : "text-muted-foreground hover:bg-foreground/8 hover:text-foreground",
          )}
        >
          part {i + 1}
        </a>
      ))}
    </div>
  );
}

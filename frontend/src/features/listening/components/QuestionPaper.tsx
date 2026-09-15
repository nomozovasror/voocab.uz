import type { FocusEventHandler } from "react";
import { Play } from "lucide-react";
import { ChoiceGroup } from "@/features/listening/components/ChoiceGroup";
import { FormCompletionGroup } from "@/features/listening/components/FormCompletionGroup";
import { MatchingGroup } from "@/features/listening/components/MatchingGroup";
import { groupNumbering, sorted } from "@/features/listening/numbering";
import { paperParts } from "@/features/listening/take-paper";
import type {
  MaterialTake,
  QuestionResult,
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
  /** Plays a whole part, where the author marked where it starts and ends.
   *  Passed only when the rules allow moving the playhead — an exam does not
   *  let a candidate skip to part 3 — which is why it arrives as a handler
   *  rather than as a flag this component would have to interpret. */
  onPlayPart?: (startMs: number | null, endMs: number | null) => void;
  disabled?: boolean;
  /** Questions the candidate marked to come back to, and the toggle for one.
   *  Present while sitting the paper and absent while reading it back: after
   *  grading there is nothing left to come back to. */
  flagged?: Set<string>;
  onFlag?: (questionId: string) => void;
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
  onPlayPart,
  disabled,
  flagged,
  onFlag,
  onFocus,
  onBlur,
}: QuestionPaperProps) {
  const parts = sorted(material.parts);
  const startNumbers = groupNumbering(material);
  // The same walk the header and the navigator make, so "Questions 7–14"
  // over a part cannot disagree with the numbers printed inside it.
  const spans = paperParts(material);

  return (
    <div className="space-y-10" onFocus={onFocus} onBlur={onBlur}>
      {parts.map((part, i) => (
        // scroll-mt clears the whole sticky block — app header, audio, and
        // the chips that did the jumping — because a jump that lands the
        // part's own heading underneath the bar that sent you there looks
        // like it went somewhere else.
        <section key={part.id} id={`part-${part.id}`} className="scroll-mt-52">
          {/* A rule ABOVE the heading rather than under it. A part is a break
              in a continuous paper, not a box around a set of questions, and
              the line that says so belongs where the break is. */}
          <h2 className="mb-4 flex flex-wrap items-baseline gap-x-3 gap-y-1 border-t border-border pt-4">
            <span className="text-sm font-medium text-foreground">
              Part {i + 1}
            </span>
            {spans[i] && spans[i].rows.length > 0 && (
              <span className="text-xs tabular-nums text-muted-foreground">
                Questions {spans[i].from}
                {spans[i].to > spans[i].from ? `\u2013${spans[i].to}` : ""}
              </span>
            )}
            {part.title && part.title.toLowerCase() !== `part ${i + 1}` && (
              <span className="text-xs text-muted-foreground">{part.title}</span>
            )}
            {/* Where the author marked the part's boundaries, the learner can
                hear it from the top. That marking already existed and did
                nothing: the editor asked for it and no page ever played it. */}
            {onPlayPart && part.audio_start_ms != null && (
              <button
                type="button"
                onClick={() => onPlayPart(part.audio_start_ms, part.audio_end_ms)}
                title={`Play part ${i + 1} from the start`}
                className="ml-auto flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs text-muted-foreground transition-colors duration-fast hover:bg-surface-hover hover:text-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                <Play className="size-3" aria-hidden />
                Play this part
              </button>
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
                flagged,
                onFlag,
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

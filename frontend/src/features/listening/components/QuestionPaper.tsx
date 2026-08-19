import type { FocusEventHandler } from "react";
import { Play } from "lucide-react";
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
  /** Plays a whole part, where the author marked where it starts and ends.
   *  Passed only when the rules allow moving the playhead — an exam does not
   *  let a candidate skip to part 3 — which is why it arrives as a handler
   *  rather than as a flag this component would have to interpret. */
  onPlayPart?: (startMs: number | null, endMs: number | null) => void;
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
  onPlayPart,
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
          <h2 className="mb-4 flex items-baseline gap-2 border-b border-border pb-2 text-xs tracking-[0.14em] text-muted-foreground uppercase">
            part {i + 1}
            {part.title && part.title.toLowerCase() !== `part ${i + 1}` && (
              <span className="normal-case tracking-normal">{part.title}</span>
            )}
            {/* Where the author marked the part's boundaries, the learner can
                hear it from the top. That marking already existed and did
                nothing: the editor asked for it and no page ever played it. */}
            {onPlayPart && part.audio_start_ms != null && (
              <button
                type="button"
                onClick={() => onPlayPart(part.audio_start_ms, part.audio_end_ms)}
                title={`Play part ${i + 1} from the start`}
                className="ml-auto flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[11px] normal-case tracking-normal transition-colors hover:bg-foreground/8 hover:text-primary"
              >
                <Play className="size-3" aria-hidden />
                play this part
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

/** How much of a part is answered, by part id. */
export type PartProgress = Map<string, { answered: number; total: number }>;

/** Jump links along the bottom of the sticky block. Drawn only where there is
 *  more than one part to jump between — a single-part material would be
 *  offering a way back to the page you are on.
 *
 *  With `progress` they also say how much of each part is left. That is the
 *  question a candidate two parts in actually has — "what have I still not
 *  answered" — and without it the only way to find out is to scroll the whole
 *  paper looking for empty boxes. A finished part goes quiet rather than
 *  bright: what wants the eye is what is unfinished. */
export function PartChips({
  parts,
  active,
  progress,
}: {
  parts: TakePart[];
  active: string | null;
  progress?: PartProgress;
}) {
  if (parts.length < 2) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {parts.map((part, i) => {
        const done = progress?.get(part.id);
        const complete = done && done.total > 0 && done.answered >= done.total;
        return (
          <a
            key={part.id}
            href={`#part-${part.id}`}
            className={cn(
              "flex items-baseline gap-1.5 rounded-md px-2 py-1 text-xs transition-colors",
              active === part.id
                ? "bg-primary/12 text-primary"
                : "text-muted-foreground hover:bg-foreground/8 hover:text-foreground",
            )}
          >
            part {i + 1}
            {done && done.total > 0 && (
              <span
                className={cn(
                  "font-mono text-[10px] tabular-nums",
                  complete ? "opacity-40" : "text-warning",
                )}
              >
                {done.answered}/{done.total}
              </span>
            )}
          </a>
        );
      })}
    </div>
  );
}

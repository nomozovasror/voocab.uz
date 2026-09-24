import { forwardRef } from "react";
import { cn } from "@/lib/utils";

export interface GapFieldProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "type" | "className"> {
  /** Border and text colour for whatever this gap's state is right now —
   *  correct, incorrect, filled, empty on a take screen; the practice
   *  session's own verdict colours in the vocabulary module. Computed by the
   *  caller, because what counts as "correct" differs between a graded take
   *  answer and a spaced-repetition verdict, and this component has no
   *  opinion on either. */
  tone?: string;
  className?: string;
}

/**
 * The gap: a rule under a piece of writing, not a box on a form.
 *
 * Pulled out of `FormCompletionGroup`, where it used to be the one text
 * `<input>` inline among the selects, so the vocabulary module's recall
 * exercise could use the identical control rather than writing a second gap
 * that would drift from this one's look the first time either was touched.
 * Sharing it is not incidental — the whole argument for the practice
 * exercise being "fill the gap in a sentence" rather than "type the
 * translation" is that it is the SAME skill a completion task already
 * asks for (see `features/vocabulary/CLAUDE.md`).
 *
 * No visual or behavioural change on the take screen: every prop
 * `FormCompletionGroup` set on the inline `<input>` it still sets here, by
 * forwarding straight through — `data-question`, `value`, `onChange`,
 * `disabled`, `aria-label`, `aria-invalid` and now, for the practice screen,
 * `onKeyDown`, `autoFocus` and `placeholder` too.
 */
export const GapField = forwardRef<HTMLInputElement, GapFieldProps>(
  function GapField({ tone, className, ...props }, ref) {
    return (
      <input
        ref={ref}
        type="text"
        autoComplete="off"
        autoCorrect="off"
        spellCheck={false}
        className={cn(
          // No ring: the underline IS the focus state, and a ring around a
          // borderless field draws a box the design spent the rest of this
          // rule removing.
          "w-36 border-0 border-b-2 bg-transparent px-1 pb-0.5 font-mono text-[1em] text-foreground transition-colors duration-fast placeholder:text-muted-foreground focus-visible:border-primary focus-visible:outline-none",
          tone,
          className,
        )}
        {...props}
      />
    );
  },
);

import { useEffect, useRef } from "react";
import { Plus, X } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  MAX_MATCH_OPTIONS,
  matchLetter,
  newMatchOption,
  type MatchOption,
} from "@/features/paper/matching";

/**
 * The box of lettered options a group is answered from.
 *
 * Two tasks print one, and it is the same box both times: matching, where the
 * items are a list, and a completion task printed with a word list, where they
 * are gaps in a paragraph. So this is one component rather than two that would
 * drift — the letters are positions, an option is identified by id, and the
 * only thing either caller decides is what to call it and what to show beside
 * the "add" row.
 *
 * Tinted and set apart from the questions, because it belongs to the group:
 * the paper prints it once, above or below the whole set, and reading it as
 * part of the first question is reading the block wrong.
 */

interface OptionsBoxProps {
  options: MatchOption[];
  /** Applied against the latest list — two edits can land between renders. */
  onChange: (edit: (current: MatchOption[]) => MatchOption[]) => void;
  /** Removing an option has to clear whatever pointed at it, which is the
   *  caller's business: it owns the questions. */
  onRemove: (optionId: string) => void;
  /** What this box is, in the words the task uses. */
  label: string;
  /** Rides on the "add an option" line, at its right: a tally, a switch. Both
   *  are about the box as a whole, and two half-empty rows in a row is a gap
   *  for no reason. */
  trailing?: React.ReactNode;
}

export function OptionsBox({
  options,
  onChange,
  onRemove,
  label,
  trailing,
}: OptionsBoxProps) {
  // The caret goes into the option a press of Enter just made, which is what
  // lets a box be typed straight down.
  const inputs = useRef(new Map<string, HTMLInputElement>());
  const pendingFocus = useRef<string | null>(null);

  useEffect(() => {
    const key = pendingFocus.current;
    if (!key) return;
    const el = inputs.current.get(key);
    if (!el) return;
    pendingFocus.current = null;
    el.focus();
  });

  const append = () => {
    if (options.length >= MAX_MATCH_OPTIONS) return;
    const option = newMatchOption();
    pendingFocus.current = option.id;
    onChange((current) =>
      current.length >= MAX_MATCH_OPTIONS ? current : [...current, option],
    );
  };

  return (
    <div className="rounded-lg border border-border bg-foreground/[0.025] px-3 py-2.5">
      <p className="mb-1.5 text-xs text-muted-foreground">{label}</p>
      <ul className="space-y-1">
        {options.map((option, index) => {
          const letter = matchLetter(index);
          return (
            <li key={option.id} className="group/option flex items-center gap-2">
              <span
                aria-hidden
                className="flex size-6 shrink-0 items-center justify-center rounded-full border border-border text-xs font-semibold text-muted-foreground"
              >
                {letter.toUpperCase()}
              </span>
              <input
                type="text"
                ref={(el) => {
                  if (el) inputs.current.set(option.id, el);
                  else inputs.current.delete(option.id);
                }}
                value={option.text}
                onChange={(e) =>
                  onChange((current) =>
                    current.map((o) =>
                      o.id === option.id ? { ...o, text: e.target.value } : o,
                    ),
                  )
                }
                onKeyDown={(e) => {
                  if (e.key !== "Enter") return;
                  e.preventDefault();
                  append();
                }}
                placeholder="option"
                aria-label={`Option ${letter.toUpperCase()}`}
                className="min-w-0 flex-1 border-b border-transparent bg-transparent pb-0.5 text-base text-foreground placeholder:text-muted-foreground/50 hover:border-border focus-visible:border-primary focus-visible:outline-none"
              />
              {/* Two is the fewest a box can have; below that there is nothing
                  to choose between. Its space is held either way, so nothing
                  shifts when it appears on hover. */}
              <span className="flex size-6 shrink-0 items-center justify-center">
                {options.length > 2 && (
                  <button
                    type="button"
                    onClick={() => onRemove(option.id)}
                    aria-label={`Remove option ${letter.toUpperCase()}`}
                    title="Remove this option, and any answer using it"
                    className="flex size-6 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-opacity group-hover/option:opacity-100 hover:text-destructive focus-visible:opacity-100"
                  >
                    <X className="size-3.5" aria-hidden />
                  </button>
                )}
              </span>
            </li>
          );
        })}

        {/* The next option, drawn as one but a size down: it lines up with the
            letters above it without competing with them for the eye. */}
        <li className="flex items-center gap-2 pt-0.5">
          <button
            type="button"
            onClick={append}
            title="Add an option"
            className="group/add flex min-w-0 items-center gap-2 text-left"
          >
            <span className="flex size-5 shrink-0 items-center justify-center rounded-full border border-dashed border-border text-muted-foreground transition-colors group-hover/add:border-primary group-hover/add:text-primary">
              <Plus className="size-3" aria-hidden />
            </span>
            <span className="text-sm text-muted-foreground/60 transition-colors group-hover/add:text-foreground">
              add an option
            </span>
          </button>
          {trailing && (
            <span className={cn("ml-auto shrink-0 pl-2")}>{trailing}</span>
          )}
        </li>
      </ul>
    </div>
  );
}

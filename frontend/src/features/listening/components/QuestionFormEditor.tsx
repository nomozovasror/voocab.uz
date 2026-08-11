import { useMemo } from "react";
import { CircleAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import { FormBuilder } from "@/features/listening/components/FormBuilder";
import { docGaps, docIssues, isDocEmpty } from "@/features/listening/form-syntax";
import type { DocBlock } from "@/features/listening/form-syntax";

interface QuestionFormEditorProps {
  doc: DocBlock[];
  onChange: (doc: DocBlock[]) => void;
  instructions: string;
  onInstructionsChange: (v: string) => void;
  wordLimit: number | null;
  onWordLimitChange: (v: number | null) => void;
  partLabel: string;
  /** Set while a publish attempt is blocked on this part, so the offending
   *  gaps are marked even if the author hadn't looked yet. */
  showIssues?: boolean;
  disabled?: boolean;
  /** Shown under the type chip — e.g. a note that a part's usual question
   *  type (map labelling, MCQ, matching…) isn't built yet and only form
   *  completion is available for it. */
  note?: string;
}

/** The rubric on the paper is one of a handful of fixed phrasings, so it's a
 *  choice rather than free text — and the stored value is the number the take
 *  page needs, not the sentence. */
const WORD_LIMITS: { value: number | null; label: string }[] = [
  { value: null, label: "no limit" },
  { value: 1, label: "one word" },
  { value: 2, label: "two words" },
  { value: 3, label: "three words" },
];

export function QuestionFormEditor({
  doc,
  onChange,
  instructions,
  onInstructionsChange,
  wordLimit,
  onWordLimitChange,
  partLabel,
  showIssues,
  disabled,
  note,
}: QuestionFormEditorProps) {
  const issues = useMemo(() => docIssues(doc), [doc]);
  const gaps = useMemo(() => docGaps(doc), [doc]);
  const touched = !isDocEmpty(doc);

  const flaggedGaps = useMemo(
    () =>
      gaps.filter((g) => !g.answers.some((a) => a.trim())).map((g) => g.number),
    [gaps],
  );

  return (
    <div className={cn(disabled && "pointer-events-none opacity-40")}>
      <div className="mb-3.5 flex items-center gap-2.5 text-xs text-muted-foreground">
        <span className="rounded-full bg-foreground/8 px-2.5 py-0.5 text-foreground">
          form completion
        </span>
        <span>{partLabel}</span>
        <span className="ml-auto tabular-nums">
          {gaps.length} {gaps.length === 1 ? "gap" : "gaps"}
        </span>
      </div>

      {note && (
        <p className="mb-3.5 rounded-md bg-foreground/6 px-3 py-2 text-[11px] text-muted-foreground">
          {note}
        </p>
      )}

      {/* The rubric, laid out the way it sits above the form on the paper:
          the instruction, then the answer-length limit under it. */}
      <div className="mb-3 space-y-1.5">
        <input
          type="text"
          value={instructions}
          onChange={(e) => onInstructionsChange(e.target.value)}
          placeholder="Complete the form below."
          aria-label="Instructions"
          className="w-full rounded-md border border-border bg-transparent px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:outline-none"
        />
        <div className="flex items-center gap-2 pl-1 text-[11px] text-muted-foreground">
          <span>write no more than</span>
          <select
            value={wordLimit === null ? "" : String(wordLimit)}
            onChange={(e) =>
              onWordLimitChange(e.target.value === "" ? null : Number(e.target.value))
            }
            aria-label="Answer length limit"
            className="rounded border border-border bg-transparent px-1.5 py-0.5 text-foreground focus-visible:border-ring focus-visible:outline-none"
          >
            {WORD_LIMITS.map((option) => (
              <option key={option.label} value={option.value ?? ""}>
                {option.label}
              </option>
            ))}
          </select>
          <span>for each answer</span>
        </div>
      </div>

      {/* No separate preview: the builder is already laid out as the form, so
          a second copy below it would only be somewhere for the two to
          disagree. */}
      <FormBuilder
        doc={doc}
        onChange={onChange}
        flaggedGaps={showIssues || touched ? flaggedGaps : []}
      />

      {(showIssues || touched) && issues.length > 0 && (
        <ul className="mt-2 space-y-1">
          {issues.map((issue) => (
            <li
              key={issue}
              className="flex items-start gap-1.5 text-[11px] text-destructive"
            >
              <CircleAlert className="mt-0.5 size-3 shrink-0" aria-hidden />
              {issue}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

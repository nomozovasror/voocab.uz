import { useMemo, useState } from "react";
import { ChevronDown, CircleAlert, SquareDashed } from "lucide-react";
import { cn } from "@/lib/utils";
import { FormBuilder } from "@/features/listening/components/FormBuilder";
import { docGaps, docPublishIssues } from "@/features/listening/form-syntax";
import { ANSWER_RUBRICS, deriveRubric } from "@/features/listening/rubric";
import type { DocBlock } from "@/features/listening/form-syntax";
import type { AnswerRubric } from "@/features/listening/types";

interface QuestionFormEditorProps {
  doc: DocBlock[];
  /** Applied against the latest document — see FormBuilder's note. */
  onChange: (edit: (current: DocBlock[]) => DocBlock[]) => void;
  instructions: string;
  onInstructionsChange: (v: string) => void;
  rubric: AnswerRubric | null;
  onRubricChange: (v: AnswerRubric | null) => void;
  /** The part this section authors, e.g. "Part 1". */
  partLabel: string;
  /** Set while a publish attempt is blocked on this part, so the offending
   *  gaps are marked even if the author hadn't looked yet. */
  showIssues?: boolean;
  markChecks?: Map<string, { found: boolean; heardAtMs: number | null }>;
  /** Where in the recording the author is pointing, for marking a gap. */
  onMarkAudio?: (
    answers: string[],
    apply: (range: { startMs: number; endMs: number }) => void,
  ) => void;
  disabled?: boolean;
  /** Shown under the header — e.g. a note that a part's usual question type
   *  (map labelling, MCQ, matching…) isn't built yet and only form completion
   *  is available for it. */
  note?: string;
}

function flaggedGapCount(gaps: { answers: string[] }[]): number {
  return gaps.filter((g) => !g.answers.some((a) => a.trim())).length;
}

export function QuestionFormEditor({
  doc,
  onChange,
  instructions,
  onInstructionsChange,
  rubric,
  onRubricChange,
  partLabel,
  showIssues,
  markChecks,
  onMarkAudio,
  disabled,
  note,
}: QuestionFormEditorProps) {
  const issues = useMemo(() => docPublishIssues(doc), [doc]);
  const gaps = useMemo(() => docGaps(doc), [doc]);

  // "No gaps yet" is true of every form the moment it's begun, so it waits
  // for a publish attempt. A gap left without an answer is a real mistake and
  // is called out as soon as it exists.
  const showsIssues =
    issues.length > 0 && (showIssues || flaggedGapCount(gaps) > 0);

  // What is selected inside a value right now. Held here rather than in the
  // builder so the offer to turn it into an answer can sit with the rubric,
  // where the other answer-level settings are.
  const [selectedText, setSelectedText] = useState("");

  /** Wraps the selection in brackets. Typed through execCommand rather than
   *  assigned: the value region reads itself back on input, so an edit it
   *  never saw would be invisible to it — and this way the browser's own undo
   *  keeps the change. */
  const markAsAnswer = () => {
    if (!selectedText) return;
    document.execCommand("insertText", false, `[${selectedText}]`);
    setSelectedText("");
  };

  // What the answers imply, offered as the default. Left on "auto" it is what
  // gets stored — the take page can't work it out for itself, since it never
  // sees the answers.
  const derived = useMemo(() => deriveRubric(doc), [doc]);
  const derivedLabel = ANSWER_RUBRICS.find((r) => r.value === derived)?.label;

  const flaggedGaps = useMemo(
    () =>
      gaps.filter((g) => !g.answers.some((a) => a.trim())).map((g) => g.number),
    [gaps],
  );

  return (
    <div className={cn(disabled && "pointer-events-none opacity-40")}>
      {/* The part leads and the question type follows it. They used to share a
          line as equals under a rule, which read as two labels rather than a
          heading — and the rule only repeated a boundary the section spacing
          already draws. */}
      <div className="mb-3 flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
        <h3 className="text-base font-medium text-foreground">{partLabel}</h3>
        <span className="ml-auto text-[11px] tabular-nums text-muted-foreground">
          {gaps.length} {gaps.length === 1 ? "question" : "questions"}
        </span>
        <span className="rounded-full bg-primary/12 px-2 py-0.5 text-[11px] text-primary">
          Form completion
        </span>
      </div>

      {note && (
        <p className="mb-3 rounded-md bg-foreground/6 px-3 py-2 text-[11px] text-muted-foreground">
          {note}
        </p>
      )}

      {/* The rubric, in the order it appears on the paper: what to do, then
          how long an answer may be. */}
      <div className="mb-3 space-y-1.5">
        <input
          type="text"
          value={instructions}
          onChange={(e) => onInstructionsChange(e.target.value)}
          placeholder="Complete the form below."
          aria-label="Instructions"
          className="w-full rounded-md border border-border bg-transparent px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:outline-none"
        />
        <label className="flex items-center gap-2 pl-1 text-xs text-muted-foreground">
          <span className="whitespace-nowrap">Answer length</span>
          {/* A native select for the behaviour — keyboard, mobile, no menu to
              reimplement — with its own chrome stripped and the app's put
              back, so it stops looking like something the browser drew. The
              open list itself is the OS's and can't be styled. */}
          <span className="relative inline-flex items-center">
            <select
              value={rubric ?? ""}
              onChange={(e) =>
                onRubricChange(
                  e.target.value === ""
                    ? null
                    : (e.target.value as AnswerRubric),
                )
              }
              aria-label="Answer length"
              className="appearance-none rounded-md border border-border bg-transparent py-1 pr-7 pl-2.5 text-xs text-foreground transition-colors hover:border-foreground/30 focus-visible:border-ring focus-visible:outline-none"
            >
              <option value="">
              {derivedLabel ? `auto — ${derivedLabel}` : "auto"}
            </option>
              {ANSWER_RUBRICS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <ChevronDown
              aria-hidden
              className="pointer-events-none absolute right-2 size-3.5 text-muted-foreground"
            />
          </span>

          {/* Only once a word is selected. The selection is named in the
              tooltip rather than in the label: spelled out inline, a long
              phrase pushed this row onto two lines. */}
          {selectedText && (
            <button
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={markAsAnswer}
              title={`Mark “${selectedText}” as the answer`}
              className="flex shrink-0 items-center gap-1.5 rounded-md bg-primary/15 px-2 py-1 whitespace-nowrap text-primary transition-colors hover:bg-primary/25"
            >
              <SquareDashed className="size-3.5 shrink-0" aria-hidden />
              Mark as answer
            </button>
          )}
        </label>
      </div>

      {/* No separate preview: the builder is already laid out as the form, so
          a second copy below it would only be somewhere for the two to
          disagree. */}
      <FormBuilder
        doc={doc}
        onChange={onChange}
        flaggedGaps={flaggedGaps}
        markChecks={markChecks}
        onSelectionChange={setSelectedText}
        onMarkAudio={onMarkAudio}
      />

      {showsIssues && (
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

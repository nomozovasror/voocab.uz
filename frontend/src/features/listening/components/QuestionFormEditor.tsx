import { useRef, useState } from "react";
import { Plus, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { FormRow } from "@/features/listening/template";

const inputBase =
  "bg-transparent font-mono text-foreground placeholder:text-muted-foreground outline-none";

interface QuestionFormEditorProps {
  rows: FormRow[];
  onChange: (rows: FormRow[]) => void;
  instructions: string;
  onInstructionsChange: (v: string) => void;
  partLabel: string;
  badRowIndex: number | null;
  disabled?: boolean;
  /** Shown under the type chip — e.g. a note that a part's usual question
   *  type (map labelling, MCQ, matching…) isn't built yet and only form
   *  completion is available for it. */
  note?: string;
}

export function QuestionFormEditor({
  rows,
  onChange,
  instructions,
  onInstructionsChange,
  partLabel,
  badRowIndex,
  disabled,
  note,
}: QuestionFormEditorProps) {
  const [focusedRow, setFocusedRow] = useState<number | null>(null);
  const altRefs = useRef<Record<string, HTMLInputElement | null>>({});

  const patchRow = (i: number, patch: Partial<FormRow>) =>
    onChange(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));

  const setAnswer = (i: number, j: number, value: string) =>
    patchRow(i, {
      answers: rows[i].answers.map((a, idx) => (idx === j ? value : a)),
    });

  const addAlt = (i: number) => {
    patchRow(i, { answers: [...rows[i].answers, ""] });
    const key = `${i}-${rows[i].answers.length}`;
    requestAnimationFrame(() => altRefs.current[key]?.focus());
  };

  const removeAlt = (i: number, j: number) =>
    patchRow(i, { answers: rows[i].answers.filter((_, idx) => idx !== j) });

  const addRow = () => onChange([...rows, { label: "", answers: [""] }]);

  const removeRow = (i: number) => onChange(rows.filter((_, idx) => idx !== i));

  const fromTranscript = (i: number) => {
    const text = window.getSelection()?.toString().trim();
    if (text) setAnswer(i, 0, text);
  };

  return (
    <div className={cn(disabled && "pointer-events-none opacity-40")}>
      <div className="mb-3.5 flex items-center gap-2.5 text-xs text-muted-foreground">
        <span className="rounded-full bg-foreground/8 px-2.5 py-0.5 text-foreground">
          form completion
        </span>
        <span>{partLabel}</span>
      </div>

      {note && (
        <p className="mb-3.5 rounded-md bg-foreground/6 px-3 py-2 text-[11px] text-muted-foreground">
          {note}
        </p>
      )}

      <input
        type="text"
        value={instructions}
        onChange={(e) => onInstructionsChange(e.target.value)}
        placeholder="complete the form below. write no more than three words and/or a number for each answer."
        aria-label="Instructions"
        className={cn(
          inputBase,
          "mb-4.5 w-full rounded-md border border-border px-3 py-2 text-sm focus-visible:border-ring",
        )}
      />

      <div className="grid grid-cols-[auto_1fr] items-baseline gap-x-4.5 gap-y-3.5 rounded-lg bg-card px-5 py-4.5">
        {rows.map((row, i) => (
          <div key={i} className="group contents">
            <div>
              <label className="sr-only" htmlFor={`field-label-${i}`}>
                Field label {i + 1}
              </label>
              <input
                id={`field-label-${i}`}
                type="text"
                value={row.label}
                onChange={(e) => patchRow(i, { label: e.target.value })}
                placeholder="field"
                className={cn(inputBase, "w-full text-sm text-muted-foreground")}
              />
            </div>

            <div className="flex flex-wrap items-baseline gap-2.5">
              <span className="text-[11px] text-muted-foreground">{i + 1}</span>
              <input
                type="text"
                value={row.answers[0] ?? ""}
                onChange={(e) => setAnswer(i, 0, e.target.value)}
                onFocus={() => setFocusedRow(i)}
                onBlur={() => setFocusedRow((v) => (v === i ? null : v))}
                placeholder="answer"
                aria-label={`Answer ${i + 1}`}
                aria-invalid={badRowIndex === i}
                className={cn(
                  inputBase,
                  "min-w-36 flex-1 border-b-2 border-border px-0.5 pb-0.5 text-sm focus:border-primary",
                  badRowIndex === i && "border-destructive",
                )}
              />

              {row.answers.slice(1).map((alt, j) => (
                <span key={j} className="inline-flex items-center gap-1">
                  <input
                    ref={(el) => {
                      altRefs.current[`${i}-${j + 1}`] = el;
                    }}
                    type="text"
                    value={alt}
                    onChange={(e) => setAnswer(i, j + 1, e.target.value)}
                    onFocus={() => setFocusedRow(i)}
                    onBlur={() => setFocusedRow((v) => (v === i ? null : v))}
                    placeholder="alt answer"
                    aria-label={`Alternative answer ${j + 1} for gap ${i + 1}`}
                    className={cn(
                      inputBase,
                      "w-24 border-b-2 border-border px-0.5 pb-0.5 text-xs focus:border-primary",
                    )}
                  />
                  <button
                    type="button"
                    onClick={() => removeAlt(i, j + 1)}
                    aria-label={`Remove alternative answer ${j + 1} for gap ${i + 1}`}
                    className="text-muted-foreground hover:text-destructive"
                  >
                    <X className="size-3" />
                  </button>
                </span>
              ))}

              {focusedRow === i && (
                <button
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => fromTranscript(i)}
                  className="text-[11px] text-muted-foreground hover:text-primary"
                >
                  ⤺ from transcript
                </button>
              )}

              <button
                type="button"
                onClick={() => addAlt(i)}
                className="text-[11px] text-muted-foreground hover:text-foreground"
              >
                + alt{row.answers.length > 1 ? ` · ${row.answers.length - 1}` : ""}
              </button>

              <button
                type="button"
                onClick={() => removeRow(i)}
                aria-label={`Remove field ${i + 1}`}
                className="ml-auto text-muted-foreground opacity-0 hover:text-destructive focus-visible:opacity-100 group-hover:opacity-100"
              >
                <X className="size-3.5" />
              </button>
            </div>
          </div>
        ))}
      </div>

      <button
        type="button"
        onClick={addRow}
        className="mt-3.5 w-full rounded-md border border-dashed border-border px-3.5 py-2.5 text-left text-xs text-muted-foreground transition-colors hover:border-primary hover:text-foreground"
      >
        <Plus className="mr-1 inline size-3" aria-hidden />
        add field
      </button>
    </div>
  );
}

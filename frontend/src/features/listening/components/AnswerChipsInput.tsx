import { useId, useState, type KeyboardEvent } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

interface AnswerChipsInputProps {
  label: string;
  value: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  /** Shown under the field when non-empty (e.g. a validation message). */
  error?: string;
}

/** A "type + Enter" multi-value chip input for accepted answers per gap.
 *  Fully keyboard-operable: Enter/comma commits the pending value, Backspace
 *  on an empty field pops the last chip, and every chip has its own
 *  focusable remove button. */
export function AnswerChipsInput({
  label,
  value,
  onChange,
  placeholder,
  error,
}: AnswerChipsInputProps) {
  const [draft, setDraft] = useState("");
  const inputId = useId();
  const errorId = useId();

  const commit = () => {
    const trimmed = draft.trim();
    if (!trimmed) {
      setDraft("");
      return;
    }
    if (!value.includes(trimmed)) onChange([...value, trimmed]);
    setDraft("");
  };

  const removeAt = (i: number) => onChange(value.filter((_, idx) => idx !== i));

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      commit();
    } else if (e.key === "Backspace" && draft === "" && value.length > 0) {
      removeAt(value.length - 1);
    }
  };

  return (
    <div className="space-y-1.5">
      <label htmlFor={inputId} className="text-sm font-medium text-foreground">
        {label}
      </label>
      <div
        className={cn(
          "flex flex-wrap items-center gap-1.5 rounded-md border border-border bg-background p-1.5 focus-within:ring-2 focus-within:ring-ring",
          error && "border-destructive",
        )}
      >
        {value.map((answer, i) => (
          <span
            key={`${answer}-${i}`}
            className="inline-flex items-center gap-1 rounded-full bg-primary/10 py-0.5 pr-1 pl-2 text-xs text-primary"
          >
            {answer}
            <button
              type="button"
              onClick={() => removeAt(i)}
              className="rounded-full p-0.5 hover:bg-primary/20 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              aria-label={`Remove answer "${answer}"`}
            >
              <X className="size-3" />
            </button>
          </span>
        ))}
        <input
          id={inputId}
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={commit}
          placeholder={value.length === 0 ? placeholder : "Add another…"}
          className="min-w-32 flex-1 bg-transparent px-1 py-0.5 text-sm text-foreground placeholder:text-muted-foreground outline-none"
          aria-describedby={error ? errorId : undefined}
          aria-invalid={!!error}
        />
      </div>
      {error && (
        <p id={errorId} className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

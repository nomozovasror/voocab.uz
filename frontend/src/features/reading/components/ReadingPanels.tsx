import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { helpFor } from "@/features/reading/help";
import { LOOKUP_BUDGET } from "@/features/reading/lookups";
import type { QuestionGroupType } from "@/features/paper/types";
import type { Selected } from "@/features/reading/selection";

/**
 * The three small panels the tools open, and what each one is careful about.
 *
 * All of them hang under the header rather than over the passage. A panel
 * covering the prose is a panel that hides the thing it is about — the word
 * being looked up, the sentence being annotated, the question the help is
 * explaining — and a reader then has to close it to use what it told them.
 */

function Panel({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  useEffect(() => {
    const escape = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [onClose]);

  return (
    <aside className="absolute top-19 right-4 z-40 w-80 rounded-xl border border-border bg-card p-4 shadow-lg sm:right-6">
      <header className="mb-2 flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold text-foreground">{title}</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="rounded-md p-0.5 text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          <X className="size-3.5" aria-hidden />
        </button>
      </header>
      {children}
    </aside>
  );
}

/**
 * What this kind of question asks for.
 *
 * Follows the group the reader is IN, because advice about matching
 * headings while somebody is filling a summary is worse than none: they
 * asked the page a question and it answered a different one. Three lines,
 * and the reasons for each are in `features/reading/help.ts`.
 */
export function HelpPanel({
  type,
  onClose,
}: {
  type: QuestionGroupType | null;
  onClose: () => void;
}) {
  const help = helpFor(type);
  if (!help) return null;
  return (
    <Panel title="What to do here" onClose={onClose}>
      <dl className="space-y-2.5 text-xs leading-relaxed">
        <div>
          <dt className="sr-only">The task</dt>
          <dd className="text-foreground">{help.do}</dd>
        </div>
        <div>
          <dt className="mb-0.5 text-[0.7rem] tracking-caps text-muted-foreground uppercase">
            Watch for
          </dt>
          <dd className="text-muted-foreground">{help.rule}</dd>
        </div>
        <div>
          <dt className="mb-0.5 text-[0.7rem] tracking-caps text-muted-foreground uppercase">
            Technique
          </dt>
          <dd className="text-muted-foreground">{help.tip}</dd>
        </div>
      </dl>
    </Panel>
  );
}

/**
 * A note on a stretch of the passage.
 *
 * Opens with whatever is already there, so pressing Note on a stretch that
 * has one is editing it rather than starting again — and an empty box
 * REMOVES the note, which is the only gesture anybody looks for.
 */
export function NotePanel({
  at,
  existing,
  onSave,
  onClose,
}: {
  at: Selected;
  existing: string;
  onSave: (text: string) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState(existing);
  const box = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => box.current?.focus(), []);

  return (
    <Panel title="Note" onClose={onClose}>
      <p className="mb-2 line-clamp-2 border-l-2 border-mark-key pl-2 text-xs text-muted-foreground italic">
        {at.text}
      </p>
      <textarea
        ref={box}
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={3}
        placeholder="What did you notice?"
        className="w-full resize-none rounded-lg border border-border bg-background px-2.5 py-2 text-xs text-foreground placeholder:text-muted-foreground focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        onKeyDown={(e) => {
          // Enter saves, shift+enter breaks the line. A note is a sentence,
          // not a document.
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            onSave(text.trim());
          }
        }}
      />
      <div className="mt-2 flex items-center justify-end gap-2">
        <Button variant="ghost" size="xs" onClick={onClose}>
          Cancel
        </Button>
        <Button size="xs" onClick={() => onSave(text.trim())}>
          {text.trim() ? "Save" : existing ? "Remove" : "Save"}
        </Button>
      </div>
    </Panel>
  );
}

/**
 * A word the reader spent one of their three on.
 *
 * The dictionary itself is a separate piece of work; what exists here is the
 * budget and the states around it, which are the parts that have to be right
 * before any definition is worth fetching. Saying so plainly beats a panel
 * that pretends to be looking something up.
 */
export function LookupPanel({
  word,
  spent,
  onClose,
}: {
  word: string;
  spent: number;
  onClose: () => void;
}) {
  return (
    <Panel title={word} onClose={onClose}>
      <p className="text-xs text-muted-foreground">
        No dictionary is connected yet, so there is nothing to show for this
        one.
      </p>
      <p className="mt-2 text-[0.7rem] text-muted-foreground">
        {spent} of {LOOKUP_BUDGET} used on this passage. Looking the same word
        up again is free.
      </p>
    </Panel>
  );
}

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { getErrorMessage } from "@/lib/api";
import { toast } from "@/lib/toast";
import { vocabularyApi } from "@/features/vocabulary/api";
import type { TranslationReportWhere } from "@/features/vocabulary/types";

const NOTE_MAX = 500;

/**
 * "This translation is wrong" — a quiet link, never a modal, on the two
 * screens the spec names: the word page and the practice reveal. Not the
 * lookup popover, on purpose — that screen is spending one of a reader's
 * three look-ups on a first glance at a word, not judging one it has
 * barely had time to read.
 *
 * One report per (learner, sense) stays open on the server; a second press
 * here is a no-op 200, so this never checks first and never disables itself
 * once sent — pressing it again just says thanks again.
 */
export function ReportTranslation({
  senseId,
  where,
  className,
}: {
  senseId: string;
  where: TranslationReportWhere;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [sent, setSent] = useState(false);

  const report = useMutation({
    mutationFn: () =>
      vocabularyApi.translationReport({
        sense_id: senseId,
        where,
        note: note.trim() || undefined,
      }),
    onSuccess: () => {
      setSent(true);
      setOpen(false);
    },
    onError: (e) => toast(getErrorMessage(e)),
  });

  if (sent) {
    return (
      <p className={cn("text-[0.7rem] text-muted-foreground", className)}>
        Thanks — we&apos;ll check it.
      </p>
    );
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn(
          "text-[0.7rem] text-muted-foreground underline-offset-2 transition-colors hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:rounded-sm focus-visible:outline-none",
          className,
        )}
      >
        This translation is wrong
      </button>
    );
  }

  return (
    <form
      className={cn("space-y-1.5", className)}
      onSubmit={(e) => {
        e.preventDefault();
        report.mutate();
      }}
    >
      <textarea
        value={note}
        onChange={(e) => setNote(e.target.value)}
        maxLength={NOTE_MAX}
        rows={2}
        autoFocus
        placeholder="Anything to add? (optional)"
        // Stopped from bubbling rather than left to the practice page's own
        // document-level hotkeys: Enter there means "advance to the next
        // word" once a reveal is showing, which is exactly where this form
        // lives, and typing a note must not double as leaving it. Enter on
        // its own submits (shift+Enter breaks the line) — the app's own
        // pattern, see `NotePanel`; Escape cancels the form rather than
        // exiting the whole session.
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            e.stopPropagation();
            report.mutate();
          } else if (e.key === "Enter" || e.key === "Escape") {
            e.stopPropagation();
            if (e.key === "Escape") {
              setOpen(false);
              setNote("");
            }
          }
        }}
        className="w-full resize-none rounded-lg border border-border bg-background px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      />
      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={() => {
            setOpen(false);
            setNote("");
          }}
          className="text-[0.7rem] text-muted-foreground transition-colors hover:text-foreground"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={report.isPending}
          className="rounded-md bg-surface-hover px-2 py-1 text-[0.7rem] text-foreground transition-colors duration-fast hover:bg-foreground/15 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-50"
        >
          {report.isPending ? "Sending…" : "Send"}
        </button>
      </div>
    </form>
  );
}

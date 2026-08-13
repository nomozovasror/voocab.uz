import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { Visibility } from "@/features/listening/types";

/**
 * Asking before deleting a material.
 *
 * The question is not "are you sure" — nobody reads that — it is what
 * specifically is about to go. A material is rarely just a material: it may
 * be public, and it may have been sat, in which case deleting it takes
 * everyone's attempt and score with it. Both callers know enough to say so,
 * so the dialog says it instead of warning in general terms.
 *
 * There is no undo to offer. The server deletes for real, in one
 * transaction, and an "undo" toast that couldn't put the attempts back would
 * be a promise this can't keep.
 */

/** The facts the question is built from — not a list row and not a material
 *  detail, since it is asked from both. */
export interface DeletableMaterial {
  title: string;
  visibility: Visibility;
  questionCount: number;
  /** How many people have sat it, where that is known. Null means nobody has
   *  counted — the editor has no attempt count of its own — and the warning
   *  falls back to naming attempts without numbering them. */
  attempts: number | null;
}

interface DeleteMaterialDialogProps {
  /** The material to delete, or null when the dialog is closed. Held as the
   *  facts rather than an id so the title and counts stay on screen through
   *  the closing animation, instead of blanking as the row goes. */
  material: DeletableMaterial | null;
  onCancel: () => void;
  onConfirm: () => void;
  deleting?: boolean;
}

/** What goes with it, worst first, and only what is true of this one. */
function consequences(material: DeletableMaterial): string[] {
  const lines: string[] = [];
  if (material.attempts === null) {
    lines.push("Any attempts on it, and the scores, are deleted too.");
  } else if (material.attempts > 0) {
    lines.push(
      `${material.attempts} ${material.attempts === 1 ? "attempt" : "attempts"} ` +
        "on it, and the scores, are deleted too.",
    );
  }
  if (material.visibility === "public") {
    lines.push("It's public — anyone holding the link will find nothing there.");
  }
  if (material.questionCount > 0) {
    lines.push(
      `${material.questionCount} ${
        material.questionCount === 1 ? "question" : "questions"
      } and the audio you attached go with it.`,
    );
  }
  return lines;
}

export function DeleteMaterialDialog({
  material,
  onCancel,
  onConfirm,
  deleting,
}: DeleteMaterialDialogProps) {
  return (
    <Dialog
      open={material !== null}
      onOpenChange={(open) => {
        // Never while the request is in flight: the row would come back
        // under the pointer and then vanish a moment later anyway.
        if (!open && !deleting) onCancel();
      }}
    >
      <DialogContent className="modal-stagger gap-5 p-6 font-mono duration-200 sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-base font-medium">
            Delete “{material?.title}”?
          </DialogTitle>
          <DialogDescription className="text-xs">
            This can't be undone.
          </DialogDescription>
        </DialogHeader>

        {material && consequences(material).length > 0 && (
          <ul className="space-y-1.5 text-xs leading-relaxed text-muted-foreground">
            {consequences(material).map((line) => (
              <li key={line} className="flex gap-2">
                <span aria-hidden className="text-muted-foreground/60">
                  –
                </span>
                {line}
              </li>
            ))}
          </ul>
        )}

        <div className="flex justify-end gap-2">
          <Button
            variant="outline"
            size="sm"
            className="font-mono lowercase"
            onClick={onCancel}
            disabled={deleting}
          >
            cancel
          </Button>
          <Button
            variant="destructive"
            size="sm"
            className="font-mono lowercase"
            onClick={onConfirm}
            disabled={deleting}
          >
            {deleting && <Loader2 className="size-4 animate-spin" />}
            delete
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

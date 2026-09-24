import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/**
 * Asking before a BULK delete — same pattern as
 * `components/studio/DeleteMaterialDialog.tsx`, and for the same reason: more
 * than one word is a batch a learner cannot see all of at once, so the
 * question names how many rather than asking "are you sure" about a list
 * that just left the screen.
 *
 * Deleting exactly ONE word never opens this. It gets the cheaper answer —
 * the row itself turns into "Removed · Undo" for a few seconds
 * (`pendingDelete.ts`) — because a single, reversible action does not need
 * a modal in front of it. Undo doesn't scale to a batch a dialog already
 * asked about, and a batch would be defeating the dialog to reintroduce it.
 */

interface DeleteWordsDialogProps {
  /** Null closes the dialog. Held as the count itself rather than the
   *  selection, so the number on screen doesn't change out from under the
   *  reader mid-animation if the selection is cleared the instant the
   *  request lands. */
  count: number | null;
  onCancel: () => void;
  onConfirm: () => void;
  deleting?: boolean;
}

export function DeleteWordsDialog({
  count,
  onCancel,
  onConfirm,
  deleting,
}: DeleteWordsDialogProps) {
  return (
    <Dialog
      open={count !== null}
      onOpenChange={(open) => {
        // Never while the request is in flight — same reason
        // `DeleteMaterialDialog` refuses it: the count would sit under the
        // pointer and then vanish a moment later anyway.
        if (!open && !deleting) onCancel();
      }}
    >
      <DialogContent className="gap-5 sm:max-w-sm">
        <DialogHeader>
          <DialogTitle className="text-base font-medium">
            Delete {count} words?
          </DialogTitle>
          <DialogDescription className="text-xs">
            Their history stays; the words don&apos;t. This can&apos;t be
            undone.
          </DialogDescription>
        </DialogHeader>

        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onCancel} disabled={deleting}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={onConfirm}
            disabled={deleting}
          >
            {deleting && <Loader2 className="size-4 animate-spin" aria-hidden />}
            Delete
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

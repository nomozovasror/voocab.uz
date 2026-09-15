import { useEffect, useState } from "react";
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
 * Naming a collection, before there is one.
 *
 * Creating one takes a title and nothing else — an author starts by naming
 * the thing they are about to build, and a create form that demanded its
 * contents up front is a form nobody could fill in. One field is not a page,
 * so it is asked for here and the author is put straight into the collection
 * afterwards: naming a course is not the thing they came to do.
 *
 * Presentational on purpose, like the delete dialog beside it: the page owns
 * the mutation and decides where the author lands, so the dialog cannot be
 * the reason those two disagree.
 */
export function NewCollectionDialog({
  open,
  onOpenChange,
  onCreate,
  creating,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (title: string) => void;
  creating?: boolean;
}) {
  const [title, setTitle] = useState("");

  // Emptied on the way out rather than on the way in, so a failed create
  // leaves what was typed on screen — the dialog stays open on failure, and
  // clearing the field would be the page taking the author's words back.
  useEffect(() => {
    if (!open) setTitle("");
  }, [open]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const name = title.trim();
    if (!name || creating) return;
    onCreate(name);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        // Never while the request is in flight: the collection would be
        // created into a dialog that had already gone.
        if (!next && creating) return;
        onOpenChange(next);
      }}
    >
      <DialogContent className="modal-stagger gap-5 p-6 font-mono duration-200 sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-base font-medium">
            New collection
          </DialogTitle>
          <DialogDescription className="text-xs">
            An order to work through. You put the materials in next.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} className="flex flex-col gap-5">
          <input
            // The one field, focused on open — a dialog asking for a name
            // that has to be clicked into first is a dialog with a step in it
            // nobody wanted.
            autoFocus
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            aria-label="Collection title"
            placeholder="part 1 from scratch"
            maxLength={200}
            className="w-full rounded-lg border border-border bg-card px-3 py-2 font-mono text-sm text-foreground placeholder:text-muted-foreground/70 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40 focus-visible:outline-none"
          />

          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="font-mono lowercase"
              onClick={() => onOpenChange(false)}
              disabled={creating}
            >
              cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              className="font-mono lowercase"
              disabled={!title.trim() || creating}
            >
              {creating && <Loader2 className="size-4 animate-spin" />}
              create
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

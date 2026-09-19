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
import { LISTENING, READING } from "@/features/paper/skill";
import type { Skill } from "@/features/paper/skill";
import { cn } from "@/lib/utils";

//: In the order the studio's own tabs name them, so the two cannot come to
//: disagree about which exam is first.
const SKILLS = [LISTENING, READING];

/**
 * Naming a collection, before there is one.
 *
 * Creating one takes a title and which exam it is a course in, and nothing
 * else — an author starts by naming the thing they are about to build, and a
 * create form that demanded its contents up front is a form nobody could
 * fill in. Two decisions are not a page, so they are asked for here and the
 * author is put straight into the collection afterwards: naming a course is
 * not the thing they came to do.
 *
 * **The exam is asked HERE because it can never be asked again.** A
 * collection is a sequence through one paper — `next_material_id` is the
 * first of its items the learner has not sat, and the picker that fills it
 * offers that paper's catalogue — so a course that changed exam would be a
 * course whose order had stopped meaning anything. The server takes `skill`
 * on create and on nothing else.
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
  onCreate: (title: string, skill: Skill["id"]) => void;
  creating?: boolean;
}) {
  const [title, setTitle] = useState("");
  const [skill, setSkill] = useState<Skill["id"]>("listening");

  // Emptied on the way out rather than on the way in, so a failed create
  // leaves what was typed on screen — the dialog stays open on failure, and
  // clearing the field would be the page taking the author's words back.
  useEffect(() => {
    if (!open) {
      setTitle("");
      setSkill("listening");
    }
  }, [open]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const name = title.trim();
    if (!name || creating) return;
    onCreate(name, skill);
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

          {/* Two positions, one switch — the same control the studio tabs
              are, for the same reason: two buttons with one shaded is a pair
              of buttons where one happens to be on. It sits under the title
              because it is the second thing decided and the first thing that
              cannot be undone. */}
          <div
            role="radiogroup"
            aria-label="Which exam"
            className="flex rounded-lg border border-border bg-muted/40 p-0.5"
          >
            {SKILLS.map((one) => (
              <button
                key={one.id}
                type="button"
                role="radio"
                aria-checked={skill === one.id}
                onClick={() => setSkill(one.id)}
                disabled={creating}
                className={cn(
                  "flex-1 rounded-md px-3 py-1.5 font-mono text-xs lowercase transition-colors",
                  skill === one.id
                    ? "bg-card text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {one.name}
              </button>
            ))}
          </div>

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

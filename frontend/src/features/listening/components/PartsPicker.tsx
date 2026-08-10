import { ClipboardList, Layers, ListChecks, Map, NotebookPen } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface PickerPart {
  n: 1 | 2 | 3 | 4;
  available: boolean;
  blurb: string;
  icon: LucideIcon;
}

// Only form completion is built — Part 1 and Part 4 are typically form/note
// completion in IELTS Listening, so they're the only single-part starting
// points offered. Part 2 (map/plan labelling) and Part 3 (MCQ, matching)
// aren't authorable yet; say so plainly rather than let someone pick a part
// we can't grade. Each icon names that part's characteristic question type,
// so the row reads as information rather than decoration.
const PICKER_PARTS: PickerPart[] = [
  { n: 1, available: true, blurb: "Form completion", icon: ClipboardList },
  { n: 2, available: false, blurb: "Map / plan labelling — soon", icon: Map },
  { n: 3, available: false, blurb: "Multiple choice, matching — soon", icon: ListChecks },
  { n: 4, available: true, blurb: "Note completion", icon: NotebookPen },
];

interface PartsPickerProps {
  /** 0-based order indices to seed as new, empty parts. */
  onPick: (orderIndices: number[]) => void;
}

/** The step before the editor at /studio/listening/new. Picking doesn't touch
 *  the API: it only seeds the editor's local part state, and everything gets
 *  created for real on the first autosave like the rest of the editor. */
export function PartsPicker({ onPick }: PartsPickerProps) {
  return (
    <div className="modal-stagger w-full">
      {/* The whole test leads — it's the common case, and it makes the single
          parts below read as the narrower choice. It goes solid on hover,
          against the parts' dashed edge, so the two kinds of choice stay
          visually distinct. */}
      <button
        type="button"
        onClick={() => onPick([0, 1, 2, 3])}
        className="flex w-full items-center gap-3.5 rounded-lg border border-dashed border-border px-4 py-4 text-left text-muted-foreground transition-colors hover:border-solid hover:border-primary hover:text-foreground focus-visible:border-solid focus-visible:border-primary focus-visible:outline-none"
      >
        <Layers className="size-5 shrink-0 text-primary" aria-hidden />
        <span>
          <span className="block text-foreground">Full test</span>
          <span className="mt-1 block text-xs text-muted-foreground">
            Seed all four parts — audio and questions added per part
          </span>
        </span>
      </button>

      <div className="modal-stagger mt-3 grid grid-cols-2 gap-3">
        {PICKER_PARTS.map((p) => {
          const Icon = p.icon;
          return (
            <button
              key={p.n}
              type="button"
              disabled={!p.available}
              onClick={() => onPick([p.n - 1])}
              aria-disabled={!p.available}
              className={cn(
                "flex items-start gap-3 rounded-lg border border-dashed px-4 py-4 text-left transition-colors",
                p.available
                  ? "border-border text-muted-foreground hover:border-primary hover:text-foreground focus-visible:border-primary focus-visible:outline-none"
                  : "cursor-default border-border/50 text-muted-foreground opacity-50",
              )}
            >
              <Icon
                className={cn(
                  "mt-0.5 size-4 shrink-0",
                  p.available ? "text-primary" : "text-muted-foreground",
                )}
                aria-hidden
              />
              <span className="min-w-0">
                <span className="flex items-center gap-2">
                  <span className="text-foreground">Part {p.n}</span>
                  {!p.available && (
                    <span className="rounded-full bg-foreground/8 px-2 py-0.5 text-[10px] font-bold tracking-wider text-muted-foreground uppercase">
                      soon
                    </span>
                  )}
                </span>
                <span className="mt-1 block text-[11px] text-muted-foreground">
                  {p.blurb}
                </span>
              </span>
            </button>
          );
        })}
      </div>

      <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
        Start with a single part, or seed the full test — parts can be added or
        removed later.
      </p>
    </div>
  );
}

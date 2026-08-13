import { ClipboardList, Layers, ListChecks, Map, NotebookPen } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {
  QUESTION_TYPE_LABEL,
  questionTypesForPart,
} from "@/features/listening/parts";

interface PickerPart {
  n: 1 | 2 | 3 | 4;
  icon: LucideIcon;
}

// Only the part is chosen here. What kind of questions go in it is decided in
// the editor, where it can be offered per part — Part 1 is a completion task
// and nothing else, so it is never asked the question at all
// (features/listening/parts.ts).
//
// The icon names what the part is known for, which is not always what we can
// author yet: Part 2's is map/plan labelling, still to be built. The blurb
// underneath is what it can actually be given, read from the same table the
// editor offers, so the two can't come to disagree.
const PICKER_PARTS: PickerPart[] = [
  { n: 1, icon: ClipboardList },
  { n: 2, icon: Map },
  { n: 3, icon: ListChecks },
  { n: 4, icon: NotebookPen },
];

/** "Multiple choice, form completion" — the types this part can be given, in
 *  the order it is offered them, as one line of prose. */
function availableTypes(n: number): string {
  return questionTypesForPart(n - 1)
    .map((type, index) => {
      const label = QUESTION_TYPE_LABEL[type];
      return index === 0 ? label : label.toLowerCase();
    })
    .join(", ");
}

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
              onClick={() => onPick([p.n - 1])}
              className="flex items-start gap-3 rounded-lg border border-dashed border-border px-4 py-4 text-left text-muted-foreground transition-colors hover:border-primary hover:text-foreground focus-visible:border-primary focus-visible:outline-none"
            >
              <Icon className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
              <span className="min-w-0">
                <span className="block text-foreground">Part {p.n}</span>
                <span className="mt-1 block text-xs text-muted-foreground">
                  {availableTypes(p.n)}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

import {
  QUESTION_TYPE_BLURB,
  QUESTION_TYPE_ICON,
  QUESTION_TYPE_LABEL,
} from "@/features/listening/parts";
import type { QuestionGroupType } from "@/features/listening/types";

/**
 * The question "what kind?", as a row of cards.
 *
 * It is asked in two places — once for each part as the material is opened
 * (EditorSetup), and again for any group added later (GroupTypeChooser) —
 * and it has to look like the same question both times. Kept here so it is
 * literally the same one.
 */

interface QuestionTypeChoicesProps {
  types: QuestionGroupType[];
  onChoose: (type: QuestionGroupType) => void;
}

export function QuestionTypeChoices({
  types,
  onChoose,
}: QuestionTypeChoicesProps) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {types.map((type) => {
        const Icon = QUESTION_TYPE_ICON[type];
        return (
          <button
            key={type}
            type="button"
            onClick={() => onChoose(type)}
            className="flex items-start gap-3 rounded-lg border border-border px-4 py-3 text-left transition-colors hover:border-primary hover:bg-foreground/[0.03] focus-visible:border-primary focus-visible:outline-none"
          >
            <Icon className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
            <span className="min-w-0">
              <span className="block text-sm text-foreground">
                {QUESTION_TYPE_LABEL[type]}
              </span>
              <span className="mt-1 block text-xs text-muted-foreground">
                {QUESTION_TYPE_BLURB[type]}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

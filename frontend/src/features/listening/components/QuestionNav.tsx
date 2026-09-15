import { useCallback, useRef } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { answeredIn, type PaperPart } from "@/features/listening/take-paper";

/**
 * The strip along the bottom: every question on the paper, at once.
 *
 * Lifted from the real computer-delivered IELTS, and for the three reasons it
 * is there. It says which questions are answered without scrolling the paper;
 * it is the fastest way to any of them; and it is the interface a candidate
 * will sit the real test in front of — a practice page that teaches the exam's
 * furniture is doing part of the job.
 *
 * Fixed rather than sticky, because the one thing it must never do is leave.
 * A forty-question paper is four screens long, and a submit button at the
 * bottom of it is a submit button nobody can find.
 *
 * The parts WRAP rather than being dealt into two fixed rows. Forty questions
 * across four parts comes out as two rows on a normal window, which is what
 * the design asks for — but a single-part material has one part, and a rule
 * that always draws two rows would draw an empty one under it.
 */

interface QuestionNavProps {
  parts: PaperPart[];
  answers: Record<string, string>;
  flagged: Set<string>;
  /** The question being worked on — see take-focus.ts. */
  current: string | null;
  onGo: (questionId: string) => void;
  onSubmit: () => void;
  submitLabel: string;
  /** How many of the paper's numbers are answered, out of how many there are.
   *
   *  Here rather than at the top of the page, and not only because there is
   *  no room up there any more: forty coloured squares say WHICH are answered
   *  and counting them is work. The figure is the answer to the question the
   *  squares raise, and it belongs beside them. */
  answered: number;
  total: number;
  submitting?: boolean;
  /** How many numbers are still blank, and whether the page is waiting for an
   *  answer about them. */
  blank: number;
  confirming: boolean;
  onKeepWorking: () => void;
  ref?: React.Ref<HTMLDivElement>;
}

interface Cell {
  n: number;
  id: string;
  answered: boolean;
}

/** One button per NUMBER, not per question. A "choose TWO letters" is printed
 *  as two numbers on the paper and carries two marks, so it is two boxes here
 *  — and with one letter picked the first is answered and the second is not,
 *  which is the same arithmetic the header counts with. */
function cellsOf(part: PaperPart, answers: Record<string, string>): Cell[] {
  return part.rows.flatMap((row) => {
    const done = answeredIn(row, answers[row.id]);
    return Array.from({ length: row.span }, (_, k) => ({
      n: row.number + k,
      id: row.id,
      answered: k < done,
    }));
  });
}

export function QuestionNav({
  parts,
  answers,
  flagged,
  current,
  onGo,
  onSubmit,
  submitLabel,
  answered,
  total,
  submitting,
  blank,
  confirming,
  onKeepWorking,
  ref,
}: QuestionNavProps) {
  const cells = useRef<Array<HTMLButtonElement | null>>([]);
  const flat = parts.flatMap((part) => cellsOf(part, answers));

  // Roving focus. Forty tab stops between the paper and the submit button
  // would make Tab useless for anything else, so the strip is one stop and
  // the arrows move inside it — the same bargain a toolbar makes.
  const move = useCallback((from: number, by: number) => {
    const buttons = cells.current.filter(Boolean);
    const to = Math.max(0, Math.min(from + by, buttons.length - 1));
    buttons[to]?.focus();
  }, []);

  const currentIndex = Math.max(
    0,
    flat.findIndex((cell) => cell.id === current),
  );

  let index = -1;

  return (
    <div
      ref={ref}
      className="fixed inset-x-0 bottom-0 z-sticky border-t border-border bg-card"
    >
      {/* The warning lives here rather than beside the button because it is
          about the paper, not about the button: "three questions are blank"
          is answered by going back to them, and the strip that gets you there
          is directly underneath. */}
      {confirming && (
        <div className="mx-auto flex w-full max-w-7xl items-center gap-3 border-b border-border-subtle px-4 py-2 sm:px-6 lg:px-8">
          <p className="min-w-0 flex-1 text-sm text-attention">
            {blank} {blank === 1 ? "answer is" : "answers are"} still blank.
            Check anyway?
          </p>
          <button
            type="button"
            onClick={onKeepWorking}
            className="shrink-0 rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors duration-fast hover:bg-surface-hover hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            Keep working
          </button>
        </div>
      )}

      <div className="mx-auto flex w-full max-w-7xl items-center gap-4 px-4 py-2.5 sm:px-6 lg:px-8">
        <div
          role="group"
          aria-label="Questions on this paper"
          className="flex min-w-0 flex-1 flex-wrap items-center gap-x-5 gap-y-1.5"
        >
          {parts.map((part) => (
            <div key={part.id} className="flex items-center gap-2">
              {/* Only where there is more than one part to tell apart. On a
                  single-part material "P1" labels the only thing there is. */}
              {parts.length > 1 && (
                <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                  P{part.index + 1}
                </span>
              )}
              <div className="flex flex-wrap gap-1">
                {cellsOf(part, answers).map((cell) => {
                  index += 1;
                  const at = index;
                  const isCurrent = cell.id === current;
                  return (
                    <button
                      key={cell.n}
                      type="button"
                      ref={(el) => {
                        cells.current[at] = el;
                      }}
                      tabIndex={at === currentIndex ? 0 : -1}
                      onClick={() => onGo(cell.id)}
                      onKeyDown={(e) => {
                        const by =
                          e.key === "ArrowRight"
                            ? 1
                            : e.key === "ArrowLeft"
                              ? -1
                              : 0;
                        if (by === 0) return;
                        e.preventDefault();
                        move(at, by);
                      }}
                      aria-current={isCurrent ? "true" : undefined}
                      aria-label={`Question ${cell.n}${
                        cell.answered ? ", answered" : ", not answered"
                      }${flagged.has(cell.id) ? ", flagged for review" : ""}`}
                      className={cn(
                        "relative flex size-6 items-center justify-center rounded-md text-xs tabular-nums transition-colors duration-fast",
                        "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                        cell.answered
                          ? "bg-correct/20 text-correct"
                          : "bg-surface-sunken text-muted-foreground hover:bg-surface-hover hover:text-foreground",
                        // A ring rather than a colour, so it can sit on top of
                        // answered and unanswered alike — where you are and
                        // what you have done are two different facts and the
                        // strip has to be able to say both.
                        isCurrent && "ring-2 ring-primary",
                      )}
                    >
                      {cell.n}
                      {flagged.has(cell.id) && (
                        <span
                          aria-hidden
                          className="absolute top-0.5 right-0.5 size-1 rounded-full bg-attention"
                        />
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        {/* Held at a fixed width, so the row does not shuffle sideways every
            time an answer is typed. Hidden on a narrow window, where the
            squares are what there is room for. */}
        <span className="hidden w-28 shrink-0 text-right font-mono text-xs tabular-nums text-muted-foreground sm:block">
          {answered} of {total}
          <span className="text-muted-foreground/60"> answered</span>
        </span>

        <button
          type="button"
          onClick={onSubmit}
          disabled={submitting}
          className="inline-flex shrink-0 items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity duration-fast hover:opacity-90 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card focus-visible:outline-none disabled:opacity-60"
        >
          {submitting && <Loader2 className="size-4 animate-spin" aria-hidden />}
          {confirming ? "Check anyway" : submitLabel}
        </button>
      </div>
    </div>
  );
}

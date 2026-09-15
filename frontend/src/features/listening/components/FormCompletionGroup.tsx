import { useMemo } from "react";
import { Volume2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { FlagQuestion } from "@/features/listening/components/FlagQuestion";
import { Q_ANCHOR } from "@/features/listening/take-focus";
import { FormLayout } from "@/features/listening/components/FormLayout";
import { TaskPicture } from "@/features/listening/components/TaskPicture";
import { parseTemplateLayout } from "@/features/listening/form-syntax";
import { matchLetter } from "@/features/listening/matching";
import { rubricSentence } from "@/features/listening/rubric";
import type { QuestionResult, TakeQuestionGroup } from "@/features/listening/types";

interface FormCompletionGroupProps {
  group: TakeQuestionGroup;
  answers: Record<string, string>;
  onChange: (questionId: string, value: string) => void;
  /** The number this group's first gap carries on the page. Gaps are stored
   *  numbered 1..N within their group; what the candidate reads runs across
   *  the whole material. */
  startNumber: number;
  results?: Record<string, QuestionResult>;
  /** Replays the moment this answer is said. Only ever called after grading:
   *  the timings aren't in the take payload until then. */
  onReplay?: (startMs: number | null, endMs: number | null) => void;
  disabled?: boolean;
  /** Only while the paper is being sat — see QuestionPaper. */
  flagged?: Set<string>;
  onFlag?: (questionId: string) => void;
}

export function FormCompletionGroup({
  group,
  answers,
  onChange,
  startNumber,
  results,
  onReplay,
  disabled,
  flagged,
  onFlag,
}: FormCompletionGroupProps) {
  const rubric = rubricSentence(group.config.answer_rubric, group.word_limit);
  // "Complete the summary using the list of words, A–H." With a box there is
  // nothing to type: each gap takes one of these letters, which is why the box
  // has to reach the candidate — they cannot answer without reading it.
  const box = group.config.options ?? [];
  // A map or diagram lettered A-H is the same box with its options drawn onto
  // a picture instead of listed: how many letters is all there is to send,
  // since what letter C means is a place on the drawing. So the count feeds
  // the same select, and everything below asks `letters` rather than the box.
  const letters = box.length || (group.config.image_letters ?? 0);

  const byNumber = useMemo(() => {
    const map = new Map<number, (typeof group.questions)[number]>();
    for (const q of group.questions) map.set(q.number, q);
    return map;
  }, [group.questions]);

  // Same parse the editor previews with, so what the author saw is what the
  // candidate sits — layout can't drift between the two.
  const blocks = useMemo(
    () => parseTemplateLayout(group.config.template ?? ""),
    [group.config.template],
  );

  return (
    <div className="space-y-3">
      <p className="text-sm text-foreground">{group.instructions}</p>
      {rubric && <p className="text-xs text-muted-foreground">{rubric}</p>}

      <div className="rounded-xl border border-border bg-card p-5">
        {/* Above the labels, where the paper prints it. Its size is known
            before the bytes arrive, so nothing under it moves as it lands. */}
        {group.config.image_url &&
          group.config.image_width &&
          group.config.image_height && (
            <TaskPicture
              url={group.config.image_url}
              width={group.config.image_width}
              height={group.config.image_height}
              adapt={group.config.image_adapt ?? true}
              alt="The picture this task is labelled on"
              className="mb-4"
            />
          )}
        <FormLayout
          blocks={blocks}
          blankPerRow={(group.config.image_letters ?? 0) > 0}
          // One question per line, numbered down the side, which is how a
          // paper prints these two and only these two. Notes and a summary
          // keep their number at the gap, because there the gap is somewhere
          // inside a sentence rather than the whole of the line.
          numberInMargin={
            group.type === "sentence_completion" ||
            group.type === "short_answer"
          }
          renderNumber={(n) => startNumber + n - 1}
          renderGap={(n, numbered) => {
            const question = byNumber.get(n);
            // A token with no question behind it can only come from a
            // template we didn't author; show the gap rather than pretend.
            if (!question) return <span className="text-muted-foreground">{`{{${n}}}`}</span>;
            const shown = startNumber + n - 1;
            const result = results?.[question.id];
            const graded = result !== undefined;
            const filled = (answers[question.id] ?? "").trim().length > 0;
            // The gap is the one control on this page a candidate spends
            // their whole time in, and it is drawn the way the editor draws
            // it: a rule under a piece of writing, not a box on a form. Take
            // and author have to look like the same object or the author is
            // laying out something they never see.
            const fieldTone = graded
              ? result.is_correct
                ? "border-correct text-correct"
                : "border-incorrect text-incorrect"
              : filled
                ? // A filled gap's rule is brighter, so a form with three
                  // left in it can be read as a shape rather than by
                  // checking each line.
                  "border-border-strong"
                : "border-border";
            return (
              <span
                {...{ [Q_ANCHOR]: question.id }}
                className="mx-1 inline-flex items-baseline gap-1 align-baseline"
              >
                {numbered && (
                  <span
                    aria-hidden
                    className="text-xs font-semibold text-muted-foreground"
                  >
                    {shown}
                  </span>
                )}
                {letters > 0 ? (
                  // A native select, inline in the prose: the letters are a
                  // closed list, and a field to type one into would invite a
                  // word the paper didn't ask for.
                  <select
                    data-question={question.id}
                    className={cn(
                      "rounded-md border bg-transparent px-2 py-0.5 font-mono text-base text-foreground transition-colors duration-fast focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                      fieldTone,
                    )}
                    value={answers[question.id] ?? ""}
                    onChange={(e) => onChange(question.id, e.target.value)}
                    disabled={disabled}
                    aria-label={`Answer ${shown}`}
                    aria-invalid={graded && !result.is_correct}
                  >
                    <option value="">—</option>
                    {Array.from({ length: letters }, (_, i) => (
                      <option key={i} value={matchLetter(i)}>
                        {matchLetter(i).toUpperCase()}
                      </option>
                    ))}
                  </select>
                ) : (
                <input
                  type="text"
                  // Read by the take page's focus timer, which attributes
                  // held focus by walking up from whatever has it. One
                  // attribute here beats threading onFocus/onBlur through
                  // every group component and the layout between them.
                  data-question={question.id}
                  autoComplete="off"
                  autoCorrect="off"
                  spellCheck={false}
                  className={cn(
                    // No ring: the underline IS the focus state, and a ring
                    // around a borderless field draws a box the design spent
                    // the rest of this rule removing.
                    "w-36 border-0 border-b-2 bg-transparent px-1 pb-0.5 font-mono text-base text-foreground transition-colors duration-fast placeholder:text-muted-foreground focus-visible:border-primary focus-visible:outline-none",
                    fieldTone,
                  )}
                  value={answers[question.id] ?? ""}
                  onChange={(e) => onChange(question.id, e.target.value)}
                  disabled={disabled}
                  aria-label={`Answer ${shown}`}
                  aria-invalid={graded && !result.is_correct}
                />
                )}
                {graded && !result.is_correct && (
                  <span className="text-xs text-muted-foreground">
                    (
                    {letters > 0
                      ? result.correct_answers
                          .map((letter) => letter.trim().toUpperCase())
                          .join(", ")
                      : `accepted: ${result.correct_answers.join(", ")}`}
                    )
                  </span>
                )}
                {onFlag && (
                  <FlagQuestion
                    number={String(shown)}
                    flagged={flagged?.has(question.id) ?? false}
                    onToggle={() => onFlag(question.id)}
                  />
                )}
                {/* Only where the author marked it — a review that offered
                    replay on every gap and played the wrong moment on half of
                    them would be worse than not offering it. */}
                {graded && onReplay && result.replay_start_ms != null && (
                  <button
                    type="button"
                    onClick={() =>
                      onReplay(result.replay_start_ms, result.replay_end_ms)
                    }
                    title="Hear where this answer is said"
                    aria-label={`Hear where answer ${shown} is said`}
                    className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-foreground/8 hover:text-primary"
                  >
                    <Volume2 className="size-3.5" aria-hidden />
                    hear it
                  </button>
                )}
              </span>
            );
          }}
        />
      </div>

      {/* Under the text, where the paper prints it: "complete the summary
          below using the list of words below". The editor puts it in the same
          place, so what the author lays out is what the candidate sits. */}
      {box.length > 0 && (
        <>
          <ul className="space-y-1 rounded-lg border border-border bg-background p-3">
            {box.map((text, index) => (
              <li key={index} className="flex items-baseline gap-2 text-sm">
                <span
                  aria-hidden
                  className="flex size-5 shrink-0 items-center justify-center self-center rounded-full border border-border text-xs font-semibold text-muted-foreground"
                >
                  {matchLetter(index).toUpperCase()}
                </span>
                <span className="text-foreground">{text}</span>
              </li>
            ))}
          </ul>
          {group.config.allow_reuse && (
            <p className="text-xs text-muted-foreground">
              NB You may use any letter more than once.
            </p>
          )}
        </>
      )}
    </div>
  );
}

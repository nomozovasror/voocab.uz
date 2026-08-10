import type { ListeningQuestion, QuestionIn } from "@/features/listening/types";

/** One row of the editor's real-form view: a field label ("date of birth")
 *  plus its accepted answers ("12 september", "september 12"). The author
 *  never sees `{{N}}` — it's generated/parsed here, at the edges. */
export interface FormRow {
  label: string;
  answers: string[];
}

/** Build `config.template` + `questions` from the editor's rows. Always
 *  renumbers 1..N from row order (the server requires the {{N}} tokens to be
 *  contiguous and to exactly match the question numbers — see
 *  QuestionGroupIn._tokens_match_questions in app/schemas/listening.py), so
 *  reordering/deleting rows never desyncs the template from the questions. */
export function buildTemplate(rows: FormRow[]): {
  template: string;
  questions: QuestionIn[];
} {
  const template = rows
    .map((row, i) => {
      const n = i + 1;
      const label = row.label.trim();
      return label ? `${label}: {{${n}}}` : `{{${n}}}`;
    })
    .join("\n");

  const questions: QuestionIn[] = rows.map((row, i) => ({
    number: i + 1,
    correct_answers: row.answers.map((a) => a.trim()).filter(Boolean),
  }));

  return { template, questions };
}

// Matches "<label>: {{N}}" (label optional) at the end of a line.
const ROW_RE = /^(?:(.*?):\s*)?\{\{(\d+)\}\}\s*$/;

/** Inverse of buildTemplate: parse a hydrated template + its questions back
 *  into editable rows. Lines that don't match the generator's own shape
 *  (e.g. a template authored elsewhere) are skipped — this editor can only
 *  round-trip templates it produced itself. */
export function parseTemplate(
  template: string,
  questions: ListeningQuestion[],
): FormRow[] {
  const byNumber = new Map(questions.map((q) => [q.number, q]));

  const rows: { number: number; row: FormRow }[] = [];
  for (const line of template.split("\n")) {
    const match = ROW_RE.exec(line.trim());
    if (!match) continue;
    const [, label, numStr] = match;
    const number = Number(numStr);
    const question = byNumber.get(number);
    rows.push({
      number,
      row: {
        label: label ?? "",
        answers: question?.correct_answers?.length ? question.correct_answers : [""],
      },
    });
  }

  return rows.sort((a, b) => a.number - b.number).map((r) => r.row);
}

/** Whether the current rows + instructions are complete enough to persist as
 *  a question group without tripping the server's 422s (every gap needs >=1
 *  non-blank answer). Used to gate autosave — an incomplete draft simply
 *  isn't sent yet, rather than erroring on every keystroke. */
export function isGroupPersistable(rows: FormRow[], instructions: string): boolean {
  if (!instructions.trim()) return false;
  if (rows.length === 0) return false;
  return rows.every((r) => r.answers.some((a) => a.trim() !== ""));
}

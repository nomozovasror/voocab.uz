import { questionSpan, sorted } from "@/features/listening/numbering";
import type { MaterialTake } from "@/features/listening/types";

/**
 * The paper as a flat list of questions, in the order they are printed.
 *
 * Three things need this walk and they must agree or the page contradicts
 * itself: the header's "3 of 40 answered", the navigator along the bottom,
 * and the submit. So it is walked once, here, rather than three times in
 * three components — the numbering module already owns the RULES, and this
 * owns the walk.
 *
 * One question is not always one number. A "Choose TWO letters" is printed as
 * *Questions 23 and 24* and carries two marks, which is why every row has a
 * span and nothing here counts questions.
 */

export interface PaperRow {
  id: string;
  /** The first number this question carries on the paper. */
  number: number;
  /** How many of the paper's numbers it takes. */
  span: number;
  partId: string;
  /** Zero-based, so `partIndex + 1` is what the reader sees. */
  partIndex: number;
}

export interface PaperPart {
  id: string;
  index: number;
  /** Where this part's numbering starts on its own paper, when it came out of
   *  a real one. Carried through so the heading can print the part's true
   *  number — the index says 0 for every seeded material, whichever part it
   *  actually is. */
  first_number?: number | null;
  title: string;
  audioStartMs: number | null;
  audioEndMs: number | null;
  rows: PaperRow[];
  /** The first and last numbers in the part — "Questions 1–6". */
  from: number;
  to: number;
}

export function paperParts(material: MaterialTake): PaperPart[] {
  const parts: PaperPart[] = [];
  let seen = 0;

  for (const [index, part] of sorted(material.parts).entries()) {
    // The same rule as `groupNumbering`, and it has to be: this walk feeds
    // the header count, the navigator and the review, and that one feeds the
    // numbers printed beside the questions. A part that came out of a real
    // paper knows where its numbering starts -- Part 4 is Questions 31-40,
    // which is what the recording says aloud.
    if (part.first_number != null) seen = part.first_number - 1;
    const rows: PaperRow[] = [];
    for (const group of sorted(part.question_groups)) {
      const span = questionSpan(group.config.answers_per_question);
      // By the number the question carries inside its own group, which is
      // the order it is printed in. Questions arrive in whatever order the
      // API happened to serialise them.
      const questions = group.questions
        .slice()
        .sort((a, b) => a.number - b.number);
      for (const [i, question] of questions.entries()) {
        rows.push({
          id: question.id,
          number: seen + i * span + 1,
          span,
          partId: part.id,
          partIndex: index,
        });
      }
      seen += questions.length * span;
    }
    parts.push({
      id: part.id,
      index,
      first_number: part.first_number,
      title: part.title,
      audioStartMs: part.audio_start_ms,
      audioEndMs: part.audio_end_ms,
      rows,
      from: rows.length ? rows[0].number : seen + 1,
      to: seen,
    });
  }

  return parts;
}

export function paperRows(parts: PaperPart[]): PaperRow[] {
  return parts.flatMap((part) => part.rows);
}

/**
 * How many of a question's numbers are answered.
 *
 * A "choose TWO" with one letter picked is half answered, and says so. It is
 * also the one case where a candidate can leave a number blank without
 * leaving a field empty — which is exactly what the warning before submitting
 * is for.
 */
export function answeredIn(row: PaperRow, value: string | undefined): number {
  const given = (value ?? "").trim();
  if (!given) return 0;
  if (row.span === 1) return 1;
  return Math.min(row.span, given.split(",").filter(Boolean).length);
}

/** The total number of marks on the paper — not the number of questions. */
export function paperTotal(rows: PaperRow[]): number {
  return rows.reduce((n, row) => n + row.span, 0);
}

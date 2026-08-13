import type { ListeningQuestion, QuestionIn } from "@/features/listening/types";

/**
 * The form-completion document: what the builder edits, and how it becomes
 * what the API stores.
 *
 * A real IELTS form is not a list of "label: blank" pairs — a gap sits inside
 * a sentence ("outside the ___ at about 4 pm"), rows carry context with no gap
 * at all ("Date of birth | 14 December 1977"), one label can head several
 * bulleted lines, and the whole is broken up by a title and section headings.
 * The author builds that visually; this module is the only place that knows
 * how to write it down and read it back.
 *
 * Stored form — the layout rides along inside `config.template`, so no schema
 * change was needed; the server only ever validates the `{{N}}` tokens:
 *
 *     # Crime report form
 *     Type of crime | theft
 *
 *     ## Personal information
 *     Nationality | {{1}}
 *     Reason for visit | business (to buy antique {{2}})
 *     Items stolen | - a wallet containing approximately £ {{3}}
 *      | - a {{4}}
 */

// ── Layout model (what gets rendered, by the builder and the take page) ───

export type FormPart =
  | { kind: "text"; text: string }
  | { kind: "gap"; number: number };

export interface FormLine {
  bullet: boolean;
  parts: FormPart[];
}

export type FormBlock =
  | { kind: "title"; text: string }
  | { kind: "heading"; text: string }
  | { kind: "row"; label: string; lines: FormLine[] }
  /** A rule across the form. On the printed page these separate groups of
   *  fields rather than every row, so they are placed, never implied. */
  | { kind: "divider" }
  | { kind: "space" };

// ── Escaping ─────────────────────────────────────────────────────────────

// `|` separates a label from its value, so a pipe typed into the text itself
// is escaped on the way out and restored on the way back in. Without this, a
// labelless row whose text happened to contain a pipe would come back with
// everything before it silently promoted to a label.
function escapePipes(text: string): string {
  return text.replace(/\\/g, "\\\\").replace(/\|/g, "\\|");
}

function unescapePipes(text: string): string {
  return text.replace(/\\([\\|])/g, "$1");
}

/** Index of the first `|` that isn't escaped, or -1. */
function separatorIndex(line: string): number {
  for (let i = 0; i < line.length; i++) {
    if (line[i] === "\\") {
      i++;
      continue;
    }
    if (line[i] === "|") return i;
  }
  return -1;
}

// ── Parsing a stored template into layout ────────────────────────────────

const TOKEN_RE = /\{\{(\d+)\}\}/g;
/** Gaps are masked before the line is split, so a token can't be confused
 *  with anything the author typed. */
const MASK_RE = /\u0000(\d+)\u0000/g;

function splitParts(
  text: string,
  numberOf: (index: number) => number,
): FormPart[] {
  const parts: FormPart[] = [];
  let last = 0;
  for (const match of text.matchAll(MASK_RE)) {
    const at = match.index ?? 0;
    if (at > last) {
      parts.push({ kind: "text", text: unescapePipes(text.slice(last, at)) });
    }
    parts.push({ kind: "gap", number: numberOf(Number(match[1])) });
    last = at + match[0].length;
  }
  if (last < text.length) {
    parts.push({ kind: "text", text: unescapePipes(text.slice(last)) });
  }
  return parts;
}

function parseBlocks(
  masked: string,
  numberOf: (index: number) => number,
): FormBlock[] {
  const blocks: FormBlock[] = [];
  let openRow: Extract<FormBlock, { kind: "row" }> | null = null;

  for (const raw of masked.split("\n")) {
    const line = raw.replace(/\s+$/, "");
    if (!line.trim()) {
      openRow = null;
      blocks.push({ kind: "space" });
      continue;
    }

    const trimmed = line.trim();
    if (/^-{3,}$/.test(trimmed)) {
      openRow = null;
      blocks.push({ kind: "divider" });
      continue;
    }
    if (trimmed.startsWith("## ")) {
      openRow = null;
      blocks.push({
        kind: "heading",
        text: unescapePipes(trimmed.slice(3).trim()),
      });
      continue;
    }
    if (trimmed.startsWith("# ")) {
      openRow = null;
      blocks.push({ kind: "title", text: unescapePipes(trimmed.slice(2).trim()) });
      continue;
    }

    const bar = separatorIndex(trimmed);
    const label = bar >= 0 ? trimmed.slice(0, bar).trim() : "";
    let value = bar >= 0 ? trimmed.slice(bar + 1).trim() : trimmed;

    const bullet = value.startsWith("- ");
    if (bullet) value = value.slice(2).trim();
    const formLine: FormLine = { bullet, parts: splitParts(value, numberOf) };

    // A bar with nothing before it continues the row above: that's how one
    // label heads several bulleted lines.
    if (bar >= 0 && !label && openRow) {
      openRow.lines.push(formLine);
      continue;
    }

    openRow = { kind: "row", label: unescapePipes(label), lines: [formLine] };
    blocks.push(openRow);
  }

  while (blocks.length > 0 && blocks[blocks.length - 1].kind === "space") {
    blocks.pop();
  }
  return blocks;
}

/** Parse a stored template back into layout. Gap numbers come from the tokens
 *  rather than from position, so this stays right even for a template that
 *  was authored elsewhere. */
export function parseTemplateLayout(template: string): FormBlock[] {
  const numbers: number[] = [];
  const masked = template.replace(TOKEN_RE, (_match, n: string) => {
    const index = numbers.length;
    numbers.push(Number(n));
    return `\u0000${index}\u0000`;
  });
  return parseBlocks(masked, (i) => numbers[i]);
}

// ── The editable document ────────────────────────────────────────────────

export type DocPart =
  | { kind: "text"; text: string }
  /** `id` is what the answers hang off. A gap's *number* comes from its
   *  position, so anything keyed by number would silently reattach every
   *  later answer to the wrong gap the moment one is inserted in the middle. */
  | {
      kind: "gap";
      id: string;
      answers: string[];
      /** Where in the recording this answer is said, if the author marked
       *  it. Travels with the gap for the same reason the answers do. */
      replayStartMs?: number | null;
      replayEndMs?: number | null;
    };

export interface DocLine {
  id: string;
  bullet: boolean;
  parts: DocPart[];
}

export type DocBlock =
  | { id: string; kind: "title"; text: string }
  | { id: string; kind: "heading"; text: string }
  | { id: string; kind: "divider" }
  | { id: string; kind: "row"; label: string; lines: DocLine[] };

let idCounter = 0;
export function newId(): string {
  idCounter += 1;
  return `b${idCounter}`;
}

export function newTextLine(text = ""): DocLine {
  return { id: newId(), bullet: false, parts: [{ kind: "text", text }] };
}

export function newRow(label = ""): DocBlock {
  return { id: newId(), kind: "row", label, lines: [newTextLine()] };
}

export function newDoc(): DocBlock[] {
  return [newRow()];
}

/** Every gap in document order — which is what numbers them. */
export interface DocGap {
  id: string;
  number: number;
  answers: string[];
  replayStartMs?: number | null;
  replayEndMs?: number | null;
}

export function docGaps(doc: DocBlock[]): DocGap[] {
  const gaps: DocGap[] = [];
  for (const block of doc) {
    if (block.kind !== "row") continue;
    for (const line of block.lines) {
      for (const part of line.parts) {
        if (part.kind === "gap") {
          gaps.push({
            id: part.id,
            number: gaps.length + 1,
            answers: part.answers,
            replayStartMs: part.replayStartMs,
            replayEndMs: part.replayEndMs,
          });
        }
      }
    }
  }
  return gaps;
}

/** Gap id → its 1-based number, for rendering. */
export function gapNumbers(doc: DocBlock[]): Map<string, number> {
  return new Map(docGaps(doc).map((g) => [g.id, g.number]));
}

function lineToText(line: DocLine, numberOf: (id: string) => number): string {
  const body = line.parts
    .map((part) =>
      part.kind === "text" ? escapePipes(part.text) : `{{${numberOf(part.id)}}}`,
    )
    .join("");
  return line.bullet ? `- ${body}` : body;
}

/** Document → what the API stores. Numbering is positional, so the tokens are
 *  always contiguous from 1 and always match the questions. */
export function docToGroup(doc: DocBlock[]): {
  template: string;
  questions: QuestionIn[];
} {
  const numbers = gapNumbers(doc);
  const numberOf = (id: string) => numbers.get(id) ?? 0;

  const lines: string[] = [];
  for (const block of doc) {
    if (block.kind === "divider") {
      lines.push("---");
      continue;
    }
    if (block.kind === "title") {
      lines.push(`# ${escapePipes(block.text)}`, "");
      continue;
    }
    if (block.kind === "heading") {
      if (lines.length > 0 && lines[lines.length - 1] !== "") lines.push("");
      lines.push(`## ${escapePipes(block.text)}`);
      continue;
    }
    block.lines.forEach((line, i) => {
      const body = lineToText(line, numberOf);
      if (i === 0) {
        // A labelless first line is written bare: writing it with a leading
        // bar would read back as a continuation of the row above.
        lines.push(
          block.label.trim() ? `${escapePipes(block.label)} | ${body}` : body,
        );
      } else {
        lines.push(` | ${body}`);
      }
    });
  }

  const questions: QuestionIn[] = docGaps(doc).map((gap) => ({
    number: gap.number,
    correct_answers: gap.answers.map((a) => a.trim()).filter(Boolean),
    replay_start_ms: gap.replayStartMs ?? null,
    replay_end_ms: gap.replayEndMs ?? null,
  }));

  return { template: lines.join("\n").trim(), questions };
}

/** The inverse, for reopening a saved material. */
export function docFromGroup(
  template: string,
  questions: ListeningQuestion[],
): DocBlock[] {
  const byNumber = new Map(questions.map((q) => [q.number, q]));
  const doc: DocBlock[] = [];

  for (const block of parseTemplateLayout(template)) {
    if (block.kind === "space") continue;
    if (block.kind === "divider") {
      doc.push({ id: newId(), kind: "divider" });
      continue;
    }
    if (block.kind === "title" || block.kind === "heading") {
      doc.push({ id: newId(), kind: block.kind, text: block.text });
      continue;
    }
    doc.push({
      id: newId(),
      kind: "row",
      label: block.label,
      lines: block.lines.map((line) => ({
        id: newId(),
        bullet: line.bullet,
        parts: line.parts.map((part) =>
          part.kind === "text"
            ? { kind: "text" as const, text: part.text }
            : {
                kind: "gap" as const,
                id: newId(),
                answers: byNumber.get(part.number)?.correct_answers ?? [],
                replayStartMs: byNumber.get(part.number)?.replay_start_ms ?? null,
                replayEndMs: byNumber.get(part.number)?.replay_end_ms ?? null,
              },
        ),
      })),
    });
  }

  return doc.length > 0 ? doc : newDoc();
}

/** The document as layout, for rendering it exactly as the take page will. */
export function docToLayout(doc: DocBlock[]): FormBlock[] {
  const numbers = gapNumbers(doc);
  return doc.map((block) =>
    block.kind === "divider"
      ? { kind: "divider" as const }
      : block.kind === "row"
        ? {
          kind: "row" as const,
          label: block.label,
          lines: block.lines.map((line) => ({
            bullet: line.bullet,
            parts: line.parts.map((part) =>
              part.kind === "text"
                ? { kind: "text" as const, text: part.text }
                : { kind: "gap" as const, number: numbers.get(part.id) ?? 0 },
            ),
          })),
        }
      : { kind: block.kind, text: block.text },
  );
}

// ── Validation ───────────────────────────────────────────────────────────

/** What still has to be filled in, phrased for the author. Empty means it's
 *  publishable.
 *
 *  `offset` is how many questions come before this group in the material, so
 *  the numbers quoted are the ones printed beside the gaps rather than the
 *  1..N this group happens to store. */
export function docIssues(doc: DocBlock[], offset = 0): string[] {
  const gaps = docGaps(doc);
  if (gaps.length === 0) {
    return ["No questions yet — put an answer in brackets, like [Chinese]."];
  }
  const unanswered = gaps
    .filter((g) => !g.answers.some((a) => a.trim()))
    .map((g) => g.number + offset);
  if (unanswered.length === 0) return [];
  return [
    unanswered.length === 1
      ? `Question ${unanswered[0]} has no accepted answer yet.`
      : `Questions ${unanswered.join(", ")} have no accepted answers yet.`,
  ];
}

/** What has to be true to publish, over and above being savable: every gap
 *  must also be linked to the moment it is said. Kept apart from `docIssues`
 *  so a half-finished draft still autosaves — an author shouldn't have to
 *  mark the audio before they're allowed to write the next row. */
export function docPublishIssues(doc: DocBlock[], offset = 0): string[] {
  const issues = docIssues(doc, offset);
  if (issues.length > 0) return issues;
  const unmarked = docGaps(doc)
    .filter((g) => g.replayStartMs == null)
    .map((g) => g.number + offset);
  if (unmarked.length === 0) return [];
  return [
    unmarked.length === 1
      ? `Question ${unmarked[0]} isn't linked to the audio yet.`
      : `Questions ${unmarked.join(", ")} aren't linked to the audio yet.`,
  ];
}

/** Whether this form can be persisted without tripping the server's 422s.
 *  Gates autosave, so an incomplete draft simply isn't sent yet rather than
 *  erroring on every keystroke.
 *
 *  Only one thing holds a form back: a gap with no accepted answer, which the
 *  server refuses because a gap nobody can answer isn't a draft of anything.
 *  Everything else about an unfinished form — no instructions, no gaps at
 *  all, nothing but a heading — is a form being written, and saving it is the
 *  whole point. This used to also require instructions and at least one gap,
 *  which meant the beginning of a group was never stored at all. */
export function isGroupPersistable(doc: DocBlock[]): boolean {
  return docGaps(doc).every((gap) => gap.answers.some((a) => a.trim()));
}

/** Whether the author has put anything of their own in yet. */
export function isDocEmpty(doc: DocBlock[]): boolean {
  return doc.every((block) => {
    if (block.kind === "divider") return true;
    if (block.kind !== "row") return block.text.trim() === "";
    if (block.label.trim()) return false;
    return block.lines.every((line) =>
      line.parts.every((p) => p.kind === "text" && p.text.trim() === ""),
    );
  });
}


// ── A line as text, for editing ──────────────────────────────────────────

/**
 * A value line is edited as plain text and read as chips. Typing into a
 * contentEditable holding inline chip elements means keeping the DOM and the
 * model in step on every keystroke, and losing the caret whenever they
 * disagree; a plain field types natively and wraps natively, and the chips are
 * rendered from it the moment it loses focus.
 */

const LINE_GAP_RE = /\[([^\]]*)\]/g;

export function partsToText(parts: DocPart[]): string {
  return parts
    .map((part) =>
      part.kind === "text" ? part.text : `[${part.answers.join(", ")}]`,
    )
    .join("");
}

function sameAnswers(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((x, i) => x === b[i]);
}

/** Parse an edited line back into parts, carrying gaps' identities across.
 *
 *  Answers travel in the text, so they can't desync — but a gap's audio mark
 *  hangs off its id, and that has to survive the author fixing a typo in the
 *  words around it. A gap is matched to the old one with the same answers
 *  where there is one, and to the one in the same position otherwise. */
export function textToParts(text: string, previous: DocPart[]): DocPart[] {
  const old = previous.filter((p) => p.kind === "gap") as Extract<
    DocPart,
    { kind: "gap" }
  >[];
  const taken = new Set<number>();
  const parts: DocPart[] = [];
  let last = 0;
  let ordinal = 0;

  for (const match of text.matchAll(LINE_GAP_RE)) {
    const at = match.index ?? 0;
    if (at > last) parts.push({ kind: "text", text: text.slice(last, at) });

    const answers = match[1]
      .split(",")
      .map((a) => a.trim())
      .filter(Boolean);

    let reuse = old.findIndex(
      (g, i) => !taken.has(i) && sameAnswers(g.answers, answers),
    );
    if (reuse < 0 && !taken.has(ordinal) && old[ordinal]) reuse = ordinal;

    if (reuse >= 0) {
      taken.add(reuse);
      parts.push({ ...old[reuse], answers });
    } else {
      parts.push({ kind: "gap", id: newId(), answers });
    }

    last = at + match[0].length;
    ordinal += 1;
  }

  if (last < text.length) parts.push({ kind: "text", text: text.slice(last) });
  if (parts.length === 0) parts.push({ kind: "text", text: "" });
  return parts;
}

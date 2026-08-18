import type {
  CompletionType,
  ListeningQuestion,
  QuestionIn,
} from "@/features/listening/types";

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
 * **A row with no label runs the full width.** That one rule is what makes
 * this a completion builder rather than a form builder: notes, sentences, a
 * summary paragraph and short-answer questions are all full-width lines with
 * gaps in them, and they differ from a form only in not having a label column.
 * The storage format has said so from the start — a labelled row is written
 * with a bar, a labelless one bare — because a bar with nothing before it
 * already means "continue the row above". So there is no third thing to store
 * and nothing to migrate; the layout simply stopped reserving a column for a
 * label that isn't there.
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
 *
 * and the same file holding notes, where nothing has a label:
 *
 *     ## Museum tour
 *     - Meet outside the {{1}} at 4 pm
 *     - Tour lasts {{2}} minutes
 *
 * A table is a run of `+` lines, cells separated by the same bar. The first
 * of the run is the header row — which is what a table's first row is on the
 * paper, and leaving it blank is how a table without one is written:
 *
 *     + Tour | Price | Departs
 *     + Harbour trip | £12 | {{1}}
 *     + City walk | {{2}} | 11 am
 *
 A flow chart is a run of `>` lines, one per step, drawn as boxes with an
 * arrow between them. The prefix reads as "then", which is what the arrow
 * means:
 *
 *     > Application form sent to {{1}}
 *     > Interview with the {{2}}
 *     > Decision within {{3}} days
 *
 * The `+` and the `>` are what make these runs unambiguous. A bar-delimited line on its own
 * already means something here — a label and its value, or, with nothing
 * before the bar, a continuation of the row above — so a table's rows have to
 * say that is what they are.
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
  /** A grid. `head` is the header row, given rather than answered — a table
   *  completion never gaps its own headers. Every body row carries one cell
   *  per column, padded on the way in so the grid is always rectangular. */
  | { kind: "table"; head: string[]; rows: FormLine[][] }
  /** A chain of steps, drawn as boxes with an arrow between them. Linear on
   *  purpose: a real flow-chart completion is a process in order, and the
   *  branching kind is rare enough that offering it would be offering authors
   *  a diagram to get wrong. */
  | { kind: "flow"; steps: FormLine[] }
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

/** Every `|`-separated field of a line, taking escaped bars as text. For a
 *  table row, where the bar is a column boundary rather than the one break
 *  between a label and its value. */
function splitCells(line: string): string[] {
  const cells: string[] = [];
  let start = 0;
  for (let i = 0; i < line.length; i++) {
    if (line[i] === "\\") {
      i++;
      continue;
    }
    if (line[i] === "|") {
      cells.push(line.slice(start, i));
      start = i + 1;
    }
  }
  cells.push(line.slice(start));
  return cells.map((cell) => cell.trim());
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
  let openTable: Extract<FormBlock, { kind: "table" }> | null = null;
  let openFlow: Extract<FormBlock, { kind: "flow" }> | null = null;
  /** Anything that isn't another cell, or another step, closes them all. */
  const closeBlocks = () => {
    openRow = null;
    openTable = null;
    openFlow = null;
  };

  for (const raw of masked.split("\n")) {
    const line = raw.replace(/\s+$/, "");
    if (!line.trim()) {
      closeBlocks();
      blocks.push({ kind: "space" });
      continue;
    }

    const trimmed = line.trim();
    if (/^-{3,}$/.test(trimmed)) {
      closeBlocks();
      blocks.push({ kind: "divider" });
      continue;
    }
    if (trimmed.startsWith("## ")) {
      closeBlocks();
      blocks.push({
        kind: "heading",
        text: unescapePipes(trimmed.slice(3).trim()),
      });
      continue;
    }
    if (trimmed.startsWith("# ")) {
      closeBlocks();
      blocks.push({ kind: "title", text: unescapePipes(trimmed.slice(2).trim()) });
      continue;
    }
    if (trimmed === ">" || trimmed.startsWith("> ")) {
      const step = { bullet: false, parts: splitParts(trimmed.slice(1).trim(), numberOf) };
      openRow = null;
      openTable = null;
      if (openFlow) {
        openFlow.steps.push(step);
      } else {
        openFlow = { kind: "flow", steps: [step] };
        blocks.push(openFlow);
      }
      continue;
    }
    openFlow = null;

    if (trimmed === "+" || trimmed.startsWith("+ ")) {
      const cells = splitCells(trimmed.slice(1).trim());
      openRow = null;
      if (openTable) {
        // A cell is a line, which is what lets the editor put the same value
        // field in one as it puts in a form's value.
        openTable.rows.push(
          cells.map((cell) => ({ bullet: false, parts: splitParts(cell, numberOf) })),
        );
      } else {
        // The first row of a run is the header. That is what a table's first
        // row is on the paper, and it is why a headerless one is written by
        // leaving these blank rather than by leaving the line out.
        openTable = {
          kind: "table",
          head: cells.map(unescapePipes),
          rows: [],
        };
        blocks.push(openTable);
      }
      continue;
    }
    openTable = null;

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

  // Squared off after the fact rather than refused: a template written
  // elsewhere, or one an edit left ragged, still has to render as a grid, and
  // a row a cell short is a row with an empty cell.
  for (const block of blocks) {
    if (block.kind !== "table") continue;
    const columns = Math.max(
      block.head.length,
      ...block.rows.map((row) => row.length),
    );
    while (block.head.length < columns) block.head.push("");
    for (const row of block.rows) {
      while (row.length < columns) row.push({ bullet: false, parts: [] });
    }
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
      /** The option this gap is answered by, where the group is printed with
       *  a box — by option ID, never by letter.
       *
       *  A letter is a position, so it moves the moment an option is inserted
       *  above it; a gap remembering "c" would silently reattach to whatever
       *  ended up third. Letters appear only at the edges: on the page, and
       *  in what gets sent. Null until the author picks one, which is the
       *  ordinary state of every gap in a boxed task while the text around it
       *  is still being written. */
      optionId?: string | null;
    };

export interface DocLine {
  id: string;
  bullet: boolean;
  parts: DocPart[];
}

export interface DocTableRow {
  id: string;
  /** One per column. A cell is a line, so the builder puts the same value
   *  field in it that it puts in a form's value, and a gap works the same way
   *  wherever it is. */
  cells: DocLine[];
}

export type DocBlock =
  | { id: string; kind: "title"; text: string }
  | { id: string; kind: "heading"; text: string }
  | { id: string; kind: "divider" }
  | { id: string; kind: "row"; label: string; lines: DocLine[] }
  | { id: string; kind: "table"; head: string[]; rows: DocTableRow[] }
  | { id: string; kind: "flow"; steps: DocLine[] };

let idCounter = 0;
export function newId(): string {
  idCounter += 1;
  return `b${idCounter}`;
}

export function newTextLine(text = ""): DocLine {
  return { id: newId(), bullet: false, parts: [{ kind: "text", text }] };
}

/** A block of the sheet. With a label it is a form row, label column and all;
 *  without one it is a line running the full width — a note, a sentence, a
 *  short-answer question. The two are one kind because they are one thing to
 *  the storage format, and because an author turning a form row into a note is
 *  clearing a field rather than replacing a block. */
export function newRow(label = ""): Extract<DocBlock, { kind: "row" }> {
  return { id: newId(), kind: "row", label, lines: [newTextLine()] };
}

/** A row that is already one question: a name to write on the left, one blank
 *  on the right.
 *
 *  This is the whole of a labelling sheet. "Write the correct letter next to
 *  questions 15-20" prints a list — *15 coffee room ......., 16 warehouse
 *  .......* — where every line has exactly one answer and no line has anything
 *  else. Built out of the ordinary row plus typed brackets, an author had to
 *  know that `[]` is how a blank is made before they could write the first
 *  item; born with the blank in it, the sheet is a list they type down and the
 *  brackets never come up.
 *
 *  Still an ordinary row underneath, so it stores, parses and renders like any
 *  other — and an author who wants two blanks on a line, or a sentence around
 *  one, can still type them. */
export function newLabelRow(label = ""): Extract<DocBlock, { kind: "row" }> {
  const line: DocLine = {
    id: newId(),
    bullet: false,
    parts: [{ kind: "gap", id: newId(), answers: [] }],
  };
  return { id: newId(), kind: "row", label, lines: [line] };
}

/** How wide and deep a table starts. Three columns and two body rows is the
 *  commonest shape on the paper, and a grid with something in every direction
 *  is quicker to read than one cell asking to be grown. */
const TABLE_COLUMNS = 3;
const TABLE_ROWS = 2;

export function newTableRow(columns: number): DocTableRow {
  return {
    id: newId(),
    cells: Array.from({ length: columns }, () => newTextLine()),
  };
}

/** How many steps a chart starts with. Three is the shortest thing that reads
 *  as a process rather than as a pair. */
const FLOW_STEPS = 3;

export function newFlow(): DocBlock {
  return {
    id: newId(),
    kind: "flow",
    steps: Array.from({ length: FLOW_STEPS }, () => newTextLine()),
  };
}

export function newTable(): DocBlock {
  return {
    id: newId(),
    kind: "table",
    head: Array.from({ length: TABLE_COLUMNS }, () => ""),
    rows: Array.from({ length: TABLE_ROWS }, () => newTableRow(TABLE_COLUMNS)),
  };
}

/** The sheet a new group starts as.
 *
 *  A form starts as a labelled row, a table as a grid; every other completion
 *  task starts as one full-width line, bulleted for notes because that is how
 *  notes are printed.
 *
 *  A starting point, not a constraint. Every block is reachable from every
 *  task — an author writing notes with a labelled row among them is writing
 *  the paper in front of them, and the five tasks are one document underneath
 *  precisely so that costs nothing. */
export function newDoc(type: CompletionType = "form_completion"): DocBlock[] {
  if (type === "table_completion") return [newTable()];
  if (type === "flow_chart_completion") return [newFlow()];
  // A labelling sheet is a list of things to name, so it starts as the first
  // line of one — blank included, since every line of it has exactly one.
  if (type === "map_labelling" || type === "diagram_labelling") {
    return [newLabelRow()];
  }
  const row = newRow();
  if (type !== "note_completion") return [row];
  return [{ ...row, lines: [{ ...row.lines[0], bullet: true }] }];
}

/** Drops every blank nobody has answered, leaving the text around it.
 *
 *  For one moment only: a labelling sheet being turned from letters to words.
 *  The blanks on a lettered sheet are made by the page, and the page made them
 *  because a letter is chosen rather than typed; without letters they become
 *  chips with nothing in them that cannot be typed into either, so the author
 *  would have to delete each one before writing an answer where it stood.
 *
 *  Answered gaps are kept. Those are the ones the author wrote themselves, in
 *  brackets, and they mean the same thing in both forms of the task. */
export function clearEmptyGaps(doc: DocBlock[]): DocBlock[] {
  const prune = (line: DocLine): DocLine => ({
    ...line,
    parts: line.parts.filter(
      (part) =>
        part.kind !== "gap" || part.answers.some((answer) => answer.trim()),
    ),
  });
  return doc.map((block) => {
    if (block.kind === "row") return { ...block, lines: block.lines.map(prune) };
    if (block.kind === "flow") return { ...block, steps: block.steps.map(prune) };
    if (block.kind === "table") {
      return {
        ...block,
        rows: block.rows.map((row) => ({ ...row, cells: row.cells.map(prune) })),
      };
    }
    return block;
  });
}

/** Every gap in document order — which is what numbers them. */
export interface DocGap {
  id: string;
  number: number;
  answers: string[];
  replayStartMs?: number | null;
  replayEndMs?: number | null;
  /** The option answering it, where the group has a box. */
  optionId?: string | null;
}

export function docGaps(doc: DocBlock[]): DocGap[] {
  const gaps: DocGap[] = [];
  const take = (line: DocLine) => {
    for (const part of line.parts) {
      if (part.kind !== "gap") continue;
      gaps.push({
        id: part.id,
        number: gaps.length + 1,
        answers: part.answers,
        replayStartMs: part.replayStartMs,
        replayEndMs: part.replayEndMs,
        optionId: part.optionId,
      });
    }
  };
  for (const block of doc) {
    // Reading order, which is the order the paper numbers them in: down the
    // rows, left to right across each.
    if (block.kind === "row") block.lines.forEach(take);
    else if (block.kind === "table") {
      for (const row of block.rows) row.cells.forEach(take);
    } else if (block.kind === "flow") block.steps.forEach(take);
  }
  return gaps;
}

/** Gap id → its 1-based number, for rendering. */
/** Every gap that pointed at this option, unanswered.
 *
 *  Called when an option leaves the box, and it has to be one edit with that
 *  removal: a gap naming a letter the box hasn't got is a payload the server
 *  refuses outright, so the two landing separately would leave the group
 *  unable to save at all. */
export function clearGapOption(
  doc: DocBlock[],
  optionId: string,
): DocBlock[] {
  const line = (l: DocLine): DocLine => ({
    ...l,
    parts: l.parts.map((part) =>
      part.kind === "gap" && part.optionId === optionId
        ? { ...part, optionId: null }
        : part,
    ),
  });
  return doc.map((block) => {
    if (block.kind === "row") return { ...block, lines: block.lines.map(line) };
    if (block.kind === "flow") return { ...block, steps: block.steps.map(line) };
    if (block.kind === "table") {
      return {
        ...block,
        rows: block.rows.map((row) => ({ ...row, cells: row.cells.map(line) })),
      };
    }
    return block;
  });
}

/** Whether this gap has an answer, which depends on what an answer is here:
 *  a letter from the group's box, or the words the author typed between the
 *  brackets. */
export function gapAnswered(gap: DocGap, boxed = false): boolean {
  return boxed ? !!gap.optionId : gap.answers.some((a) => a.trim());
}

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
export function docToGroup(
  doc: DocBlock[],
  /** Option ID -> its letter, for a group printed with a box. Given, a gap's
   *  answer is the one letter it was matched to; withheld, it is the accepted
   *  words the author typed between the brackets. Two meanings for one field,
   *  which is what the paper does: "write the missing word" against "write
   *  the correct letter". */
  letterOf?: (optionId: string) => string | undefined,
): {
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
    if (block.kind === "flow") {
      for (const step of block.steps) {
        lines.push(`> ${lineToText(step, numberOf)}`);
      }
      continue;
    }
    if (block.kind === "table") {
      lines.push(`+ ${block.head.map(escapePipes).join(" | ")}`);
      for (const row of block.rows) {
        lines.push(
          `+ ${row.cells.map((cell) => lineToText(cell, numberOf)).join(" | ")}`,
        );
      }
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

  const answersOf = (gap: DocGap): string[] => {
    if (!letterOf) return gap.answers.map((a) => a.trim()).filter(Boolean);
    // An option that has since been deleted is simply no answer. It cannot
    // normally happen — dropping an option clears the gaps that pointed at it
    // — but sending a letter the box hasn't got fails the whole save, and a
    // group that has stopped saving is far worse than an answer to set again.
    const letter = gap.optionId ? letterOf(gap.optionId) : undefined;
    return letter ? [letter] : [];
  };
  const questions: QuestionIn[] = docGaps(doc).map((gap) => ({
    number: gap.number,
    correct_answers: answersOf(gap),
    replay_start_ms: gap.replayStartMs ?? null,
    replay_end_ms: gap.replayEndMs ?? null,
  }));

  return { template: lines.join("\n").trim(), questions };
}

/** One rendered line back into an editable one, with the answers and marks
 *  its gaps had. Shared by a form's values and a table's cells: a cell is a
 *  line, so there is one conversion rather than two that can drift. */
function docLine(
  line: FormLine,
  byNumber: Map<number, ListeningQuestion>,
  optionIdOf?: (letter: string) => string | undefined,
): DocLine {
  return {
    id: newId(),
    bullet: line.bullet,
    parts: line.parts.map((part) => {
      if (part.kind === "text") return { kind: "text" as const, text: part.text };
      const question = byNumber.get(part.number);
      const stored = question?.correct_answers ?? [];
      return {
        kind: "gap" as const,
        id: newId(),
        // With a box the stored answer is a letter, and the words the author
        // reads are the option's — so nothing goes in the brackets.
        answers: optionIdOf ? [] : stored,
        optionId: optionIdOf
          ? (optionIdOf(stored[0]?.trim().toLowerCase() ?? "") ?? null)
          : null,
        replayStartMs: question?.replay_start_ms ?? null,
        replayEndMs: question?.replay_end_ms ?? null,
      };
    }),
  };
}

/** The inverse, for reopening a saved material. */
export function docFromGroup(
  template: string,
  questions: ListeningQuestion[],
  /** Letter -> the option it stands for, for a group printed with a box. */
  optionIdOf?: (letter: string) => string | undefined,
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
    if (block.kind === "flow") {
      doc.push({
        id: newId(),
        kind: "flow",
        steps: block.steps.map((step) => docLine(step, byNumber, optionIdOf)),
      });
      continue;
    }
    if (block.kind === "table") {
      doc.push({
        id: newId(),
        kind: "table",
        head: block.head,
        rows: block.rows.map((cells) => ({
          id: newId(),
          cells: cells.map((cell) => docLine(cell, byNumber, optionIdOf)),
        })),
      });
      continue;
    }
    doc.push({
      id: newId(),
      kind: "row",
      label: block.label,
      lines: block.lines.map((line) => docLine(line, byNumber, optionIdOf)),
    });
  }

  return doc.length > 0 ? doc : newDoc();
}

/** The document as layout, for rendering it exactly as the take page will. */
export function docToLayout(doc: DocBlock[]): FormBlock[] {
  const numbers = gapNumbers(doc);
  const line = (l: DocLine): FormLine => ({
    bullet: l.bullet,
    parts: l.parts.map((part) =>
      part.kind === "text"
        ? { kind: "text" as const, text: part.text }
        : { kind: "gap" as const, number: numbers.get(part.id) ?? 0 },
    ),
  });
  return doc.map((block) => {
    if (block.kind === "divider") return { kind: "divider" as const };
    if (block.kind === "row") {
      return {
        kind: "row" as const,
        label: block.label,
        lines: block.lines.map(line),
      };
    }
    if (block.kind === "flow") {
      return { kind: "flow" as const, steps: block.steps.map(line) };
    }
    if (block.kind === "table") {
      return {
        kind: "table" as const,
        head: block.head,
        rows: block.rows.map((row) => row.cells.map(line)),
      };
    }
    return { kind: block.kind, text: block.text };
  });
}

// ── Validation ───────────────────────────────────────────────────────────

/** Where a group's gaps get their letters, for the messages that have to name
 *  it. A word list printed under the task, the letters drawn on its picture,
 *  or neither — in which case the answers are words and there is no box to
 *  send anyone looking for. */
export type LetterSource = false | "box" | "picture";

/** What still has to be filled in, phrased for the author. Empty means it's
 *  publishable.
 *
 *  `offset` is how many questions come before this group in the material, so
 *  the numbers quoted are the ones printed beside the gaps rather than the
 *  1..N this group happens to store. */
export function docIssues(
  doc: DocBlock[],
  offset = 0,
  /** Where this group's letters come from, or false where its gaps are
   *  answered in words. It changes what a gap is missing — a letter rather
   *  than words — and, since the two kinds of box are in different places on
   *  the page, where to tell the author to look for one. */
  lettered: LetterSource = false,
): string[] {
  const gaps = docGaps(doc);
  if (gaps.length === 0) {
    return [
      lettered
        ? "No questions yet — put empty brackets, [], where a gap goes."
        : "No questions yet — put an answer in brackets, like [Chinese].",
    ];
  }
  const unanswered = gaps
    .filter((g) => !gapAnswered(g, !!lettered))
    .map((g) => g.number + offset);
  if (unanswered.length === 0) return [];
  if (lettered) {
    const from = lettered === "picture" ? "the picture" : "the box";
    return [
      unanswered.length === 1
        ? `Question ${unanswered[0]} has no letter from ${from} yet.`
        : `Questions ${unanswered.join(", ")} have no letter from ${from} yet.`,
    ];
  }
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
export function docPublishIssues(
  doc: DocBlock[],
  offset = 0,
  lettered: LetterSource = false,
): string[] {
  const issues = docIssues(doc, offset, lettered);
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

/** Whether the author has put anything of their own in yet. */
export function isDocEmpty(doc: DocBlock[]): boolean {
  const blank = (line: DocLine) =>
    line.parts.every((p) => p.kind === "text" && p.text.trim() === "");
  return doc.every((block) => {
    if (block.kind === "divider") return true;
    if (block.kind === "flow") return block.steps.every(blank);
    if (block.kind === "table") {
      return (
        block.head.every((cell) => !cell.trim()) &&
        block.rows.every((row) => row.cells.every(blank))
      );
    }
    if (block.kind !== "row") return block.text.trim() === "";
    if (block.label.trim()) return false;
    return block.lines.every(blank);
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

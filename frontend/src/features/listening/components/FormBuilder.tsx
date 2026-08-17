import { useEffect, useRef, useState } from "react";
import {
  AlignLeft,
  AudioLines,
  ChevronDown,
  ChevronUp,
  Columns2,
  CornerDownRight,
  Ellipsis,
  Heading,
  Minus,
  Plus,
  Table,
  Trash2,
  Type,
  Undo2,
  X,
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { ToolbarButton } from "@/features/listening/components/BuilderTools";
import { ValueField } from "@/features/listening/components/ValueField";
import { formatClock } from "@/features/studio/format";
import {
  gapNumbers,
  newId,
  newRow,
  newTable,
  newTableRow,
  newTextLine,
  type DocBlock,
  type DocLine,
  type DocPart,
} from "@/features/listening/form-syntax";

/**
 * The form builder. Structure comes from buttons, and a gap is made either by
 * typing `[answer]` where it goes — the same shorthand Wooclap uses — or by
 * selecting a word and pressing "blank". There is deliberately no other
 * syntax: the people writing these are teachers, not developers, and one
 * convention they can pick up in a second is a very different thing from a
 * markup language they have to learn.
 *
 * It is drawn as the printed form rather than as a stack of fields: a ruled
 * sheet, a title across the top, section headings, and a fixed label column.
 * The author is copying from a paper in front of them, so the closer the two
 * shapes are, the less there is to translate.
 *
 * A value line is a row of segments rather than one rich-text field. That
 * keeps the caret, selection and undo behaviour of ordinary inputs, which a
 * contentEditable would have thrown away in exchange for problems that are
 * genuinely hard to get right.
 */

type EditableEl = HTMLElement;

interface FormBuilderProps {
  doc: DocBlock[];
  /** Applied against the latest document, not the one this render was built
   *  from. Two structural edits can land between renders — Enter held down is
   *  enough — and a handler that computed from its own snapshot wrote the
   *  older one back, resurrecting deleted rows and duplicating live ones. */
  onChange: (edit: (current: DocBlock[]) => DocBlock[]) => void;
  /** How many questions come before this group in the material. Gaps store
   *  their place inside the group (1..N); what goes on the sheet is the
   *  number the candidate reads. */
  numberOffset?: number;
  /** Gap numbers reported as unanswered, highlighted so they're findable.
   *  In the same numbering as the sheet — i.e. already offset. */
  flaggedGaps?: number[];
  /** Per gap id: whether the answer is actually said inside the seconds the
   *  author marked, and where it is said instead. */
  markChecks?: Map<string, { found: boolean; heardAtMs: number | null }>;
  /** Reports what is selected inside a value, so the rubric row above can
   *  offer to turn it into an answer. */
  /** Asks the audio pane for the moment this gap is said. Asynchronous by
   *  nature: the author may still have to click the line, so the result comes
   *  back through the callback rather than as a return value. */
  onMarkAudio?: (
    answers: string[],
    apply: (range: { startMs: number; endMs: number }) => void,
  ) => void;
  /** Whether this task is one with a label column — a form. It decides which
   *  of the two "add something" buttons leads, and it opens the column on the
   *  row a brand-new form starts with. Nothing else: every block stays
   *  reachable from every task. */
  labelFirst?: boolean;
  /** Controls that belong to the group rather than to the form — adding
   *  another group after this one. They sit on the same row as the rest so
   *  everything that adds something is in one place. */
  extraTools?: React.ReactNode;
}

export function FormBuilder({
  doc,
  onChange,
  numberOffset = 0,
  flaggedGaps,
  markChecks,
  onMarkAudio,
  labelFirst,
  extraTools,
}: FormBuilderProps) {
  const numbers = new Map(
    [...gapNumbers(doc)].map(([id, number]) => [id, number + numberOffset]),
  );
  const flagged = new Set(flaggedGaps ?? []);

  // Inputs are registered by key so the caret can be placed after a change
  // that rebuilt them — otherwise typing would stop dead the moment a bracket
  // became a chip, or a new row would appear with the focus left behind.
  const inputs = useRef(new Map<string, EditableEl>());
  const pendingFocus = useRef<string | null>(null);
  const register = (key: string) => (el: EditableEl | null) => {
    if (el) inputs.current.set(key, el);
    else inputs.current.delete(key);
  };

  useEffect(() => {
    const key = pendingFocus.current;
    if (!key) return;
    // Held until the field it names actually exists, rather than cleared on
    // the first render after it was asked for. A menu item that opens a field
    // and then asks for the caret closes the menu too, and the menu's own
    // render lands first — so the request was being spent on a render where
    // there was nothing yet to focus, and the author's typing went to the
    // page instead, where the first space starts the recording playing.
    const el = inputs.current.get(key);
    if (!el) return;
    pendingFocus.current = null;
    el.focus();
    // A real field puts the caret at the end; the editable value region is
    // handed to the browser's own placement.
    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
      el.setSelectionRange(el.value.length, el.value.length);
    }
  });

  // A gap is selected by clicking it, which is what raises its toolbar. Kept
  // separate from editing so the toolbar can be reached without the answer
  // turning into a field under the pointer.
  // The word selected in a value right now. Held as the text, not a flag, so
  // the button can name what it is about to do rather than describe itself.
  const [selectedGap, setSelectedGap] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedGap) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null;
      if (target?.closest("[data-gap]")) return;
      setSelectedGap(null);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [selectedGap]);

  const replaceBlock = (id: string, next: DocBlock | null) =>
    onChange((current) =>
      next
        ? current.map((b) => (b.id === id ? next : b))
        : current.filter((b) => b.id !== id),
    );

  const moveBlock = (id: string, delta: number) =>
    onChange((current) => {
      const index = current.findIndex((b) => b.id === id);
      const to = index + delta;
      if (index < 0 || to < 0 || to >= current.length) return current;
      const next = current.slice();
      const [moved] = next.splice(index, 1);
      next.splice(to, 0, moved);
      return next;
    });

  /** New blocks land after the block being worked on, not at the very end —
   *  a form is built top to bottom, and having to drag every new row up from
   *  the bottom would undo the point of the button. */
  const insertAfter = (afterId: string, block: DocBlock, focusKey?: string) => {
    if (focusKey) pendingFocus.current = focusKey;
    onChange((current) => {
      const index = current.findIndex((b) => b.id === afterId);
      const next = current.slice();
      next.splice(index < 0 ? current.length : index + 1, 0, block);
      return next;
    });
  };

  /** Adds a block at the end. It used to land after whichever block was
   *  being worked on, which sounds helpful and isn't: a divider has nothing
   *  to focus, so it never became "current", and every row added after one
   *  went above it. A form is built top to bottom, so the end is both where
   *  the next thing goes and the only place that needs no explaining. */
  const addBlock = (block: DocBlock, focusKey?: string) => {
    if (focusKey) pendingFocus.current = focusKey;
    onChange((current) => [...current, block]);
  };

  /** A form has one title and it is the first thing on it, so this goes to
   *  the top rather than wherever the caret happens to be — which is also the
   *  answer to "how do I put something above the first row". */
  const addTitle = () => {
    const block: DocBlock = { id: newId(), kind: "title", text: "" };
    pendingFocus.current = `title#${block.id}`;
    onChange((current) => [block, ...current]);
  };

  const hasTitle = doc.some((b) => b.kind === "title");

  const patchLine = (blockId: string, lineId: string, next: DocLine) =>
    onChange((current) =>
      current.map((b) =>
        b.id === blockId && b.kind === "row"
          ? { ...b, lines: b.lines.map((l) => (l.id === lineId ? next : l)) }
          : b,
      ),
    );

  /** Puts a gap's words back into the sentence. Removing the chip outright
   *  would take the words with it, and they were the author's text before
   *  they were an answer. */
  const unblank = (gapId: string) => {
    onChange((current) =>
      current.map((b) =>
        b.kind !== "row"
          ? b
          : {
              ...b,
              lines: b.lines.map((l) => {
                if (!l.parts.some((p) => p.kind === "gap" && p.id === gapId)) {
                  return l;
                }
                const flattened = l.parts.map((p) =>
                  p.kind === "gap" && p.id === gapId
                    ? { kind: "text" as const, text: p.answers[0] ?? "" }
                    : p,
                );
                // Merge the text either side, so the line reads as one field
                // again rather than three stubs.
                const merged: DocPart[] = [];
                for (const part of flattened) {
                  const last = merged[merged.length - 1];
                  if (part.kind === "text" && last?.kind === "text") {
                    merged[merged.length - 1] = {
                      kind: "text",
                      text: last.text + part.text,
                    };
                  } else {
                    merged.push(part);
                  }
                }
                return { ...l, parts: merged };
              }),
            },
      ),
    );
  };

  /** Patches a gap wherever it is, by id. The value cell edits its own parts
   *  as text, so positions are its business, not this one's — and a mark can
   *  come back a click or two after it was asked for, by which time they may
   *  have moved. */
  const patchGapById = (
    gapId: string,
    patch: { replayStartMs: number | null; replayEndMs: number | null },
  ) => {
    onChange((current) =>
      current.map((b) =>
        b.kind !== "row"
          ? b
          : {
              ...b,
              lines: b.lines.map((l) => ({
                ...l,
                parts: l.parts.map((p) =>
                  p.kind === "gap" && p.id === gapId ? { ...p, ...patch } : p,
                ),
              })),
            },
      ),
    );
  };

  const addLine = (blockId: string) => {
    const block = doc.find((b) => b.id === blockId);
    if (!block || block.kind !== "row") return;
    // Plain, not bulleted: a second line under a label is often just more of
    // the same, and an author who wants a dash types one.
    const line = newTextLine();
    pendingFocus.current = `${line.id}#0`;
    replaceBlock(blockId, { ...block, lines: [...block.lines, line] });
  };

  /** Rows the author has asked for a label on but not yet typed one into.
   *
   *  What a row is, once it is stored, is decided by its label: with one it is
   *  a form row, without one it runs the full width as a note or a sentence.
   *  That leaves the field with nowhere to live in between — a label is empty
   *  for as long as it takes to type the first letter of it.
   *
   *  A row stays here until the author says otherwise, which is "Remove
   *  label" in its menu. It used to leave on blur, on the reading that a
   *  label left empty was never wanted — but blur is every click anywhere
   *  else, so adding a row and then reaching for the section button, or
   *  simply for the row's own value, collapsed the column out from under a
   *  row that had been asked for a moment earlier.
   *
   *  Not persisted, and not meant to be: a row reopened tomorrow with an
   *  empty label is a full-width line, which is exactly what it is. */
  const [labelling, setLabelling] = useState<Set<string>>(() =>
    // A form opens with its label column showing, because the row it opens
    // with is the only thing on the sheet and there is nothing else to infer
    // it from. Narrow on purpose: a form reopened later has its labels
    // written, and any row in it the author deliberately left labelless is a
    // full-width line and stays one.
    labelFirst && doc.length === 1 && doc[0].kind === "row" && !doc[0].label
      ? new Set([doc[0].id])
      : new Set(),
  );

  /** The row whose label column has just been opened from the menu, waiting
   *  for the caret.
   *
   *  A menu hands focus back to its own trigger as it closes, and it does so
   *  after everything this render schedules — a frame later was still too
   *  early, and the caret ended up on the trigger, where the author's next
   *  space re-opened the menu they had just used. Closing is the moment to
   *  place it, and closing is a thing the menu tells us about. */
  const focusLabelOnClose = useRef<string | null>(null);

  const openLabel = (blockId: string) => {
    focusLabelOnClose.current = blockId;
    editLabelling(blockId, true);
  };
  const editLabelling = (id: string, keep: boolean) =>
    setLabelling((current) => {
      const next = new Set(current);
      if (keep) next.add(id);
      else next.delete(id);
      return next;
    });

  const showsLabel = (block: DocBlock): boolean =>
    block.kind === "row" && (block.label.trim() !== "" || labelling.has(block.id));

  /** Adds a block below, shaped like the one being worked in: Enter at the end
   *  of a form row starts another form row, and Enter at the end of a note
   *  starts another note. The caret goes wherever there is something to type
   *  next — the label, or straight into the text where there is no label. */
  const addSibling = (afterId: string, withLabel: boolean) => {
    const row = newRow();
    if (withLabel) editLabelling(row.id, true);
    insertAfter(
      afterId,
      row,
      withLabel ? `label#${row.id}` : `${row.lines[0].id}#0`,
    );
  };

  /** Any edit to a table, against the latest copy of it. Written as one
   *  helper because every one of them has to leave the grid rectangular:
   *  a column added to the header is a cell added to every row, and a column
   *  removed takes its cell out of each. A ragged table renders as a grid with
   *  holes, and the holes move as soon as anything is typed. */
  const editTable = (
    blockId: string,
    edit: (table: Extract<DocBlock, { kind: "table" }>) => DocBlock,
  ) =>
    onChange((current) =>
      current.map((b) => (b.id === blockId && b.kind === "table" ? edit(b) : b)),
    );

  const patchCell = (
    blockId: string,
    rowId: string,
    cellId: string,
    parts: DocPart[],
  ) =>
    editTable(blockId, (table) => ({
      ...table,
      rows: table.rows.map((row) =>
        row.id === rowId
          ? {
              ...row,
              cells: row.cells.map((cell) =>
                cell.id === cellId ? { ...cell, parts } : cell,
              ),
            }
          : row,
      ),
    }));

  const addColumn = (blockId: string) =>
    editTable(blockId, (table) => ({
      ...table,
      head: [...table.head, ""],
      rows: table.rows.map((row) => ({
        ...row,
        cells: [...row.cells, newTextLine()],
      })),
    }));

  const removeColumn = (blockId: string, index: number) =>
    editTable(blockId, (table) =>
      table.head.length <= 1
        ? table
        : {
            ...table,
            head: table.head.filter((_cell, i) => i !== index),
            rows: table.rows.map((row) => ({
              ...row,
              cells: row.cells.filter((_cell, i) => i !== index),
            })),
          },
    );

  const addTableRow = (blockId: string) => {
    const block = doc.find((b) => b.id === blockId);
    if (!block || block.kind !== "table") return;
    const row = newTableRow(block.head.length);
    pendingFocus.current = `${row.cells[0].id}#0`;
    editTable(blockId, (table) => ({ ...table, rows: [...table.rows, row] }));
  };

  const removeTableRow = (blockId: string, rowId: string) =>
    editTable(blockId, (table) =>
      table.rows.length <= 1
        ? table
        : { ...table, rows: table.rows.filter((row) => row.id !== rowId) },
    );

  const removeLine = (blockId: string, lineId: string) => {
    const block = doc.find((b) => b.id === blockId);
    if (!block || block.kind !== "row" || block.lines.length <= 1) return;
    replaceBlock(blockId, {
      ...block,
      lines: block.lines.filter((l) => l.id !== lineId),
    });
  };

  const addRowTool = (
    <ToolbarButton
      key="row"
      onClick={() => {
        const row = newRow();
        editLabelling(row.id, true);
        addBlock(row, `label#${row.id}`);
      }}
      icon={<Plus className="size-3.5" aria-hidden />}
      label="row"
      title="Add a labelled row at the end — for a form"
    />
  );

  const addLineTool = (
    <ToolbarButton
      key="line"
      onClick={() => {
        const row = newRow();
        addBlock(row, `${row.lines[0].id}#0`);
      }}
      icon={<AlignLeft className="size-3.5" aria-hidden />}
      label="line"
      title="Add a full-width line at the end — for notes, sentences and short answers"
    />
  );

  const addTableTool = (
    <ToolbarButton
      key="table"
      onClick={() => addBlock(newTable())}
      icon={<Table className="size-3.5" aria-hidden />}
      label="table"
      title="Add a table at the end"
    />
  );

  return (
    <div>
      {/* Full width, ending on the same line as the header and the
          instructions above it. The row controls live inside it: one small
          trigger at the row's end costs a corner of the value it may sit over,
          which is cheaper than a permanently empty lane or a sheet that stops
          short of everything else. */}
      <div className="rounded-lg border border-border bg-card [&>*:first-child]:rounded-t-lg [&>*:last-child]:rounded-b-lg">
        {doc.map((block, blockIndex) => {
          const labelShown = showsLabel(block);
          return (
          <div key={block.id} className="group/block relative">
            <div className="flex items-start">
              <div className="min-w-0 flex-1">
                {block.kind === "divider" && (
                  // A plain rule until it's reached for. Its controls sit on
                  // the line itself rather than behind a menu: there are only
                  // three, and a rule has nothing else to say — a trigger
                  // would be one more thing to open to find that out.
                  <div className="relative px-3">
                    <div className="h-px bg-border" role="separator" />
                    <span className="absolute top-1/2 right-3 flex -translate-y-1/2 items-center gap-0.5 rounded bg-card pl-1.5 opacity-0 transition-opacity group-focus-within/block:opacity-100 group-hover/block:opacity-100">
                      <RuleButton
                        label="Move up"
                        onClick={() => moveBlock(block.id, -1)}
                        disabled={blockIndex === 0}
                        icon={<ChevronUp className="size-3.5" aria-hidden />}
                      />
                      <RuleButton
                        label="Move down"
                        onClick={() => moveBlock(block.id, 1)}
                        disabled={blockIndex === doc.length - 1}
                        icon={<ChevronDown className="size-3.5" aria-hidden />}
                      />
                      <RuleButton
                        label="Remove this rule"
                        onClick={() => replaceBlock(block.id, null)}
                        danger
                        icon={<X className="size-3.5" aria-hidden />}
                      />
                    </span>
                  </div>
                )}

                {block.kind === "title" && (
                  <input
                    type="text"
                    ref={register(`title#${block.id}`)}
                    value={block.text}
                    onChange={(e) =>
                      replaceBlock(block.id, { ...block, text: e.target.value })
                    }
                    placeholder="Form title"
                    aria-label="Form title"
                    className="w-full bg-transparent px-3 py-2.5 text-center text-base font-semibold tracking-wide text-foreground uppercase placeholder:font-normal placeholder:normal-case placeholder:text-muted-foreground focus:outline-none"
                  />
                )}

                {block.kind === "heading" && (
                  <input
                    type="text"
                    ref={register(`heading#${block.id}`)}
                    value={block.text}
                    onChange={(e) =>
                      replaceBlock(block.id, { ...block, text: e.target.value })
                    }
                    placeholder="Section heading"
                    aria-label="Section heading"
                    className="w-full bg-transparent px-3 py-1.5 text-base font-medium text-primary placeholder:font-normal placeholder:text-muted-foreground focus:outline-none"
                  />
                )}

                {block.kind === "table" && (
                  // A real table, so the columns size themselves to what is in
                  // them the way the printed grid does. The trailing narrow
                  // column is the controls': a plus in its header adds a
                  // column, an × on each row takes that row out.
                  <div className="overflow-x-auto px-3 py-2">
                    <table className="w-full border-collapse">
                      <thead>
                        <tr>
                          {block.head.map((cell, index) => (
                            <th
                              key={index}
                              scope="col"
                              className="group/col relative border border-border bg-foreground/5 p-0 text-left align-middle"
                            >
                              <input
                                type="text"
                                value={cell}
                                onChange={(e) =>
                                  editTable(block.id, (table) => ({
                                    ...table,
                                    head: table.head.map((h, i) =>
                                      i === index ? e.target.value : h,
                                    ),
                                  }))
                                }
                                placeholder="Column"
                                aria-label={`Column ${index + 1} heading`}
                                className="w-full bg-transparent px-2.5 py-1.5 pr-7 text-base font-medium text-foreground placeholder:font-normal placeholder:text-muted-foreground/50 focus:outline-none"
                              />
                              {/* One column is the fewest a table can have;
                                  below that there is no grid. */}
                              {block.head.length > 1 && (
                                <button
                                  type="button"
                                  onClick={() => removeColumn(block.id, index)}
                                  aria-label={`Remove column ${index + 1}`}
                                  title="Remove this column"
                                  className="absolute top-1/2 right-1 flex size-6 -translate-y-1/2 items-center justify-center rounded text-muted-foreground opacity-0 transition-opacity group-hover/col:opacity-100 hover:text-destructive focus-visible:opacity-100"
                                >
                                  <X className="size-3.5" aria-hidden />
                                </button>
                              )}
                            </th>
                          ))}
                          <th scope="col" className="w-8 p-0 align-middle">
                            <button
                              type="button"
                              onClick={() => addColumn(block.id)}
                              aria-label="Add a column"
                              title="Add a column"
                              className="flex size-8 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-foreground/8 hover:text-primary"
                            >
                              <Plus className="size-3.5" aria-hidden />
                            </button>
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {block.rows.map((row, rowIndex) => (
                          <tr key={row.id} className="group/row">
                            {row.cells.map((cell) => (
                              <td
                                key={cell.id}
                                className="border border-border px-2.5 py-1 align-top"
                              >
                                <ValueField
                                  line={cell}
                                  numbers={numbers}
                                  flagged={flagged}
                                  markChecks={markChecks}
                                  selectedGap={selectedGap}
                                  onSelectGap={setSelectedGap}
                                  registerInput={register(`${cell.id}#0`)}
                                  onEnter={() => addTableRow(block.id)}
                                  onChange={(parts) =>
                                    patchCell(block.id, row.id, cell.id, parts)
                                  }
                                  renderGapActions={(gapId) => {
                                    const gap = cell.parts.find(
                                      (p) => p.kind === "gap" && p.id === gapId,
                                    );
                                    if (!gap || gap.kind !== "gap") return null;
                                    return (
                                      <GapActions
                                        gapId={gapId}
                                        replayStartMs={gap.replayStartMs ?? null}
                                        replayEndMs={gap.replayEndMs ?? null}
                                        markCheck={markChecks?.get(gapId)}
                                        onMark={
                                          onMarkAudio
                                            ? () =>
                                                onMarkAudio(
                                                  gap.answers,
                                                  (range) =>
                                                    patchGapById(gapId, {
                                                      replayStartMs: range.startMs,
                                                      replayEndMs: range.endMs,
                                                    }),
                                                )
                                            : undefined
                                        }
                                        onClearMark={() =>
                                          patchGapById(gapId, {
                                            replayStartMs: null,
                                            replayEndMs: null,
                                          })
                                        }
                                        onUnblank={() => {
                                          setSelectedGap(null);
                                          unblank(gapId);
                                        }}
                                      />
                                    );
                                  }}
                                />
                              </td>
                            ))}
                            <td className="w-8 p-0 align-middle">
                              {block.rows.length > 1 && (
                                <button
                                  type="button"
                                  onClick={() => removeTableRow(block.id, row.id)}
                                  aria-label={`Remove row ${rowIndex + 1}`}
                                  title="Remove this row"
                                  className="flex size-8 items-center justify-center rounded text-muted-foreground opacity-0 transition-opacity group-hover/row:opacity-100 hover:text-destructive focus-visible:opacity-100"
                                >
                                  <X className="size-3.5" aria-hidden />
                                </button>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>

                    <button
                      type="button"
                      onClick={() => addTableRow(block.id)}
                      title="Add a row to the table"
                      className="group/addrow mt-1 flex items-center gap-1.5 text-left"
                    >
                      <span className="flex size-5 items-center justify-center rounded border border-dashed border-border text-muted-foreground transition-colors group-hover/addrow:border-primary group-hover/addrow:text-primary">
                        <Plus className="size-3" aria-hidden />
                      </span>
                      <span className="text-sm text-muted-foreground/60 transition-colors group-hover/addrow:text-foreground">
                        add a row
                      </span>
                    </button>
                  </div>
                )}

                {block.kind === "row" && (
                  <div className="transition-colors group-hover/block:bg-foreground/[0.02]">
                    {/* Each line is its own full-width row rather than a stack
                        inside the value cell. That puts every line's right
                        edge on the sheet's edge, so its control can sit in the
                        gutter beside it instead of on top of the text — and it
                        runs the rule between the columns down the whole row,
                        the way the printed table does. */}
                    {block.lines.map((line, lineIndex) => (
                      <div key={line.id} className="group/line relative flex">
                        {/* Absent, not empty, on a row with no label: the
                            column and the rule beside it are what make a form
                            look like a form, and holding them open over a note
                            is what pushed every note a quarter of the way
                            across the sheet. */}
                        {labelShown && (
                          <div className="w-64 shrink-0">
                            {lineIndex === 0 && (
                              <input
                                type="text"
                                value={block.label}
                                // Findable from outside the render that made
                                // it — see `openLabel`.
                                data-label-for={block.id}
                                ref={register(`label#${block.id}`)}
                                onChange={(e) =>
                                  replaceBlock(block.id, {
                                    ...block,
                                    label: e.target.value,
                                  })
                                }
                                onKeyDown={(e) => {
                                  if (e.key !== "Enter") return;
                                  e.preventDefault();
                                  pendingFocus.current = `${block.lines[0].id}#0`;
                                  // No edit — the pendingFocus effect just
                                  // needs a render to move into the value.
                                  onChange((current) => [...current]);
                                }}
                                placeholder="Label"
                                aria-label="Row label"
                                title={block.label}
                                // The same line box as the value beside it
                                // (leading-7 + py-1): the two columns
                                // read as one line, so a half-step
                                // between them shows.
                                className="w-full bg-transparent px-3 py-1 text-base leading-8 text-foreground placeholder:text-muted-foreground/50 focus:outline-none"
                              />
                            )}
                          </div>
                        )}

                        <div
                          className={cn(
                            "flex min-w-0 flex-1 items-center gap-1 px-3 py-1",
                            labelShown && "border-l border-border/60",
                          )}
                        >
                          {line.bullet && (
                            <span
                              aria-hidden
                              className="shrink-0 text-muted-foreground"
                            >
                              –
                            </span>
                          )}
                          <ValueField
                            line={line}
                            numbers={numbers}
                            flagged={flagged}
                            markChecks={markChecks}
                            selectedGap={selectedGap}
                            onSelectGap={setSelectedGap}
                            placeholder={
                              lineIndex > 0
                                ? undefined
                                : labelShown
                                  ? "Value"
                                  : "Sentence, note or question"
                            }
                            onEnter={() => addSibling(block.id, labelShown)}
                            onShiftEnter={() => addLine(block.id)}
                            registerInput={register(`${line.id}#0`)}
                            onChange={(parts) =>
                              patchLine(block.id, line.id, { ...line, parts })
                            }
                            renderGapActions={(gapId) => {
                              const gap = line.parts.find(
                                (p) => p.kind === "gap" && p.id === gapId,
                              );
                              if (!gap || gap.kind !== "gap") return null;
                              return (
                                <GapActions
                                  gapId={gapId}
                                  replayStartMs={gap.replayStartMs ?? null}
                                  replayEndMs={gap.replayEndMs ?? null}
                                  markCheck={markChecks?.get(gapId)}
                                  onMark={
                                    onMarkAudio
                                      ? () =>
                                          onMarkAudio(gap.answers, (range) =>
                                            patchGapById(gapId, {
                                              replayStartMs: range.startMs,
                                              replayEndMs: range.endMs,
                                            }),
                                          )
                                      : undefined
                                  }
                                  onClearMark={() =>
                                    patchGapById(gapId, {
                                      replayStartMs: null,
                                      replayEndMs: null,
                                    })
                                  }
                                  onUnblank={() => {
                                    setSelectedGap(null);
                                    unblank(gapId);
                                  }}
                                />
                              );
                            }}
                          />
                        </div>

                        {/* Only the added lines carry one: the first line is
                            the row, and removing that is Delete in the row's
                            own menu — which also owns this spot. */}
                        {lineIndex > 0 && (
                          <button
                            type="button"
                            onClick={() => removeLine(block.id, line.id)}
                            aria-label="Remove line"
                            title="Remove line"
                            className="absolute top-1 right-1 flex size-7 items-center justify-center rounded-md bg-card text-muted-foreground opacity-0 shadow-sm transition-opacity group-hover/line:opacity-100 hover:text-destructive focus-visible:opacity-100"
                          >
                            <X className="size-3.5" aria-hidden />
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* One trigger rather than four buttons: a 36px gutter is what
                  a row's height affords, and four icons only ever fitted by
                  sitting on top of the text. */}
              {block.kind !== "divider" && (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <button
                      type="button"
                      title="Row actions"
                      aria-label="Row actions"
                      // Hover only, plus its own focus: `group-focus-within`
                      // meant it appeared the moment the value beside it was
                      // typed into, sitting on the words being written.
                      className="absolute top-1 right-1 flex size-7 items-center justify-center rounded-md bg-card text-muted-foreground opacity-0 shadow-sm transition-opacity group-hover/block:opacity-100 hover:text-foreground focus-visible:opacity-100 data-[state=open]:opacity-100"
                    >
                      <Ellipsis className="size-4" aria-hidden />
                    </button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent
                    align="end"
                    className="w-52"
                    onCloseAutoFocus={(e) => {
                      const target = focusLabelOnClose.current;
                      focusLabelOnClose.current = null;
                      if (!target) return;
                      const el = document.querySelector<HTMLInputElement>(
                        `[data-label-for="${target}"]`,
                      );
                      // Not there after all — let the menu put focus back
                      // where it normally would rather than dropping it.
                      if (!el) return;
                      e.preventDefault();
                      el.focus();
                    }}
                  >
                    {block.kind === "row" && (
                      <DropdownMenuItem onClick={() => addLine(block.id)}>
                        <CornerDownRight aria-hidden />
                        Continue below
                        <DropdownMenuShortcut>⇧↵</DropdownMenuShortcut>
                      </DropdownMenuItem>
                    )}
                    {/* What kind of block this is, said as the one thing that
                        decides it. A label makes it a form row; without one it
                        runs the whole width, which is what a note, a sentence
                        and a short-answer question all are. */}
                    {block.kind === "row" &&
                      (labelShown ? (
                        <DropdownMenuItem
                          onClick={() => {
                            editLabelling(block.id, false);
                            replaceBlock(block.id, { ...block, label: "" });
                          }}
                        >
                          <AlignLeft aria-hidden />
                          Remove label
                        </DropdownMenuItem>
                      ) : (
                        <DropdownMenuItem onClick={() => openLabel(block.id)}>
                          <Columns2 aria-hidden />
                          Add label
                        </DropdownMenuItem>
                      ))}
                    <DropdownMenuItem
                      onClick={() => moveBlock(block.id, -1)}
                      disabled={blockIndex === 0}
                    >
                      <ChevronUp aria-hidden />
                      Move up
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onClick={() => moveBlock(block.id, 1)}
                      disabled={blockIndex === doc.length - 1}
                    >
                      <ChevronDown aria-hidden />
                      Move down
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      variant="destructive"
                      onClick={() => replaceBlock(block.id, null)}
                    >
                      <Trash2 aria-hidden />
                      Delete
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            </div>
          </div>
          );
        })}
      </div>

      {/* Under the sheet, where a new row goes. `title` is the exception: a
          form has one and it belongs at the top, which is also how something
          gets above the first row. What each does is in the tooltips and in
          the help card at the foot of the editor — captions alongside them
          only ever got read once, then sat there. */}
      <div className="mt-2.5 flex flex-wrap items-center justify-center gap-1.5">
        {/* Two ways to add something to write in, because there are two
            shapes on the paper and neither is a special case of the other. A
            row has a label column — the form and the table. A line runs the
            whole width — the notes, the sentences, the summary, the
            short-answer questions. Whichever this task is mostly made of
            leads; the other is still there, because a real paper mixes them. */}
        {labelFirst
          ? [addRowTool, addLineTool, addTableTool]
          : [addLineTool, addRowTool, addTableTool]}
        <ToolbarButton
          onClick={() => {
            const block: DocBlock = { id: newId(), kind: "heading", text: "" };
            addBlock(block, `heading#${block.id}`);
          }}
          icon={<Heading className="size-3.5" aria-hidden />}
          label="section"
          title="Add a section heading at the end"
        />
        <ToolbarButton
          onClick={() => {
            const block: DocBlock = { id: newId(), kind: "divider" };
            addBlock(block);
          }}
          icon={<Minus className="size-3.5" aria-hidden />}
          label="divider"
          title="Add a rule at the end"
        />
        {!hasTitle && (
          <ToolbarButton
            onClick={addTitle}
            icon={<Type className="size-3.5" aria-hidden />}
            label="title"
            title="Add the form's title at the top"
          />
        )}
        {extraTools}
      </div>
    </div>
  );
}

/** One of the rule's own controls: small, quiet, and on the line. */
function RuleButton({
  label,
  onClick,
  icon,
  danger,
  disabled,
}: {
  label: string;
  onClick: () => void;
  icon: React.ReactNode;
  danger?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      className={cn(
        "flex size-6 items-center justify-center rounded text-muted-foreground transition-colors disabled:opacity-30",
        danger
          ? "hover:bg-foreground/8 hover:text-destructive"
          : "hover:bg-foreground/8 hover:text-foreground",
      )}
    >
      {icon}
    </button>
  );
}

/** A selected gap's actions, floating over it. The chip itself is drawn
 *  inside the editable text — these are the things that belong to the gap
 *  rather than to the sentence: where it is said, and putting its words back. */
function GapActions({
  gapId,
  replayStartMs,
  replayEndMs,
  markCheck,
  onMark,
  onClearMark,
  onUnblank,
}: {
  gapId: string;
  replayStartMs: number | null;
  replayEndMs: number | null;
  markCheck?: { found: boolean; heardAtMs: number | null };
  onMark?: () => void;
  onClearMark: () => void;
  onUnblank: () => void;
}) {
  const marked = replayStartMs != null;
  const mismatch = marked && markCheck?.found === false;
  const [position, setPosition] = useState<{
    left: number;
    top: number;
  } | null>(null);

  // Anchored to the chip by measurement rather than by nesting: nothing React
  // renders may live inside the editable region, or typing near it would
  // reconcile the text around the caret.
  useEffect(() => {
    const chip = document.querySelector<HTMLElement>(`[data-gap="${gapId}"]`);
    const host = chip?.offsetParent as HTMLElement | null;
    if (!chip || !host) return;
    setPosition({ left: chip.offsetLeft, top: chip.offsetTop });
  }, [gapId]);

  if (!position) return null;

  return (
    <span
      data-gap={gapId}
      style={{ left: position.left, top: position.top }}
      className="absolute z-30 -translate-y-full pb-1"
    >
      <span className="flex w-max items-center gap-1 rounded-lg border border-border bg-card p-1 shadow-lg">
        <GapAction
          label={
            marked
              ? `Said at ${formatClock(replayStartMs ?? 0) ?? "0:00"}–${formatClock(replayEndMs ?? 0) ?? "0:00"} — press to re-mark`
              : "Mark where this is said in the recording"
          }
          onClick={onMark}
          active={marked}
          disabled={!onMark}
          icon={<AudioLines className="size-3" aria-hidden />}
        />
        {marked && (
          <GapAction
            label="Clear the audio mark"
            onClick={onClearMark}
            icon={<Undo2 className="size-4" aria-hidden />}
          />
        )}
        <span className="mx-0.5 h-5 w-px bg-border" aria-hidden />
        <GapAction
          label="Put the words back into the sentence"
          onClick={onUnblank}
          danger
          icon={<Trash2 className="size-4" aria-hidden />}
        />
        {mismatch && (
          <span className="border-l border-border px-2 text-xs whitespace-nowrap text-warning">
            {markCheck?.heardAtMs != null
              ? `heard at ${formatClock(markCheck.heardAtMs) ?? "0:00"}`
              : "not said there"}
          </span>
        )}
      </span>
    </span>
  );
}

function GapAction({
  label,
  onClick,
  icon,
  active,
  danger,
  disabled,
}: {
  label: string;
  onClick?: () => void;
  icon: React.ReactNode;
  active?: boolean;
  danger?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      className={cn(
        "flex size-8 items-center justify-center rounded-md transition-colors",
        active && "bg-primary/15 text-primary",
        !active && "text-muted-foreground",
        disabled
          ? "cursor-default opacity-40"
          : danger
            ? "hover:bg-foreground/8 hover:text-destructive"
            : "hover:bg-foreground/8 hover:text-foreground",
      )}
    >
      {icon}
    </button>
  );
}

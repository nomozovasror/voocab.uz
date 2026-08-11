import { useEffect, useRef, useState } from "react";
import {
  AudioLines,
  ChevronDown,
  ChevronUp,
  CornerDownRight,
  Heading,
  Pencil,
  Plus,
  SquareDashed,
  Trash2,
  Type,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  gapNumbers,
  newId,
  newRow,
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

/** A completed `[...]` in a value: the author's shorthand for a gap. */
const BRACKET_RE = /\[([^\]]*)\]/;

interface FormBuilderProps {
  doc: DocBlock[];
  onChange: (doc: DocBlock[]) => void;
  /** Gap numbers reported as unanswered, highlighted so they're findable. */
  flaggedGaps?: number[];
}

/** An input that grows with its content, so a gap sits in the sentence
 *  instead of after a field that runs to the edge. `ch` tracks the digit
 *  width, close enough for a proportional face given the padding. */
function AutoInput({
  value,
  onChange,
  placeholder,
  className,
  min = 6,
  pad = 1,
  inputRef,
  onKeyDown,
  onSelectCapture,
  ariaLabel,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  className?: string;
  min?: number;
  /** Slack after the text, in ch. The default leaves room for the caret; a
   *  chip's answer wants almost none, or the gap before its slash reads as a
   *  hole in the sentence. */
  pad?: number;
  inputRef?: (el: HTMLInputElement | null) => void;
  onKeyDown?: (e: React.KeyboardEvent<HTMLInputElement>) => void;
  onSelectCapture?: (e: React.SyntheticEvent<HTMLInputElement>) => void;
  ariaLabel: string;
}) {
  const width = Math.max(min, (value.length || (placeholder?.length ?? 0)) + pad);
  return (
    <input
      ref={inputRef}
      type="text"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={onKeyDown}
      onSelect={onSelectCapture}
      placeholder={placeholder}
      aria-label={ariaLabel}
      style={{ width: `${width}ch` }}
      className={cn(
        "max-w-full rounded bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus:outline-none",
        className,
      )}
    />
  );
}

export function FormBuilder({ doc, onChange, flaggedGaps }: FormBuilderProps) {
  const numbers = gapNumbers(doc);
  const flagged = new Set(flaggedGaps ?? []);

  // Inputs are registered by key so the caret can be placed after a change
  // that rebuilt them — otherwise typing would stop dead the moment a bracket
  // became a chip, or a new row would appear with the focus left behind.
  const inputs = useRef(new Map<string, HTMLInputElement>());
  const pendingFocus = useRef<string | null>(null);
  const register = (key: string) => (el: HTMLInputElement | null) => {
    if (el) inputs.current.set(key, el);
    else inputs.current.delete(key);
  };

  useEffect(() => {
    const key = pendingFocus.current;
    if (!key) return;
    pendingFocus.current = null;
    const el = inputs.current.get(key);
    if (!el) return;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  });

  // A gap is selected by clicking it, which is what raises its toolbar. Kept
  // separate from editing so the toolbar can be reached without the answer
  // turning into a field under the pointer.
  const [selectedGap, setSelectedGap] = useState<string | null>(null);
  const [editingGap, setEditingGap] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedGap && !editingGap) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null;
      if (target?.closest("[data-gap]")) return;
      setSelectedGap(null);
      setEditingGap(null);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [selectedGap, editingGap]);

  // Where the caret last was, so the toolbar's "blank" knows what to split.
  const focus = useRef<{
    blockId: string;
    lineId: string;
    partIndex: number;
    start: number;
    end: number;
  } | null>(null);

  const replaceBlock = (id: string, next: DocBlock | null) =>
    onChange(
      next
        ? doc.map((b) => (b.id === id ? next : b))
        : doc.filter((b) => b.id !== id),
    );

  const moveBlock = (index: number, delta: number) => {
    const to = index + delta;
    if (to < 0 || to >= doc.length) return;
    const next = doc.slice();
    const [moved] = next.splice(index, 1);
    next.splice(to, 0, moved);
    onChange(next);
  };

  /** New blocks land after the block being worked on, not at the very end —
   *  a form is built top to bottom, and having to drag every new row up from
   *  the bottom would undo the point of the button. */
  const insertAfter = (index: number, block: DocBlock, focusKey?: string) => {
    const next = doc.slice();
    next.splice(index + 1, 0, block);
    if (focusKey) pendingFocus.current = focusKey;
    onChange(next);
  };

  const appendBlock = (block: DocBlock, focusKey?: string) => {
    if (focusKey) pendingFocus.current = focusKey;
    onChange([...doc, block]);
  };

  const patchLine = (blockId: string, lineId: string, next: DocLine) =>
    onChange(
      doc.map((b) =>
        b.id === blockId && b.kind === "row"
          ? { ...b, lines: b.lines.map((l) => (l.id === lineId ? next : l)) }
          : b,
      ),
    );

  /** Turns the selected word into a gap, the selection becoming its first
   *  accepted answer — the word an author picks out of the sentence is almost
   *  always the answer, so it saves retyping it. */
  const makeGap = () => {
    const at = focus.current;
    if (!at) return;
    const block = doc.find((b) => b.id === at.blockId);
    if (!block || block.kind !== "row") return;
    const line = block.lines.find((l) => l.id === at.lineId);
    if (!line) return;
    const part = line.parts[at.partIndex];
    if (!part || part.kind !== "text") return;

    // Read the selection off the input itself rather than trusting the last
    // `select` event: a click elsewhere can leave that snapshot collapsed at
    // 0, which produced an empty gap with the word stranded beside it.
    const el = inputs.current.get(`${at.lineId}#${at.partIndex}`);
    let start = el?.selectionStart ?? at.start;
    let end = el?.selectionEnd ?? at.end;

    // Nothing selected: the author means "this value is the answer". Taking
    // the whole field is the only reading that isn't a no-op, and it's what
    // pressing the button on a finished value plainly looks like it does.
    if (start === end && part.text.trim()) {
      start = 0;
      end = part.text.length;
    }

    const before = part.text.slice(0, start);
    const picked = part.text.slice(start, end).trim();
    const after = part.text.slice(end);

    const parts: DocPart[] = [
      ...line.parts.slice(0, at.partIndex),
      { kind: "text", text: before },
      { kind: "gap", id: newId(), answers: picked ? [picked] : [] },
      { kind: "text", text: after },
      ...line.parts.slice(at.partIndex + 1),
    ];
    patchLine(at.blockId, at.lineId, { ...line, parts });
  };

  /** Removing a gap stitches the text either side back together, so the
   *  sentence reads as one field again rather than two stubs. */
  const removeGap = (blockId: string, lineId: string, partIndex: number) => {
    const block = doc.find((b) => b.id === blockId);
    if (!block || block.kind !== "row") return;
    const line = block.lines.find((l) => l.id === lineId);
    if (!line) return;
    const parts = line.parts.slice();
    const before = parts[partIndex - 1];
    const after = parts[partIndex + 1];
    if (before?.kind === "text" && after?.kind === "text") {
      parts.splice(partIndex - 1, 3, {
        kind: "text",
        text: before.text + after.text,
      });
    } else {
      parts.splice(partIndex, 1);
    }
    patchLine(blockId, lineId, { ...line, parts });
  };

  const setAnswer = (
    blockId: string,
    lineId: string,
    partIndex: number,
    answerIndex: number,
    value: string,
  ) => {
    const block = doc.find((b) => b.id === blockId);
    if (!block || block.kind !== "row") return;
    const line = block.lines.find((l) => l.id === lineId);
    if (!line) return;
    const parts = line.parts.map((p, i) => {
      if (i !== partIndex || p.kind !== "gap") return p;
      const answers = p.answers.length > 0 ? p.answers.slice() : [""];
      answers[answerIndex] = value;
      return { ...p, answers };
    });
    patchLine(blockId, lineId, { ...line, parts });
  };

  const addAlt = (blockId: string, lineId: string, partIndex: number) => {
    const block = doc.find((b) => b.id === blockId);
    if (!block || block.kind !== "row") return;
    const line = block.lines.find((l) => l.id === lineId);
    if (!line) return;
    const parts = line.parts.map((p, i) =>
      i === partIndex && p.kind === "gap"
        ? { ...p, answers: [...(p.answers.length ? p.answers : [""]), ""] }
        : p,
    );
    patchLine(blockId, lineId, { ...line, parts });
  };

  const setText = (
    blockId: string,
    lineId: string,
    partIndex: number,
    value: string,
  ) => {
    const block = doc.find((b) => b.id === blockId);
    if (!block || block.kind !== "row") return;
    const line = block.lines.find((l) => l.id === lineId);
    if (!line) return;

    // Typing `[Chinese]` — or `[key, keys]` — turns into a gap the moment the
    // closing bracket lands, and the caret carries on in the text after it.
    const bracket = BRACKET_RE.exec(value);
    if (bracket) {
      const answers = bracket[1]
        .split(",")
        .map((a) => a.trim())
        .filter(Boolean);
      const parts: DocPart[] = [
        ...line.parts.slice(0, partIndex),
        { kind: "text", text: value.slice(0, bracket.index) },
        { kind: "gap", id: newId(), answers },
        { kind: "text", text: value.slice(bracket.index + bracket[0].length) },
        ...line.parts.slice(partIndex + 1),
      ];
      pendingFocus.current = `${lineId}#${partIndex + 2}`;
      patchLine(blockId, lineId, { ...line, parts });
      return;
    }

    const parts = line.parts.map((p, i) =>
      i === partIndex && p.kind === "text" ? { ...p, text: value } : p,
    );
    patchLine(blockId, lineId, { ...line, parts });
  };

  const addLine = (blockId: string) => {
    const block = doc.find((b) => b.id === blockId);
    if (!block || block.kind !== "row") return;
    const line = { ...newTextLine(), bullet: true };
    pendingFocus.current = `${line.id}#0`;
    replaceBlock(blockId, { ...block, lines: [...block.lines, line] });
  };

  const removeLine = (blockId: string, lineId: string) => {
    const block = doc.find((b) => b.id === blockId);
    if (!block || block.kind !== "row" || block.lines.length <= 1) return;
    replaceBlock(blockId, {
      ...block,
      lines: block.lines.filter((l) => l.id !== lineId),
    });
  };

  /** Enter carries on down the form the way it does in a spreadsheet: from a
   *  label into its value, from a value into a fresh row below. */
  const onLabelKeyDown =
    (block: Extract<DocBlock, { kind: "row" }>) =>
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      pendingFocus.current = `${block.lines[0].id}#0`;
      onChange(doc.slice());
    };

  const onValueKeyDown =
    (blockIndex: number) => (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      const row = newRow();
      insertAfter(blockIndex, row, `label#${row.id}`);
    };

  const isEmptyStart =
    doc.length === 1 &&
    doc[0].kind === "row" &&
    !doc[0].label &&
    doc[0].lines.length === 1 &&
    doc[0].lines[0].parts.every((p) => p.kind === "text" && !p.text);

  return (
    <div>
      {/* The typing route leads, since it's the fast one and the one an author
          keeps using; the button is the discoverable fallback beside it. */}
      <div className="mb-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11px] text-muted-foreground">
        <span>
          type{" "}
          <code className="rounded bg-primary/15 px-1.5 py-0.5 font-mono text-primary">
            [answer]
          </code>{" "}
          where the gap goes
        </span>
        <button
          type="button"
          onMouseDown={(e) => e.preventDefault()}
          onClick={makeGap}
          title="Turn the selected word into a gap"
          className="flex items-center gap-1.5 rounded-md px-2 py-1 transition-colors hover:bg-foreground/8 hover:text-foreground"
        >
          <SquareDashed className="size-3.5" aria-hidden />
          or select a word
        </button>

        <span className="ml-auto flex items-center gap-1">
          <ToolbarButton
            onClick={() => appendBlock(newRow(), undefined)}
            icon={<Plus className="size-3.5" aria-hidden />}
            label="row"
          />
          <ToolbarButton
            onClick={() =>
              appendBlock({ id: newId(), kind: "heading", text: "" })
            }
            icon={<Heading className="size-3.5" aria-hidden />}
            label="section"
          />
          <ToolbarButton
            onClick={() => appendBlock({ id: newId(), kind: "title", text: "" })}
            icon={<Type className="size-3.5" aria-hidden />}
            label="title"
          />
        </span>
      </div>

      {/* The sheet. Ruled and boxed like the paper it's copied from. */}
      <div className="overflow-hidden rounded-lg border border-border bg-card">
        {doc.map((block, blockIndex) => (
          <div
            key={block.id}
            className="group/block relative border-b border-border/60 last:border-b-0"
          >
            <div className="flex items-start">
              <div className="min-w-0 flex-1">
                {block.kind === "title" && (
                  <input
                    type="text"
                    value={block.text}
                    onChange={(e) =>
                      replaceBlock(block.id, { ...block, text: e.target.value })
                    }
                    placeholder="Form title"
                    aria-label="Form title"
                    className="w-full bg-transparent px-3 py-2.5 text-center text-sm font-semibold tracking-wide text-foreground uppercase placeholder:font-normal placeholder:normal-case placeholder:text-muted-foreground focus:outline-none"
                  />
                )}

                {block.kind === "heading" && (
                  <input
                    type="text"
                    value={block.text}
                    onChange={(e) =>
                      replaceBlock(block.id, { ...block, text: e.target.value })
                    }
                    placeholder="Section heading"
                    aria-label="Section heading"
                    className="w-full bg-transparent px-3 py-1.5 text-sm font-medium text-primary placeholder:font-normal placeholder:text-muted-foreground focus:outline-none"
                  />
                )}

                {block.kind === "row" && (
                  <div className="flex transition-colors group-hover/block:bg-foreground/[0.02]">
                    <input
                      type="text"
                      value={block.label}
                      ref={register(`label#${block.id}`)}
                      onChange={(e) =>
                        replaceBlock(block.id, {
                          ...block,
                          label: e.target.value,
                        })
                      }
                      onKeyDown={onLabelKeyDown(block)}
                      placeholder="Label"
                      aria-label="Row label"
                      title={block.label}
                      className="w-64 shrink-0 bg-transparent px-3 py-1.5 text-sm text-muted-foreground placeholder:text-muted-foreground/50 focus:outline-none"
                    />
                    <div className="min-w-0 flex-1 border-l border-border/60 px-3 py-1">
                      {block.lines.map((line) => (
                        <div key={line.id} className="flex items-center gap-1">
                          {line.bullet && (
                            <span
                              aria-hidden
                              className="shrink-0 text-muted-foreground"
                            >
                              –
                            </span>
                          )}
                          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-y-1">
                            {line.parts.map((part, partIndex) =>
                              part.kind === "text" ? (
                                <AutoInput
                                  key={partIndex}
                                  value={part.text}
                                  onChange={(v) =>
                                    setText(block.id, line.id, partIndex, v)
                                  }
                                  placeholder={
                                    line.parts.length === 1 ? "Value" : ""
                                  }
                                  ariaLabel="Value text"
                                  // An empty segment beside a gap is a place
                                  // to type, not a field: given a real width
                                  // it pushed every gap-at-the-start line
                                  // right, so those rows sat out of line with
                                  // the plain ones above them.
                                  min={
                                    part.text
                                      ? 2
                                      : line.parts.length === 1
                                        ? 8
                                        : 1
                                  }
                                  className="py-0.5 placeholder:text-muted-foreground/50"
                                  inputRef={register(`${line.id}#${partIndex}`)}
                                  onKeyDown={onValueKeyDown(blockIndex)}
                                  onSelectCapture={(e) => {
                                    const el = e.currentTarget;
                                    focus.current = {
                                      blockId: block.id,
                                      lineId: line.id,
                                      partIndex,
                                      start: el.selectionStart ?? 0,
                                      end: el.selectionEnd ?? 0,
                                    };
                                  }}
                                />
                              ) : (
                                <GapChip
                                  key={partIndex}
                                  number={numbers.get(part.id) ?? 0}
                                  selected={selectedGap === part.id}
                                  editing={editingGap === part.id}
                                  onSelect={() => setSelectedGap(part.id)}
                                  onEdit={() => {
                                    setEditingGap(part.id);
                                    pendingFocus.current = `answer#${part.id}#0`;
                                  }}
                                  registerInput={register}
                                  gapId={part.id}
                                  flagged={flagged.has(
                                    numbers.get(part.id) ?? 0,
                                  )}
                                  answers={
                                    part.answers.length ? part.answers : [""]
                                  }
                                  onAnswerChange={(ai, v) =>
                                    setAnswer(
                                      block.id,
                                      line.id,
                                      partIndex,
                                      ai,
                                      v,
                                    )
                                  }
                                  onAddAlt={() => {
                                    const count = part.answers.length || 1;
                                    setEditingGap(part.id);
                                    pendingFocus.current = `answer#${part.id}#${count}`;
                                    addAlt(block.id, line.id, partIndex);
                                  }}
                                  onRemove={() => {
                                    setSelectedGap(null);
                                    setEditingGap(null);
                                    removeGap(block.id, line.id, partIndex);
                                  }}
                                />
                              ),
                            )}
                          </div>
                          {block.lines.length > 1 && (
                            <button
                              type="button"
                              onClick={() => removeLine(block.id, line.id)}
                              aria-label="Remove line"
                              title="Remove line"
                              className="shrink-0 rounded p-1 text-muted-foreground opacity-0 transition-opacity group-hover/block:opacity-100 hover:text-destructive"
                            >
                              <X className="size-3" aria-hidden />
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Block controls sit outside the sheet's right edge and only
                  appear on hover: the form should read as a form, not as a
                  control panel. */}
              <div className="absolute top-1 right-1 flex shrink-0 items-center gap-0.5 rounded-md bg-card opacity-0 shadow-sm transition-opacity group-focus-within/block:opacity-100 group-hover/block:opacity-100">
                {block.kind === "row" && (
                  <RowButton
                    onClick={() => addLine(block.id)}
                    label="Add a line under this label"
                    icon={<CornerDownRight className="size-3" aria-hidden />}
                  />
                )}
                <RowButton
                  onClick={() => moveBlock(blockIndex, -1)}
                  label="Move up"
                  icon={<ChevronUp className="size-3" aria-hidden />}
                />
                <RowButton
                  onClick={() => moveBlock(blockIndex, 1)}
                  label="Move down"
                  icon={<ChevronDown className="size-3" aria-hidden />}
                />
                <RowButton
                  onClick={() => replaceBlock(block.id, null)}
                  label="Delete"
                  danger
                  icon={<Trash2 className="size-3" aria-hidden />}
                />
              </div>
            </div>
          </div>
        ))}
      </div>

      {isEmptyStart && (
        <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
          Copy the form as it appears on the paper — a label on the left, its
          value on the right. Press Enter for the next row.
        </p>
      )}
    </div>
  );
}

function ToolbarButton({
  onClick,
  icon,
  label,
}: {
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-1.5 rounded-md px-2 py-1 transition-colors hover:bg-foreground/8 hover:text-foreground"
    >
      {icon}
      {label}
    </button>
  );
}

function RowButton({
  onClick,
  icon,
  label,
  danger,
}: {
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      className={cn(
        "rounded p-1 text-muted-foreground transition-colors hover:bg-foreground/8",
        danger ? "hover:text-destructive" : "hover:text-foreground",
      )}
    >
      {icon}
    </button>
  );
}

/** A gap: a numbered chip carrying its accepted answers. Clicking it raises
 *  a toolbar rather than putting a caret in it — the actions belong to the
 *  gap as a whole (edit, accept another answer, mark where it's said, remove)
 *  and there are too many of them to hang off the text itself.
 *
 *  The toolbar floats above the chip instead of sitting in the line. Held in
 *  the line it would have to reserve its width even while hidden, leaving a
 *  hole to the right of every gap; given no room at all, the sentence would
 *  jump each time one opened. */
function GapChip({
  gapId,
  number,
  answers,
  flagged,
  selected,
  editing,
  onSelect,
  onEdit,
  onAnswerChange,
  onAddAlt,
  onRemove,
  registerInput,
}: {
  gapId: string;
  number: number;
  answers: string[];
  flagged: boolean;
  selected: boolean;
  editing: boolean;
  onSelect: () => void;
  onEdit: () => void;
  onAnswerChange: (index: number, value: string) => void;
  onAddAlt: () => void;
  onRemove: () => void;
  registerInput: (key: string) => (el: HTMLInputElement | null) => void;
}) {
  const written = answers.filter((a) => a.trim());

  return (
    <span
      data-gap={gapId}
      className={cn(
        "relative mx-0.5 inline-flex items-baseline rounded border px-1.5 align-baseline transition-colors",
        flagged
          ? "border-destructive/60 bg-destructive/10"
          : "border-primary/30 bg-primary/10",
        selected && !flagged && "border-primary",
        selected && flagged && "border-destructive",
        !editing && "cursor-pointer hover:border-primary/60",
      )}
      onClick={() => {
        if (!editing) onSelect();
      }}
    >
      <span
        className={cn(
          "mr-1 text-[10px] font-semibold tabular-nums",
          flagged ? "text-destructive" : "text-primary",
        )}
      >
        {number}.
      </span>

      {editing ? (
        answers.map((answer, i) => (
          <span key={i} className="inline-flex items-baseline">
            {i > 0 && (
              <span aria-hidden className="px-1 text-muted-foreground">
                /
              </span>
            )}
            <AutoInput
              value={answer}
              onChange={(v) => onAnswerChange(i, v)}
              placeholder="answer"
              ariaLabel={`Accepted answer ${i + 1} for gap ${number}`}
              min={2}
              pad={0.5}
              inputRef={registerInput(`answer#${gapId}#${i}`)}
              className={cn(
                flagged
                  ? "text-destructive placeholder:text-destructive/50"
                  : "text-primary placeholder:text-primary/40",
              )}
            />
          </span>
        ))
      ) : (
        // Read-only until asked for: a form of ten gaps is ten live fields
        // otherwise, every one of them a place to lose an answer to a stray
        // keystroke.
        <span
          className={cn(
            "text-sm",
            flagged ? "text-destructive/70 italic" : "text-primary",
          )}
        >
          {written.length > 0 ? written.join(" / ") : "answer"}
        </span>
      )}

      {(selected || editing) && (
        <span className="absolute right-0 bottom-full z-20 mb-1 flex items-center gap-0.5 rounded-md border border-border bg-card p-0.5 shadow-md">
          <GapAction
            label="Edit the accepted answers"
            onClick={onEdit}
            active={editing}
            icon={<Pencil className="size-3" aria-hidden />}
          />
          <GapAction
            label="Accept another answer"
            onClick={onAddAlt}
            icon={<Plus className="size-3" aria-hidden />}
          />
          {/* Marking where the answer is said needs somewhere to store the
              timestamp, which the question model doesn't have yet — so the
              action is shown as not built rather than quietly doing nothing
              when pressed. */}
          <GapAction
            label="Mark where this is said in the audio — not built yet"
            disabled
            icon={<AudioLines className="size-3" aria-hidden />}
          />
          <span className="mx-0.5 h-4 w-px bg-border" aria-hidden />
          <GapAction
            label="Remove this gap"
            onClick={onRemove}
            danger
            icon={<Trash2 className="size-3" aria-hidden />}
          />
        </span>
      )}
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
        "rounded p-1 transition-colors",
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

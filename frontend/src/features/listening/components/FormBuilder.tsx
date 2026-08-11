import { useEffect, useRef, useState } from "react";
import {
  AudioLines,
  ChevronDown,
  ChevronUp,
  CornerDownRight,
  Ellipsis,
  Heading,
  Plus,
  SquareDashed,
  TimerReset,
  Trash2,
  Type,
  X,
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { ValueField } from "@/features/listening/components/ValueField";
import { formatClock } from "@/features/studio/format";
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

type EditableEl = HTMLElement;

interface FormBuilderProps {
  doc: DocBlock[];
  onChange: (doc: DocBlock[]) => void;
  /** Gap numbers reported as unanswered, highlighted so they're findable. */
  flaggedGaps?: number[];
  /** Per gap id: whether the answer is actually said inside the seconds the
   *  author marked, and where it is said instead. */
  markChecks?: Map<string, { found: boolean; heardAtMs: number | null }>;
  /** Asks the audio pane for the moment this gap is said. Asynchronous by
   *  nature: the author may still have to click the line, so the result comes
   *  back through the callback rather than as a return value. */
  onMarkAudio?: (
    answers: string[],
    apply: (range: { startMs: number; endMs: number }) => void,
  ) => void;
}

export function FormBuilder({
  doc,
  onChange,
  flaggedGaps,
  markChecks,
  onMarkAudio,
}: FormBuilderProps) {
  const numbers = gapNumbers(doc);
  const flagged = new Set(flaggedGaps ?? []);

  // Inputs are registered by key so the caret can be placed after a change
  // that rebuilt them — otherwise typing would stop dead the moment a bracket
  // became a chip, or a new row would appear with the focus left behind.
  const docRef = useRef(doc);
  docRef.current = doc;
  const inputs = useRef(new Map<string, EditableEl>());
  const pendingFocus = useRef<string | null>(null);
  const register = (key: string) => (el: EditableEl | null) => {
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
  const [selectedText, setSelectedText] = useState("");
  // Where the author is working, so a new row or section lands next to it
  // rather than at the far end of the form.
  const [focusedBlockId, setFocusedBlockId] = useState<string | null>(null);
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

  /** Adds a block next to the one being worked on, falling back to the end.
   *  Appending blindly meant a section always arrived at the bottom and had
   *  to be walked up past every row. */
  const addBlock = (block: DocBlock, focusKey?: string) => {
    if (focusKey) pendingFocus.current = focusKey;
    const at = doc.findIndex((b) => b.id === focusedBlockId);
    if (at < 0) {
      onChange([...doc, block]);
      return;
    }
    const next = doc.slice();
    next.splice(at + 1, 0, block);
    onChange(next);
  };

  /** A form has one title and it is the first thing on it, so this goes to
   *  the top rather than wherever the caret happens to be — which is also the
   *  answer to "how do I put something above the first row". */
  const addTitle = () => {
    const block: DocBlock = { id: newId(), kind: "title", text: "" };
    pendingFocus.current = `title#${block.id}`;
    onChange([block, ...doc]);
  };

  const hasTitle = doc.some((b) => b.kind === "title");

  const patchLine = (blockId: string, lineId: string, next: DocLine) =>
    onChange(
      doc.map((b) =>
        b.id === blockId && b.kind === "row"
          ? { ...b, lines: b.lines.map((l) => (l.id === lineId ? next : l)) }
          : b,
      ),
    );

  /** Wraps the selected word in brackets, which is all a gap is now that a
   *  value is edited as text. Written through execCommand so the field's own
   *  undo stack keeps it — replacing the value outright would make it
   *  unundoable. */
  const makeGap = () => {
    const picked = window.getSelection()?.toString().trim();
    if (!picked) return;
    // Typed rather than assigned: the editable region reads itself back on
    // input, so an edit it never saw would be invisible to it — and this way
    // the browser's own undo keeps the change.
    document.execCommand("insertText", false, `[${picked}]`);
    setSelectedText("");
  };

  /** Puts a gap's words back into the sentence. Removing the chip outright
   *  would take the words with it, and they were the author's text before
   *  they were an answer. */
  const unblank = (gapId: string) => {
    onChange(
      docRef.current.map((b) =>
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
    onChange(
      docRef.current.map((b) =>
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

  const removeLine = (blockId: string, lineId: string) => {
    const block = doc.find((b) => b.id === blockId);
    if (!block || block.kind !== "row" || block.lines.length <= 1) return;
    replaceBlock(blockId, {
      ...block,
      lines: block.lines.filter((l) => l.id !== lineId),
    });
  };

  return (
    <div>
      {/* Nothing above the sheet unless there is something to act on: the
          bracket rule reads better under the form, next to the buttons that
          build it, and this slot would otherwise be an empty line. */}
      {selectedText && (
        <div className="mb-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11px]">
          <button
            type="button"
            onMouseDown={(e) => e.preventDefault()}
            onClick={makeGap}
            title={`Blank out “${selectedText}” — it becomes the answer`}
            className="flex max-w-full items-center gap-1.5 rounded-md bg-primary/15 px-2 py-1 text-primary transition-colors hover:bg-primary/25"
          >
            <SquareDashed className="size-3.5 shrink-0" aria-hidden />
            <span className="truncate">blank out “{selectedText}”</span>
          </button>
        </div>
      )}

      {/* Deliberately not `overflow-hidden`: a gap's toolbar floats above its
          row, and clipping to the sheet cut it off. The corners are rounded on
          the end rows instead, which is all the clipping was doing. */}
      {/* Full width, ending on the same line as the header and the
          instructions above it. The row controls live inside it: one small
          trigger at the row's end costs a corner of the value it may sit over,
          which is cheaper than a permanently empty lane or a sheet that stops
          short of everything else. */}
      <div className="rounded-lg border border-border bg-card [&>*:first-child]:rounded-t-lg [&>*:last-child]:rounded-b-lg">
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
                    ref={register(`title#${block.id}`)}
                    onFocus={() => setFocusedBlockId(block.id)}
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
                    ref={register(`heading#${block.id}`)}
                    onFocus={() => setFocusedBlockId(block.id)}
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
                  <div className="transition-colors group-hover/block:bg-foreground/[0.02]">
                    {/* Each line is its own full-width row rather than a stack
                        inside the value cell. That puts every line's right
                        edge on the sheet's edge, so its control can sit in the
                        gutter beside it instead of on top of the text — and it
                        runs the rule between the columns down the whole row,
                        the way the printed table does. */}
                    {block.lines.map((line, lineIndex) => (
                      <div key={line.id} className="group/line relative flex">
                        <div className="w-64 shrink-0">
                          {lineIndex === 0 && (
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
                              onKeyDown={(e) => {
                                if (e.key !== "Enter") return;
                                e.preventDefault();
                                pendingFocus.current = `${block.lines[0].id}#0`;
                                onChange(doc.slice());
                              }}
                              onFocus={() => setFocusedBlockId(block.id)}
                              placeholder="Label"
                              aria-label="Row label"
                              title={block.label}
                              className="w-full bg-transparent px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none"
                            />
                          )}
                        </div>

                        <div className="flex min-w-0 flex-1 items-center gap-1 border-l border-border/60 px-3 py-1">
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
                            placeholder={lineIndex === 0 ? "Value" : undefined}
                            onEnter={() => {
                              const row = newRow();
                              insertAfter(blockIndex, row, `label#${row.id}`);
                            }}
                            registerInput={register(`${line.id}#0`)}
                            onSelectionChange={setSelectedText}
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
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    title="Row actions"
                    aria-label="Row actions"
                    className="absolute top-1 right-1 flex size-7 items-center justify-center rounded-md bg-card text-muted-foreground opacity-0 shadow-sm transition-opacity group-focus-within/block:opacity-100 group-hover/block:opacity-100 hover:text-foreground focus-visible:opacity-100 data-[state=open]:opacity-100"
                  >
                    <Ellipsis className="size-4" aria-hidden />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-52">
                  {block.kind === "row" && (
                    <DropdownMenuItem onClick={() => addLine(block.id)}>
                      <CornerDownRight aria-hidden />
                      Add a line under this label
                    </DropdownMenuItem>
                  )}
                  <DropdownMenuItem
                    onClick={() => moveBlock(blockIndex, -1)}
                    disabled={blockIndex === 0}
                  >
                    <ChevronUp aria-hidden />
                    Move up
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() => moveBlock(blockIndex, 1)}
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
            </div>
          </div>
        ))}
      </div>

      {/* Under the sheet, where a new row goes. `title` is the exception: a
          form has one and it belongs at the top, which is also how something
          gets above the first row. What each does is in the tooltips and in
          the help card at the foot of the editor — captions alongside them
          only ever got read once, then sat there. */}
      <div className="mt-2.5 flex flex-wrap items-center justify-center gap-1.5">
        <ToolbarButton
          onClick={() => addBlock(newRow())}
          icon={<Plus className="size-3.5" aria-hidden />}
          label="row"
          title="Add a row after the one you're on"
        />
        <ToolbarButton
          onClick={() => {
            const block: DocBlock = { id: newId(), kind: "heading", text: "" };
            addBlock(block, `heading#${block.id}`);
          }}
          icon={<Heading className="size-3.5" aria-hidden />}
          label="section"
          title="Add a section heading after the row you're on"
        />
        {!hasTitle && (
          <ToolbarButton
            onClick={addTitle}
            icon={<Type className="size-3.5" aria-hidden />}
            label="title"
            title="Add the form's title at the top"
          />
        )}
      </div>
    </div>
  );
}

function ToolbarButton({
  onClick,
  icon,
  label,
  title,
}: {
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/60 hover:bg-foreground/5 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
    >
      {icon}
      {label}
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
      <span className="flex w-max items-center gap-0.5 rounded-md border border-border bg-card p-0.5 shadow-md">
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
            icon={<TimerReset className="size-3" aria-hidden />}
          />
        )}
        <span className="mx-0.5 h-4 w-px bg-border" aria-hidden />
        <GapAction
          label="Put the words back into the sentence"
          onClick={onUnblank}
          danger
          icon={<Trash2 className="size-3" aria-hidden />}
        />
        {mismatch && (
          <span className="border-l border-border px-1.5 text-[10px] whitespace-nowrap text-warning">
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

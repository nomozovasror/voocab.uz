import { useEffect, useRef, useState } from "react";
import {
  AudioLines,
  ChevronDown,
  ChevronUp,
  CornerDownRight,
  Ellipsis,
  Heading,
  Minus,
  Plus,
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
      {/* Full width, ending on the same line as the header and the
          instructions above it. The row controls live inside it: one small
          trigger at the row's end costs a corner of the value it may sit over,
          which is cheaper than a permanently empty lane or a sheet that stops
          short of everything else. */}
      <div className="rounded-lg border border-border bg-card [&>*:first-child]:rounded-t-lg [&>*:last-child]:rounded-b-lg">
        {doc.map((block, blockIndex) => (
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
                              insertAfter(block.id, row, `label#${row.id}`);
                            }}
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
                  <DropdownMenuContent align="end" className="w-52">
                    {block.kind === "row" && (
                      <DropdownMenuItem onClick={() => addLine(block.id)}>
                        <CornerDownRight aria-hidden />
                        Add line
                        <DropdownMenuShortcut>⇧↵</DropdownMenuShortcut>
                      </DropdownMenuItem>
                    )}
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
        ))}
      </div>

      {/* Under the sheet, where a new row goes. `title` is the exception: a
          form has one and it belongs at the top, which is also how something
          gets above the first row. What each does is in the tooltips and in
          the help card at the foot of the editor — captions alongside them
          only ever got read once, then sat there. */}
      <div className="mt-2.5 flex flex-wrap items-center justify-center gap-1.5">
        <ToolbarButton
          onClick={() => {
            const row = newRow();
            addBlock(row, `label#${row.id}`);
          }}
          icon={<Plus className="size-3.5" aria-hidden />}
          label="row"
          title="Add a row at the end"
        />
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

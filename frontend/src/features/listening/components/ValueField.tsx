import { useEffect, useRef, useState } from "react";
import { textToParts } from "@/features/listening/form-syntax";
import type { DocLine, DocPart } from "@/features/listening/form-syntax";

/**
 * A form value: real text with real chips in it, in one editable region.
 *
 * The layout is the browser's — text flow is what the earlier flexbox of
 * separate inputs could never do — and so is the DOM inside this region.
 * React renders the region as an empty element and never puts a child in it:
 * the moment the author types, the browser mutates that subtree, React's
 * picture of it goes stale, and the next update it makes there duplicates and
 * garbles the content rather than replacing it. Everything inside is therefore
 * built by hand, in an effect, and only when something structural changes.
 *
 * Direction of truth follows from that. On every keystroke the DOM is read
 * back into the model. The DOM is written from the model only for a bracket
 * completing into a chip, a gap being marked, or a renumber — and the caret is
 * restored by offset afterwards, counting a chip as the text it stands for.
 *
 * Chips are `contenteditable=false`, which is what makes the browser treat
 * each as a single character: the caret steps over it, Backspace takes the
 * whole thing, and a selection never lands inside it.
 */

const RAW_GAP_RE = /\[[^\]]*\]/;

interface ValueFieldProps {
  line: DocLine;
  onChange: (parts: DocPart[]) => void;
  /** Gap id -> its number. */
  numbers: Map<string, number>;
  /** Numbers with no accepted answer. */
  flagged: Set<number>;
  markChecks?: Map<string, { found: boolean; heardAtMs: number | null }>;
  /** The actions for the selected chip, drawn over it. */
  renderGapActions?: (gapId: string) => React.ReactNode;
  selectedGap?: string | null;
  onSelectGap?: (gapId: string | null) => void;
  placeholder?: string;
  onEnter?: () => void;
  /** Shift+Enter: another line under the same label. Handled here because the
   *  browser's own answer — inserting a <br> — is invisible to the model and
   *  would vanish on the next repaint. */
  onShiftEnter?: () => void;
  registerInput?: (el: HTMLElement | null) => void;
  onSelectionChange?: (selected: string) => void;
}

// ── DOM <-> text ─────────────────────────────────────────────────────────

/** A chip counts as the text it stands for, so an offset means the same thing
 *  on both sides of the conversion. */
function nodeText(node: ChildNode): string {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? "";
  if (node instanceof HTMLElement && node.dataset.gap) {
    return `[${node.dataset.answers ?? ""}]`;
  }
  return node.textContent ?? "";
}

function readDom(root: HTMLElement): {
  text: string;
  hasRawGap: boolean;
  hasStrayNode: boolean;
} {
  let text = "";
  let hasRawGap = false;
  let hasStrayNode = false;

  for (const node of Array.from(root.childNodes)) {
    if (node.nodeType === Node.TEXT_NODE) {
      if (RAW_GAP_RE.test(node.textContent ?? "")) hasRawGap = true;
    } else if (!(node instanceof HTMLElement && node.dataset.gap)) {
      // Anything the browser put here of its own accord: a <br> left behind
      // when the text before a chip is deleted, a <div> from a paste. The
      // model can't see them — they carry no text — so they sit in the DOM
      // breaking the line while nothing upstream knows why.
      hasStrayNode = true;
    }
    text += nodeText(node);
  }

  return { text, hasRawGap, hasStrayNode };
}

function caretOffset(root: HTMLElement): number {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return 0;
  const range = selection.getRangeAt(0);

  if (range.endContainer === root) {
    return Array.from(root.childNodes)
      .slice(0, range.endOffset)
      .reduce((total, node) => total + nodeText(node).length, 0);
  }

  let offset = 0;
  for (const node of Array.from(root.childNodes)) {
    if (node === range.endContainer) return offset + range.endOffset;
    // Inside a chip: the caret belongs after it, never within.
    if (node.contains(range.endContainer))
      return offset + nodeText(node).length;
    offset += nodeText(node).length;
  }
  return offset;
}

function placeCaret(root: HTMLElement, offset: number): void {
  const selection = window.getSelection();
  if (!selection) return;
  const range = document.createRange();
  let remaining = offset;

  for (const node of Array.from(root.childNodes)) {
    const length = nodeText(node).length;
    if (remaining <= length) {
      if (node.nodeType === Node.TEXT_NODE) range.setStart(node, remaining);
      else range.setStartAfter(node);
      range.collapse(true);
      selection.removeAllRanges();
      selection.addRange(range);
      return;
    }
    remaining -= length;
  }

  range.selectNodeContents(root);
  range.collapse(false);
  selection.removeAllRanges();
  selection.addRange(range);
}

const CHIP_BASE =
  "mx-px inline-flex cursor-pointer items-baseline rounded border px-1.5 align-baseline select-none";
const CHIP_TONES = {
  noAnswer: "border-destructive/60 bg-destructive/10 text-destructive",
  unlinked: "border-border bg-foreground/5 text-muted-foreground",
  mismatch: "border-warning/60 bg-warning/10 text-warning",
  done: "border-success/50 bg-success/10 text-success",
};

/** Builds the region's contents by hand. Written as DOM rather than JSX for
 *  the reason in this file's note: React must never own anything in here. */
function paint(
  root: HTMLElement,
  parts: DocPart[],
  numbers: Map<string, number>,
  flagged: Set<number>,
  markChecks?: Map<string, { found: boolean; heardAtMs: number | null }>,
): void {
  root.replaceChildren();
  for (const part of parts) {
    if (part.kind === "text") {
      root.append(document.createTextNode(part.text));
      continue;
    }

    const number = numbers.get(part.id) ?? 0;
    const marked = part.replayStartMs != null;
    const mismatch = marked && markChecks?.get(part.id)?.found === false;
    const written = part.answers.filter((a) => a.trim());
    const tone = flagged.has(number)
      ? CHIP_TONES.noAnswer
      : !marked
        ? CHIP_TONES.unlinked
        : mismatch
          ? CHIP_TONES.mismatch
          : CHIP_TONES.done;

    const chip = document.createElement("span");
    chip.contentEditable = "false";
    chip.dataset.gap = part.id;
    chip.dataset.answers = part.answers.join(", ");
    chip.className = `${CHIP_BASE} ${tone}`;

    const label = document.createElement("span");
    label.className = "mr-1 text-xs font-semibold tabular-nums";
    label.textContent = `${number}.`;

    const answer = document.createElement("span");
    answer.className = written.length ? "text-base" : "text-base italic opacity-70";
    answer.textContent = written.length ? written.join(" / ") : "answer";

    chip.append(label, answer);
    root.append(chip);
  }
}

// ── The field ────────────────────────────────────────────────────────────

export function ValueField({
  line,
  onChange,
  numbers,
  flagged,
  markChecks,
  renderGapActions,
  selectedGap,
  onSelectGap,
  placeholder,
  onEnter,
  onShiftEnter,
  registerInput,
  onSelectionChange,
}: ValueFieldProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const partsRef = useRef<DocPart[]>(line.parts);
  const signatureRef = useRef("");
  const caretRef = useRef<number | null>(null);
  const [empty, setEmpty] = useState(
    line.parts.every((p) => p.kind === "text" && !p.text),
  );

  const signature = JSON.stringify(line.parts) + JSON.stringify([...numbers]);

  // Repaint only when something the field didn't type changes: a bracket it
  // turned into a chip, a mark applied from the transcript, a renumber, the
  // material reloading.
  useEffect(() => {
    const root = rootRef.current;
    if (!root || signature === signatureRef.current) return;
    signatureRef.current = signature;
    partsRef.current = line.parts;

    // Any repaint moves the caret, not only the ones this field asked for:
    // deleting a chip renumbers the rest, which comes back as an outside
    // change. Where no position was set aside, the current one is read off the
    // DOM first and put back after — otherwise the caret lands at the start of
    // the line and the next character typed appears there.
    const focused =
      document.activeElement === root || root.contains(document.activeElement);
    const caret = caretRef.current ?? (focused ? caretOffset(root) : null);
    caretRef.current = null;

    paint(root, line.parts, numbers, flagged, markChecks);
    setEmpty(line.parts.every((p) => p.kind === "text" && !p.text));
    if (caret !== null) placeCaret(root, caret);
  }, [signature, line.parts, numbers, flagged, markChecks]);

  const handleInput = () => {
    const root = rootRef.current;
    if (!root) return;
    const { text, hasRawGap, hasStrayNode } = readDom(root);
    const parts = textToParts(text, partsRef.current);

    if (hasRawGap || hasStrayNode) {
      // A bracket was completed, or the browser left something of its own
      // behind. Either way the DOM and the model have parted company: the
      // caret is noted and the signature left stale on purpose, so the effect
      // above repaints from the model and puts the caret back where it was.
      caretRef.current = caretOffset(root);
    } else {
      // Ordinary typing: the DOM already shows exactly this, so the effect is
      // told there is nothing to do. Repainting here would rebuild the text
      // node under the caret and send it back to the start of the line, which
      // is what typing into it looked like — the letters came out reversed.
      signatureRef.current =
        JSON.stringify(parts) + JSON.stringify([...numbers]);
    }

    partsRef.current = parts;
    setEmpty(text.trim() === "");
    onChange(parts);
  };

  return (
    <div className="relative w-full">
      <div
        ref={(el) => {
          rootRef.current = el;
          registerInput?.(el);
          if (el && el.childNodes.length === 0 && !empty) {
            paint(el, partsRef.current, numbers, flagged, markChecks);
          }
        }}
        contentEditable
        suppressContentEditableWarning
        role="textbox"
        aria-label="Value"
        onInput={handleInput}
        onPaste={(e) => {
          // Paste as text. A contentEditable takes whatever HTML the
          // clipboard holds — the source's font, colour, links and all — and
          // that styling then rides along into the stored template. Newlines
          // collapse to spaces: a value is one line, and pasted ones would
          // otherwise arrive as <div>s the model can't read back.
          e.preventDefault();
          const text = e.clipboardData
            .getData("text/plain")
            .replace(/\s*\n\s*/g, " ");
          if (text) document.execCommand("insertText", false, text);
        }}
        onKeyDown={(e) => {
          if (e.key !== "Enter") return;
          e.preventDefault();
          if (e.shiftKey) onShiftEnter?.();
          else onEnter?.();
        }}
        onClick={(e) => {
          const chip = (e.target as HTMLElement).closest("[data-gap]");
          onSelectGap?.(chip ? ((chip as HTMLElement).dataset.gap ?? null) : null);
        }}
        onKeyUp={() =>
          onSelectionChange?.(window.getSelection()?.toString().trim() ?? "")
        }
        onMouseUp={() =>
          onSelectionChange?.(window.getSelection()?.toString().trim() ?? "")
        }
        className="min-h-8 w-full text-base leading-8 break-words whitespace-pre-wrap text-foreground focus:outline-none"
      />

      {empty && placeholder && (
        <span className="pointer-events-none absolute inset-y-0 left-0 text-base leading-8 text-muted-foreground/50">
          {placeholder}
        </span>
      )}

      {selectedGap && renderGapActions?.(selectedGap)}
    </div>
  );
}

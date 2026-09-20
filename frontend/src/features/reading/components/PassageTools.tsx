import { useCallback, useEffect, useState } from "react";
import { Highlighter } from "lucide-react";
import { cn } from "@/lib/utils";
import { LEFT_PANE } from "@/features/reading/components/SplitPanes";
import type { Highlight } from "@/features/reading/highlights";

/**
 * The two things a reader does to a passage that are not answering it.
 *
 * ## Highlight
 *
 * Select the words, then press the button. Not a mode with the button held
 * down and every drag marking something: a reader drags to select for half a
 * dozen reasons — to read carefully, to count, to hold their place — and a
 * tool that marked all of them would fill the passage with yellow by the
 * third paragraph. Select-then-act also gives the button somewhere honest to
 * be disabled, which is how it says what it needs.
 *
 * Taking one off is a click on it, in the passage. That is how every
 * highlighter in every document works and it needs no second control.
 *
 * ## Size
 *
 * Nine hundred words at a size chosen for a paragraph. Three steps, because
 * a slider over a range this short is a control with more precision than
 * decisions, and it is remembered — somebody who needs larger text needs it
 * on the next passage too.
 *
 * ## Where the offsets come from
 *
 * A selection is turned into two character offsets into ONE paragraph's
 * text, by measuring a range from the start of that paragraph to the start
 * of the selection and taking the length of the string it covers. That is
 * the one technique that survives the marks already in there: the paragraph
 * renders as several elements once anything is highlighted, and every
 * approach that counts nodes rather than characters gets this wrong the
 * second time somebody marks the same paragraph.
 */

/** The three sizes, as a percentage of the pane's own. Small enough a step
 *  that nothing reflows alarmingly, large enough to be worth pressing. */
const SIZES = [100, 115, 130] as const;
const SIZE_KEY = "voocab-reading-text-size";

export function useTextSize(): [number, (next: number) => void] {
  const [size, setSize] = useState<number>(() => {
    try {
      const raw = Number(localStorage.getItem(SIZE_KEY));
      return (SIZES as readonly number[]).includes(raw) ? raw : SIZES[0];
    } catch {
      return SIZES[0];
    }
  });
  const put = useCallback((next: number) => {
    setSize(next);
    try {
      localStorage.setItem(SIZE_KEY, String(next));
    } catch {
      /* private window; the default is fine */
    }
  }, []);
  return [size, put];
}

export function PassageTools({
  marks,
  onMarks,
  size,
  onSize,
}: {
  marks: Highlight[];
  onMarks: (next: Highlight[]) => void;
  size: number;
  onSize: (next: number) => void;
}) {
  // Whether there is anything to highlight right now. Watched rather than
  // read on click, because the button has to be able to look disabled — a
  // control that does nothing when pressed teaches people not to press it.
  const [selected, setSelected] = useState<Highlight | null>(null);
  useEffect(() => {
    const check = () => setSelected(selectionIn());
    document.addEventListener("selectionchange", check);
    return () => document.removeEventListener("selectionchange", check);
  }, []);

  const mark = () => {
    if (!selected) return;
    onMarks([...marks, selected]);
    // The selection has been turned into a mark; leaving it highlighted on
    // top of the highlight is two colours over the same words.
    window.getSelection()?.removeAllRanges();
    setSelected(null);
  };

  return (
    <div className="flex shrink-0 items-center gap-1">
      <button
        type="button"
        onClick={mark}
        disabled={!selected}
        title="Highlight the selected text"
        className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors duration-fast hover:bg-surface-hover hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:pointer-events-none disabled:opacity-40"
      >
        <Highlighter className="size-3.5" aria-hidden />
        Highlight
      </button>
      {/* Only where there is something to clear. A permanently visible
          "Clear" on an unmarked passage is a button whose whole job is to be
          greyed out. */}
      {marks.length > 0 && (
        <button
          type="button"
          onClick={() => onMarks([])}
          title="Remove every highlight on this passage"
          className="rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors duration-fast hover:bg-surface-hover hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          Clear
        </button>
      )}
      <div
        role="group"
        aria-label="Text size"
        className="ml-1 flex items-center gap-0.5 rounded-md bg-surface-sunken p-0.5"
      >
        {SIZES.map((step, i) => (
          <button
            key={step}
            type="button"
            aria-pressed={size === step}
            onClick={() => onSize(step)}
            title={`Text size ${i + 1} of ${SIZES.length}`}
            className={cn(
              "rounded px-1.5 leading-none transition-colors duration-fast focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
              // The control says what it does by BEING it: each button is
              // set at the size it sets.
              i === 0 ? "text-[10px]" : i === 1 ? "text-xs" : "text-sm",
              size === step
                ? "bg-primary/15 text-primary"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            A
          </button>
        ))}
      </div>
    </div>
  );
}

/**
 * The current selection as one paragraph and two offsets, or nothing.
 *
 * Nothing for a selection that is collapsed, that is outside the passage
 * pane, or that runs across two paragraphs. The last is a real restriction
 * and a deliberate one: a mark is stored against one paragraph's text, and
 * the alternative — silently marking only the first paragraph of a
 * three-paragraph drag — would leave the reader looking at a highlight that
 * is not what they asked for.
 */
function selectionIn(): Highlight | null {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || selection.rangeCount === 0) {
    return null;
  }
  const range = selection.getRangeAt(0);
  const found = closestIn(range.commonAncestorContainer);
  if (!found) return null;
  const { paragraph, index, partId } = found;
  const before = document.createRange();
  before.selectNodeContents(paragraph);
  before.setEnd(range.startContainer, range.startOffset);
  const start = before.toString().length;
  const end = start + range.toString().length;
  return end > start ? { partId, index, start, end } : null;
}

/** The paragraph a node sits in, with the part it belongs to. */
function closestIn(
  node: Node,
): { paragraph: HTMLElement; index: number; partId: string } | null {
  const el =
    node.nodeType === Node.ELEMENT_NODE
      ? (node as Element)
      : node.parentElement;
  const paragraph = el?.closest<HTMLElement>("[data-paragraph-index]");
  if (!paragraph || !paragraph.closest(`[${LEFT_PANE}]`)) return null;
  // The ARTICLE, not the nearest id that starts the same way: a lettered
  // paragraph's own wrapper is `passage-<uuid>-C`, and reaching for that
  // would hand back a part id with the letter still stuck on the end.
  const article = paragraph.closest<HTMLElement>('article[id^="passage-"]');
  // `passage-<uuid>` — and the uuid has dashes of its own, so the id is cut
  // once at the front rather than split on them.
  const partId = article?.id.slice("passage-".length);
  const index = Number(paragraph.dataset.paragraphIndex);
  if (!partId || !Number.isInteger(index)) return null;
  return { paragraph, index, partId };
}

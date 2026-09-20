import { LEFT_PANE } from "@/features/reading/components/SplitPanes";
import type { Highlight } from "@/features/reading/highlights";

/**
 * Where the reader's selection is, in the passage's own coordinates.
 *
 * Shared by the tool row and the popover that appears at the selection —
 * they are two ways to reach the same three or four actions, and a second
 * copy of this would be a second set of off-by-one bugs.
 */

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
export interface Selected {
  /** Where it is, ready to become a mark. */
  where: Omit<Highlight, "colour" | "note">;
  /** The words themselves — what Copy puts on the clipboard and what Look
   *  up charges the budget for. */
  text: string;
  /** Where to put a popover: the selection's own box on screen. */
  rect: DOMRect;
}

export function selectionIn(): Selected | null {
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
  if (end <= start) return null;
  return {
    where: { partId, index, start, end },
    text: range.toString(),
    rect: range.getBoundingClientRect(),
  };
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

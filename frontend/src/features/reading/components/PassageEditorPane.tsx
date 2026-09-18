import { forwardRef, useImperativeHandle, useRef } from "react";
import { Plus, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { newId } from "@/features/paper/form-syntax";
import type { Passage, PassageParagraph } from "@/features/paper/types";

/**
 * The passage an author is writing questions against — the left pane of the
 * reading editor, where a listening one has its waveform.
 *
 * The two panes answer the same question: *where does the answer come from*.
 * A listening author marks a moment in a recording; a reading author selects
 * the words. So this exposes the same imperative handle the audio pane does
 * (`selectedText`), and the editor above it can ask either one what the
 * author is pointing at without knowing which pane it has.
 *
 * ## Paragraphs, and their letters
 *
 * A reading passage is stored as paragraphs rather than one block of prose,
 * because two of Reading's own tasks are answered by naming one. The letters
 * are OFFERED and not imposed: most passages have none, and a book letters
 * its paragraphs only where a task needs it. `Letter the paragraphs` fills
 * them in A, B, C…, which is the thing an author is about to do by hand the
 * moment they add a matching-headings group.
 *
 * Splitting on a blank line is how the text arrives. An author pastes a
 * passage out of a PDF or a book and it comes with its paragraph breaks in
 * it; asking them to add each paragraph one at a time would be asking them
 * to undo that and redo it by hand.
 */

export interface PassageEditorHandle {
  /** The words the author has highlighted in the passage, or null where the
   *  selection is not in it at all. The same contract the audio pane's
   *  `selectedText` has, so the editor can ask either. */
  selectedText: () => string | null;
}

interface PassageEditorPaneProps {
  /** The passage being edited, or null on a part that has none yet. */
  passage: Passage | null;
  onChange: (passage: Passage) => void;
  /** Which passage of the paper this is, for its heading. */
  partNumber: number;
  /** The part's own title, which is what the paper prints above the text. */
  title: string;
  onTitleChange: (title: string) => void;
  disabled?: boolean;
}

const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

function empty(): Passage {
  return { paragraphs: [], subtitle: null, source: null };
}

/** One pasted block, as paragraphs. Blank lines are the break, because that
 *  is how a passage arrives from anywhere it is copied out of. */
function split(text: string): PassageParagraph[] {
  return text
    .split(/\n\s*\n/)
    .map((block) => block.replace(/\s+/g, " ").trim())
    .filter(Boolean)
    .map((body) => ({ label: null, text: body }));
}

export const PassageEditorPane = forwardRef<
  PassageEditorHandle,
  PassageEditorPaneProps
>(function PassageEditorPane(
  { passage, onChange, partNumber, title, onTitleChange, disabled },
  ref,
) {
  const body = useRef<HTMLDivElement | null>(null);
  const current = passage ?? empty();
  const paragraphs = current.paragraphs;
  const lettered = paragraphs.some((p) => p.label);

  useImperativeHandle(ref, () => ({
    selectedText: () => {
      const selection = window.getSelection();
      if (!selection || selection.isCollapsed) return null;
      // Only a selection INSIDE the passage counts. A phrase highlighted in
      // the question list is the author re-reading their own work, not
      // pointing at the text — the same distinction the transcript pane
      // draws, and for the same reason.
      const within = body.current?.contains(selection.anchorNode);
      if (!within) return null;
      return selection.toString().replace(/\s+/g, " ").trim();
    },
  }));

  const put = (next: Partial<Passage>) => onChange({ ...current, ...next });

  const editParagraph = (index: number, text: string) =>
    put({
      paragraphs: paragraphs.map((p, i) => (i === index ? { ...p, text } : p)),
    });

  return (
    <div
      inert={disabled}
      className={cn("flex h-full flex-col", disabled && "opacity-40")}
    >
      <div className="mb-3 shrink-0 space-y-2">
        <input
          type="text"
          value={title}
          onChange={(e) => onTitleChange(e.target.value)}
          placeholder={`Reading Passage ${partNumber}`}
          aria-label="Passage title"
          className="h-10 w-full rounded-md border border-border bg-transparent px-3 text-sm text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:outline-none"
        />
        <input
          type="text"
          value={current.source ?? ""}
          onChange={(e) => put({ source: e.target.value || null })}
          placeholder="Source line, as the book prints it (optional)"
          aria-label="Source"
          className="h-8 w-full rounded-md border border-border bg-transparent px-3 text-xs text-muted-foreground placeholder:text-muted-foreground/70 focus-visible:border-ring focus-visible:outline-none"
        />
      </div>

      {paragraphs.length === 0 ? (
        // One box to paste into, because that is how a passage arrives. The
        // blank lines in it become the paragraphs — asking an author to add
        // nine of them one at a time would be asking them to undo the paste.
        <textarea
          onPaste={(e) => {
            const text = e.clipboardData.getData("text");
            if (!text.trim()) return;
            e.preventDefault();
            put({ paragraphs: split(text) });
          }}
          onBlur={(e) => {
            if (e.target.value.trim()) put({ paragraphs: split(e.target.value) });
          }}
          placeholder="Paste the passage. Blank lines become paragraphs."
          aria-label="Passage text"
          className="min-h-0 flex-1 resize-none rounded-md border border-dashed border-border bg-transparent p-3 text-[0.95rem] leading-7 text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:outline-none"
        />
      ) : (
        <>
          <div className="mb-2 flex shrink-0 items-center gap-2 text-xs">
            <button
              type="button"
              onClick={() =>
                put({
                  paragraphs: paragraphs.map((p, i) => ({
                    ...p,
                    // Off again clears them rather than leaving a letter no
                    // question names — the same rule the server follows about
                    // a label being what the BOOK prints.
                    label: lettered ? null : (LETTERS[i] ?? null),
                  })),
                })
              }
              aria-pressed={lettered}
              className={cn(
                "rounded-md border px-2 py-1 transition-colors duration-fast focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                lettered
                  ? "border-primary text-primary"
                  : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              {lettered ? "Lettered A–" + (LETTERS[paragraphs.length - 1] ?? "?") : "Letter the paragraphs"}
            </button>
            <span className="text-muted-foreground">
              {paragraphs.length} paragraph{paragraphs.length === 1 ? "" : "s"}
            </span>
            <span className="ml-auto text-muted-foreground">
              {/* What a reading paper is measured in. A passage that comes out
                  at 300 words is an excerpt and one at 1,500 is two. */}
              {paragraphs
                .reduce((n, p) => n + p.text.trim().split(/\s+/).length, 0)
                .toLocaleString()}{" "}
              words
            </span>
          </div>

          <div
            ref={body}
            className="scrollbar-quiet min-h-0 flex-1 space-y-2 overflow-y-auto pr-2"
          >
            {paragraphs.map((paragraph, index) => (
              <div key={index} className="flex gap-2">
                {paragraph.label && (
                  <span
                    aria-hidden
                    className="w-4 shrink-0 pt-2 text-sm font-semibold text-muted-foreground"
                  >
                    {paragraph.label}
                  </span>
                )}
                <textarea
                  value={paragraph.text}
                  onChange={(e) => editParagraph(index, e.target.value)}
                  aria-label={`Paragraph ${paragraph.label ?? index + 1}`}
                  rows={Math.max(2, Math.ceil(paragraph.text.length / 70))}
                  className="min-w-0 flex-1 resize-none rounded-md border border-transparent bg-transparent px-2 py-1.5 text-[0.95rem] leading-7 text-foreground hover:border-border focus-visible:border-ring focus-visible:outline-none"
                />
                <button
                  type="button"
                  aria-label={`Remove paragraph ${paragraph.label ?? index + 1}`}
                  onClick={() =>
                    put({
                      paragraphs: paragraphs
                        .filter((_, i) => i !== index)
                        .map((p, i) => ({
                          ...p,
                          label: lettered ? (LETTERS[i] ?? null) : p.label,
                        })),
                    })
                  }
                  className="mt-1.5 flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors duration-fast hover:text-destructive focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                >
                  <Trash2 className="size-3.5" aria-hidden />
                </button>
              </div>
            ))}
          </div>

          <button
            type="button"
            onClick={() =>
              put({
                paragraphs: [
                  ...paragraphs,
                  {
                    label: lettered ? (LETTERS[paragraphs.length] ?? null) : null,
                    text: "",
                  },
                ],
              })
            }
            className="mt-2 flex shrink-0 items-center gap-1.5 self-start rounded-md border border-border px-2 py-1 text-xs text-muted-foreground transition-colors duration-fast hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            <Plus className="size-3.5" aria-hidden />
            Add a paragraph
          </button>
        </>
      )}
    </div>
  );
});

/** A blank passage, for a part that has just been made. */
export function newPassage(): Passage {
  return empty();
}

/** Unused, but kept beside `newPassage` so the two ids come from one place
 *  if paragraphs ever need identity of their own. */
export const paragraphKey = newId;

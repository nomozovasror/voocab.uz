import { Fragment, type ReactNode } from "react";
import { ArrowDown } from "lucide-react";
import { cn } from "@/lib/utils";
import type { FormBlock } from "@/features/listening/form-syntax";

interface FormLayoutProps {
  blocks: FormBlock[];
  /** How a gap is drawn — a blank rule in the editor's preview, a real input
   *  on the take page. Keeping the layout and the gap separate is what lets
   *  the author preview the exact shape the candidate will sit. */
  renderGap: (number: number) => ReactNode;
  /** Whether every line of this sheet is one thing named and one letter — a
   *  labelling task. It swaps which of the two columns is the fixed one: the
   *  answer side holds a letter and nothing else, so the names take the room.
   *  The editor lays it out the same way, off the same fact. */
  blankPerRow?: boolean;
  className?: string;
}

/**
 * Renders a parsed completion layout: a title, section headings, rows whose
 * values can carry gaps anywhere inside them, grids, and flow charts.
 *
 * The label column is fixed rather than sized to content so the values line
 * up down the form the way they do on the printed paper — a value column
 * that jogged left and right per row would read as a list of unrelated
 * fields instead of one form.
 *
 * A row with no label has no column to line up with, and takes the whole
 * width. That is what notes, sentences, a summary paragraph and short-answer
 * questions are: the same gaps, on a page with no label column. Holding the
 * column open for them left every one of those indented past an empty quarter
 * of the sheet, which is a form with the labels rubbed out rather than the
 * thing the paper actually prints.
 */
export function FormLayout({
  blocks,
  renderGap,
  blankPerRow,
  className,
}: FormLayoutProps) {
  return (
    <div className={cn("text-sm text-foreground", className)}>
      {blocks.map((block, i) => {
        if (block.kind === "space") {
          return <div key={i} className="h-3" aria-hidden />;
        }

        if (block.kind === "divider") {
          return (
            <div key={i} className="my-2 h-px bg-border" role="separator" />
          );
        }

        if (block.kind === "title") {
          return (
            <h3
              key={i}
              className="mb-3 text-center text-sm font-semibold tracking-wide text-foreground uppercase"
            >
              {block.text}
            </h3>
          );
        }

        if (block.kind === "heading") {
          return (
            <h4 key={i} className="mt-3 mb-1.5 font-medium text-primary">
              {block.text}
            </h4>
          );
        }

        if (block.kind === "flow") {
          return (
            // Narrower than the sheet and centred: a chart is read down, and
            // boxes stretched to the full width would read as rows.
            <div key={i} className="mx-auto my-2 max-w-md">
              {block.steps.map((step, sIndex) => (
                <Fragment key={sIndex}>
                  {sIndex > 0 && (
                    <div className="flex justify-center py-1" aria-hidden>
                      <ArrowDown className="size-4 text-muted-foreground" />
                    </div>
                  )}
                  <div className="rounded-md border border-border px-3 py-2 leading-7 text-foreground">
                    {step.parts.map((part, k) =>
                      part.kind === "text" ? (
                        <Fragment key={k}>{part.text}</Fragment>
                      ) : (
                        <Fragment key={k}>{renderGap(part.number)}</Fragment>
                      ),
                    )}
                  </div>
                </Fragment>
              ))}
            </div>
          );
        }

        if (block.kind === "table") {
          // An all-blank header row isn't drawn: that is how a table without
          // one is written, and an empty band across the top of the grid
          // would be a header saying nothing.
          const hasHead = block.head.some((cell) => cell.trim());
          return (
            // Scrolls inside itself. A four-column table on a phone is wider
            // than the page, and the page is not the thing that should move.
            <div key={i} className="my-2 overflow-x-auto">
              <table className="w-full border-collapse">
                {hasHead && (
                  <thead>
                    <tr>
                      {block.head.map((cell, c) => (
                        <th
                          key={c}
                          scope="col"
                          className="border border-border bg-foreground/5 px-2.5 py-1.5 text-left font-medium text-foreground"
                        >
                          {cell}
                        </th>
                      ))}
                    </tr>
                  </thead>
                )}
                <tbody>
                  {block.rows.map((row, r) => (
                    <tr key={r}>
                      {row.map((cell, c) => (
                        <td
                          key={c}
                          className="border border-border px-2.5 py-1.5 align-top leading-7 text-foreground"
                        >
                          {cell.parts.map((part, k) =>
                            part.kind === "text" ? (
                              <Fragment key={k}>{part.text}</Fragment>
                            ) : (
                              <Fragment key={k}>
                                {renderGap(part.number)}
                              </Fragment>
                            ),
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }

        return (
          <div key={i} className="flex gap-3 py-0.5">
            {/* Full strength, like the value beside it: on the paper a label
                is content, not a caption. The column and its rule already
                separate the two — dimming real text to do that job again cost
                legibility for nothing.

                Absent entirely when there is no label, rather than empty: a
                held-open column is what made every note and every sentence
                start a quarter of the way across the page. */}
            {block.label.trim() && (
              <div
                className={cn(
                  "text-foreground",
                  blankPerRow ? "min-w-0 flex-1" : "w-64 shrink-0",
                )}
              >
                {block.label}
              </div>
            )}
            <div
              className={cn(
                "space-y-1",
                block.label.trim() && blankPerRow
                  ? "w-40 shrink-0"
                  : "min-w-0 flex-1",
              )}
            >
              {block.lines.map((line, j) => (
                <div key={j} className={cn("flex gap-1.5", line.bullet && "pl-0")}>
                  {line.bullet && (
                    <span aria-hidden className="text-muted-foreground">
                      –
                    </span>
                  )}
                  <div className="min-w-0 flex-1 leading-7">
                    {line.parts.map((part, k) =>
                      part.kind === "text" ? (
                        <Fragment key={k}>{part.text}</Fragment>
                      ) : (
                        <Fragment key={k}>{renderGap(part.number)}</Fragment>
                      ),
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

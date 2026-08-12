import { Fragment, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { FormBlock } from "@/features/listening/form-syntax";

interface FormLayoutProps {
  blocks: FormBlock[];
  /** How a gap is drawn — a blank rule in the editor's preview, a real input
   *  on the take page. Keeping the layout and the gap separate is what lets
   *  the author preview the exact shape the candidate will sit. */
  renderGap: (number: number) => ReactNode;
  className?: string;
}

/**
 * Renders a parsed form-completion layout: a title, section headings, and
 * label/value rows whose values can carry gaps anywhere inside them and run
 * to several bulleted lines.
 *
 * The label column is fixed rather than sized to content so the values line
 * up down the form the way they do on the printed paper — a value column
 * that jogged left and right per row would read as a list of unrelated
 * fields instead of one form.
 */
export function FormLayout({ blocks, renderGap, className }: FormLayoutProps) {
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

        return (
          <div key={i} className="flex gap-3 py-0.5">
            {/* Full strength, like the value beside it: on the paper a label
                is content, not a caption. The column and its rule already
                separate the two — dimming real text to do that job again cost
                legibility for nothing. */}
            <div className="w-64 shrink-0 text-foreground">
              {block.label}
            </div>
            <div className="min-w-0 flex-1 space-y-1">
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

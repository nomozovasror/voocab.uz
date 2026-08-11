import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * The few things about building a form that can't be worked out by clicking
 * something: the bracket rule, and what a gap's colour means.
 *
 * It sits at the foot of the questions pane and gets out of the way on its
 * own — dismissed by hand, retired once a few gaps have been authored, and
 * hidden the moment the form grows tall enough to reach it, since by then the
 * space it occupies belongs to the work.
 */

const DISMISSED_KEY = "voocab:form-help-dismissed";
/** Gaps authored before it steps aside for good. Three is enough to have used
 *  the brackets, seen a chip, and linked one to the audio. */
const LEARNED_AT = 3;

interface FormHelpCardProps {
  /** Gaps in this material with an answer written — the closest thing to
   *  evidence the author knows how this works. */
  authoredGaps: number;
  /** False once the form is long enough that the card would sit on top of
   *  it. Decided by the pane, which is the only thing that can measure it. */
  visible?: boolean;
  /** Asked for by hand, from the editor's own "tips" button. Overrides both
   *  the dismissal and the fit check: someone who has just asked for this
   *  wants to see it, not be told there's no room. */
  forceOpen?: boolean;
  onDismiss?: () => void;
}

export function FormHelpCard({
  authoredGaps,
  visible = true,
  forceOpen,
  onDismiss,
}: FormHelpCardProps) {
  const [dismissed, setDismissed] = useState(true);

  // Resolved after mount so the first paint doesn't flash the card at an
  // author who put it behind them long ago.
  useEffect(() => {
    setDismissed(window.localStorage.getItem(DISMISSED_KEY) === "1");
  }, []);

  useEffect(() => {
    if (authoredGaps < LEARNED_AT) return;
    window.localStorage.setItem(DISMISSED_KEY, "1");
    setDismissed(true);
  }, [authoredGaps]);

  if (!forceOpen && (dismissed || !visible)) return null;

  // `mt-auto` is what puts it at the foot of the pane: sticky alone only pins
  // once the content overflows, so on a short form it just sat under the last
  // thing above it. Sticky stays for the case in between — the form long
  // enough to scroll, but not yet long enough for the card to step aside.
  return (
    <div className="pointer-events-none sticky bottom-0 z-10 mt-auto pt-3">
      <div className="pointer-events-auto relative rounded-lg border border-border bg-card px-3.5 py-3 text-[11px] shadow-lg">
        <button
          type="button"
          onClick={() => {
            window.localStorage.setItem(DISMISSED_KEY, "1");
            setDismissed(true);
            onDismiss?.();
          }}
          title="Hide this — the tips button up top brings it back"
          aria-label="Hide the form-building tips"
          className="absolute top-1.5 right-1.5 rounded p-1 text-muted-foreground transition-colors hover:text-foreground"
        >
          <X className="size-3.5" aria-hidden />
        </button>

        {/* Three columns rather than three stacked rows: the prose needs the
            width, the legend and the keys don't, and side by side they fill
            the space the card already occupies instead of leaving it blank to
            the right of two short lines. */}
        <div className="grid gap-x-6 gap-y-3 pr-6 sm:grid-cols-[minmax(0,1.7fr)_auto_auto]">
          {/* The bracket rule is the only thing here an author can't discover
              by clicking something, so it leads — and it's put in terms of
              what the learner ends up seeing, which is the part that makes it
              make sense. */}
          {/* A step up from the reference columns beside it: this is the one
              thing here that is read as a sentence rather than scanned. */}
          <p className="text-xs leading-relaxed text-muted-foreground">
            Put each answer in brackets —{" "}
            <Code>
              Nationality: <Bracket>[</Bracket>Uzbek<Bracket>]</Bracket>
            </Code>
            . Learners see a numbered blank there and type their answer in. A
            comma accepts either:{" "}
            <Code>
              <Bracket>[</Bracket>20, twenty<Bracket>]</Bracket>
            </Code>
            .
          </p>

          {/* All four colours a chip can take, in the order they get better.
              Red isn't where a gap starts — brackets create one around an
              answer — but it is reachable by emptying one, and a legend that
              leaves a colour out is a legend you can't trust. */}
          <div className="flex flex-col gap-1.5 text-muted-foreground">
            <Swatch className="border-destructive/60 bg-destructive/10">
              no answer
            </Swatch>
            <Swatch className="border-border bg-foreground/5">
              not linked to audio
            </Swatch>
            <Swatch className="border-warning/60 bg-warning/10">
              not said there
            </Swatch>
            <Swatch className="border-success/50 bg-success/10">done</Swatch>
          </div>

          <div className="flex flex-col gap-1.5 text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <Key>Space</Key> play/pause
            </span>
            <span className="flex items-center gap-1.5">
              <Key>
                <span className="text-sm leading-none">⌘</span>
              </Key>
              +<Key>S</Key> save
            </span>
            <span className="flex items-center gap-1.5">
              <Key>Enter</Key> next row
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

/** A colour sample and what it means, on one line so the four read as a
 *  legend rather than a list. */
function Swatch({
  className,
  children,
}: {
  className: string;
  children: React.ReactNode;
}) {
  return (
    <span className="flex items-center gap-1.5">
      <span
        aria-hidden
        className={cn("h-3 w-6 shrink-0 rounded-sm border", className)}
      />
      {children}
    </span>
  );
}

/** The brackets are the instruction; the words between them are only an
 *  example, so the brackets are what carries the colour. */
function Bracket({ children }: { children: React.ReactNode }) {
  return <span className="font-semibold text-primary">{children}</span>;
}

function Code({ children }: { children: React.ReactNode }) {
  return (
    <code className="rounded bg-foreground/8 px-1.5 py-0.5 font-mono text-foreground">
      {children}
    </code>
  );
}

function Key({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="inline-flex min-w-6 items-center justify-center rounded border border-border bg-foreground/5 px-1.5 py-0.5 font-mono text-[11px] text-foreground">
      {children}
    </kbd>
  );
}

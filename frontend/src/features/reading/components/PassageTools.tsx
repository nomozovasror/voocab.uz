import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeftRight,
  BookOpen,
  CircleHelp,
  Highlighter,
  MoreHorizontal,
  StickyNote,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useMediaQuery } from "@/hooks/use-media-query";
import { selectionIn, type Selected } from "@/features/reading/selection";
import {
  MARK_COLOURS,
  MARK_MEANING,
  type Highlight,
  type MarkColour,
} from "@/features/reading/highlights";
import {
  LOOKUP_BUDGET,
  canOpen,
  known,
  left,
  type Lookups,
} from "@/features/reading/lookups";

/**
 * Everything a reader does to the passage that is not answering it.
 *
 * Nine controls in three groups, and the grouping is most of what keeps it
 * readable:
 *
 *     Highlight · Note · Clear  │  A A A  │  Swap · Look up 3 · Help
 *
 * What MARKS the passage, what SETS it, and what sits beside it. A rule
 * between each, because nine buttons in a row is a row of nine buttons — the
 * reader has to scan all of them to find the one they want, every time.
 *
 * ## Select first, then act
 *
 * Not a mode with a pen held down. A reader drags to select for half a dozen
 * reasons — reading carefully, counting, holding their place — and a tool
 * that marked every one of them fills the passage with colour by the third
 * paragraph. Select-then-act also gives every button here somewhere honest
 * to be disabled, which is how each one says what it needs.
 *
 * There are two ways to the same few actions, deliberately: this row is the
 * one a reader can SEE, and the popover at the selection is the one they
 * reach for once they know it is there. Neither is a shortcut for the other
 * — they are the visible path and the fast path.
 *
 * ## Why Look up carries a number
 *
 * See `features/reading/lookups.ts`. The count IS the feature: a reader with
 * three left spends them on the words the questions turn on rather than on
 * the first unfamiliar noun in paragraph A.
 */

/** The three sizes, as a percentage of the pane's own. Small enough a step
 *  that nothing reflows alarmingly, large enough to be worth pressing. */
const SIZES = [100, 115, 130] as const;
const SIZE_KEY = "voocab-reading-text-size";
const COLOUR_KEY = "voocab-reading-mark-colour";

export function useTextSize(): [number, (next: number) => void] {
  return useRemembered<number>(SIZE_KEY, SIZES[0], (raw) =>
    (SIZES as readonly number[]).includes(Number(raw)) ? Number(raw) : null,
  );
}

/** The colour the next mark takes. Remembered, because a reader who has
 *  decided blue means "the answer is here" means it for the whole paper. */
export function useMarkColour(): [MarkColour, (next: MarkColour) => void] {
  return useRemembered<MarkColour>(COLOUR_KEY, "key", (raw) =>
    MARK_COLOURS.includes(raw as MarkColour) ? (raw as MarkColour) : null,
  );
}

function useRemembered<T>(
  key: string,
  fallback: T,
  parse: (raw: string) => T | null,
): [T, (next: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      return (raw !== null ? parse(raw) : null) ?? fallback;
    } catch {
      return fallback;
    }
  });
  const put = useCallback(
    (next: T) => {
      setValue(next);
      try {
        localStorage.setItem(key, String(next));
      } catch {
        /* private window; the default is fine */
      }
    },
    [key],
  );
  return [value, put];
}

export interface PassageToolsProps {
  marks: Highlight[];
  onMarks: (next: Highlight[]) => void;
  size: number;
  onSize: (next: number) => void;
  colour: MarkColour;
  onColour: (next: MarkColour) => void;
  /** Ask for a note on the current selection. The page owns the writing of
   *  it: the panel that opens belongs to the page, not to a row of buttons
   *  in the header. */
  onNote: (at: Selected) => void;
  swapped: boolean;
  onSwap: () => void;
  lookups: Lookups;
  onLookup: (word: string) => void;
  /** False in an exam: there is no dictionary in the hall. */
  allowLookup: boolean;
  onHelp: () => void;
  helpOpen: boolean;
}

export function PassageTools({
  marks,
  onMarks,
  size,
  onSize,
  colour,
  onColour,
  onNote,
  swapped,
  onSwap,
  lookups,
  onLookup,
  allowLookup,
  onHelp,
  helpOpen,
}: PassageToolsProps) {
  const selected = useSelection();
  const [picking, setPicking] = useState(false);
  // Below this the nine do not fit beside a title and a clock, so the third
  // group folds into one button — the two it holds are the two a reader
  // reaches for least often per passage.
  const roomy = useMediaQuery("(min-width: 80rem)");
  const [more, setMore] = useState(false);

  const mark = (which: MarkColour) => {
    onColour(which);
    if (selected) {
      onMarks([...marks, { ...selected.where, colour: which }]);
      window.getSelection()?.removeAllRanges();
    }
    setPicking(false);
  };

  const word = selected?.text.trim() ?? "";
  const oneWord = word.length > 0 && !/\s/.test(word);
  const aside = (
    <Aside
      stacked={!roomy}
      swapped={swapped}
      onSwap={onSwap}
      lookupLeft={left(lookups)}
      canLookUp={oneWord && canOpen(lookups, word)}
      free={oneWord && known(lookups, word)}
      onLookup={() => onLookup(word)}
      allowLookup={allowLookup}
      onHelp={onHelp}
      helpOpen={helpOpen}
    />
  );

  return (
    <div className="relative flex shrink-0 items-center gap-1">
      {/* ── What marks the passage ─────────────────────────────────── */}
      <Tool
        icon={Highlighter}
        label="Highlight"
        pressed={picking}
        onClick={() => setPicking((was) => !was)}
        swatch={colour}
      />
      <Tool
        icon={StickyNote}
        label="Note"
        disabled={!selected}
        title={selected ? "Write a note on this" : "Select the words first"}
        onClick={() => selected && onNote(selected)}
      />
      {/* Only where there is something to clear. A permanently visible
          "Clear" on an unmarked passage is a button whose whole job is to be
          greyed out. */}
      {marks.length > 0 && <Tool label="Clear" onClick={() => onMarks([])} />}

      <Rule />

      {/* ── What sets it ───────────────────────────────────────────── */}
      <div
        role="group"
        aria-label="Text size"
        className="flex items-center gap-0.5 rounded-md bg-surface-sunken p-0.5"
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

      <Rule />

      {/* ── What sits beside it ────────────────────────────────────── */}
      {roomy ? (
        aside
      ) : (
        <>
          <Tool
            icon={MoreHorizontal}
            label="More tools"
            hideLabel
            pressed={more}
            onClick={() => setMore((was) => !was)}
          />
          {more && <Tray onClose={() => setMore(false)}>{aside}</Tray>}
        </>
      )}

      {/* The colours, under the button that opens them. */}
      {picking && (
        <Tray onClose={() => setPicking(false)} className="right-auto left-0">
          {MARK_COLOURS.map((which) => (
            <button
              key={which}
              type="button"
              onClick={() => mark(which)}
              className={cn(
                "flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs whitespace-nowrap transition-colors duration-fast hover:bg-surface-hover focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                colour === which ? "text-foreground" : "text-muted-foreground",
              )}
            >
              <Swatch colour={which} ring={colour === which} />
              {MARK_MEANING[which]}
            </button>
          ))}
          {!selected && (
            // Said rather than left to be discovered: pressing the button
            // before selecting anything is the natural order, and it does
            // nothing visible.
            <p className="mt-1 border-t border-border px-2 pt-1.5 text-[0.7rem] text-muted-foreground">
              Select the words first, then pick a colour.
            </p>
          )}
        </Tray>
      )}
    </div>
  );
}

function Aside({
  stacked,
  swapped,
  onSwap,
  lookupLeft,
  canLookUp,
  free,
  onLookup,
  allowLookup,
  onHelp,
  helpOpen,
}: {
  stacked?: boolean;
  swapped: boolean;
  onSwap: () => void;
  lookupLeft: number;
  canLookUp: boolean;
  free: boolean;
  onLookup: () => void;
  allowLookup: boolean;
  onHelp: () => void;
  helpOpen: boolean;
}) {
  return (
    <div
      className={cn(
        "flex items-center gap-1",
        stacked && "flex-col items-stretch",
      )}
    >
      <Tool
        icon={ArrowLeftRight}
        label="Swap"
        pressed={swapped}
        title={
          swapped
            ? "Put the passage back on the left"
            : "Put the passage on the right"
        }
        onClick={onSwap}
        stacked={stacked}
      />
      {/* Absent in an exam rather than disabled. A greyed-out dictionary is
          the page telling a candidate what they may not have, every minute
          of an hour. */}
      {allowLookup && (
        <Tool
          icon={BookOpen}
          label={`Look up ${lookupLeft}`}
          disabled={!canLookUp}
          title={
            free
              ? "Already looked up — this one is free"
              : lookupLeft === 0
                ? `No look-ups left — ${LOOKUP_BUDGET} a passage`
                : "Select one word, then look it up"
          }
          onClick={onLookup}
          stacked={stacked}
          // Spent looks spent even where a free word is selected: the number
          // is what the reader is budgeting against.
          dim={lookupLeft === 0}
        />
      )}
      <Tool
        icon={CircleHelp}
        label="Help"
        pressed={helpOpen}
        title="What this kind of question asks for"
        onClick={onHelp}
        stacked={stacked}
      />
    </div>
  );
}

function Tool({
  icon: Icon,
  label,
  hideLabel,
  pressed,
  disabled,
  dim,
  title,
  onClick,
  swatch,
  stacked,
}: {
  icon?: typeof Highlighter;
  label: string;
  hideLabel?: boolean;
  pressed?: boolean;
  disabled?: boolean;
  dim?: boolean;
  title?: string;
  onClick: () => void;
  swatch?: MarkColour;
  stacked?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title ?? label}
      aria-pressed={pressed}
      aria-label={hideLabel ? label : undefined}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs whitespace-nowrap transition-colors duration-fast focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:pointer-events-none disabled:opacity-40",
        stacked && "w-full justify-start",
        pressed
          ? "bg-primary/15 text-primary"
          : "text-muted-foreground hover:bg-surface-hover hover:text-foreground",
        dim && "opacity-50",
      )}
    >
      {Icon && <Icon className="size-3.5 shrink-0" aria-hidden />}
      {!hideLabel && label}
      {swatch && <Swatch colour={swatch} small />}
    </button>
  );
}

export function Swatch({
  colour,
  ring,
  small,
}: {
  colour: MarkColour;
  ring?: boolean;
  small?: boolean;
}) {
  return (
    <span
      aria-hidden
      className={cn(
        "shrink-0 rounded-full",
        small ? "size-2" : "size-3",
        ring && "ring-2 ring-foreground/30 ring-offset-1 ring-offset-background",
        colour === "key"
          ? "bg-mark-key"
          : colour === "found"
            ? "bg-mark-found"
            : "bg-mark-doubt",
      )}
    />
  );
}

function Rule() {
  return <span aria-hidden className="mx-1 h-4 w-px bg-border" />;
}

/** A small panel hanging under the row, closed by anything outside it. */
function Tray({
  children,
  onClose,
  className,
}: {
  children: React.ReactNode;
  onClose: () => void;
  className?: string;
}) {
  const box = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const away = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) onClose();
    };
    const escape = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    // `mousedown` rather than click: the row's own buttons act on click, and
    // a close running first would eat the press that opened this.
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", escape);
    };
  }, [onClose]);
  return (
    <div
      ref={box}
      className={cn(
        "absolute top-full right-0 z-50 mt-2 flex min-w-48 flex-col gap-0.5 rounded-xl border border-border bg-card p-1.5 shadow-lg",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** The selection, watched rather than read on click — every button that
 *  needs one has to be able to look disabled without one. */
export function useSelection(): Selected | null {
  const [selected, setSelected] = useState<Selected | null>(null);
  useEffect(() => {
    const check = () => setSelected(selectionIn());
    document.addEventListener("selectionchange", check);
    return () => document.removeEventListener("selectionchange", check);
  }, []);
  return selected;
}

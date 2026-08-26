import { useEffect, useRef, useState } from "react";
import { ChevronDown, Command, Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { hasPlatformModifier, isApplePlatform } from "@/lib/platform";
import {
  SCOPE_PARTS,
  SORT_LABEL,
  SORT_ORDER,
  scopeLabel,
} from "@/features/listening/practice";
import type {
  FilterOption,
  PracticeFilterState,
  Scope,
  SortKey,
} from "@/features/listening/practice";
import type {
  DifficultyBand,
  QuestionGroupType,
} from "@/features/listening/types";

/**
 * What narrows the list: one search field and one row of controls.
 *
 * Which controls combine and which replace each other follows from what each
 * one asks. The scope chips — All, Part 1–4, Full test — are answers to a
 * single question ("which materials"), so exactly one is true at a time, and
 * clicking the one that is already on puts it back to All: a filter you can
 * turn on and not off is a trap.
 *
 * Everything else layers on top. "Show done" is about the reader, the question
 * type is about what is inside, the difficulty is about how it turned out —
 * and "Part 3, matching, not done yet" is a request somebody actually has.
 * Those last two are multi-select for the same reason the scope is not:
 * "Easy or Medium" is one request, not two.
 *
 * Type and difficulty are menus rather than chips so the whole thing stays on
 * one line. Eleven type chips would be a second navigation bar above a list of
 * five materials, and the names don't shorten — "Flow-chart completion" is
 * what the paper calls it, and abbreviating it would mean the filter and the
 * row it filters call the same task two things.
 */

interface SearchFieldProps {
  value: string;
  onChange: (value: string) => void;
  /** Down-arrow out of the field lands on the first row — the field and the
   *  list are one flow, and having to Tab past the chips to reach the results
   *  is the kind of thing that makes people use the mouse. */
  onDown?: () => void;
  count: number;
  /**
   * The field has reached the top and is sitting in the header's row of
   * islands, so it dresses as one: the frosted ground, the border, the shadow.
   *
   * A state on ONE element, never a second copy in the header. The field
   * travels there under `position: sticky` and this is what it puts on when
   * it arrives — which is why the arrival can be watched rather than only
   * noticed afterwards.
   */
  landed?: boolean;
}

export function SearchField({
  value,
  onChange,
  onDown,
  count,
  landed = false,
}: SearchFieldProps) {
  const input = useRef<HTMLInputElement | null>(null);
  // The hint is only worth drawing where the field is empty and idle. Once
  // there is a query in it, the key cap sits next to the answer to a question
  // nobody is still asking.
  const [focused, setFocused] = useState(false);

  // ⌘K on a Mac, Ctrl+K everywhere else — the same decision that prints the
  // key cap below, so the two can't disagree (see lib/platform.ts).
  //
  // Registered here, on the component that owns the input, rather than in the
  // page: the shortcut IS this field, and a listener living anywhere else
  // would be one that outlives it.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "k" && event.key !== "K") return;
      if (!hasPlatformModifier(event)) return;
      // Chrome sends ⌘K to the address bar and Firefox to its search box;
      // both offer it to the page first, which is the whole reason this
      // shortcut is ours to take.
      event.preventDefault();
      input.current?.focus();
      // Selected, not merely focused: pressing it again with a query already
      // typed should let you start over without reaching for Backspace.
      input.current?.select();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div
      className={cn(
        // The island's own height and radius from the start, so the only
        // things left to change on landing are colour and depth — a shape
        // that morphs mid-flight reads as two shapes.
        "relative h-12 rounded-2xl border",
        "transition-[background-color,border-color,box-shadow] duration-300 ease-out motion-reduce:transition-none",
        // backdrop-blur is on the whole way: over the page's own background
        // it costs nothing to look at, and switching a blur on is the one
        // part of this that cannot be animated smoothly.
        "backdrop-blur-md",
        landed
          ? "border-border bg-background/70 shadow-sm supports-[backdrop-filter]:bg-background/60"
          : "border-border bg-card shadow-none",
      )}
    >
      <Search
        aria-hidden
        className="pointer-events-none absolute top-1/2 left-4 size-4 -translate-y-1/2 text-muted-foreground"
      />
      <input
        ref={input}
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" && onDown) {
            e.preventDefault();
            onDown();
          }
        }}
        placeholder="Search by title, topic or author"
        aria-label="Search materials"
        // The count is announced, not drawn: the list header already says it
        // in print, and a screen reader needs to hear that typing changed
        // something.
        aria-describedby="practice-result-count"
        className={cn(
          // Room for the widest the caps get ("Ctrl" + "K"), kept whether or
          // not they are showing, so the text doesn't shift sideways the
          // moment the field is focused.
          "h-full w-full rounded-2xl bg-transparent pr-20 pl-11 text-sm text-foreground",
          "placeholder:text-muted-foreground focus-visible:outline-none",
          // Safari draws its own clear button on type=search, which lands on
          // top of nothing useful and looks nothing like the rest of this.
          "[&::-webkit-search-cancel-button]:appearance-none",
        )}
      />
      {/* One chip for the whole shortcut, the two keys spaced inside it.
          aria-hidden: a screen-reader user is not hunting for a key cap, and
          the field already announces itself. Pointer-events off so the chip
          is part of the field to click on rather than a hole in it. */}
      {!focused && value === "" && (
        <kbd
          aria-hidden
          className="pointer-events-none absolute top-1/2 right-3 flex h-5 -translate-y-1/2 items-center gap-1 rounded-md border border-border-subtle bg-surface-hover px-1.5 text-xs leading-none text-muted-foreground"
        >
          {/* Lucide's own ⌘ rather than the character: U+2318 is in almost no
              UI font, so it arrives from whatever fallback the system offers
              and is drawn to a different weight and height than the letter
              beside it. An icon is the same stroke as everything else in this
              interface, at a size we choose. `Ctrl` is a word and stays one. */}
          {isApplePlatform() ? (
            <Command className="size-3" />
          ) : (
            <span>Ctrl</span>
          )}
          <span>K</span>
        </kbd>
      )}
      <span id="practice-result-count" className="sr-only" aria-live="polite">
        {count} material{count === 1 ? "" : "s"}
      </span>
    </div>
  );
}

/** The pill every control in the row wears, on or off. One definition, so a
 *  chip and a menu trigger can't drift into being two shapes.
 *
 *  `h-8` rather than the button's own height: inside the bar below, the gap
 *  between a chip and the bar's edge is what makes it look set INTO something
 *  rather than dropped on top of it. */
const PILL = "h-8 rounded-full px-3 text-xs";
const PILL_ON =
  "bg-primary/15 text-primary hover:bg-primary/20 hover:text-primary aria-expanded:bg-primary/20 aria-expanded:text-primary";
const PILL_OFF = "text-muted-foreground hover:bg-surface-hover hover:text-foreground";

/** One chip. A `Button` rather than a bare `<button>`, reshaped into a pill:
 *  the focus ring, the disabled handling and the active nudge all come with
 *  it, and there is one definition of a button in the app. */
function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      aria-pressed={active}
      onClick={onClick}
      className={cn(PILL, active ? PILL_ON : PILL_OFF)}
    >
      {children}
    </Button>
  );
}

/** The rule between groups of controls — they answer different questions and
 *  a gap alone doesn't say so. */
function ChipDivider() {
  return <span aria-hidden className="mx-1.5 h-5 w-px bg-border-subtle" />;
}

interface FilterChipsProps {
  filters: PracticeFilterState;
  onChange: (next: Partial<PracticeFilterState>) => void;
  /** The two multi-selects flip one value rather than being handed a new
   *  list, and that is not a style choice: computing `[...bands, band]` here
   *  reads the array off THIS render, so two toggles landing in one batch
   *  would both start from the same list and the first would be lost. The
   *  page does the flip inside the state updater, where `prev` is current. */
  onToggleBand: (band: DifficultyBand) => void;
  onToggleType: (type: QuestionGroupType) => void;
  /** Only what the catalogue actually holds, with counts. */
  typeOptions: FilterOption<QuestionGroupType>[];
  bandOptions: FilterOption<DifficultyBand>[];
}

export function FilterChips({
  filters,
  onChange,
  onToggleBand,
  onToggleType,
  typeOptions,
  bandOptions,
}: FilterChipsProps) {
  const { scope, showDone, bands, types } = filters;

  /** Picking the scope that is already picked clears it. Without this the
   *  only way out of "Full test" is Clear filters, which also throws away the
   *  search and everything else the reader had set. */
  const pickScope = (next: Scope) =>
    onChange({ scope: scope === next ? "all" : next });

  return (
    // One bar rather than chips loose on the page: it says the row is a set
    // of controls that belong together, it gives the active chip something to
    // be lit against, and it stops eleven scattered pills from reading as
    // eleven separate decisions.
    //
    // rounded-2xl and not rounded-full: on a narrow screen the row wraps to
    // two lines, and a pill shape two lines tall looks like a mistake where a
    // soft rectangle looks deliberate. justify-center so each wrapped line
    // centres itself instead of the block centring and its contents sitting
    // left.
    <div
      role="group"
      aria-label="Filter materials"
      className="inline-flex flex-wrap items-center justify-center gap-0.5 rounded-2xl border border-border-subtle bg-card/50 p-1"
    >
      <Chip active={scope === "all"} onClick={() => onChange({ scope: "all" })}>
        All
      </Chip>
      {SCOPE_PARTS.map((part) => (
        <Chip key={part} active={scope === part} onClick={() => pickScope(part)}>
          {scopeLabel(part)}
        </Chip>
      ))}

      <ChipDivider />

      <Chip active={scope === "full"} onClick={() => pickScope("full")}>
        Full test
      </Chip>
      {/* The one chip that starts the list off narrower than the catalogue.
          It reads as what it does rather than as what it hides — "Show done"
          off is a list of what there is left to practise, which is the
          question the page is here to answer. */}
      <Chip
        active={showDone}
        onClick={() => onChange({ showDone: !showDone })}
      >
        Show done
      </Chip>

      {(typeOptions.length > 0 || bandOptions.length > 0) && <ChipDivider />}

      {/* Absent while the catalogue is still loading, and on the day it holds
          nothing — a menu whose every option returns nothing is a dead end
          dressed as a choice. */}
      {typeOptions.length > 0 && (
        <MultiSelectMenu
          name="Question type"
          plural="question types"
          options={typeOptions}
          selected={types}
          onToggle={onToggleType}
          onClear={() => onChange({ types: [] })}
          className="w-60"
        />
      )}
      {bandOptions.length > 0 && (
        <MultiSelectMenu
          name="Difficulty"
          plural="levels"
          options={bandOptions}
          selected={bands}
          onToggle={onToggleBand}
          onClear={() => onChange({ bands: [] })}
          className="w-44"
        />
      )}
    </div>
  );
}

/**
 * A pill that opens a list of checkboxes — the same control for "which task"
 * and "how hard", because they are the same question shape.
 *
 * The count beside each option answers "is this worth clicking" before the
 * click, and the menu stays open while they are ticked: picking three types
 * should not be three trips.
 */
function MultiSelectMenu<T extends string>({
  name,
  plural,
  options,
  selected,
  onToggle,
  onClear,
  className,
}: {
  name: string;
  plural: string;
  options: FilterOption<T>[];
  selected: T[];
  onToggle: (value: T) => void;
  onClear: () => void;
  className?: string;
}) {
  // One selection names itself; several count themselves. A trigger reading
  // "Form completion, Multiple choice, Matching" would be wider than the list.
  const label =
    selected.length === 0
      ? name
      : selected.length === 1
        ? (options.find((o) => o.value === selected[0])?.label ?? name)
        : `${selected.length} ${plural}`;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className={cn(PILL, selected.length > 0 ? PILL_ON : PILL_OFF)}
        >
          {label}
          <ChevronDown className="size-3" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className={className}>
        {options.map(({ value, label: optionLabel, count }) => (
          <DropdownMenuCheckboxItem
            key={value}
            checked={selected.includes(value)}
            onSelect={(e) => {
              e.preventDefault();
              onToggle(value);
            }}
          >
            <span className="flex-1">{optionLabel}</span>
            <span className="tabular-nums text-muted-foreground">{count}</span>
          </DropdownMenuCheckboxItem>
        ))}
        {selected.length > 0 && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={onClear}>Clear {plural}</DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/**
 * Above the list: how many there are, and in what order.
 *
 * The order used to be a printed statement, which meant it never changed and
 * read as decoration. It is a control now — four orders, each answerable from
 * what a row already shows. "Most popular" and "Suits you" are the obvious
 * next two and stay absent until the data behind them is (see `SortKey`).
 */
export function ListHeader({
  count,
  filtered,
  loading,
  hiddenDone = 0,
  sort,
  onSort,
  onClear,
}: {
  count: number;
  filtered: boolean;
  /** Held open while the list loads. A count is the one thing on this row
   *  that isn't known yet, and printing "0 materials" over a page of
   *  skeletons is the page answering a question it hasn't asked. */
  loading?: boolean;
  /** How many materials the default "done are put away" is holding back, over
   *  and above whatever the chips are doing. Printed, because a list quietly
   *  short of what the reader knows is in it is a list that looks broken —
   *  the chip above turns them back on. */
  hiddenDone?: number;
  sort: SortKey;
  onSort: (sort: SortKey) => void;
  onClear: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4 px-3 py-1.5">
      <p className="flex items-center gap-2 text-xs text-muted-foreground">
        {loading ? (
          <Skeleton className="inline-block h-[0.8em] w-20" />
        ) : (
          <span>
            <span className="tabular-nums text-foreground">{count}</span>{" "}
            material{count === 1 ? "" : "s"}
            {hiddenDone > 0 && (
              <>
                {" · "}
                <span className="tabular-nums">{hiddenDone}</span> done, put
                away
              </>
            )}
          </span>
        )}
        {filtered && (
          // A pill like everything in the row above, not an underlined link:
          // underlined text sitting in a line of plain text reads as sitting a
          // pixel low even when it doesn't, because the rule under it is what
          // the eye takes for the baseline.
          <Button
            type="button"
            variant="ghost"
            size="xs"
            onClick={onClear}
            className="rounded-full px-2 text-xs text-muted-foreground hover:text-foreground"
          >
            <X className="size-3" aria-hidden />
            Clear filters
          </Button>
        )}
      </p>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="xs"
            aria-label={`Sort: ${SORT_LABEL[sort]}`}
            className="rounded-full px-2 text-xs text-muted-foreground hover:text-foreground"
          >
            {/* Before the words, not after. It is the handle on the control
                — what says this is a menu rather than a statement — and read
                left to right that is the first thing about it worth knowing.
                Trailing, it landed at the far right corner of the list where
                nothing else is, and read as punctuation. */}
            <ChevronDown className="size-3" aria-hidden />
            {SORT_LABEL[sort]}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-44">
          <DropdownMenuRadioGroup
            value={sort}
            onValueChange={(value) => onSort(value as SortKey)}
          >
            {SORT_ORDER.map((key) => (
              <DropdownMenuRadioItem key={key} value={key}>
                {SORT_LABEL[key]}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

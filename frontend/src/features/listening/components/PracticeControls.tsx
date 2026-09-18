import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useMediaQuery } from "@/hooks/use-media-query";
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
  COURSE_COVERS_LABEL,
  COURSE_COVERS_ORDER,
  COURSE_LENGTH_LABEL,
  COURSE_LENGTH_ORDER,
  COURSE_STATUS_LABEL,
  COURSE_STATUS_ORDER,
  DRILL_PART_ORDER,
  drillPartLabel,
  LIST_MODES,
  LIST_MODE_LABEL,
  SCOPE_OPTIONS,
  SORT_LABEL,
  SORT_ORDER,
  scopeLabel,
} from "@/features/listening/practice";
import type {
  CourseCovers,
  DrillPart,
  TaskFamily,
  CourseLength,
  CourseStatus,
  FilterOption,
  ListMode,
  PracticeFilterState,
  Scope,
  SortKey,
} from "@/features/listening/practice";
import type {
  DifficultyBand,
  PracticeFacet,
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
  /** Which list is being searched. The field is the one control that spans
   *  both, so it says which one it is pointed at rather than making the
   *  reader infer it from what comes back. */
  mode?: ListMode;
}

export function SearchField({
  value,
  onChange,
  onDown,
  count,
  landed = false,
  mode = "materials",
}: SearchFieldProps) {
  const noun =
    mode === "courses"
      ? "collection"
      : mode === "drills"
        ? "exercise"
        : "material";
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
        placeholder={
          mode === "courses"
            ? "Search collections by title or author"
            : mode === "drills"
              ? // Two screens, one field, and it means something different on
                // each: the grid is a choice between kinds of question, the
                // list is a choice between papers. Saying both is what stops
                // it reading as broken on whichever one you are not on.
                "Search a kind of question, or a book"
              : "Search by title, topic or author"
        }
        aria-label={
          mode === "courses"
            ? "Search collections"
            : mode === "drills"
              ? "Search exercises"
              : "Search materials"
        }
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
        {count} {noun}
        {count === 1 ? "" : "s"}
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

/** Horizontal slack inside the box that clips the swapping control groups, so
 *  its edge never cuts through a focus ring. Four, against the ring's three. */
const SLACK = 4;
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

/**
 * The two lists, and which one is showing.
 *
 * A segmented control at the head of the filter bar. It is not a filter — it
 * decides which list there is rather than narrowing one — but it belongs in
 * the same row because that is where somebody looks for it, and it earns its
 * place at the head: everything to its right narrows, and this is the widest
 * question in the row.
 *
 * What keeps it from reading as one more chip is the lit background on the
 * selected side. A chip is on or off against the bar; this is one control
 * with two halves and one of them always lit, which is a different shape even
 * before you read it.
 */
function ModeSwitch({
  mode,
  onChange,
}: {
  mode: ListMode;
  onChange: (mode: ListMode) => void;
}) {
  return (
    <div
      role="tablist"
      aria-label="What to show"
      className="flex items-center gap-0.5"
    >
      {LIST_MODES.map((value) => (
        <Button
          key={value}
          type="button"
          role="tab"
          aria-selected={mode === value}
          variant="ghost"
          size="sm"
          onClick={() => onChange(value)}
          className={cn(
            PILL,
            mode === value
              ? "bg-foreground/10 text-foreground hover:bg-foreground/10 hover:text-foreground"
              : PILL_OFF,
          )}
        >
          {LIST_MODE_LABEL[value]}
        </Button>
      ))}
    </div>
  );
}

/**
 * One of the two sets of controls, in the box they share.
 *
 * The active one is in the flow and sets the box's height; the inactive one is
 * lifted out of it, so the two never push each other about and the box is
 * always exactly the size of what is showing.
 *
 * The fade is deliberately faster than the resize. Half the point of the
 * animation is that the row is understood to be the SAME row asking a
 * different question, and a fade that outlasted the movement would read as
 * two rows changing places.
 */
function Group({
  ref,
  active,
  children,
}: {
  ref: React.Ref<HTMLDivElement>;
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      ref={ref}
      inert={!active}
      aria-hidden={!active}
      className={cn(
        "flex flex-wrap items-center gap-0.5 transition-opacity duration-fast ease-out motion-reduce:transition-none sm:flex-nowrap",
        // `sm:w-max` on the active one too: it takes its own natural width
        // rather than the box's, which is what keeps the measurement honest
        // (see FilterChips). Below `sm` it wraps instead, and no width is
        // being animated there anyway.
        active
          ? "relative opacity-100 sm:w-max"
          : "pointer-events-none absolute inset-y-0 left-1 w-max opacity-0",
      )}
    >
      {children}
    </div>
  );
}

/**
 * The courses list's one filter.
 *
 * A radio menu, the same shape as the scope menu beside it in the other mode
 * — which is most of why the swap reads as one row changing its mind rather
 * than as two rows. Four answers to one question, exactly one true, and "All
 * courses" is an option rather than a clear button: going back to everything
 * is picking an answer, not undoing one.
 */
function StatusMenu({
  status,
  onChange,
}: {
  status: CourseStatus;
  onChange: (status: CourseStatus) => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className={cn(PILL, status !== "all" ? PILL_ON : PILL_OFF)}
        >
          {COURSE_STATUS_LABEL[status]}
          <ChevronDown className="size-3" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-40">
        <DropdownMenuRadioGroup
          value={status}
          onValueChange={(value) => onChange(value as CourseStatus)}
        >
          {COURSE_STATUS_ORDER.map((option) => (
            <DropdownMenuRadioItem key={option} value={option}>
              {COURSE_STATUS_LABEL[option]}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/**
 * A menu of one-of-many answers, with how many rows each would leave.
 *
 * The counts are the difference between a filter and a trap. There are a
 * dozen courses and three menus over them, so a list is one click from empty
 * — and an option that returns nothing is a dead end dressed as a choice.
 * Anything the library does not hold is simply not offered.
 *
 * "Any …" is an option in the list rather than a clear button beneath it:
 * going back to everything is picking an answer, not undoing one.
 */
function CountedMenu<T extends string>({
  value,
  anyLabel,
  options,
  labels,
  counts,
  onChange,
  width,
}: {
  value: T | "all";
  anyLabel: string;
  options: readonly T[];
  labels: Record<T | "all", string>;
  counts: PracticeFacet[];
  onChange: (value: T | "all") => void;
  width: string;
}) {
  const byValue = new Map(counts.map((row) => [row.value, row.count]));
  const offered = options.filter((option) => (byValue.get(option) ?? 0) > 0);

  // Nothing to choose between is not a menu. On a young library every course
  // is a Part 1 drill, and a menu whose one option is the whole list is a
  // control that can only ever do nothing.
  if (offered.length === 0) return null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className={cn(PILL, value !== "all" ? PILL_ON : PILL_OFF)}
        >
          {value === "all" ? anyLabel : labels[value]}
          <ChevronDown className="size-3" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className={width}>
        <DropdownMenuRadioGroup
          value={value}
          onValueChange={(next) => onChange(next as T | "all")}
        >
          <DropdownMenuRadioItem value="all">{anyLabel}</DropdownMenuRadioItem>
          {offered.map((option) => (
            <DropdownMenuRadioItem key={option} value={option}>
              <span className="flex-1">{labels[option]}</span>
              <span className="tabular-nums text-muted-foreground">
                {byValue.get(option)}
              </span>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

interface FilterChipsProps {
  filters: PracticeFilterState;
  onChange: (next: Partial<PracticeFilterState>) => void;
  /** Which list is showing. Courses have no part number and no difficulty
   *  band, so this row swaps to the questions a course can answer. */
  mode: ListMode;
  onMode: (mode: ListMode) => void;
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
  /** The courses list's own filters, and what there is to filter by. Three
   *  different questions: where the reader is with a course, which part of
   *  the paper it drills, and how much of their life it wants. */
  status: CourseStatus;
  onStatus: (status: CourseStatus) => void;
  covers: CourseCovers;
  onCovers: (covers: CourseCovers) => void;
  length: CourseLength;
  onLength: (length: CourseLength) => void;
  coverOptions: PracticeFacet[];
  lengthOptions: PracticeFacet[];
  /** The drill the reader has opened, if any. Null is the grid of task
   *  cards, where there is nothing to narrow yet. */
  /** The card the reader has opened, if any. Null is the grid, where there
   *  is nothing to narrow yet. */
  drillFamily: TaskFamily | null;
  onDrillFamily: (family: TaskFamily | null) => void;
  drillPart: DrillPart;
  onDrillPart: (part: DrillPart) => void;
}

export function FilterChips({
  filters,
  onChange,
  mode,
  onMode,
  onToggleBand,
  onToggleType,
  typeOptions,
  bandOptions,
  status,
  onStatus,
  covers,
  onCovers,
  length,
  onLength,
  coverOptions,
  lengthOptions,
  drillFamily,
  onDrillFamily,
  drillPart,
  onDrillPart,
}: FilterChipsProps) {
  const { scope, showDone, bands, types } = filters;

  // --- The two sets of controls, and the width between them ----------------
  //
  // Both are rendered at all times; the inactive one is lifted out of the
  // flow and faded, and the strip they share is given the active one's width.
  // Swapped by mounting and unmounting instead, the row simply changed size
  // in one frame — which reads as the controls having broken rather than as
  // their having become a different question.
  //
  // Measured rather than written down: the material row's width moves as its
  // own menus change label ("Difficulty" becoming "2 levels"), and a number
  // typed in here would be wrong every time that happened.
  //
  // Both groups size themselves (`w-max`) and the box is given THEIR width,
  // never the other way round. That direction is the whole of what makes the
  // measurement work: constrained by the box, a group's own width stops
  // changing when its contents do, the ResizeObserver never fires again, and
  // the box keeps whatever width it was given on the first paint — which is
  // the width of a filter row whose menus had not loaded yet, with the rest
  // of the controls hanging outside the bar.
  const materialsRef = useRef<HTMLDivElement | null>(null);
  const coursesRef = useRef<HTMLDivElement | null>(null);
  const drillsRef = useRef<HTMLDivElement | null>(null);
  const [widths, setWidths] = useState<Record<ListMode, number>>({
    materials: 0,
    courses: 0,
    drills: 0,
  });

  // Guarded, so it can be called on every render without looping: React only
  // bails out of a `setState` when the value is identical, and a fresh object
  // never is.
  const measure = useCallback(() => {
    const next = {
      materials: materialsRef.current?.scrollWidth ?? 0,
      courses: coursesRef.current?.scrollWidth ?? 0,
      drills: drillsRef.current?.scrollWidth ?? 0,
    };
    setWidths((was) =>
      was.materials === next.materials &&
      was.courses === next.courses &&
      was.drills === next.drills
        ? was
        : next,
    );
  }, []);

  // Twice over, and it needs to be both.
  //
  // The observer catches a group changing size on its own — a menu label
  // growing as its counts load. What it does NOT reliably catch is a group
  // gaining a CHILD on the same commit the box is asked to resize, and that
  // is the common case here: opening a card adds two chips to the drills
  // group, and measured only by the observer the box kept the width it had
  // on the grid and clipped them out of sight. So the measurement also runs
  // after every render, where the guard above makes it free when nothing
  // moved.
  useLayoutEffect(measure);

  useEffect(() => {
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    if (materialsRef.current) observer.observe(materialsRef.current);
    if (coursesRef.current) observer.observe(coursesRef.current);
    if (drillsRef.current) observer.observe(drillsRef.current);
    return () => observer.disconnect();
  }, [measure]);

  // Only where the row is on one line. Below `sm` it wraps, an explicit width
  // would fight the wrapping, and `scrollWidth` measured off a wrapped row is
  // not the number this wants anyway. A phone gets the swap without the
  // width animation, which is the part that needs the room.
  const oneLine = useMediaQuery("(min-width: 40rem)");
  // Plus the slack the box carries so a focus ring on the pill at either end
  // survives the clipping — see the note on it below.
  const width = oneLine && widths[mode] ? widths[mode] + SLACK * 2 : undefined;

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
      aria-label={mode === "courses" ? "Filter collections" : "Filter materials"}
      className="inline-flex flex-wrap items-center justify-center gap-0.5 rounded-2xl border border-border-subtle bg-card/50 p-1"
    >
      <ModeSwitch mode={mode} onChange={onMode} />

      {/*
        The controls the switch swaps between, stacked in one box that resizes
        to whichever is showing.

        `inert` rather than only `pointer-events-none`: the hidden row is
        still in the document, and a keyboard would otherwise tab straight
        into controls nobody can see.
      */}
      {/*
        `overflow-hidden` is what turns the resize into a reveal: the incoming
        group is already at its full width behind the edge, and the box opens
        onto it rather than the controls sliding in from somewhere.

        The negative margin and matching padding are the price of clipping —
        without them the box's edge would cut through the focus ring of the
        pill at either end. Four pixels of slack is more than the three the
        ring needs, and the negative margin puts the visible edge back exactly
        where it was.
      */}
      <div
        style={{ width }}
        className="relative -mx-1 overflow-hidden px-1 transition-[width] duration-slow ease-out motion-reduce:transition-none"
      >
        <Group ref={materialsRef} active={mode === "materials"}>
          <ChipDivider />

          <ScopeMenu
            scope={scope}
            onChange={(next) => onChange({ scope: next })}
          />
          {/* The one chip that starts the list off narrower than the
              catalogue. It reads as what it does rather than as what it hides
              — "Show done" off is a list of what there is left to practise,
              which is the question the page is here to answer. */}
          <Chip
            active={showDone}
            onClick={() => onChange({ showDone: !showDone })}
          >
            Show done
          </Chip>

          {(typeOptions.length > 0 || bandOptions.length > 0) && <ChipDivider />}

          {/* Absent while the catalogue is still loading, and on the day it
              holds nothing — a menu whose every option returns nothing is a
              dead end dressed as a choice. */}
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
        </Group>

        {/* The same four questions the catalogue's row asks, in the same
            order, about a course instead of a paper: which part of the paper
            it drills, where the reader is with it, and what is in it. That
            the two rows come out near enough the same width is a consequence
            rather than the aim — but it is why the swap reads as one row
            changing its mind. */}
        <Group ref={coursesRef} active={mode === "courses"}>
          <ChipDivider />
          <CountedMenu
            value={covers}
            anyLabel={COURSE_COVERS_LABEL.all}
            options={COURSE_COVERS_ORDER}
            labels={COURSE_COVERS_LABEL}
            counts={coverOptions}
            onChange={onCovers}
            width="w-40"
          />
          <StatusMenu status={status} onChange={onStatus} />
          <ChipDivider />
          <CountedMenu
            value={length}
            anyLabel={COURSE_LENGTH_LABEL.all}
            options={COURSE_LENGTH_ORDER}
            labels={COURSE_LENGTH_LABEL}
            counts={lengthOptions}
            onChange={onLength}
            width="w-48"
          />
        </Group>

        {/* Drills. On the grid of task cards this group is empty on purpose:
            the cards ARE the navigation, and there is nothing to narrow until
            one is picked, so the box collapses to the switch alone.

            Inside a kind of drill it carries the one thing that stops the row
            reading as broken — a chip naming what you are looking at, which
            is also the way back to the grid — and the "done" toggle, which
            means the same here as it does over the catalogue. */}
        <Group ref={drillsRef} active={mode === "drills"}>
          <ChipDivider />
          {/* The part menu is here on BOTH screens, and it does the same
              thing on each: on the grid it narrows the counts the cards
              report, in a list it narrows the list. Which part a task
              belongs to is the sharpest question there is about these —
              every map in the library is Part 2 and every form completion
              Part 1 — so the cards for a chosen part are the tasks that
              actually appear in it. */}
          <DrillPartMenu part={drillPart} onChange={onDrillPart} />
          {drillFamily && (
            <>
              <Chip active onClick={() => onDrillFamily(null)}>
                {drillFamily.label}
                <X className="ml-1 size-3" aria-hidden />
              </Chip>
              <Chip
                active={showDone}
                onClick={() => onChange({ showDone: !showDone })}
              >
                Show done
              </Chip>
            </>
          )}
        </Group>
      </div>
    </div>
  );
}

/**
 * The scope, as one menu.
 *
 * Radio rather than checkbox, because these are six answers to one question
 * ("which materials") and exactly one is true at a time — which is also why
 * "All parts" is an option in the list rather than a clear button underneath
 * it: going back to everything is picking an answer, not undoing one.
 */
function ScopeMenu({
  scope,
  onChange,
}: {
  scope: Scope;
  onChange: (scope: Scope) => void;
}) {
  const narrowed = scope !== "all";
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className={cn(PILL, narrowed ? PILL_ON : PILL_OFF)}
        >
          {scopeLabel(scope)}
          <ChevronDown className="size-3" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-40">
        <DropdownMenuRadioGroup
          value={String(scope)}
          onValueChange={(value) =>
            onChange(
              value === "all" || value === "full"
                ? value
                : (Number(value) as Scope),
            )
          }
        >
          {SCOPE_OPTIONS.map((option) => (
            <DropdownMenuRadioItem key={option} value={String(option)}>
              {scopeLabel(option)}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** Which part of the paper a drill came from. The scope menu's shape, asked
 *  of a question group instead of a material — and without "Full test",
 *  which means nothing about a single task. */
function DrillPartMenu({
  part,
  onChange,
}: {
  part: DrillPart;
  onChange: (part: DrillPart) => void;
}) {
  const narrowed = part !== "all";
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className={cn(PILL, narrowed ? PILL_ON : PILL_OFF)}
        >
          {drillPartLabel(part)}
          <ChevronDown className="size-3" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-36">
        <DropdownMenuRadioGroup
          value={String(part)}
          onValueChange={(value) =>
            onChange(value === "all" ? "all" : (Number(value) as DrillPart))
          }
        >
          <DropdownMenuRadioItem value="all">
            {drillPartLabel("all")}
          </DropdownMenuRadioItem>
          {DRILL_PART_ORDER.map((option) => (
            <DropdownMenuRadioItem key={option} value={String(option)}>
              {drillPartLabel(option)}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
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
        {/* The count goes in the foreground as a whole phrase, not just the
            digit: "8" lit and "materials" greyed reads as a number with a
            caption, and the answer to "how much is there" is the phrase. */}
        {loading ? (
          <Skeleton className="inline-block h-[0.8em] w-20" />
        ) : (
          <span className="text-foreground">
            <span className="tabular-nums">{count}</span>{" "}
            material{count === 1 ? "" : "s"}
            {/* Dimmer than the count, because it is a different kind of
                statement: the count is the answer to "how much is there", and
                this is a footnote about what the page has done with the rest.
                At the same weight the two read as one long sentence, and the
                answer gets lost in its own caveat.

                Said plainly, too. "12 done, put away" left the reader to work
                out both what was put away and by whom — beside "4 materials"
                it read as a contradiction rather than as the explanation of
                one. */}
            {hiddenDone > 0 && (
              <span className="text-muted-foreground">
                {" · "}
                <span className="tabular-nums">{hiddenDone}</span> done{" "}
                {hiddenDone === 1 ? "one is" : "ones are"} hidden
              </span>
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
            // The order is a live setting, not a note about one. Greyed it
            // read as a caption on the list; it is a control, and the thing
            // it currently says is a fact about what is on screen.
            className="rounded-full px-2 text-xs text-foreground"
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

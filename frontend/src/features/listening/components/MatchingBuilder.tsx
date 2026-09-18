import { useEffect, useRef } from "react";
import { CircleAlert, CornerUpLeft, Plus, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatClock } from "@/features/studio/format";
import { ToolbarButton } from "@/features/listening/components/BuilderTools";
import {
  MAX_MATCH_OPTIONS,
  matchLetter,
  matchTo,
  markItem,
  matchedSummary,
  newMatchItem,
  newMatchOption,
  patchItem,
  setMatch,
  takenOptions,
  type MatchItem,
  type MatchOption,
  type MatchingIssue,
} from "@/features/paper/matching";

/**
 * The matching builder.
 *
 * Same sheet as the other two — one bordered card, controls that appear on
 * hover, a row of tools underneath — because an author moving between them
 * inside one part should not have to learn a third editor. What differs is
 * that this card has two halves, and they are not the same kind of thing.
 *
 * The top half is the box: the options, lettered, that the whole group is
 * answered from. It is tinted and sits above a divider because it belongs to
 * the group rather than to any question — the paper prints it once, above the
 * set, and an author who reads it as "the first question" has read the block
 * wrong.
 *
 * The bottom half is the items, one per number on the page, and each of them
 * carries the box's letters again — this time as buttons. Pressing one is how
 * an item is answered, and it is the same one gesture the multiple-choice
 * builder uses: the press opens the transcript, and the line picked there
 * settles both which option is right and where that answer is given. The time
 * reads out at the row's edge afterwards, as a reading rather than a button.
 *
 * Where a letter may only answer one item, pressing one that another item
 * already holds MOVES it. That is what the gesture means on paper — there is
 * one A and it goes in one box — and refusing the press instead would leave
 * the author to go and find the other item before they could fix this one.
 */

interface MatchingBuilderProps {
  options: MatchOption[];
  items: MatchItem[];
  /** Both applied against the latest copy rather than the one this render
   *  was built from — see FormBuilder's note; holding Enter on an option is
   *  enough to land two edits between renders. */
  onOptionsChange: (edit: (current: MatchOption[]) => MatchOption[]) => void;
  onItemsChange: (edit: (current: MatchItem[]) => MatchItem[]) => void;
  /** Removing an option has to clear the answers that pointed at it, so it
   *  is one edit over both halves rather than two that could land apart. */
  onRemoveOption: (optionId: string) => void;
  /** The number the first item of this group carries on the page. */
  startNumber: number;
  /** Whether one option may answer more than one item. */
  allowReuse: boolean;
  /** What is still missing. The box's own problems arrive with a null
   *  `itemId` and are shown once, above the items. */
  issues?: MatchingIssue[];
  transcriptSelection?: string;
  /** Marking where the answer is said, the same way a gap does it: the page
   *  owns the transcript, so it takes the phrases to look for and hands back
   *  a range. Absent while there is no recording to mark against. */
  onMarkAudio?: (
    answers: string[],
    apply: (range: { startMs: number; endMs: number }) => void,
  ) => void;
  extraTools?: React.ReactNode;
}

export function MatchingBuilder({
  options,
  items,
  onOptionsChange,
  onItemsChange,
  onRemoveOption,
  startNumber,
  allowReuse,
  issues,
  transcriptSelection,
  onMarkAudio,
  extraTools,
}: MatchingBuilderProps) {
  // Inputs are registered by key so the caret can be put where the edit
  // implies it should go: into the option a press of Enter just created,
  // into the item "+ question" just added.
  const inputs = useRef(new Map<string, HTMLInputElement>());
  const pendingFocus = useRef<string | null>(null);
  const register = (key: string) => (el: HTMLInputElement | null) => {
    if (el) inputs.current.set(key, el);
    else inputs.current.delete(key);
  };

  useEffect(() => {
    const key = pendingFocus.current;
    if (!key) return;
    pendingFocus.current = null;
    const el = inputs.current.get(key);
    if (!el) return;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  });

  // Which field the author was last in, so a phrase taken from the transcript
  // lands where they were working. Held for the whole card rather than per
  // row: both halves are being written from the same recording, and a group
  // of eight items would otherwise carry eight copies of one button.
  const lastField = useRef<HTMLInputElement | null>(null);
  const remember = (e: React.FocusEvent<HTMLInputElement>) => {
    lastField.current = e.currentTarget;
  };

  /** Drops the selected transcript words into the field last worked in.
   *  Typed through execCommand rather than assigned, so the browser's own
   *  undo keeps the change and the caret ends up after it. */
  const takeFromTranscript = () => {
    const field = lastField.current;
    if (!field || !transcriptSelection) return;
    field.focus();
    document.execCommand("insertText", false, transcriptSelection);
  };

  const appendOption = () => {
    if (options.length >= MAX_MATCH_OPTIONS) return;
    const option = newMatchOption();
    pendingFocus.current = `option#${option.id}`;
    onOptionsChange((current) =>
      current.length >= MAX_MATCH_OPTIONS ? current : [...current, option],
    );
  };

  const addItem = () => {
    const item = newMatchItem();
    pendingFocus.current = `item#${item.id}`;
    onItemsChange((current) => [...current, item]);
  };

  /** The one press that answers an item. Nothing is matched until the
   *  transcript has been answered too — they are the same decision, so a
   *  cancelled pick leaves the item exactly as it was. */
  const chooseAnswer = (item: MatchItem, option: MatchOption) => {
    // Already this one: pressing it again takes it back, which is the only
    // way out of a wrong press. Nothing to ask the transcript about.
    if (item.answer === option.id || !onMarkAudio) {
      onItemsChange((current) =>
        matchTo(current, item.id, option.id, allowReuse),
      );
      return;
    }
    // Both, because either may be what the recording says: the item is named
    // outright far more often than the option's wording is, but a set whose
    // options are places has it the other way round.
    const phrases = [item.prompt.trim(), option.text.trim()].filter(Boolean);
    // Set rather than toggled: this runs once per line picked, and the author
    // may shift-click a second one to widen the phrase. Toggling here took
    // the answer back off on that second pick.
    onMarkAudio(phrases, (range) =>
      onItemsChange((current) =>
        markItem(setMatch(current, item.id, option.id, allowReuse), item.id, range),
      ),
    );
  };

  const boxIssue = issues?.find((issue) => issue.itemId === null);
  const issueByItem = new Map(
    (issues ?? [])
      .filter((issue) => issue.itemId !== null)
      .map((issue) => [issue.itemId as string, issue]),
  );
  const taken = takenOptions(items);

  return (
    <div>
      <div className="overflow-hidden rounded-lg border border-border bg-card">
        {/* The box. Tinted and above a divider because it belongs to the
            group: it is answered FROM, not answered. */}
        <div className="border-b border-border bg-foreground/[0.025] px-3 py-2.5">
          <p className="mb-1.5 text-xs text-muted-foreground">
            Options to match from
          </p>
          <ul className="space-y-1">
            {options.map((option, index) => {
              const letter = matchLetter(index);
              return (
                <li
                  key={option.id}
                  className="group/option flex items-center gap-2"
                >
                  <span
                    aria-hidden
                    className="flex size-6 shrink-0 items-center justify-center rounded-full border border-border text-xs font-semibold text-muted-foreground"
                  >
                    {letter.toUpperCase()}
                  </span>
                  <input
                    type="text"
                    ref={register(`option#${option.id}`)}
                    value={option.text}
                    onChange={(e) =>
                      onOptionsChange((current) =>
                        current.map((o) =>
                          o.id === option.id ? { ...o, text: e.target.value } : o,
                        ),
                      )
                    }
                    onFocus={remember}
                    onKeyDown={(e) => {
                      if (e.key !== "Enter") return;
                      e.preventDefault();
                      appendOption();
                    }}
                    placeholder="option"
                    aria-label={`Option ${letter.toUpperCase()}`}
                    className="min-w-0 flex-1 border-b border-transparent bg-transparent pb-0.5 text-base text-foreground placeholder:text-muted-foreground/50 hover:border-border focus-visible:border-primary focus-visible:outline-none"
                  />
                  {/* Two is the fewest a box can have; below that there is
                      nothing to match between. Its space is held either way,
                      so nothing shifts when it appears on hover. */}
                  <span className="flex size-6 shrink-0 items-center justify-center">
                    {options.length > 2 && (
                      <button
                        type="button"
                        onClick={() => onRemoveOption(option.id)}
                        aria-label={`Remove option ${letter.toUpperCase()}`}
                        title="Remove this option, and any answer using it"
                        className="flex size-6 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-opacity group-hover/option:opacity-100 hover:text-destructive focus-visible:opacity-100"
                      >
                        <X className="size-3.5" aria-hidden />
                      </button>
                    )}
                  </span>
                </li>
              );
            })}

            {/* The next option, drawn as one but a size down, and the tally
                riding on the same line: both are about the box, and two
                half-empty rows in a row is a gap for no reason. */}
            <li className="flex items-center gap-2 pt-0.5">
              <button
                type="button"
                onClick={appendOption}
                title="Add an option"
                className="group/add flex min-w-0 items-center gap-2 text-left"
              >
                <span className="flex size-5 shrink-0 items-center justify-center rounded-full border border-dashed border-border text-muted-foreground transition-colors group-hover/add:border-primary group-hover/add:text-primary">
                  <Plus className="size-3" aria-hidden />
                </span>
                <span className="text-sm text-muted-foreground/60 transition-colors group-hover/add:text-foreground">
                  add an option
                </span>
              </button>
              <span
                className={cn(
                  "ml-auto shrink-0 pl-2 text-xs tabular-nums",
                  items.every((item) => item.answer)
                    ? "text-success"
                    : "text-muted-foreground/70",
                )}
              >
                {matchedSummary(items)}
              </span>
            </li>
          </ul>

          {/* A rule about the box as a whole — too few options for the
              questions under it, say. Not something any single row shows, so
              it is said here, once. */}
          {boxIssue && !boxIssue.selfEvident && (
            <p className="mt-2 flex items-start gap-1.5 text-xs text-destructive">
              <CircleAlert className="mt-0.5 size-3 shrink-0" aria-hidden />
              {boxIssue.detail}
            </p>
          )}
        </div>

        <div className="divide-y divide-border">
          {items.map((item, index) => (
            <ItemRow
              key={item.id}
              item={item}
              number={startNumber + index}
              startNumber={startNumber}
              options={options}
              allowReuse={allowReuse}
              taken={taken}
              items={items}
              issue={issueByItem.get(item.id)}
              register={register}
              onFocusField={remember}
              onPrompt={(prompt) =>
                onItemsChange((current) =>
                  patchItem(current, item.id, (i) => ({ ...i, prompt })),
                )
              }
              onChoose={(option) => chooseAnswer(item, option)}
              // The only item in a group can't be removed: a group with no
              // questions is not a thing the API will store, and deleting the
              // group is the thing the author actually means.
              onRemove={
                items.length > 1
                  ? () =>
                      onItemsChange((current) =>
                        current.filter((i) => i.id !== item.id),
                      )
                  : undefined
              }
            />
          ))}
        </div>
      </div>

      <div className="mt-2.5 flex flex-wrap items-center justify-center gap-1.5">
        <ToolbarButton
          onClick={addItem}
          icon={<Plus className="size-3.5" aria-hidden />}
          label="question"
          title="Add a question at the end"
        />
        {/* Only once there is something to take, so most of the time this row
            is just the two buttons. One for the whole card rather than one
            per row: everything in here is being written from the same
            recording, and eight items would carry eight of them. */}
        {transcriptSelection && (
          <button
            type="button"
            // Keeps the transcript selection alive: a plain click would
            // collapse it before there was anything to read.
            onMouseDown={(e) => e.preventDefault()}
            onClick={takeFromTranscript}
            title={`Put “${transcriptSelection}” into the last field you were in`}
            className="flex items-center gap-1 rounded-md border border-transparent px-2.5 py-1 text-xs text-primary transition-colors hover:text-primary/80"
          >
            <CornerUpLeft className="size-3" aria-hidden />
            from transcript
          </button>
        )}
        {extraTools}
      </div>
    </div>
  );
}

interface ItemRowProps {
  item: MatchItem;
  number: number;
  /** The number the group's FIRST item carries, so a letter held elsewhere
   *  can say which question has it. */
  startNumber: number;
  options: MatchOption[];
  allowReuse: boolean;
  /** Option ids already spoken for. Only meaningful without reuse. */
  taken: Set<string>;
  /** Every item, so a letter another one holds can say which. */
  items: MatchItem[];
  issue?: MatchingIssue;
  register: (key: string) => (el: HTMLInputElement | null) => void;
  onFocusField: (e: React.FocusEvent<HTMLInputElement>) => void;
  onPrompt: (prompt: string) => void;
  onChoose: (option: MatchOption) => void;
  onRemove?: () => void;
}

function ItemRow({
  item,
  number,
  startNumber,
  options,
  allowReuse,
  taken,
  items,
  issue,
  register,
  onFocusField,
  onPrompt,
  onChoose,
  onRemove,
}: ItemRowProps) {
  const marked = item.replayStartMs != null;

  return (
    <div
      className={cn(
        "group/item px-3 py-2.5 transition-colors",
        issue && "bg-destructive/5",
      )}
    >
      <div className="flex items-center gap-2">
        <span className="shrink-0 text-sm tabular-nums text-muted-foreground">
          {number}.
        </span>
        <input
          type="text"
          ref={register(`item#${item.id}`)}
          value={item.prompt}
          onChange={(e) => onPrompt(e.target.value)}
          onFocus={onFocusField}
          placeholder="what is being matched"
          aria-label={`Question ${number}`}
          className="min-w-0 flex-1 border-b border-transparent bg-transparent pb-0.5 text-base text-foreground placeholder:text-muted-foreground/50 hover:border-border focus-visible:border-primary focus-visible:outline-none"
        />
        {/* In the flow rather than floating over the input's right edge,
            where it would sit on top of whatever had been typed. Its space is
            held whether or not it is showing, so nothing shifts on hover. */}
        <span className="-mr-1.5 flex size-6 shrink-0 items-center justify-center">
          {onRemove && (
            <button
              type="button"
              onClick={onRemove}
              aria-label={`Remove question ${number}`}
              title="Remove this question"
              className="flex size-6 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-opacity group-hover/item:opacity-100 hover:text-destructive focus-visible:opacity-100"
            >
              <X className="size-3.5" aria-hidden />
            </button>
          )}
        </span>

        {/* When the answer is given, read out at the card's edge — the same
            column the multiple-choice builder puts it in, and settled by the
            same press. An answered item with no time can only come from work
            made before the two became one press; it shows the shape of a time
            it hasn't got, in warning colour, and pressing the letter twice
            fills it in. */}
        <span
          title={
            item.answer && !marked
              ? "Not linked to the audio — press the letter twice to set it"
              : undefined
          }
          className={cn(
            "w-12 shrink-0 text-right text-xs tabular-nums",
            marked ? "text-primary" : "text-warning",
          )}
        >
          {item.answer && (marked ? formatClock(item.replayStartMs ?? 0) : "--:--")}
        </span>
      </div>

      {/* The box again, as buttons, under the item it answers. Round, because
          an item takes exactly one of them — the same shape the candidate
          will be given. Indented to line up with the item's text rather than
          with its number, so the row reads as "this, answered by that". */}
      <div className="mt-1.5 ml-6 flex flex-wrap items-center gap-1">
        {options.map((option, index) => {
          const letter = matchLetter(index);
          const chosen = item.answer === option.id;
          // Spoken for by another item, where a letter answers only one.
          // Still pressable: pressing it moves it here.
          const elsewhere =
            !allowReuse && !chosen && taken.has(option.id);
          const holder = elsewhere
            ? items.findIndex((other) => other.answer === option.id)
            : -1;
          return (
            <button
              key={option.id}
              type="button"
              onClick={() => onChoose(option)}
              aria-pressed={chosen}
              aria-label={
                chosen
                  ? `Question ${number} is matched to ${letter.toUpperCase()} — press to unmatch`
                  : `Match question ${number} to ${letter.toUpperCase()} and say where it is given`
              }
              title={
                chosen
                  ? "Matched — press to unmatch"
                  : elsewhere
                    ? `${letter.toUpperCase()} is question ${startNumber + holder}'s — pressing it moves it here`
                    : "Match, then click the line where the answer is given"
              }
              className={cn(
                "flex size-6 shrink-0 items-center justify-center rounded-full border text-xs font-semibold transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                chosen
                  ? "border-success/50 bg-success/15 text-success"
                  : elsewhere
                    ? "border-border/60 text-muted-foreground/40 hover:border-foreground/30 hover:text-foreground"
                    : "border-border text-muted-foreground hover:border-foreground/30 hover:text-foreground",
              )}
            >
              {letter.toUpperCase()}
            </button>
          );
        })}
      </div>

      {/* What the row can't already show — see `selfEvident`. An unlit row of
          letters is an item with no answer, so that one says nothing here. */}
      {issue && !issue.selfEvident && (
        <p className="mt-2 flex items-start gap-1.5 text-xs text-destructive">
          <CircleAlert className="mt-0.5 size-3 shrink-0" aria-hidden />
          {issue.detail}
        </p>
      )}
    </div>
  );
}

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, CircleAlert, SquareDashed } from "lucide-react";
import { cn } from "@/lib/utils";
import { FormBuilder } from "@/features/listening/components/FormBuilder";
import { GroupHeader } from "@/features/listening/components/GroupHeader";
import { questionRangeLabel } from "@/features/listening/numbering";
import {
  QUESTION_TYPE_LABEL,
  QUESTION_TYPE_RUBRIC,
} from "@/features/listening/parts";
import {
  docGaps,
  docPublishIssues,
  gapAnswered,
} from "@/features/listening/form-syntax";
import { GroupPicture } from "@/features/listening/components/GroupPicture";
import { OptionsBox } from "@/features/listening/components/OptionsBox";
import {
  matchLetter,
  newMatchOptions,
  pictureLetterBox,
  type MatchOption,
} from "@/features/listening/matching";
import { ANSWER_RUBRICS, deriveRubric } from "@/features/listening/rubric";
import type { DocBlock, LetterSource } from "@/features/listening/form-syntax";
import type {
  AnswerRubric,
  CompletionType,
  GroupImage,
} from "@/features/listening/types";

interface QuestionFormEditorProps {
  /** Which completion task this group is. It decides what the group is
   *  called, what the instruction line offers as a placeholder, and which of
   *  the builder's "add something" buttons lead with — and nothing else, since
   *  the nine tasks are one document underneath. */
  task: CompletionType;
  doc: DocBlock[];
  /** Applied against the latest document — see FormBuilder's note. */
  onChange: (edit: (current: DocBlock[]) => DocBlock[]) => void;
  instructions: string;
  onInstructionsChange: (v: string) => void;
  rubric: AnswerRubric | null;
  onRubricChange: (v: AnswerRubric | null) => void;
  /** The box this group's gaps are answered from, where the paper prints one.
   *  Empty is the ordinary task, answered in the words the candidate heard. */
  options: MatchOption[];
  onOptionsChange: (edit: (current: MatchOption[]) => MatchOption[]) => void;
  /** Dropping an option has to clear the gaps that pointed at it, so it is
   *  one edit over both halves rather than two that could land apart. */
  onRemoveOption: (optionId: string) => void;
  allowReuse: boolean;
  onAllowReuseChange: (v: boolean) => void;
  /** Everything the picture half of a labelling task needs — and absent for
   *  the seven tasks that don't have one, which is what this block being one
   *  optional prop rather than nine loose ones says. */
  picture?: {
    image: GroupImage | null;
    /** How many letters are drawn on it. Zero is the other real form of the
     *  task: numbered blanks, answered in the words the candidate heard. */
    letters: number;
    adapt: boolean;
    uploading: boolean;
    error?: string | null;
    onUpload: (file: File) => void;
    onRemove: () => void;
    onLettersChange: (n: number) => void;
    onAdaptChange: (v: boolean) => void;
  };
  /** The number the first gap of this group carries on the page. */
  startNumber: number;
  /** Set while a publish attempt is blocked on this group, so the offending
   *  gaps are marked even if the author hadn't looked yet. */
  showIssues?: boolean;
  markChecks?: Map<string, { found: boolean; heardAtMs: number | null }>;
  /** Where in the recording the author is pointing, for marking a gap. */
  onMarkAudio?: (
    answers: string[],
    apply: (range: { startMs: number; endMs: number }) => void,
  ) => void;
  disabled?: boolean;
  extraTools?: React.ReactNode;
  onMoveUp?: () => void;
  onMoveDown?: () => void;
  onDelete?: () => void;
  canMoveUp?: boolean;
  canMoveDown?: boolean;
}

/** Whether this task is printed with a list of words to choose from.
 *
 *  It sits where "Answer length" does, and replaces it, because the two are
 *  the same question asked of the two forms of the task: how long may the
 *  answer be, against there being no answer to write at all — only a letter to
 *  pick. */
function BoxToggle({
  value,
  onChange,
}: {
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={value}
      onClick={() => onChange(!value)}
      title={
        value
          ? "The paper says: choose your answers from the box"
          : "Answers are written in, not chosen from a list"
      }
      className={cn(
        "flex shrink-0 items-center gap-1.5 rounded-md border px-2 py-1 text-xs transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
        value
          ? "border-primary/40 bg-primary/10 text-primary"
          : "border-border text-muted-foreground hover:bg-foreground/4 hover:text-foreground",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "flex size-3.5 shrink-0 items-center justify-center rounded-[3px] border transition-colors",
          value ? "border-primary bg-primary/20" : "border-border",
        )}
      >
        {value && <Check className="size-2.5" aria-hidden />}
      </span>
      answers from a box
    </button>
  );
}

/** Whether one option may answer more than one gap — the paper's "NB you may
 *  use any letter more than once". The same switch matching has, in the box
 *  they share. */
function ReuseToggle({
  value,
  onChange,
}: {
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={value}
      onClick={() => onChange(!value)}
      title={
        value
          ? "The paper says: NB You may use any letter more than once"
          : "Each option answers one gap"
      }
      className={cn(
        "flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-xs transition-colors",
        value
          ? "bg-primary/12 text-primary"
          : "text-muted-foreground/70 hover:bg-foreground/6 hover:text-foreground",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "flex size-3.5 shrink-0 items-center justify-center rounded-[3px] border transition-colors",
          value ? "border-primary bg-primary/20" : "border-border",
        )}
      >
        {value && <Check className="size-2.5" aria-hidden />}
      </span>
      reuse letters
    </button>
  );
}

/** How far up the alphabet a picture's letters run — or that there are none,
 *  and the candidate writes what they heard.
 *
 *  It stands where the box switch does on the other tasks, and for the same
 *  reason: it is the same question. What differs is that a picture's letters
 *  can't be typed here — they were drawn by whoever drew the map — so all
 *  there is to say about them is how many.
 *
 *  Twelve is where it stops. A real map is lettered A-H at most, and a list
 *  running to Z would be a list nobody scrolls to the bottom of. */
const MAX_PICTURE_LETTERS = 12;

function LettersControl({
  value,
  onChange,
}: {
  value: number;
  onChange: (n: number) => void;
}) {
  return (
    <span className="relative inline-flex items-center">
      <select
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label="Letters on the picture"
        title="How many letters are drawn on the picture"
        className="appearance-none rounded-md border border-border bg-transparent py-1 pr-7 pl-2.5 text-xs text-foreground transition-colors hover:border-foreground/30 focus-visible:border-ring focus-visible:outline-none"
      >
        <option value={0}>answers written in</option>
        {Array.from({ length: MAX_PICTURE_LETTERS - 1 }, (_, i) => i + 2).map(
          (count) => (
            <option key={count} value={count}>
              letters A–{matchLetter(count - 1).toUpperCase()}
            </option>
          ),
        )}
      </select>
      <ChevronDown
        aria-hidden
        className="pointer-events-none absolute right-2 size-3.5 text-muted-foreground"
      />
    </span>
  );
}

/** The syntax itself, drawn rather than described. The sentence around it
 *  is what an author reads once; the brackets are what they have to
 *  remember, so they get the weight — the same tint a gap wears in the form
 *  below, which is what they turn into. */
function Brackets({ children }: { children?: React.ReactNode }) {
  return (
    <span className="rounded bg-primary/12 px-1 font-semibold text-primary">
      [{children}]
    </span>
  );
}

export function QuestionFormEditor({
  task,
  doc,
  onChange,
  instructions,
  onInstructionsChange,
  rubric,
  onRubricChange,
  options,
  onOptionsChange,
  onRemoveOption,
  allowReuse,
  onAllowReuseChange,
  picture,
  startNumber,
  showIssues,
  markChecks,
  onMarkAudio,
  disabled,
  extraTools,
  onMoveUp,
  onMoveDown,
  onDelete,
  canMoveUp,
  canMoveDown,
}: QuestionFormEditorProps) {
  const offset = startNumber - 1;
  const boxed = options.length > 0;
  /** Whether a gap here is answered by picking a letter rather than by
   *  writing words, and if so from where — a box of words under the task, or
   *  the letters drawn on its picture. One question, because everything that
   *  asks it treats the two the same: what a gap needs before it counts as
   *  answered, and whether "how long may the answer be" is a question worth
   *  asking at all. Which of the two it is only matters when telling the
   *  author where to look. */
  const lettered: LetterSource = boxed
    ? "box"
    : (picture?.letters ?? 0) > 0
      ? "picture"
      : false;
  const issues = useMemo(
    () => docPublishIssues(doc, offset, lettered),
    [doc, offset, lettered],
  );
  const gaps = useMemo(() => docGaps(doc), [doc]);
  /** The box as the builder needs it: each option with the letter it currently
   *  wears. Worked out here, from position, so the letters exist in exactly
   *  one place and nothing downstream stores one.
   *
   *  A picture's letters arrive the same way and are the same thing — a row of
   *  letters to press on a gap — except that they have no words, since what
   *  letter C means is a place on the drawing. */
  const box = useMemo(
    () =>
      boxed
        ? options.map((option, index) => ({
            id: option.id,
            letter: matchLetter(index),
            text: option.text,
          }))
        : pictureLetterBox(picture?.letters ?? 0),
    [options, boxed, picture?.letters],
  );

  // "No gaps yet" is true of every form the moment it's begun, so it waits
  // for a publish attempt. A gap left without an answer is a real mistake and
  // is called out as soon as it exists.
  const showsIssues =
    issues.length > 0 &&
    (showIssues || gaps.filter((g) => !gapAnswered(g, !!lettered)).length > 0);

  // What is selected inside a value right now. Held here rather than in the
  // builder so the offer to turn it into an answer can sit with the rubric,
  // where the other answer-level settings are.
  const [selectedText, setSelectedText] = useState("");
  const formRef = useRef<HTMLDivElement>(null);

  // Watched on the document rather than reported by the field the selection
  // is in. A field only hears its own mouseup and keyup, so clicking away —
  // onto the transcript, onto another question, anywhere at all — collapsed
  // the selection without telling anyone, and the offer to mark it stayed on
  // screen pointing at nothing. `selectionchange` fires wherever it happens.
  useEffect(() => {
    const onSelectionChange = () => {
      const selection = window.getSelection();
      if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
        setSelectedText("");
        return;
      }
      const inside = formRef.current?.contains(
        selection.getRangeAt(0).commonAncestorContainer,
      );
      setSelectedText(inside ? selection.toString().trim() : "");
    };
    document.addEventListener("selectionchange", onSelectionChange);
    return () =>
      document.removeEventListener("selectionchange", onSelectionChange);
  }, []);

  /** Wraps the selection in brackets. Typed through execCommand rather than
   *  assigned: the value region reads itself back on input, so an edit it
   *  never saw would be invisible to it — and this way the browser's own undo
   *  keeps the change. */
  const markAsAnswer = () => {
    if (!selectedText) return;
    document.execCommand("insertText", false, `[${selectedText}]`);
    setSelectedText("");
  };

  // What the answers imply, offered as the default. Left on "auto" it is what
  // gets stored — the take page can't work it out for itself, since it never
  // sees the answers.
  const derived = useMemo(() => deriveRubric(doc), [doc]);
  const derivedLabel = ANSWER_RUBRICS.find((r) => r.value === derived)?.label;

  const flaggedGaps = useMemo(
    () =>
      gaps
        .filter((g) => !gapAnswered(g, !!lettered))
        .map((g) => g.number + offset),
    [gaps, offset, lettered],
  );

  // `inert` rather than only dimming and blocking the pointer: without it
  // everything in here stays tabbable, so a keyboard can walk into a section
  // that looks — and, for a mouse, is — switched off.
  return (
    <div inert={disabled} className={cn(disabled && "opacity-40")}>
      <GroupHeader
        range={questionRangeLabel(startNumber - 1, gaps.length)}
        count={gaps.length}
        typeLabel={QUESTION_TYPE_LABEL[task]}
        onMoveUp={onMoveUp}
        onMoveDown={onMoveDown}
        onDelete={onDelete}
        canMoveUp={canMoveUp}
        canMoveDown={canMoveDown}
      />

      {/* The rubric, in the order it appears on the paper: what to do, then
          how long an answer may be. */}
      <div className="mb-3 space-y-1.5">
        <input
          type="text"
          value={instructions}
          onChange={(e) => onInstructionsChange(e.target.value)}
          placeholder={QUESTION_TYPE_RUBRIC[task]}
          aria-label="Instructions"
          className="w-full rounded-md border border-border bg-transparent px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:outline-none"
        />
        <label className="flex items-center gap-2 pl-1 text-xs text-muted-foreground">
          {/* First, ahead of the answer-length label, because it is the
              question that decides whether that label applies at all: with
              letters there is no answer to write.

              A labelling task's letters are on its picture, so that is the
              only box it is offered. The word-list form of it exists on
              paper, rarely, and the server would store it — but two controls
              that must never both be on is a trap, and this is the one an
              author reaches for. */}
          {picture && (
            <LettersControl
              value={picture.letters}
              onChange={picture.onLettersChange}
            />
          )}
          {/* How long an answer may be is not a question you can ask about a
              letter, so once the answers are letters this makes way for
              whichever control turned them into letters. */}
          {!lettered && <span className="whitespace-nowrap">Answer length</span>}
          {/* A native select for the behaviour — keyboard, mobile, no menu to
              reimplement — with its own chrome stripped and the app's put
              back, so it stops looking like something the browser drew. The
              open list itself is the OS's and can't be styled. */}
          {!picture && (
            <BoxToggle
              value={boxed}
              onChange={(on) =>
                onOptionsChange(() => (on ? newMatchOptions() : []))
              }
            />
          )}

          <span
            className={cn(
              "relative inline-flex items-center",
              lettered && "hidden",
            )}
          >
            <select
              value={rubric ?? ""}
              onChange={(e) =>
                onRubricChange(
                  e.target.value === ""
                    ? null
                    : (e.target.value as AnswerRubric),
                )
              }
              aria-label="Answer length"
              className="appearance-none rounded-md border border-border bg-transparent py-1 pr-7 pl-2.5 text-xs text-foreground transition-colors hover:border-foreground/30 focus-visible:border-ring focus-visible:outline-none"
            >
              <option value="">
              {derivedLabel ? `auto — ${derivedLabel}` : "auto"}
            </option>
              {ANSWER_RUBRICS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <ChevronDown
              aria-hidden
              className="pointer-events-none absolute right-2 size-3.5 text-muted-foreground"
            />
          </span>

          {/* One place, two things, never both. With a word selected it is
              the button that acts on it; without one it is the sentence that
              explains how to do the same thing by typing. They are the two
              halves of the same instruction, so they take turns rather than
              sit side by side — and the row never grows a second line.

              The selection is named in the tooltip rather than in the label:
              spelled out inline, a long phrase pushed this row onto two
              lines. */}
          {selectedText ? (
            <button
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={markAsAnswer}
              title={`Mark “${selectedText}” as the answer`}
              className="flex shrink-0 items-center gap-1.5 rounded-md bg-primary/15 px-2 py-1 whitespace-nowrap text-primary transition-colors hover:bg-primary/25"
            >
              <SquareDashed className="size-3.5 shrink-0" aria-hidden />
              Mark as answer
            </button>
          ) : picture && picture.letters > 0 ? (
            // Not the bracket sentence. On this sheet the blank arrives with
            // the line, so an author never has to make one — telling them how
            // to would be teaching a step the page has already taken.
            <span className="flex min-w-0 items-center gap-1.5 truncate text-foreground">
              Name each place, then press its letter on the blank
            </span>
          ) : lettered ? (
            <span className="flex min-w-0 items-center gap-1.5 truncate text-foreground">
              Put
              <Brackets />
              where a gap goes, then press a letter on it
            </span>
          ) : (
            <span className="flex min-w-0 items-center gap-1.5 truncate text-foreground">
              Write the answer in
              <Brackets />
              like
              {/* A number and its spelling rather than two colours: variants
                  are mostly here because the recording says "ten" and the
                  answer sheet takes 10, which is the case an author meets on
                  their first form. */}
              <Brackets>10, ten</Brackets>
            </span>
          )}
        </label>
      </div>

      {/* Above the labels, where the paper prints it — and because the labels
          are written while looking at it. */}
      {picture && (
        <GroupPicture
          image={picture.image}
          onUpload={picture.onUpload}
          onRemove={picture.onRemove}
          uploading={picture.uploading}
          error={picture.error}
          adapt={picture.adapt}
          onAdaptChange={picture.onAdaptChange}
          noun={task === "map_labelling" ? "map" : "diagram"}
        />
      )}

      {/* No separate preview: the builder is already laid out as the form, so
          a second copy below it would only be somewhere for the two to
          disagree. */}
      <div ref={formRef}>
        <FormBuilder
          doc={doc}
          onChange={onChange}
          numberOffset={offset}
          flaggedGaps={flaggedGaps}
          markChecks={markChecks}
          onMarkAudio={onMarkAudio}
          labelFirst={task === "form_completion"}
          // Only where the answers are letters. A blank the author fills by
          // pressing a letter is one the page can make for them; a blank they
          // fill by writing words is not — the chip can't be typed into, so a
          // ready-made one would have to be deleted before the answer could go
          // in. That form of the task is an ordinary completion sheet, and is
          // written like one.
          blankPerRow={(picture?.letters ?? 0) > 0}
          box={box.length > 0 ? box : undefined}
          extraTools={extraTools}
        />
      </div>

      {/* Under the sheet, where the paper prints it: "complete the summary
          below using the list of words below". Above it, the box was the first
          thing on a block whose point is the text — and the author reads the
          text first, then reaches for the letters. */}
      {boxed && (
        <div className="mt-3">
          <OptionsBox
            options={options}
            onChange={onOptionsChange}
            onRemove={onRemoveOption}
            label="Options to choose from"
            trailing={
              <ReuseToggle value={allowReuse} onChange={onAllowReuseChange} />
            }
          />
        </div>
      )}

      {showsIssues && (
        <ul className="mt-2 space-y-1">
          {issues.map((issue) => (
            <li
              key={issue}
              className="flex items-start gap-1.5 text-xs text-destructive"
            >
              <CircleAlert className="mt-0.5 size-3 shrink-0" aria-hidden />
              {issue}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

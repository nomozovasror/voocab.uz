import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, CircleAlert, SquareDashed } from "lucide-react";
import { cn } from "@/lib/utils";
import { FormBuilder } from "@/features/listening/components/FormBuilder";
import { GroupHeader } from "@/features/listening/components/GroupHeader";
import { questionRangeLabel } from "@/features/paper/numbering";
import { QUESTION_TYPE_LABEL, QUESTION_TYPE_RUBRIC } from "@/features/paper/question-types";
import {
  docGaps,
  docPublishIssues,
  gapAnswered,
} from "@/features/paper/form-syntax";
import { GroupPicture } from "@/features/listening/components/GroupPicture";
import { OptionsBox } from "@/features/listening/components/OptionsBox";
import {
  matchLetter,
  newMatchOptions,
  pictureLetterBox,
  type MatchOption,
} from "@/features/paper/matching";
import { ANSWER_RUBRICS, deriveRubric } from "@/features/paper/rubric";
import type { DocBlock, LetterSource } from "@/features/paper/form-syntax";
import type {
  AnswerRubric,
  CompletionType,
  GroupImage,
} from "@/features/paper/types";

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
    /** How many letters are drawn on it, where that is how it is answered. */
    letters: number;
    adapt: boolean;
    uploading: boolean;
    error?: string | null;
    onUpload: (file: File) => void;
    onRemove: () => void;
    /** Which of the three ways this picture is answered — see
     *  :func:`AnswerSourceControl`. A number is that many letters drawn on
     *  it. */
    onAnswerSourceChange: (source: "words" | "box" | number) => void;
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

/** What this task's gaps are answered from. Every completion task has this
 *  question and only the picture ones have three answers to it:
 *
 *  * **written in** — the candidate writes what they heard between the
 *    brackets. Every ordinary completion task, and the commonest diagram:
 *    "Label the diagram below. Write NO MORE THAN TWO WORDS for each answer."
 *  * **from a box** — a lettered list of words is printed with the task.
 *    "Choose FIVE answers from the box and write the correct letter, A–H."
 *  * **letters A–x** — only where there is a picture, because that is where
 *    the letters are drawn. "Write the correct letter, A–J, next to questions
 *    15–20." The commonest map.
 *
 *  One control rather than a switch beside a select: they are one question,
 *  and two controls that must never both be on is a trap to build rather than
 *  a choice to offer. Its options are short values, not phrases, so it reads
 *  as "Answers [written in]" — the same shape as the answer length beside it,
 *  which is what stops the row looking assembled out of spare parts.
 *
 *  Twelve letters is where it stops. A real picture is lettered A–J at most,
 *  and a list running to Z would be a list nobody scrolls to the bottom of. */
const MAX_PICTURE_LETTERS = 12;

function AnswerSourceControl({
  letters,
  boxed,
  withPicture,
  onChange,
}: {
  letters: number;
  boxed: boolean;
  /** Whether to offer the letters. Without a picture there is nowhere for
   *  them to be drawn. */
  withPicture: boolean;
  onChange: (source: "words" | "box" | number) => void;
}) {
  const value = boxed ? "box" : letters > 0 ? String(letters) : "words";
  return (
    <span className="relative inline-flex items-center">
      <select
        value={value}
        onChange={(e) => {
          const next = e.target.value;
          onChange(next === "words" || next === "box" ? next : Number(next));
        }}
        aria-label="What the answers are"
        title="What the candidate answers with"
        className="appearance-none rounded-md border border-border bg-transparent py-1 pr-7 pl-2.5 text-xs text-foreground transition-colors hover:border-foreground/30 focus-visible:border-ring focus-visible:outline-none"
      >
        <option value="words">written in</option>
        <option value="box">from a box</option>
        {withPicture &&
          Array.from({ length: MAX_PICTURE_LETTERS - 1 }, (_, i) => i + 2).map(
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
        {/* Two settings and a sentence, and they were all three in one row.
            They are not three of a kind: the settings are what the paper says,
            the sentence is how to type it — so the settings share a row and
            the sentence gets its own, deliberately rather than by wrapping
            when it happens not to fit.

            Both settings read "label [value]" now. One of them used to be a
            select whose options were whole phrases and the other a labelled
            value, which is what made the row look assembled out of spare
            parts. */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 pl-1 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span className="whitespace-nowrap">Answers</span>
            <AnswerSourceControl
              letters={picture?.letters ?? 0}
              boxed={boxed}
              withPicture={picture !== undefined}
              onChange={(source) => {
                // A picture task's change is the group's to make — the letters
                // and the box are two of three states, and moving between them
                // has to reach the answers already chosen. Everywhere else the
                // box is the only thing that moves.
                if (picture) picture.onAnswerSourceChange(source);
                else onOptionsChange(() => (source === "box" ? newMatchOptions() : []));
              }}
            />
          </span>

          {/* How long an answer may be is not a question you can ask about a
              letter, so once the answers are letters this makes way. */}
          {!lettered && (
            <span className="flex items-center gap-1.5">
              <span className="whitespace-nowrap">Answer length</span>
              {/* A native select for the behaviour — keyboard, mobile, no menu
                  to reimplement — with its own chrome stripped and the app's
                  put back, so it stops looking like something the browser
                  drew. The open list itself is the OS's and can't be styled. */}
              <span className="relative inline-flex items-center">
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
                  className="max-w-52 appearance-none truncate rounded-md border border-border bg-transparent py-1 pr-7 pl-2.5 text-xs text-foreground transition-colors hover:border-foreground/30 focus-visible:border-ring focus-visible:outline-none"
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
            </span>
          )}
        </div>

        {/* One place, two things, never both. With a word selected it is the
            button that acts on it; without one it is the sentence that
            explains how to do the same thing by typing. They are the two
            halves of the same instruction, so they take turns rather than sit
            side by side.

            The selection is named in the tooltip rather than in the label: a
            long phrase spelled out inline made this jump about as it was
            typed. */}
        <div className="flex min-h-6 items-center pl-1 text-xs text-muted-foreground">
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
            <span className="flex items-center gap-1.5 text-foreground">
              Name each place, then press its letter on the blank
            </span>
          ) : lettered ? (
            <span className="flex items-center gap-1.5 text-foreground">
              Put
              <Brackets />
              where a gap goes, then press a letter on it
            </span>
          ) : (
            <span className="flex items-center gap-1.5 text-foreground">
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
        </div>
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
          marks={picture.letters > 0 ? "letters" : "numbers"}
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
          // A letter on a picture marks one place on it, so it answers one
          // question and there is no switch to say otherwise. A box of words
          // has one, and it is the author's.
          lettersUsedOnce={picture ? true : !allowReuse}
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

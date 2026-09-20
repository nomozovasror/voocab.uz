import { ChevronDown, Volume2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { FlagQuestion } from "@/features/listening/components/FlagQuestion";
import { Q_ANCHOR } from "@/features/paper/take-focus";
import { matchLabel, paragraphNamed } from "@/features/paper/matching";
import type {
  LabelStyle,
  QuestionResult,
  TakeQuestion,
  TakeQuestionGroup,
} from "@/features/paper/types";

/**
 * A matching group, as the candidate sits it.
 *
 * The box comes down on the GROUP — it is printed once above the whole set —
 * and each question is one item answered from it. The answer travels as the
 * chosen letter, which is the same string the server grades and stores, and
 * the same one a multiple-choice answer of one letter travels as.
 *
 * Nothing here knows which letter is right until the attempt comes back
 * graded: the take payload carries the box and the items, and there is no
 * field in it that could carry more.
 *
 * Unlike multiple choice, nothing is capped. A "choose two" that lets you tick
 * four is marked wrong for a reason the candidate never sees, so the extra
 * ticks are refused there. Here every item is graded on its own letter, so a
 * candidate who puts A against two items is simply right about one of them and
 * wrong about the other — which is what the real paper does, and stopping them
 * would be telling them one of the two is wrong.
 */

interface MatchingGroupProps {
  group: TakeQuestionGroup;
  /** question id -> the chosen letter. */
  answers: Record<string, string>;
  onChange: (questionId: string, value: string) => void;
  /** The number this group's first item carries on the page. */
  startNumber: number;
  results?: Record<string, QuestionResult>;
  /** Playing back the moment the answer is given, once the attempt has been
   *  marked. Only where the author marked one. */
  onReplay?: (startMs: number | null, endMs: number | null) => void;
  disabled?: boolean;
  /** Only while the paper is being sat — see QuestionPaper. */
  flagged?: Set<string>;
  onFlag?: (questionId: string) => void;
  /** The passage paragraph the reader is looking at, so an item that names
   *  that paragraph can say so. Reading only — see `paragraphNamed`. */
  litParagraph?: string | null;
}

export function MatchingGroup({
  group,
  answers,
  onChange,
  startNumber,
  results,
  onReplay,
  disabled,
  flagged,
  onFlag,
  litParagraph,
}: MatchingGroupProps) {
  const options = group.config.options ?? [];
  // Matching headings is printed in roman numerals, because ITS items are
  // the lettered paragraphs: two alphabets on one page so that an answer of
  // "C" can only ever mean one of them. Everything else is lettered.
  const style: LabelStyle = group.config.label_style ?? "letters";
  // ...and a roman numeral stays lowercase. "VII" is not how the paper prints
  // it, and upper-casing it would make iii and III two spellings of one
  // answer for a reader comparing the box against their own sheet.
  const cased = (label: string) =>
    style === "roman" ? label : label.toUpperCase();

  // Whether the box says anything beyond its own labels.
  //
  // Matching information's options ARE the paragraph letters — "A", "B",
  // "C" — and a row of small circles is the right control for them: the
  // letter on the button is the whole of the option, so there is nothing to
  // hold in your head while you aim at it.
  //
  // Matching headings is the opposite. Each of its ten options is a
  // sentence, and the roman numeral is only a handle for one. Printed as ten
  // small circles it became seventy identical targets down the page, each
  // standing for something the candidate had to have memorised from a list
  // further up. So a box that SPEAKS gets a bank and a dropdown, and a box
  // that is only its own alphabet keeps the circles.
  const wordy = options.some(
    (text, index) =>
      text.trim().toLowerCase() !== matchLabel(index, style).toLowerCase(),
  );
  // Which options have been spent, for dimming them in the bank. Not where
  // the paper says a letter may be used again — there, "used" means nothing.
  const used = new Set(
    group.config.allow_reuse
      ? []
      : group.questions
          .map((q) => (answers[q.id] ?? "").trim().toLowerCase())
          .filter(Boolean),
  );

  return (
    <div className="space-y-3">
      <p className="text-sm text-foreground">{group.instructions}</p>
      {/* The paper's own NB line, and only when it is true — printed on a set
          where each letter is used once, it would be a lie the candidate
          plans around. */}
      {group.config.allow_reuse && (
        <p className="text-xs text-muted-foreground">
          NB You may use any letter more than once.
        </p>
      )}

      <ul className="space-y-1 rounded-lg border border-border bg-background p-3">
        {options.map((text, index) => {
          const label = matchLabel(index, style);
          // Spent options fade rather than disappear. What is left is the
          // thing a candidate is actually reasoning about by the fifth
          // heading, and a list that shortened as they worked would move
          // every remaining line under their eye each time they answered.
          const spent = wordy && used.has(label);
          return (
            <li
              key={index}
              className={cn(
                "flex items-baseline gap-2 text-sm transition-opacity duration-fast",
                spent && "opacity-40",
              )}
            >
              <span
                aria-hidden
                className="flex size-5 shrink-0 items-center justify-center self-center rounded-full border border-border text-xs font-semibold text-muted-foreground"
              >
                {cased(label)}
              </span>
              <span className="text-foreground">{text}</span>
            </li>
          );
        })}
      </ul>

      <div className="space-y-1.5">
        {group.questions
          .slice()
          .sort((a, b) => a.number - b.number)
          .map((question, index) => (
            <MatchingItem
              key={question.id}
              question={question}
              // One item is one number: the arithmetic a "choose two" forces
              // on multiple choice has nothing to do here.
              number={startNumber + index}
              options={options}
              style={style}
              wordy={wordy}
              litParagraph={litParagraph}
              chosen={(answers[question.id] ?? "").trim().toLowerCase()}
              onChange={(letter) => onChange(question.id, letter)}
              result={results?.[question.id]}
              onReplay={onReplay}
              disabled={disabled}
              flagged={flagged?.has(question.id) ?? false}
              onFlag={onFlag ? () => onFlag(question.id) : undefined}
            />
          ))}
      </div>
    </div>
  );
}

function MatchingItem({
  question,
  number,
  options,
  style,
  wordy,
  litParagraph,
  chosen,
  onChange,
  result,
  onReplay,
  disabled,
  flagged,
  onFlag,
}: {
  question: TakeQuestion;
  number: number;
  options: string[];
  style: LabelStyle;
  /** Whether the box says anything beyond its own labels — see the group. */
  wordy: boolean;
  litParagraph?: string | null;
  chosen: string;
  onChange: (letter: string) => void;
  result?: QuestionResult;
  onReplay?: (startMs: number | null, endMs: number | null) => void;
  disabled?: boolean;
  flagged?: boolean;
  onFlag?: () => void;
}) {
  const graded = result !== undefined;
  // The answer, once it is allowed to exist here — never before grading.
  const key = graded ? result.correct_answers[0]?.trim().toLowerCase() : undefined;
  const names = paragraphNamed(question.prompt);

  return (
    <fieldset
      // What the navigator scrolls to, and what the page reads to know which
      // question is being worked on.
      {...{ [Q_ANCHOR]: question.id }}
      // Which paragraph this item is about, where it is about one. Read
      // both ways: the take screen lights the prose when the pointer is on
      // the row, and lights the row when the pointer is on the prose.
      {...(names ? { "data-paragraph": names } : {})}
      className={cn(
        // Padding rather than a negative margin bleeding into the pane's
        // own: `-mx-2` put eight pixels past the content box and gave the
        // question pane a horizontal scrollbar.
        "flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md px-2 py-0.5 transition-colors duration-fast",
        names && litParagraph === names && "bg-surface-hover",
      )}
      aria-invalid={graded && !result.is_correct}
    >
      <legend className="sr-only">Question {number}</legend>
      <span
        aria-hidden
        className="w-6 shrink-0 text-sm font-semibold tabular-nums text-muted-foreground"
      >
        {number}
      </span>
      <span className="min-w-0 flex-1 text-base text-foreground">
        {question.prompt}
      </span>
      {onFlag && (
        <FlagQuestion
          number={String(number)}
          flagged={!!flagged}
          onToggle={onFlag}
        />
      )}

      {wordy ? (
        <Picker
          number={number}
          options={options}
          style={style}
          chosen={chosen}
          onChange={onChange}
          questionId={question.id}
          graded={graded}
          right={graded ? result.is_correct : undefined}
          answer={key}
          disabled={disabled}
        />
      ) : (
      <div className="flex shrink-0 flex-wrap items-center gap-1">
        {options.map((_text, index) => {
          const letter = matchLabel(index, style);
          const shown = style === "roman" ? letter : letter.toUpperCase();
          const picked = chosen === letter;
          const isKey = graded && key === letter;
          return (
            <label
              key={letter}
              className={cn(
                "flex h-7 min-w-7 cursor-pointer items-center justify-center rounded-full border px-1.5 text-xs font-semibold transition-colors",
                // The real input is sr-only, so the ring goes on the visible
                // letter. `has-[:focus-visible]` because the input is a child
                // of this label, not a preceding sibling — there is no peer.
                // Drawn outside the border box, so it survives all four
                // colour states below.
                "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring",
                // Before grading, only what the candidate chose is coloured.
                // After it, the answer leads: the right letter is marked
                // whether or not they found it, and a wrong pick is marked as
                // theirs.
                isKey
                  ? "border-success bg-success/10 text-success"
                  : graded && picked
                    ? "border-destructive bg-destructive/10 text-destructive"
                    : picked
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border text-muted-foreground hover:border-border-strong",
                disabled && "cursor-default",
              )}
            >
              <input
                type="radio"
                name={question.id}
                data-question={question.id}
                checked={picked}
                onChange={() => onChange(letter)}
                disabled={disabled}
                className="sr-only"
              />
              <span aria-hidden>{shown}</span>
              <span className="sr-only">
                Question {number}, option {shown}
              </span>
            </label>
          );
        })}
      </div>
      )}

      {/* Only where the author marked it — a review that offered replay on
          every item and played the wrong moment on half of them would be
          worse than not offering it. */}
      {graded && onReplay && result.replay_start_ms != null && (
        <button
          type="button"
          onClick={() => onReplay(result.replay_start_ms, result.replay_end_ms)}
          title="Hear where this answer is given"
          aria-label={`Hear where the answer to question ${number} is given`}
          className="inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-foreground/8 hover:text-primary"
        >
          <Volume2 className="size-3.5" aria-hidden />
          hear it
        </button>
      )}
    </fieldset>
  );
}

/**
 * One item's answer, where the box is ten sentences rather than ten letters.
 *
 * A real `<select>`, and it is the control underneath rather than beside:
 * it is stretched invisibly over the face below it, so the thing the reader
 * sees is the mock's compact `iii ▾` while the thing the browser operates is
 * a native picker. That matters more than it sounds. A listbox built out of
 * divs has to reimplement type-ahead, Home and End, page up, the escape key
 * and every screen reader's idea of what a choice is — and IELTS candidates
 * are exactly the population most likely to be working by keyboard on an
 * unfamiliar machine.
 *
 * The LIST reads "iii — Evidence from brain scans"; the closed control shows
 * only the numeral, because the sentence is already printed once in the bank
 * above and a second copy inside every row is the same page twice.
 */
function Picker({
  number,
  options,
  style,
  chosen,
  onChange,
  questionId,
  graded,
  right,
  answer,
  disabled,
}: {
  number: number;
  options: string[];
  style: LabelStyle;
  chosen: string;
  onChange: (letter: string) => void;
  questionId: string;
  graded: boolean;
  right?: boolean;
  answer?: string;
  disabled?: boolean;
}) {
  const cased = (label: string) =>
    style === "roman" ? label : label.toUpperCase();
  return (
    <span className="relative inline-flex shrink-0 items-center">
      <select
        data-question={questionId}
        value={chosen}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        aria-label={`Answer ${number}`}
        aria-invalid={graded && !right}
        className="absolute inset-0 cursor-pointer opacity-0 disabled:cursor-default"
      >
        <option value="">Choose</option>
        {options.map((text, index) => {
          const label = matchLabel(index, style);
          return (
            <option key={label} value={label}>
              {cased(label)} — {text}
            </option>
          );
        })}
      </select>
      <span
        aria-hidden
        className={cn(
          "flex h-8 min-w-[6.5rem] items-center justify-between gap-2 rounded-lg border bg-surface-sunken px-2.5 text-xs font-semibold transition-colors",
          // The same four states the circles draw, so a candidate who works
          // through a matching-information group and then a headings group
          // is reading one colour language.
          graded && right
            ? "border-correct/40 text-correct"
            : graded
              ? "border-incorrect/40 text-incorrect"
              : chosen
                ? "border-primary/40 text-primary"
                : "border-border text-muted-foreground",
        )}
      >
        <span>{chosen ? cased(chosen) : "Choose"}</span>
        <ChevronDown className="size-3 opacity-60" />
      </span>
      {/* After grading, what it should have been — beside the pick rather
          than replacing it, so the candidate can see both at once. */}
      {graded && !right && answer && (
        <span className="ml-2 shrink-0 text-xs font-semibold text-correct">
          {cased(answer)}
        </span>
      )}
    </span>
  );
}

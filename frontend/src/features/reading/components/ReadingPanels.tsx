import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, Plus, TriangleAlert, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getErrorMessage } from "@/lib/api";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { CefrTag } from "@/features/vocabulary/components/CefrTag";
import { helpFor } from "@/features/reading/help";
import { LOOKUP_BUDGET } from "@/features/reading/lookups";
import type { QuestionGroupType } from "@/features/paper/types";
import type { Selected } from "@/features/reading/selection";
import { vocabularyApi } from "@/features/vocabulary/api";

/**
 * The three small panels the tools open, and what each one is careful about.
 *
 * All of them hang under the header rather than over the passage. A panel
 * covering the prose is a panel that hides the thing it is about — the word
 * being looked up, the sentence being annotated, the question the help is
 * explaining — and a reader then has to close it to use what it told them.
 */

function Panel({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  useEffect(() => {
    const escape = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [onClose]);

  return (
    <aside className="absolute top-19 right-4 z-40 w-80 rounded-xl border border-border bg-card p-4 shadow-lg sm:right-6">
      <header className="mb-2 flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold text-foreground">{title}</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="rounded-md p-0.5 text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          <X className="size-3.5" aria-hidden />
        </button>
      </header>
      {children}
    </aside>
  );
}

/**
 * What this kind of question asks for.
 *
 * Follows the group the reader is IN, because advice about matching
 * headings while somebody is filling a summary is worse than none: they
 * asked the page a question and it answered a different one. Three lines,
 * and the reasons for each are in `features/reading/help.ts`.
 */
export function HelpPanel({
  type,
  onClose,
}: {
  type: QuestionGroupType | null;
  onClose: () => void;
}) {
  const help = helpFor(type);
  if (!help) return null;
  return (
    <Panel title="What to do here" onClose={onClose}>
      <dl className="space-y-2.5 text-xs leading-relaxed">
        <div>
          <dt className="sr-only">The task</dt>
          <dd className="text-foreground">{help.do}</dd>
        </div>
        <div>
          <dt className="mb-0.5 text-[0.7rem] tracking-caps text-muted-foreground uppercase">
            Watch for
          </dt>
          <dd className="text-muted-foreground">{help.rule}</dd>
        </div>
        <div>
          <dt className="mb-0.5 text-[0.7rem] tracking-caps text-muted-foreground uppercase">
            Technique
          </dt>
          <dd className="text-muted-foreground">{help.tip}</dd>
        </div>
      </dl>
    </Panel>
  );
}

/**
 * A note on a stretch of the passage.
 *
 * Opens with whatever is already there, so pressing Note on a stretch that
 * has one is editing it rather than starting again — and an empty box
 * REMOVES the note, which is the only gesture anybody looks for.
 */
export function NotePanel({
  at,
  existing,
  onSave,
  onClose,
}: {
  at: Selected;
  existing: string;
  onSave: (text: string) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState(existing);
  const box = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => box.current?.focus(), []);

  return (
    <Panel title="Note" onClose={onClose}>
      <p className="mb-2 line-clamp-2 border-l-2 border-mark-key pl-2 text-xs text-muted-foreground italic">
        {at.text}
      </p>
      <textarea
        ref={box}
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={3}
        placeholder="What did you notice?"
        className="w-full resize-none rounded-lg border border-border bg-background px-2.5 py-2 text-xs text-foreground placeholder:text-muted-foreground focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        onKeyDown={(e) => {
          // Enter saves, shift+enter breaks the line. A note is a sentence,
          // not a document.
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            onSave(text.trim());
          }
        }}
      />
      <div className="mt-2 flex items-center justify-end gap-2">
        <Button variant="ghost" size="xs" onClick={onClose}>
          Cancel
        </Button>
        <Button size="xs" onClick={() => onSave(text.trim())}>
          {text.trim() ? "Save" : existing ? "Remove" : "Save"}
        </Button>
      </div>
    </Panel>
  );
}

/**
 * A word the reader spent one of their three on, answered where they asked.
 *
 * ## Why this is a popover and not the panel in the corner
 *
 * The other two hang under the header because what they are about is the
 * whole screen — the kind of question being worked, a note on a stretch of
 * prose. This one is about ONE word, the reader is looking straight at it,
 * and an answer that appears four hundred pixels away makes them look up,
 * read, and look back to find their place again. Twice more and they stop
 * using the feature.
 *
 * So it arrives at the words, with an arrow pointing at them, 282px wide —
 * narrow enough to sit beside a line of the passage rather than across it.
 *
 * ## English above Uzbek, and that is deliberate
 *
 * The opposite of what it looks like it should be. A learner reading in
 * Uzbek would want their own language first; a learner sitting IELTS is
 * training the skill the paper actually tests, which is understanding an
 * English paraphrase of an English word. So the English gloss is the
 * foreground colour and the Uzbek sits under it, quieter — there to check
 * against when the paraphrase did not land, not to replace it.
 *
 * ## No title row
 *
 * The word is written once. The old panel had it twice — as the panel's
 * heading and again as the lemma — which in a box this size is a quarter of
 * the height spent saying nothing new.
 *
 * ## Save is here because this is the moment
 *
 * They have just spent one of three on it, which is the strongest evidence
 * anywhere in the app that this particular word is worth their time. Asking
 * them to remember it until the review page is asking them to do the
 * app's job.
 *
 * ## The list has no edges the reader can see
 *
 * Which words the pipeline happened to prepare is an optimisation, not a
 * boundary anybody is entitled to be told about. A live answer and an
 * extracted one are drawn identically; the only difference is that one of
 * them takes a second, and the waiting says "preparing" rather than
 * anything about a list. Where nothing at all can be said, the panel says
 * that IT did not find a meaning — the system's ignorance is never handed
 * to the learner as theirs — and the look-up is not charged.
 */
export function LookupPopover({
  materialId,
  word,
  where,
  rect,
  budget,
  onKept,
  onClose,
}: {
  materialId: string;
  word: string;
  /** Where in the passage they tapped. What makes the answer exact, and the
   *  whole of how a phrase is recognised — an entry whose span contains this
   *  point needs no string matching at all. */
  where?: { paragraphIndex: number; offset: number };
  /** The selection's box on screen, to hang this off. Absent only if the
   *  selection went away between the press and the render, and then it
   *  falls back to the top-right corner rather than to nowhere. */
  rect?: DOMRect | null;
  /**
   * The three-a-passage budget, where there is one.
   *
   * Absent on the REVIEW page, and that absence is the whole rule rather
   * than a relaxation of it. Three lookups exist to protect an exam habit:
   * a candidate who can look anything up is reading with a dictionary,
   * which is not the skill being scored. Once the paper is submitted there
   * is no habit left to protect, and rationing a learner's own curiosity
   * after the fact teaches nothing.
   *
   * One object rather than three props because they are one thing: with no
   * budget there is nothing to charge, nothing to ask whether a word was
   * free, and no counter to print. A caller in review mode passes nothing
   * and the card simply has no last line.
   */
  budget?: {
    spent: number;
    /** Whether this lemma was already opened on this passage, asked BEFORE
     *  anything is charged.
     *
     *  A function rather than a boolean, and that is the fix for a real bug:
     *  the caller only has the raw selected text, and what gets charged is
     *  the LEMMA the server returns. Tapping `proponents` charges
     *  `proponent`, and a boolean computed from `proponents` would say "not
     *  free" for ever on a word the budget was quietly treating as free. */
    isKnown: (lemma: string) => boolean;
    /** Charged only when something came back. */
    onFound: (lemma: string) => void;
  };
  /** A word was answered, with the lemma that answered it.
   *
   *  The review page uses it to refresh its list, so a word glossed on the
   *  spot joins the passage's marking and the panel beside it at once
   *  rather than after a reload — it IS part of the passage's vocabulary
   *  now, and a page that knew and did not say would be asking the reader
   *  to look it up twice.
   *
   *  The LEMMA rather than a "this was generated" flag, because the wire
   *  does not carry one and should not have to: the caller holds the list
   *  and can see for itself whether this lemma is new to it. Which also
   *  keeps the refetch off every cached answer, where there is nothing to
   *  fetch. */
  onKept?: (lemma: string) => void;
  onClose: () => void;
}) {
  const found = useQuery({
    queryKey: ["lookup", materialId, word.toLowerCase(), where?.offset ?? -1],
    queryFn: () =>
      vocabularyApi.lookUp(materialId, word, where, budget ? "take" : "review"),
    // A word looked up twice in one sitting is the same word: the budget
    // says so, and re-asking the server would contradict it.
    staleTime: Infinity,
    retry: false,
  });

  // The PHRASE leads where there is one. Somebody who tapped `rise` inside
  // `give rise to` is reading the phrase whatever their finger landed on,
  // and every word in it is separately common — the phrase is the thing
  // that stopped them. The word's own sense goes underneath, one line, for
  // the case where it was not.
  const lead = found.data?.phrase ?? found.data?.word ?? null;
  const under = found.data?.phrase ? found.data.word : null;

  // The WORD is what gets charged, not the phrase around it: the phrase came
  // free, as context. Charging it would file the look-up under a string the
  // reader never touched, and the review would name a word they did not ask
  // about.
  const charged = found.data?.word ?? found.data?.phrase ?? null;

  // Whether it was free, decided once, on the way in. Asked before `onFound`
  // in the same tick — `isKnown` closes over the state as it was before this
  // look-up — because a moment later the answer is always yes.
  const [wasFree, setWasFree] = useState<boolean | null>(null);
  // Charged on the way back rather than on the way out. `onFound` is
  // idempotent — `opened()` ignores a word already on the list — so a
  // re-render or a refetch cannot spend twice.
  useEffect(() => {
    if (!charged || !budget) return;
    setWasFree((was) => was ?? budget.isKnown(charged.lemma));
    budget.onFound(charged.lemma);
  }, [charged, budget]);

  // Told once per answer. Whether it is NEWS is the caller's to decide —
  // see the prop — and the ref is here so a re-render of an open card does
  // not say it again.
  const told = useRef(false);
  useEffect(() => {
    if (!onKept || told.current) return;
    const answer = found.data?.word ?? found.data?.phrase;
    if (!answer) return;
    told.current = true;
    onKept(answer.lemma);
  }, [found.data, onKept]);

  useEffect(() => {
    const escape = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [onClose]);

  const keep = useMutation({
    mutationFn: (lemma: string) => vocabularyApi.save(materialId, [lemma]),
    onError: (e) => toast(getErrorMessage(e)),
  });
  // Saved for as long as this popover is open. Not read back from the
  // server: the answer to "is this on my list" is one round trip for a
  // button that has just been pressed, and the review page is where the
  // real state is shown.
  const [saved, setSaved] = useState(false);

  const box = place(rect ?? null);

  return createPortal(
    <div
      // `pointer-events-auto` on the card and none on the frame: a fixed
      // box over the passage would otherwise swallow the click that starts
      // the next selection.
      className="pointer-events-none fixed inset-0 z-50"
    >
      <div
        role="dialog"
        aria-label={`Meaning of ${word}`}
        className={cn(
          "pointer-events-auto absolute w-[282px] -translate-x-1/2 rounded-xl border border-border bg-popover p-3.5 shadow-lg",
          box.above ? "-translate-y-full" : "",
        )}
        style={{ left: box.left, top: box.top }}
        // The selection survives a press on this: a pointerdown anywhere
        // else collapses it, and a reader who then reaches for Highlight
        // would find nothing to mark.
        onMouseDown={(e) => e.preventDefault()}
      >
        {/* The arrow, pointing back at the words. It is what makes this an
            answer ABOUT something rather than a box that appeared. */}
        {/* Centred, because the card is centred on the selection — an
            arrow parked at the left edge points at whatever words happen to
            be under that corner, which is the one thing it must not do. It
            goes slightly wrong only when the card has been clamped against
            a viewport edge, and being right in the middle of the passage
            beats being right at the margins. */}
        <span
          aria-hidden
          className={cn(
            "absolute left-1/2 -ml-[5px] size-2.5 rotate-45 border-border bg-popover",
            box.above
              ? "-bottom-[5px] border-r border-b"
              : "-top-[5px] border-t border-l",
          )}
        />

        <header className="mb-2 flex items-baseline gap-2">
          <span className="text-[0.95rem] leading-tight font-medium text-foreground">
            {lead ? lead.lemma : word}
          </span>
          {lead?.pos && (
            <span className="text-[0.7rem] text-muted-foreground italic">
              {lead.pos}
            </span>
          )}
          {/* Coloured from here on, and it is the same colour the review
              will use for this word an hour from now — which is the whole
              point of the scale having one. See
              `features/vocabulary/cefr.ts`. */}
          <CefrTag level={lead?.cefr_level} />
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="-mr-1 ml-auto rounded p-0.5 text-muted-foreground/70 transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            <X className="size-3.5" aria-hidden />
          </button>
        </header>

        {found.isPending && (
          <p className="flex items-center gap-2 py-1 text-xs text-muted-foreground">
            <span
              aria-hidden
              className="size-3 animate-spin rounded-full border-2 border-border border-t-primary"
            />
            Preparing the meaning…
          </p>
        )}

        {/* Both failures read the same, and they read as OURS. "We could not
            find a meaning" is the system admitting a limit; "this word is
            not in our list" makes the reader's choice of word the problem. */}
        {(found.isError || (found.data && !lead)) && (
          <p className="text-xs leading-snug text-muted-foreground">
            We couldn&apos;t find a meaning for that one — it isn&apos;t
            counted.
          </p>
        )}

        {lead && (
          <>
            <p className="text-[0.82rem] leading-snug text-foreground">
              {lead.meaning_en}
            </p>
            <p className="mt-1 text-[0.8rem] leading-snug text-muted-foreground">
              {lead.meaning_uz}
            </p>
          </>
        )}

        {/* The word on its own, under the phrase it was standing in. One
            line and the Uzbek only: the English is already above, said of
            the expression the reader is actually reading. */}
        {under && (
          <div className="mt-2.5 border-t border-border pt-2">
            <p className="text-[0.66rem] text-muted-foreground/70">
              {under.lemma} — on its own
            </p>
            <p className="mt-0.5 text-[0.78rem] leading-snug text-muted-foreground">
              {under.meaning_uz}
            </p>
          </div>
        )}

        {/* Only where it is true, and short. `bank` as the side of a river
            is the nastiest kind of hard word — nothing about it looks
            difficult, so nothing tells the reader to check. */}
        {lead?.unusual && (
          <p className="mt-2.5 flex items-start gap-1.5 border-t border-border pt-2 text-[0.7rem] leading-snug text-warning">
            <TriangleAlert className="mt-px size-3 shrink-0" aria-hidden />
            Not its usual sense here
          </p>
        )}

        {lead && (
          <div className="mt-2.5 flex items-center gap-2.5 border-t border-border pt-2">
            <button
              type="button"
              disabled={saved || keep.isPending}
              onClick={() =>
                keep.mutate(lead.lemma, { onSuccess: () => setSaved(true) })
              }
              className={cn(
                "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[0.7rem] transition-colors duration-fast focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                saved || lead.saved
                  ? "bg-correct/10 text-correct"
                  : "bg-surface-hover text-foreground hover:bg-surface-hover/70",
              )}
            >
              {saved || lead.saved ? (
                <>
                  <Check className="size-3" aria-hidden />
                  Saved
                </>
              ) : (
                <>
                  <Plus className="size-3" aria-hidden />
                  Save
                </>
              )}
            </button>
            {/* Short, and absent entirely where nothing is being counted.
                The rule that a repeat is free belongs in the tool row's
                tooltip, not on every card a reader opens — and on the review
                page there is no count at all, so printing "unlimited" there
                would be the page congratulating itself. */}
            {budget && (
              <span className="ml-auto text-[0.68rem] tabular-nums text-muted-foreground/70">
                {wasFree ? "free" : `${budget.spent} of ${LOOKUP_BUDGET}`}
              </span>
            )}
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}

/** Where to put the card, given the selection's own box.
 *
 *  Below the words by default so the arrow points up at them; above where
 *  there is not room below. Clamped to the viewport at both edges, because
 *  a word at the right margin would otherwise put half the card off screen
 *  — and the card is 282 wide, so half of it is a lot. */
function place(rect: DOMRect | null): {
  left: number;
  top: number;
  above: boolean;
} {
  if (!rect) {
    return { left: window.innerWidth - 160, top: 76, above: false };
  }
  const above = rect.bottom + 200 > window.innerHeight && rect.top > 220;
  return {
    left: Math.min(
      Math.max(rect.left + rect.width / 2, 150),
      window.innerWidth - 150,
    ),
    top: above ? rect.top - 10 : rect.bottom + 10,
    above,
  };
}

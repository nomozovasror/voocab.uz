import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { helpFor } from "@/features/reading/help";
import { LOOKUP_BUDGET } from "@/features/reading/lookups";
import type { QuestionGroupType } from "@/features/paper/types";
import type { Selected } from "@/features/reading/selection";
import { vocabularyApi } from "@/features/vocabulary/api";
import type { VocabularyEntry } from "@/features/vocabulary/types";

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
 * A word the reader spent one of their three on.
 *
 * ## What it shows, and what it deliberately does not
 *
 * Lemma, part of speech, level, the meaning in THIS passage, and the Uzbek.
 * Nothing else. No etymology, no other senses, no synonyms — and no example
 * sentence, which is the one that looks like an omission and is not: the
 * reader is looking at the sentence. It is six inches to the left.
 *
 * The budget is three, so each lookup is expensive to the reader and has to
 * pay for itself in about two seconds. A panel that reads like a dictionary
 * page is a panel somebody closes and goes back to guessing, having spent
 * one of three for the privilege.
 *
 * ## The phrase comes first
 *
 * Somebody who tapped `rise` inside `give rise to` is reading the phrase,
 * whatever their finger landed on — and the phrase is the thing that stopped
 * them, because each of its words is separately common. So it is shown
 * above, and the word's own meaning below it, for the case where the phrase
 * was not the difficulty.
 *
 * ## An empty answer is ordinary
 *
 * A name, a number, a word in another language, or a morning the dictionary
 * is unreachable. The panel says so plainly, and — this is the part that
 * matters — the lookup is NOT charged. Spending one of three to be told
 * nothing is the kind of small unfairness a learner remembers.
 */
export function LookupPanel({
  materialId,
  word,
  where,
  spent,
  isKnown,
  onFound,
  onClose,
}: {
  materialId: string;
  word: string;
  /** Where in the passage they tapped. What makes the answer exact, and the
   *  whole of how a phrase is recognised — an entry whose span contains this
   *  point needs no string matching at all. */
  where?: { paragraphIndex: number; offset: number };
  spent: number;
  /** Whether this lemma was already opened on this passage, asked BEFORE
   *  anything is charged.
   *
   *  A function rather than a boolean, and that is the fix for a real bug:
   *  the caller only has the raw selected text, and what gets charged is the
   *  LEMMA the server returns. Tapping `proponents` charges `proponent`, and
   *  a boolean computed from `proponents` would say "not free" for ever on a
   *  word the budget was quietly treating as free. */
  isKnown: (lemma: string) => boolean;
  /** Charged only when something came back. */
  onFound: (lemma: string) => void;
  onClose: () => void;
}) {
  const found = useQuery({
    queryKey: ["lookup", materialId, word.toLowerCase(), where?.offset ?? -1],
    queryFn: () => vocabularyApi.lookUp(materialId, word, where),
    // A word looked up twice in one sitting is the same word: the budget
    // says so, and re-asking the server would contradict it.
    staleTime: Infinity,
    retry: false,
  });

  // The WORD is what gets charged, not the phrase around it. Somebody who
  // tapped `vogue` and was shown `in vogue` above it looked up `vogue`; the
  // phrase came free, as context. Charging the phrase instead would file the
  // lookup under a string the reader never touched, and the review would
  // then name a word they did not ask about.
  const entry = found.data?.word ?? found.data?.phrase ?? null;

  // Whether it was free, decided once, on the way in. Asked before `onFound`
  // in the same tick — `isKnown` closes over the state as it was before this
  // lookup — because a moment later the answer is always yes.
  const [wasFree, setWasFree] = useState<boolean | null>(null);
  // Charged on the way back rather than on the way out. `onFound` is
  // idempotent — `opened()` ignores a word already on the list — so a
  // re-render or a refetch cannot spend twice.
  useEffect(() => {
    if (!entry) return;
    setWasFree((was) => was ?? isKnown(entry.lemma));
    onFound(entry.lemma);
  }, [entry, isKnown, onFound]);

  return (
    <Panel title={word} onClose={onClose}>
      {found.isPending && (
        <p className="text-xs text-muted-foreground">Looking it up…</p>
      )}
      {found.isError && (
        <p className="text-xs text-muted-foreground">
          The dictionary could not be reached. This one is not charged.
        </p>
      )}
      {found.data && !entry && (
        <p className="text-xs text-muted-foreground">
          No meaning for that one — it may be a name or a number. This lookup is
          not charged.
        </p>
      )}
      {found.data?.phrase && (
        <Sense entry={found.data.phrase} lead="The phrase here" />
      )}
      {found.data?.word && (
        <Sense
          entry={found.data.word}
          lead={found.data.phrase ? "The word on its own" : undefined}
        />
      )}
      {entry && (
        <p className="mt-3 border-t border-border pt-2 text-[0.7rem] text-muted-foreground">
          {wasFree
            ? "Already looked up — this one was free."
            : `${spent} of ${LOOKUP_BUDGET} used on this passage. Looking the same word up again is free.`}
        </p>
      )}
    </Panel>
  );
}

/**
 * One meaning: the word, what kind of word it is, its level, and two lines.
 *
 * The level is printed and the frequency band is not, which is the whole of
 * that decision: `C1` is a scale a learner already has a feel for, and
 * "NGSL rank 2400" is a fact about a corpus. The band exists — it is what
 * lets two passages be compared — and it stays on the server, where the
 * arithmetic is.
 */
function Sense({ entry, lead }: { entry: VocabularyEntry; lead?: string }) {
  return (
    <div className="mt-1 first:mt-0 [&+&]:mt-3 [&+&]:border-t [&+&]:border-border [&+&]:pt-2.5">
      {lead && (
        <p className="mb-1 text-[0.7rem] tracking-caps text-muted-foreground uppercase">
          {lead}
        </p>
      )}
      <p className="flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
        <span className="text-sm font-semibold text-foreground">
          {entry.lemma}
        </span>
        {entry.pos && (
          <span className="text-[0.7rem] text-muted-foreground italic">
            {entry.pos}
          </span>
        )}
        {entry.cefr_level && (
          <span className="rounded border border-border px-1 text-[0.65rem] font-medium text-muted-foreground">
            {entry.cefr_level}
          </span>
        )}
      </p>
      {/* Said out loud where it costs most to miss. A reader who tapped a
          word they thought they knew has to be told that they do — the
          meaning alone would read as the app being unhelpful, when what is
          happening is that the passage has moved the word. */}
      {entry.unusual && (
        <p className="mt-0.5 text-[0.7rem] text-muted-foreground">
          Not the usual sense of this word.
        </p>
      )}
      <p className="mt-1 text-xs leading-relaxed text-foreground">
        {entry.meaning_uz}
      </p>
      <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
        {entry.meaning_en}
      </p>
    </div>
  );
}

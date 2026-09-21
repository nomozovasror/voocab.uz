import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { toast } from "@/lib/toast";
import { getErrorMessage } from "@/lib/api";
import { vocabularyApi, vocabularyKey } from "@/features/vocabulary/api";
import type {
  VocabularyEntry,
  VocabularyList,
} from "@/features/vocabulary/types";

/**
 * What this passage was worth learning, offered once it can no longer help.
 *
 * ## Why it is here and not anywhere else
 *
 * An IELTS teacher whose student struggles with a passage sets its vocabulary
 * as homework. That is the actual practice this automates, and it is the
 * single most valuable thing on this page after the mistakes — because the
 * words come out of a text the reader has just spent twenty minutes inside.
 * A word met in a passage somebody argued with is remembered; the same word
 * on a list of four hundred is not.
 *
 * It cannot be shown before the paper is submitted, and not only as a matter
 * of taste: the server refuses the list to anybody who has not finished
 * (`may_see_all`). Eighty-six glosses open mid-paper would make the three
 * lookups a formality.
 *
 * ## It is half of a pair now, not a section at the bottom of a page
 *
 * This used to be a bordered panel under the mistakes, and the list ran to
 * a hundred and one entries of four lines each — about ten screens of words
 * with no passage anywhere near them, which is a dictionary with the one
 * thing that made it worth reading taken out.
 *
 * Now it is one of two tabs beside the passage itself, and the passage is
 * marked with what this list is talking about. Pointing at an entry lights
 * the word where it stands in the text; pointing at the text lights the
 * entry. That is the whole argument for saving vocabulary from a paper
 * rather than from a list, made visible instead of written down.
 *
 * ## The words they looked up come first, and separately
 *
 * They are not a subset worth a badge — they are a different fact. Every
 * other word here is one the frequency lists think is hard. Those two or
 * three are the ones that stopped THIS reader, mid-paper, badly enough to
 * spend one of three on. Nothing else on the platform knows which words
 * those were, which is why "Save my look-ups" is the most valuable of the
 * three save buttons and reads as the smallest.
 *
 * ## B2 and up are open; B1 is folded away
 *
 * Not a single collapsed block. Sorting by level and then hiding all of it
 * gets the ordering right and the emphasis wrong — what somebody sitting a
 * band 6 paper should be studying is the B2 and C1 words, and making them
 * press something to reach those while the B1 list has equal billing is the
 * page having no opinion.
 *
 * Sorted by level rather than by where the words stand in the passage,
 * which is the opposite of the lookup panel's order and right for the
 * opposite reason: mid-paper the question is "what does this one mean", and
 * here it is "which of these should I learn first".
 *
 * ## The trap count
 *
 * "Six of them are common words in an unexpected sense" is the one figure
 * neither measure reports alone — the frequency says easy, the level says
 * C1, and the disagreement is the finding. It goes in the header rather than
 * on the rows, because what a candidate takes from it is a habit ("a word I
 * know can still be the wrong word here") rather than six facts.
 */

const LEVELS = ["B1", "B2", "C1"] as const;

export function ReviewVocabulary({
  materialId,
  data,
  lookedUp,
  savedEarlier,
  lit,
  onPoint,
  className,
}: {
  materialId: string;
  /** The passage's words. Fetched by the PAGE rather than here, because the
   *  passage beside this list is marked from the same rows — and two
   *  components asking the same question of the same cache is one of them
   *  reading a copy it did not know it had. */
  data: VocabularyList;
  /** The lemmas this attempt spent its lookups on, from the attempt itself.
   *  Empty for a sitting before the measurement existed, and for anybody who
   *  looked nothing up. */
  lookedUp: string[];
  /** Which were already on the learner's list when this page opened.
   *
   *  Not the same as `entry.saved`, which moves the moment somebody presses
   *  a button here. "Saved earlier" is a claim about a DIFFERENT DAY — you
   *  met this word a fortnight ago and here it is again — and a badge that
   *  appeared on a word two seconds after it was saved would be the page
   *  congratulating somebody on remembering what they just did. */
  savedEarlier: Set<string>;
  /** The lemma being pointed at, from either side. */
  lit: string | null;
  onPoint: (lemma: string | null) => void;
  className?: string;
}) {
  const qc = useQueryClient();
  const key = vocabularyKey(materialId);

  const save = useMutation({
    mutationFn: (lemmas: string[]) => vocabularyApi.save(materialId, lemmas),
    // Marked saved in place rather than refetched. The server's answer is
    // the learner's whole list, which is not what this page is showing, and
    // a refetch of eighty-six rows to change one button is a page that
    // flickers every time somebody presses Save.
    onSuccess: (_result, lemmas) => {
      qc.setQueryData<VocabularyList>(key, (was) =>
        was
          ? {
              ...was,
              entries: was.entries.map((entry) =>
                lemmas.includes(entry.lemma)
                  ? { ...entry, saved: true }
                  : entry,
              ),
            }
          : was,
      );
    },
    onError: (e) => toast(getErrorMessage(e)),
  });

  const { opened, main, easiest } = useMemo(() => {
    const entries = data.entries;
    const wanted = new Set(lookedUp);
    const byLevel = (a: VocabularyEntry, b: VocabularyEntry) =>
      LEVELS.indexOf(a.cefr_level as (typeof LEVELS)[number]) -
        LEVELS.indexOf(b.cefr_level as (typeof LEVELS)[number]) ||
      a.paragraph_index - b.paragraph_index ||
      a.offset_start - b.offset_start;
    const rest = entries
      .filter((entry) => !wanted.has(entry.lemma))
      .sort(byLevel);
    return {
      opened: entries.filter((entry) => wanted.has(entry.lemma)),
      // An entry with no level sits with the harder ones rather than being
      // folded away: unrated is not the same as easy, and hiding it would
      // be the page making a claim it has no basis for.
      main: rest.filter((entry) => entry.cefr_level !== "B1"),
      easiest: rest.filter((entry) => entry.cefr_level === "B1"),
    };
  }, [data, lookedUp]);

  const unsaved = data.entries.filter((entry) => !entry.saved);
  const openedUnsaved = opened.filter((entry) => !entry.saved);
  const hardest = unsaved.filter((entry) => entry.cefr_level === "C1");

  const row = (entry: VocabularyEntry) => (
    <Word
      key={entry.id}
      entry={entry}
      earlier={savedEarlier.has(entry.lemma)}
      lit={lit === entry.lemma}
      onPoint={onPoint}
      busy={save.isPending}
      onSave={() => save.mutate([entry.lemma])}
    />
  );

  return (
    <section className={cn("min-w-0", className)}>
      <header className="rounded-xl bg-surface-sunken px-4 py-3">
        <h2 className="text-sm font-semibold text-foreground">
          {data.total} words worth learning here
        </h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {LEVELS.filter((level) => data.levels[level])
            .map((level) => `${level} ${data.levels[level]}`)
            .join(" · ")}
          {data.unusual > 0 &&
            ` — ${data.unusual} of them in a sense you would not expect`}
        </p>

        {/* Three ways to save a handful at once, and each answers a
            different question somebody actually asks. "All of them" is the
            reader who wants the passage's whole vocabulary; "just C1" is the
            one who already knows most of it and wants the top of the list;
            the third is the one who only wants what beat them, and it is
            the one worth the most — nothing else on the platform knows
            which words those were. */}
        {unsaved.length > 0 && (
          <div className="mt-2.5 flex flex-wrap items-center gap-1">
            {openedUnsaved.length > 0 && (
              <Button
                variant="ghost"
                size="xs"
                disabled={save.isPending}
                onClick={() =>
                  save.mutate(openedUnsaved.map((entry) => entry.lemma))
                }
              >
                Save my {openedUnsaved.length} look-up
                {openedUnsaved.length === 1 ? "" : "s"}
              </Button>
            )}
            {hardest.length > 1 && hardest.length < unsaved.length && (
              <Button
                variant="ghost"
                size="xs"
                disabled={save.isPending}
                onClick={() => save.mutate(hardest.map((entry) => entry.lemma))}
              >
                Save the {hardest.length} C1
              </Button>
            )}
            <Button
              variant="ghost"
              size="xs"
              disabled={save.isPending}
              onClick={() => save.mutate(unsaved.map((entry) => entry.lemma))}
            >
              Save all {unsaved.length}
            </Button>
          </div>
        )}
      </header>

      {opened.length > 0 && (
        <div className="mt-4">
          <h3 className="mb-1 text-xs tracking-caps text-muted-foreground uppercase">
            The {opened.length === 1 ? "word" : `${opened.length} words`} you
            looked up
          </h3>
          <ul>{opened.map(row)}</ul>
        </div>
      )}

      {main.length > 0 && (
        <div className="mt-4">
          <h3 className="mb-1 text-xs tracking-caps text-muted-foreground uppercase">
            {opened.length > 0
              ? "The rest of the passage"
              : "From this passage"}
          </h3>
          <ul>{main.map(row)}</ul>
        </div>
      )}

      {/* The B1 words, behind one line. Not junk — somebody who wants them
          is one press away — but not what this passage taught a reader
          sitting for band 6 or 7, and giving them equal billing is the page
          declining to have an opinion. */}
      {easiest.length > 0 && (
        <details className="mt-4 border-t border-border">
          <summary className="cursor-pointer py-3 text-sm text-muted-foreground transition-colors hover:text-foreground">
            {easiest.length} easier {easiest.length === 1 ? "word" : "words"}{" "}
            (B1)
          </summary>
          <ul>{easiest.map(row)}</ul>
        </details>
      )}
    </section>
  );
}

/**
 * One word, with the sentence it was met in.
 *
 * The example is the reason this is worth more than a word list, so it is
 * printed rather than hidden behind the row: what a learner will remember is
 * the passage, and the sentence is the handle on it. It is the passage's own
 * sentence, cut from the text rather than written by a model — see
 * `seed/read_vocabulary.py`.
 *
 * Beside a marked passage the example earns its place twice over: pointing
 * at the row lights the word where it stands, so the sentence in the row and
 * the paragraph on the left are visibly the same place.
 */
function Word({
  entry,
  earlier,
  lit,
  onPoint,
  busy,
  onSave,
}: {
  entry: VocabularyEntry;
  earlier: boolean;
  lit: boolean;
  onPoint: (lemma: string | null) => void;
  busy: boolean;
  onSave: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  return (
    <li
      onMouseEnter={() => {
        setHovered(true);
        onPoint(entry.lemma);
      }}
      onMouseLeave={() => {
        setHovered(false);
        onPoint(null);
      }}
      className={cn(
        "-mx-2 flex items-start gap-3 rounded-lg border-b border-border/60 px-2 py-2.5 transition-colors duration-fast last:border-b-0",
        (hovered || lit) && "bg-surface-hover",
      )}
    >
      <div className="min-w-0 flex-1">
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
          {/* The blue of the Saved layer, because it is the same claim: this
              is a word you have met before, and there it is in the passage.
              A reader who has turned that layer on should recognise the
              colour without being told they are the same thing. */}
          {earlier && (
            <span className="rounded border border-mark-found/40 px-1 text-[0.65rem] text-mark-found">
              Saved earlier
            </span>
          )}
          {/* Named rather than badged. A badge says "this one is special"
              and leaves the reader to work out how; the sentence says what
              is actually going on, which is the only part that helps. */}
          {entry.unusual && (
            <span className="text-[0.7rem] text-muted-foreground">
              · not the usual sense
            </span>
          )}
        </p>
        {/* English in the mono face the rest of the paper's own words are
            set in, Uzbek in the sans — the app's global rule, and here it
            also does the work of telling two one-line definitions apart at
            a glance without a label in front of either. */}
        <p className="mt-0.5 font-mono text-xs text-foreground/80">
          {entry.meaning_en}
        </p>
        <p className="text-xs text-muted-foreground">{entry.meaning_uz}</p>
        {entry.example && (
          <p className="mt-1 border-l-2 border-border pl-2 text-xs leading-relaxed text-muted-foreground italic">
            {entry.example}
          </p>
        )}
      </div>
      <button
        type="button"
        disabled={entry.saved || busy}
        onClick={onSave}
        title={entry.saved ? "On your list" : "Add to your vocabulary"}
        aria-label={entry.saved ? "On your list" : `Save ${entry.lemma}`}
        className={cn(
          "mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg transition-colors duration-fast focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
          entry.saved
            ? "text-correct"
            : "text-muted-foreground hover:bg-surface-hover hover:text-foreground",
          // Present but quiet until the row is under the pointer. Eighty of
          // these at full contrast is a column of buttons with a vocabulary
          // list behind it.
          !entry.saved && !hovered && "opacity-40",
        )}
      >
        {entry.saved ? (
          <Check className="size-3.5" aria-hidden />
        ) : (
          <Plus className="size-3.5" aria-hidden />
        )}
      </button>
    </li>
  );
}

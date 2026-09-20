import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { toast } from "@/lib/toast";
import { getErrorMessage } from "@/lib/api";
import { vocabularyApi } from "@/features/vocabulary/api";
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
 * as homework. That is the actual practice this section automates, and it is
 * the single most valuable thing on this page after the mistakes — because
 * the words come out of a text the reader has just spent twenty minutes
 * inside. A word met in a passage somebody argued with is remembered; the
 * same word on a list of four hundred is not.
 *
 * It cannot be shown before the paper is submitted, and not only as a matter
 * of taste: the server refuses the list to anybody who has not finished
 * (`may_see_all`). Eighty-six glosses open mid-paper would make the three
 * lookups a formality.
 *
 * ## The words they looked up come first, and separately
 *
 * They are not a subset worth a badge — they are a different fact. Every
 * other word here is one the frequency lists think is hard. Those two or
 * three are the ones that stopped THIS reader, mid-paper, badly enough to
 * spend one of three on. Nothing else on the platform knows which words
 * those were.
 *
 * ## The rest is collapsed, and sorted by level
 *
 * Eighty entries open under a review would bury the mistakes above them. The
 * count is the invitation; opening is the reader deciding they want it.
 *
 * Sorted B1 → C1 rather than by where they stand in the passage, which is
 * the opposite of the lookup panel's order and right for the opposite
 * reason: mid-paper the question is "what does this one mean", and here it
 * is "which of these should I learn first". Level answers that; position
 * does not.
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
  lookedUp,
  className,
}: {
  materialId: string;
  /** The lemmas this attempt spent its lookups on, from the attempt itself.
   *  Empty for a sitting before the measurement existed, and for anybody who
   *  looked nothing up. */
  lookedUp: string[];
  className?: string;
}) {
  const qc = useQueryClient();
  const key = ["vocabulary", materialId];
  const { data, isPending, isError } = useQuery({
    queryKey: key,
    queryFn: () => vocabularyApi.list(materialId),
    // Refused with a 403 until the paper is submitted, and there is no
    // retrying past that: it is an answer, not a failure.
    retry: false,
  });

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

  const { opened, rest } = useMemo(() => {
    const entries = data?.entries ?? [];
    const wanted = new Set(lookedUp);
    return {
      opened: entries.filter((entry) => wanted.has(entry.lemma)),
      rest: [...entries]
        .filter((entry) => !wanted.has(entry.lemma))
        .sort(
          (a, b) =>
            LEVELS.indexOf(a.cefr_level as (typeof LEVELS)[number]) -
              LEVELS.indexOf(b.cefr_level as (typeof LEVELS)[number]) ||
            a.paragraph_index - b.paragraph_index ||
            a.offset_start - b.offset_start,
        ),
    };
  }, [data, lookedUp]);

  // Silent rather than apologetic. A listening paper has no vocabulary, a
  // reading one the extraction has not reached has none yet, and a 403 means
  // this is somebody else's attempt — none of the three is worth a panel
  // explaining itself on a page about how the reader did.
  if (isPending || isError || !data || data.total === 0) return null;

  const unsaved = data.entries.filter((entry) => !entry.saved);
  const openedUnsaved = opened.filter((entry) => !entry.saved);

  return (
    <section className={cn("rounded-xl border border-border", className)}>
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-5 py-4">
        <div>
          <h2 className="text-sm font-semibold text-foreground">
            {data.total} words worth learning here
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {LEVELS.filter((level) => data.levels[level])
              .map((level) => `${level} ${data.levels[level]}`)
              .join(" · ")}
          </p>
          {data.unusual > 0 && (
            <p className="mt-1 text-xs text-muted-foreground">
              {data.unusual} of them are everyday words in a sense you would not
              expect — the kind a passage does not warn you about.
            </p>
          )}
        </div>
        {unsaved.length > 0 && (
          <Button
            variant="ghost"
            size="xs"
            disabled={save.isPending}
            onClick={() => save.mutate(unsaved.map((entry) => entry.lemma))}
          >
            Save all {unsaved.length}
          </Button>
        )}
      </header>

      {opened.length > 0 && (
        <div className="border-t border-border px-5 py-4">
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <h3 className="text-xs tracking-caps text-muted-foreground uppercase">
              The {opened.length === 1 ? "word" : `${opened.length} words`} you
              looked up
            </h3>
            {openedUnsaved.length > 1 && (
              <Button
                variant="ghost"
                size="xs"
                disabled={save.isPending}
                onClick={() =>
                  save.mutate(openedUnsaved.map((entry) => entry.lemma))
                }
              >
                Save these {openedUnsaved.length}
              </Button>
            )}
          </div>
          <ul>
            {opened.map((entry) => (
              <Word
                key={entry.id}
                entry={entry}
                busy={save.isPending}
                onSave={() => save.mutate([entry.lemma])}
              />
            ))}
          </ul>
        </div>
      )}

      <details className="border-t border-border">
        <summary className="cursor-pointer px-5 py-3 text-sm text-muted-foreground transition-colors hover:text-foreground">
          {opened.length > 0
            ? `The other ${rest.length}, by level`
            : `All ${rest.length}, by level`}
        </summary>
        <ul className="border-t border-border px-5 py-2">
          {rest.map((entry) => (
            <Word
              key={entry.id}
              entry={entry}
              busy={save.isPending}
              onSave={() => save.mutate([entry.lemma])}
            />
          ))}
        </ul>
      </details>
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
 */
function Word({
  entry,
  busy,
  onSave,
}: {
  entry: VocabularyEntry;
  busy: boolean;
  onSave: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  return (
    <li
      className="flex items-start gap-3 border-b border-border/60 py-2.5 last:border-b-0"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
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
          {/* Named rather than badged. A badge says "this one is special"
              and leaves the reader to work out how; the sentence says what
              is actually going on, which is the only part that helps. */}
          {entry.unusual && (
            <span className="text-[0.7rem] text-muted-foreground">
              · not the usual sense
            </span>
          )}
        </p>
        <p className="mt-0.5 text-xs text-foreground">{entry.meaning_uz}</p>
        <p className="text-xs text-muted-foreground">{entry.meaning_en}</p>
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

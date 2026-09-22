import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Trash2 } from "lucide-react";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { toast } from "@/lib/toast";
import { getErrorMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import { CefrTag } from "@/features/vocabulary/components/CefrTag";
import { meanings } from "@/features/vocabulary/meaning";
import { vocabularyApi } from "@/features/vocabulary/api";
import type { SavedWord, SavedWords } from "@/features/vocabulary/types";

/**
 * The words this learner has kept, and every passage each was met in.
 *
 * ## What this is, and what it is not
 *
 * It is the list. It is not the spaced-repetition module — no scheduling, no
 * review queue, no "next due in three days" — and that absence is deliberate
 * rather than unfinished: scheduling is its own brief, and inventing an
 * interval here would be guessing at that design from the outside and then
 * having to migrate away from the guess.
 *
 * What it must do today is much smaller and not optional. The review page
 * offers a Save button on eighty-six words, and a Save button whose result
 * cannot be looked at is a button that quietly does nothing. This is where
 * the words land.
 *
 * ## One word, several contexts
 *
 * `spring` met in a passage about seasons and again in one about coils is
 * ONE word with two meanings, which is why the saved list deduplicates by
 * lemma and hangs each meeting off it. Both are printed, each with the
 * sentence it came from and a link back to the passage — that pair is the
 * whole argument for saving words from a paper rather than from a list: the
 * learner was there, and the sentence is the handle on the memory.
 *
 * The meanings are COPIES, taken at the moment of saving. A material can be
 * edited and re-glossed, and a saved word changing meaning underneath
 * somebody is worse than one that has aged.
 */
export default function VocabularyPage() {
  const qc = useQueryClient();
  const { data, isPending, isError } = useQuery({
    queryKey: ["vocabulary", "saved"],
    queryFn: () => vocabularyApi.saved(),
  });

  const forget = useMutation({
    mutationFn: (lemma: string) => vocabularyApi.forget(lemma),
    onSuccess: (_result, lemma) => {
      qc.setQueryData<SavedWords>(["vocabulary", "saved"], (was) =>
        was
          ? {
              total: was.total - 1,
              words: was.words.filter((word) => word.lemma !== lemma),
            }
          : was,
      );
    },
    onError: (e) => toast(getErrorMessage(e)),
  });

  if (isPending) return <SavedSkeleton />;

  if (isError) {
    return (
      <div className="mx-auto w-full max-w-2xl py-16">
        <h1 className="text-2xl font-semibold text-foreground">Vocabulary</h1>
        <p className="mt-2 text-sm text-destructive">
          Your words couldn&apos;t be loaded.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-2xl pb-24">
      <header className="pt-2 pb-6">
        <h1 className="text-2xl font-semibold text-foreground">Vocabulary</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {data.total > 0
            ? `${data.total} ${data.total === 1 ? "word" : "words"} you kept, with the passage each came from.`
            : "Words you keep from a passage collect here."}
        </p>
      </header>

      {data.total === 0 ? (
        <Empty />
      ) : (
        <ul className="space-y-3">
          {data.words.map((word) => (
            <Word
              key={word.lemma}
              word={word}
              busy={forget.isPending}
              onForget={() => forget.mutate(word.lemma)}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function Word({
  word,
  busy,
  onForget,
}: {
  word: SavedWord;
  busy: boolean;
  onForget: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  // The first context carries the headline meaning. It is the one they met
  // first, and where a word has only one context — which is nearly all of
  // them — it is the only one.
  const [first, ...rest] = word.contexts;
  // The word's own meaning, said ONCE above everything the passages had to
  // say about it. That is the shape the card wants: `spring` met in a
  // passage about seasons and again in one about coils is one word, and
  // repeating "a season of the year" over each meeting would be the card
  // arguing with its own headline.
  //
  // Taken from the first context that has one, because it is a fact about
  // the word rather than about any meeting, and two contexts phrasing it
  // differently is two runs of the same question and not a disagreement
  // worth printing twice. Absent on a word saved before the field existed
  // and not yet enriched, and then each meeting prints its own meaning as
  // it always did.
  const core = word.contexts.find((one) => one.meaning_core_en) ?? null;

  return (
    <li
      className="rounded-xl border border-border px-5 py-4"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
            <span className="text-base font-semibold text-foreground">
              {word.lemma}
            </span>
            {first?.pos && (
              <span className="text-xs text-muted-foreground italic">
                {first.pos}
              </span>
            )}
            <CefrTag level={first?.cefr_level} />
            {rest.length > 0 && (
              <span className="text-[0.7rem] text-muted-foreground">
                · {word.contexts.length} passages
              </span>
            )}
          </p>
          {core && (
            <>
              <p className="mt-1 text-sm text-foreground">
                {core.meaning_core_uz}
              </p>
              <p className="text-xs text-muted-foreground">
                {core.meaning_core_en}
              </p>
            </>
          )}
          {first && <Sense context={first} headline={!core} />}
          {rest.map((context) => (
            <Sense
              key={context.material_id}
              context={context}
              headline={!core}
              separated
            />
          ))}
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={onForget}
          title="Take it off your list"
          aria-label={`Remove ${word.lemma}`}
          className={cn(
            "mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors duration-fast hover:bg-surface-hover hover:text-destructive focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
            !hovered && "opacity-0",
          )}
        >
          <Trash2 className="size-3.5" aria-hidden />
        </button>
      </div>
    </li>
  );
}

/** One meeting: what it meant THERE where that is a different thing from
 *  what the word usually means, the sentence, and the way back.
 *
 *  The usual meaning leads here as it does everywhere else, and this is the
 *  screen where it matters most: a card somebody studies from. A learner
 *  revising `learn` off a passage about artificial intelligence had one
 *  line to go on — "a computer process of finding patterns in data" — and
 *  nothing on the page to tell them it was the passage talking. See
 *  `features/vocabulary/meaning.ts`.
 *
 *  Uzbek above English, which is this page's own order and the opposite of
 *  the review's: the review is read beside an English passage with the
 *  English still in the reader's eye, and this is read cold. */
function Sense({
  context,
  headline,
  separated = false,
}: {
  context: SavedWord["contexts"][number];
  /** Whether this meeting has to print the word's meaning itself. False
   *  where the card has already said it once above — see `Word` — and true
   *  for a word saved before the usual meaning existed, which has nothing
   *  else to show. */
  headline: boolean;
  separated?: boolean;
}) {
  const sense = meanings(context);
  return (
    <div className={cn(separated && "mt-3 border-t border-border/60 pt-2.5")}>
      {headline && (
        <>
          <p className="mt-1 text-sm text-foreground">{sense.uz}</p>
          <p className="text-xs text-muted-foreground">{sense.en}</p>
        </>
      )}
      {sense.here && (
        <p className="mt-1 border-l-2 border-border pl-2">
          <span className="block text-sm text-foreground">
            <span className="text-muted-foreground">Here: </span>
            {sense.here.uz}
          </span>
          <span className="block text-xs text-muted-foreground">
            {sense.here.en}
          </span>
        </p>
      )}
      {context.example && (
        <p className="mt-1.5 border-l-2 border-border pl-2 text-xs leading-relaxed text-muted-foreground italic">
          {context.example}
        </p>
      )}
      {context.material_title && (
        <Link
          to={`/reading/${context.material_id}`}
          className="mt-1.5 inline-flex items-center gap-1.5 text-[0.7rem] text-muted-foreground transition-colors hover:text-foreground"
        >
          <BookOpen className="size-3" aria-hidden />
          {context.material_title}
        </Link>
      )}
    </div>
  );
}

/** Nothing saved yet, said in terms of the thing that fills it. A list that
 *  explains only that it is empty leaves the reader to guess how it stops
 *  being. */
function Empty() {
  return (
    <div className="rounded-xl border border-dashed border-border px-5 py-10 text-center">
      <p className="text-sm text-muted-foreground">
        Sit a reading passage, and the words worth learning from it are waiting
        on the review page afterwards — with what each one means in that
        passage.
      </p>
      <Link
        to="/reading"
        className="mt-4 inline-flex items-center gap-1.5 text-sm text-primary transition-colors hover:underline"
      >
        <BookOpen className="size-3.5" aria-hidden />
        Find a passage
      </Link>
    </div>
  );
}

/** The page's shape, held open while it loads. Built from the real
 *  component's own class strings — `frontend/CLAUDE.md`. */
function SavedSkeleton() {
  return (
    <SkeletonBlock
      label="Loading your words"
      className="mx-auto w-full max-w-2xl pb-24"
    >
      <header className="pt-2 pb-6">
        <h1 className="text-2xl font-semibold">
          <Skeleton className="inline-block h-[0.8em] w-40" />
        </h1>
        <p className="mt-1 text-sm">
          <Skeleton className="inline-block h-[0.8em] w-72 max-w-full" />
        </p>
      </header>
      <ul className="space-y-3">
        {[0, 1, 2].map((row) => (
          <li key={row} className="rounded-xl border border-border px-5 py-4">
            <p className="text-base">
              <Skeleton className="inline-block h-[0.8em] w-28" />
            </p>
            <p className="mt-1 text-sm">
              <Skeleton className="inline-block h-[0.8em] w-52" />
            </p>
            <p className="text-xs">
              <Skeleton className="inline-block h-[0.8em] w-64 max-w-full" />
            </p>
          </li>
        ))}
      </ul>
    </SkeletonBlock>
  );
}

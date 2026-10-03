import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, ChevronLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { toast } from "@/lib/toast";
import { getErrorMessage } from "@/lib/api";
import { fmtClock, timeAgo, timeUntil } from "@/lib/time";
import { SenseList } from "@/features/vocabulary/components/SenseList";
import { CefrTag } from "@/features/vocabulary/components/CefrTag";
import { StatusChip } from "@/features/vocabulary/components/StatusChip";
import { ReportTranslation } from "@/features/vocabulary/components/ReportTranslation";
import { meanings } from "@/features/vocabulary/meaning";
import {
  ACTION_LABEL,
  LEECH_LABEL,
  RATING_LABEL,
  RATING_TONE,
  activeLevelLabel,
  passiveLevelLabel,
} from "@/features/vocabulary/status";
import {
  scheduleDelete,
  useFlushPendingDeletesOnLeave,
} from "@/features/vocabulary/pendingDelete";
import { vocabularyApi, vocabularyWordsKey, wordDetailKey } from "@/features/vocabulary/api";
import type { LeechChoice, SavedWord } from "@/features/vocabulary/types";

/**
 * `/vocabulary/words/:id` — the plan's screen 5, and the one screen this
 * module shows a single word from every angle at once: what it means,
 * everywhere it was met, where each direction's card stands, and the trail
 * of answers that put it there.
 *
 * Addressed by id, not by lemma: a saved word is one `LexemeSense` per
 * learner, and `bank` the finance term and `bank` the river bank are two
 * rows with two ids.
 *
 * It is reached from the words list and, in stage 2, also from "See it
 * where you met it" on a leech's reveal — the spec's §5 names this page
 * as that choice's destination in words, not a modal over the session.
 */
export default function VocabularyWordPage() {
  const { id = "" } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  // Registers this page too, alongside the words list, as somewhere
  // "Removed · Undo" could be shown — see `pendingDelete.ts`. Deleting here
  // navigates away before that row is ever drawn on THIS page, but the
  // timer it starts has to survive the navigation, and unregistering only
  // when neither page is mounted is what lets it.
  useFlushPendingDeletesOnLeave();

  const { data, isPending, isError } = useQuery({
    queryKey: wordDetailKey(id),
    queryFn: () => vocabularyApi.wordDetail(id),
  });

  const bulk = useMutation({
    mutationFn: (action: "known" | "suspend" | "restore") =>
      vocabularyApi.bulkWords({ word_ids: [id], action }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: vocabularyWordsKey });
      void qc.invalidateQueries({ queryKey: ["vocabulary", "practice", "summary"] });
      void qc.invalidateQueries({ queryKey: wordDetailKey(id) });
    },
    onError: (e) => toast(getErrorMessage(e)),
  });

  // Deleting this one word never confirms — it defers instead: the request
  // waits a few seconds in `pendingDelete.ts` while the words list (where
  // this navigates to at once) shows "Removed · Undo" in its place. See
  // `VocabularyPage.tsx`'s `RemovedRow` for the other half of this.
  function handleDelete() {
    scheduleDelete(id);
    navigate("/vocabulary/words");
  }

  const leech = useMutation({
    mutationFn: (choice: LeechChoice) => vocabularyApi.leech(id, choice),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: wordDetailKey(id) });
      void qc.invalidateQueries({ queryKey: vocabularyWordsKey });
      // Same reason as the bulk actions below: a leech choice can move
      // this word out of `due_now` (set aside) or back into it (keep), so
      // the practice home's counts have to be told too.
      void qc.invalidateQueries({ queryKey: ["vocabulary", "practice", "summary"] });
    },
    onError: (e) => toast(getErrorMessage(e)),
  });

  if (isPending) return <WordSkeleton />;

  if (isError || !data) {
    return (
      <div className="mx-auto w-full max-w-2xl py-16 text-center">
        <p className="text-sm text-destructive">
          That word couldn&apos;t be found.
        </p>
        <Link
          to="/vocabulary/words"
          className="mt-3 inline-block text-sm text-primary hover:underline"
        >
          Back to your words
        </Link>
      </div>
    );
  }

  // The server nests the row under `word` (`SavedWordDetailOut`), so
  // everything below reads off `word`/`history` rather than `data`
  // directly -- a flat destructure keeps the JSX identical to the words
  // list's, which reads a bare `SavedWord`.
  const { word, history } = data;
  const meaning = wordHeadline(word);

  return (
    <div className="mx-auto w-full max-w-2xl pb-24 pt-2">
      <Link
        to="/vocabulary/words"
        className="inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        <ChevronLeft className="size-3.5" aria-hidden />
        Your words
      </Link>

      <header className="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <h1 className="text-2xl font-semibold text-foreground">{word.lemma}</h1>
        {word.pos && <span className="text-sm text-muted-foreground italic">{word.pos}</span>}
        <CefrTag level={word.sense_cefr || word.cefr_level} />
        <StatusChip status={word.status} />
      </header>

      {(meaning.uz || meaning.en) && (
        <p className="mt-2">
          <span className="text-base text-foreground">{meaning.uz}</span>
          {meaning.en && (
            <span className="ml-2 text-sm text-muted-foreground">{meaning.en}</span>
          )}
        </p>
      )}

      {word.sense_id && (
        <ReportTranslation senseId={word.sense_id} where="word_page" className="mt-1.5" />
      )}

      {word.status === "leech" && (
        <section className="mt-4 rounded-xl border border-attention/40 bg-attention/10 px-4 py-3">
          <p className="text-sm text-foreground">
            This word keeps coming back wrong. Choose what happens next.
          </p>
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={leech.isPending}
              onClick={() => leech.mutate("set_aside")}
            >
              {LEECH_LABEL.set_aside}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={leech.isPending}
              onClick={() => leech.mutate("see_context")}
            >
              {LEECH_LABEL.see_context}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={leech.isPending}
              onClick={() => leech.mutate("keep")}
            >
              {LEECH_LABEL.keep}
            </Button>
          </div>
        </section>
      )}

      {word.senses && word.senses.length > 1 && (
        <section className="mt-5" aria-labelledby="all-meanings">
          <h2 id="all-meanings" className="text-sm font-semibold text-foreground">
            All meanings
          </h2>
          <SenseList senses={word.senses} />
        </section>
      )}

      <section className="mt-5 grid grid-cols-2 gap-3">
        <DirectionState
          title="Passive · recognising and recalling"
          level={passiveLevelLabel(word.passive_level)}
          due={word.passive_due}
          stability={word.passive_stability}
          lapses={word.passive_lapses}
        />
        <DirectionState
          title="Active · producing"
          level={word.active_paused ? "Paused" : activeLevelLabel(word.active_level)}
          due={word.active_level ? word.active_due : null}
          stability={word.active_level ? word.active_stability : null}
          lapses={word.active_level ? word.active_lapses : null}
        />
      </section>

      <section className="mt-6">
        <h2 className="text-sm font-semibold text-foreground">
          {word.contexts.length} {word.contexts.length === 1 ? "context" : "contexts"}
        </h2>
        <ul className="mt-2 space-y-3">
          {word.contexts.map((ctx, i) => (
            <Context key={`${ctx.material_id}-${i}`} context={ctx} />
          ))}
        </ul>
      </section>

      {history.length > 0 && (
        <section className="mt-6">
          <h2 className="text-sm font-semibold text-foreground">Review history</h2>
          <ul className="mt-2 divide-y divide-border/60 rounded-xl border border-border">
            {history.map((turn, i) => (
              <li
                key={i}
                className="flex items-center justify-between gap-3 px-3 py-2 text-xs"
              >
                <span className="text-muted-foreground">{timeAgo(turn.reviewed_at)}</span>
                <span className="text-muted-foreground">
                  {turn.direction} · {turn.exercise_type}
                </span>
                <span className="min-w-0 flex-1 truncate text-right text-foreground/80">
                  {turn.given || "—"}
                </span>
                <span className="text-muted-foreground">{fmtClock(turn.elapsed_ms)}</span>
                <span className={cn("font-medium", RATING_TONE[turn.rating])}>
                  {RATING_LABEL[turn.rating]}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="mt-6 flex flex-wrap gap-1.5">
        {word.status !== "known" && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={bulk.isPending}
            onClick={() => bulk.mutate("known")}
          >
            {ACTION_LABEL.markKnown}
          </Button>
        )}
        {word.status !== "suspended" && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={bulk.isPending}
            onClick={() => bulk.mutate("suspend")}
          >
            Set aside
          </Button>
        )}
        {(word.status === "known" || word.status === "suspended") && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={bulk.isPending}
            onClick={() => bulk.mutate("restore")}
          >
            {ACTION_LABEL.returnToRotation}
          </Button>
        )}
        <Button type="button" variant="destructive" size="sm" onClick={handleDelete}>
          Delete
        </Button>
      </section>
    </div>
  );
}

/** The word's own meaning — see `VocabularyPage.tsx`'s `wordMeaning`, the
 *  same fallback repeated rather than shared, since one is read off a list
 *  row and this off the word half of a `WordDetail` and importing one from
 *  the other would tie two pages together for a few lines. `definition_en`/
 *  `meaning_uz` are read LIVE off the word's sense and lead; the rest is
 *  what a word saved before those fields existed falls back to. */
function wordHeadline(word: SavedWord): { en: string; uz: string } {
  if (word.definition_en || word.meaning_uz) {
    return { en: word.definition_en, uz: word.meaning_uz };
  }
  if (word.meaning_core_en || word.meaning_core_uz) {
    return { en: word.meaning_core_en, uz: word.meaning_core_uz };
  }
  const core = word.contexts.find((c) => c.meaning_core_en) ?? word.contexts[0];
  return {
    en: core?.meaning_core_en || core?.meaning_en || "",
    uz: core?.meaning_core_uz || core?.meaning_uz || "",
  };
}

/** One direction's card, in plain words rather than a wire token — level,
 *  next review, lapses, per the fixes brief's §8. `lapses` is `null` for the
 *  active side before it has started at all (there is nothing to have
 *  lapsed yet), printed differently from "0 lapses", which is a card that
 *  HAS started and simply never has. */
function DirectionState({
  title,
  level,
  due,
  stability,
  lapses,
}: {
  title: string;
  level: string;
  due: string | null;
  stability: number | null;
  lapses: number | null;
}) {
  return (
    <div className="rounded-xl border border-border px-3.5 py-3">
      <p className="text-xs text-muted-foreground">{title}</p>
      <p className="mt-1 text-sm font-medium text-foreground">{level}</p>
      {due && (
        <p className="mt-1 text-xs text-muted-foreground">Next review {timeUntil(due)}</p>
      )}
      {stability != null && (
        <p className="text-xs text-muted-foreground">
          {Math.round(stability)} {Math.round(stability) === 1 ? "day" : "days"} stability
        </p>
      )}
      {lapses != null && (
        <p className="text-xs text-muted-foreground">
          {lapses} {lapses === 1 ? "lapse" : "lapses"}
        </p>
      )}
    </div>
  );
}

/** One meeting: the sentence, its date, `Here:` only where the sense
 *  genuinely differs (see `meaning.ts`), and the way back to the passage —
 *  every context the fixes brief's §8 asks for, in the order a learner
 *  reads them. */
function Context({ context }: { context: SavedWord["contexts"][number] }) {
  const sense = meanings(context);
  return (
    <li className="rounded-lg border border-border/60 px-3.5 py-2.5">
      <div className="flex items-baseline justify-between gap-2">
        {context.example && (
          <p className="text-sm leading-relaxed text-foreground/90 italic">
            {context.example}
          </p>
        )}
        <span className="shrink-0 text-[0.7rem] text-muted-foreground">
          {timeAgo(context.created_at)}
        </span>
      </div>
      {sense.here && (
        <p className="mt-1.5 border-l-2 border-border pl-2">
          <span className="block text-sm text-foreground">
            <span className="text-muted-foreground">Here: </span>
            {sense.here.uz}
          </span>
          <span className="block text-xs text-muted-foreground">{sense.here.en}</span>
        </p>
      )}
      {context.material_title && (
        <Link
          to={`/reading/${context.material_id}`}
          className="mt-1.5 inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          <BookOpen className="size-3" aria-hidden />
          {context.material_title}
        </Link>
      )}
    </li>
  );
}

function WordSkeleton() {
  return (
    <SkeletonBlock
      label="Loading this word"
      className="mx-auto w-full max-w-2xl pb-24 pt-2"
    >
      <p className="text-xs">
        <Skeleton className="inline-block h-[0.8em] w-24" />
      </p>
      <h1 className="mt-2 text-2xl font-semibold">
        <Skeleton className="inline-block h-[0.8em] w-32" />
      </h1>
      <p className="mt-2 text-base">
        <Skeleton className="inline-block h-[0.8em] w-64 max-w-full" />
      </p>
      <div className="mt-5 grid grid-cols-2 gap-3">
        <Skeleton className="h-20 rounded-xl" />
        <Skeleton className="h-20 rounded-xl" />
      </div>
    </SkeletonBlock>
  );
}

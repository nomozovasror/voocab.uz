import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { HeaderGround } from "@/components/layout/HeaderGround";
import { useAttempt, useTakeMaterial } from "@/features/paper/queries";
import { Q_ANCHOR } from "@/features/paper/take-focus";
import { sorted } from "@/features/paper/numbering";
import {
  passageQuote,
  reviewRows,
  tallyMistakes,
} from "@/features/paper/review";
import { ReviewItem } from "@/features/paper/components/ReviewItem";
import {
  ReviewFilter,
  type ReviewScope,
} from "@/features/paper/components/ReviewFilter";
import { ReviewMistakes } from "@/features/paper/components/ReviewMistakes";
import { ReviewScore } from "@/features/paper/components/ReviewScore";
import {
  PassagePane,
  paragraphId,
} from "@/features/reading/components/PassagePane";
import { loadHighlights } from "@/features/reading/highlights";
import { ReviewVocabulary } from "@/features/vocabulary/components/ReviewVocabulary";
import type { QuoteSource } from "@/features/paper/review";
import type { AttemptResult } from "@/features/paper/types";

/**
 * A marked reading paper, read back.
 *
 * Every rule of the listening review holds here and is the same code: the
 * paper is not redrawn, one quoted line stands for where the question was,
 * "mistakes only" is the default and locks itself to "All" on a clean sheet,
 * and the score is given context rather than left as a percentage.
 *
 * What changes is what the quote is quoting. Listening's is the transcript
 * across the moment the answer is said, which the server sends with the
 * attempt. Reading's is the sentence in the passage the answer is in, found
 * HERE — the passage came down with the paper — and found by the same text
 * match, under the same rule: an answer that appears twice is not quoted at
 * all, because a quote pointing at the wrong occurrence teaches a candidate
 * they misread something they never read.
 *
 * And there is no player. The listening review's play button covers the
 * sentence on screen; here the sentence IS on screen, which is the whole of
 * what the button was for.
 */
export default function ReadingResultsPage() {
  const { attemptId } = useParams<{ attemptId: string }>();
  const location = useLocation();
  const seed = (location.state as { result?: AttemptResult } | null)?.result;
  const { data, isLoading, isError } = useAttempt("reading", attemptId, seed);
  // Non-blocking: the review stands without it — an attempt outlives the
  // material's visibility — and what it adds is where each question sat and
  // the passage to quote from.
  const { data: material } = useTakeMaterial("reading", data?.material_id);

  const quote = useCallback(
    (result: Parameters<typeof passageQuote>[1]) =>
      passageQuote(material, result),
    [material],
  );

  const rows = useMemo(
    () => reviewRows(data?.results ?? [], material, quote),
    [data, material, quote],
  );
  const mistakes = useMemo(() => tallyMistakes(data?.results ?? []), [data]);
  const wrong = useMemo(() => rows.filter((r) => !r.result.is_correct), [rows]);

  // What they marked while they were reading it. Read-only here: the marks
  // are a record of how the paper was worked, and the value of seeing them
  // again is being able to ask whether the answer really was where they
  // thought it was. Keyed by material, so they are waiting on this page
  // even though the take session was cleared by the submit that reached it.
  const marks = useMemo(
    () => (data?.material_id ? loadHighlights(data.material_id) : []),
    [data?.material_id],
  );

  // The words they spent a look-up on, from the ATTEMPT rather than from
  // the browser. `lookups.ts` remembers across sittings on purpose — a word
  // this reader has already been told the meaning of is free for ever — so
  // on a retake its list holds words from a sitting that is over, and this
  // page is about one sitting. Empty for an attempt made before the column
  // existed, which reads correctly as "nothing to separate out".
  const looked = useMemo(() => data?.looked_up ?? [], [data?.looked_up]);

  const [chosen, setChosen] = useState<ReviewScope>("mistakes");
  // The passages are closed until somebody wants them, and "Paragraph C"
  // is somebody wanting them. Controlled rather than a bare <details>, or
  // the link would scroll to a paragraph inside a panel that is shut.
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState<{
    where: QuoteSource;
    nth: number;
  } | null>(null);

  const goToParagraph = useCallback((where: QuoteSource) => {
    setOpen(true);
    // Parked, not scrolled to. A closed <details> does not lay its contents
    // out, so the paragraph has no position until React has committed the
    // open panel — and a `requestAnimationFrame` is not that moment: it can
    // run before the commit, which is why the first version of this opened
    // the panel and left the page exactly where it was. The counter is what
    // makes clicking the same paragraph twice work; the value alone would
    // not change, so the effect would not run again.
    setHighlight((prev) => ({ where, nth: (prev?.nth ?? 0) + 1 }));
  }, []);

  useEffect(() => {
    if (!highlight || !open) return;
    document
      .getElementById(
        paragraphId(highlight.where.partId, highlight.where.label),
      )
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [highlight, open]);
  const scope: ReviewScope = wrong.length === 0 ? "all" : chosen;
  const shown = scope === "mistakes" ? wrong : rows;

  /** Jumping to a question the filter is hiding has to open the view holding
   *  it, or the click lands on nothing and the page appears not to work.
   *
   *  Two steps rather than one, exactly as the listening review does it:
   *  switching the view and scrolling in the same breath scrolls to a row
   *  React has not rendered yet. So the id is parked and the effect below
   *  runs it once the list it belongs to is on the page. Parked in STATE and
   *  not in a ref — a ref nothing reads is a jump that silently never
   *  happens, which is what this was. */
  const [pending, setPending] = useState<string | null>(null);
  useEffect(() => {
    if (pending == null) return;
    scrollToQuestion(pending);
    setPending(null);
  }, [pending]);

  const jumpTo = useCallback(
    (questionId: string) => {
      const row = rows.find((r) => r.result.question_id === questionId);
      if (row && row.result.is_correct && scope === "mistakes") {
        setChosen("all");
        setPending(questionId);
        return;
      }
      scrollToQuestion(questionId);
    },
    [rows, scope],
  );

  const nextMistake = useCallback(() => {
    const first = wrong[0];
    if (first) scrollToQuestion(first.result.question_id);
  }, [wrong]);

  if (isLoading) return <ResultsSkeleton />;
  if (isError || !data) {
    return (
      <div className="mx-auto max-w-3xl space-y-4 py-10">
        <p className="text-sm text-destructive">
          This result couldn&apos;t be loaded.
        </p>
        <Link
          to="/reading"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          Back to reading
        </Link>
      </div>
    );
  }

  const passages = material ? sorted(material.parts) : [];

  return (
    <div className="mx-auto max-w-3xl pb-24">
      <HeaderGround />

      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 pt-2 pb-3">
        <Link
          to="/reading"
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" />
          Reading
        </Link>
        <h1 className="min-w-0 flex-1 truncate text-2xl font-semibold text-foreground">
          {data.material_title}
        </h1>
        {/* Which paper this was, where the title used to carry it. */}
        {data.material_reference &&
          data.material_reference !== data.material_title && (
            <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
              {data.material_reference}
            </span>
          )}
      </div>

      <ReviewScore data={data} rows={rows} onJump={jumpTo} />

      {wrong.length === 0 && <CleanSheet />}

      <div className="mt-6 mb-1">
        <ReviewFilter
          scope={scope}
          onScope={setChosen}
          mistakes={wrong.length}
          total={rows.length}
          onNextMistake={wrong.length > 1 ? nextMistake : undefined}
        />
      </div>

      <div>
        {shown.map((row) => (
          <ReviewItem
            key={row.result.question_id}
            row={row}
            anchor={{ [Q_ANCHOR]: row.result.question_id }}
            // No onPlay: a passage has nothing to play, and ReviewItem draws
            // the button only where one is handed to it. What reading has
            // instead is the paragraph, and the same rule applies — the
            // control exists only where there is one to go to.
            onGoTo={goToParagraph}
          />
        ))}
      </div>

      <ReviewMistakes groups={mistakes} skill="reading" className="mt-10" />

      {data.material_id && (
        <ReviewVocabulary
          materialId={data.material_id}
          lookedUp={looked}
          className="mt-6"
        />
      )}

      {/* The passages themselves, at the bottom and collapsed.
      
          Not beside the questions the way the take screen has them: sitting
          the paper, the passage is what you are working FROM, and reading it
          back, the four lines you got wrong are. But it has to be reachable —
          a candidate checking whether "not given" really was not given needs
          the text, and sending them back to the take screen to find it would
          start a second attempt. */}
      {passages.length > 0 && (
        <details
          open={open}
          onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
          className="mt-10 rounded-xl border border-border"
        >
          <summary className="cursor-pointer px-5 py-3 text-sm text-muted-foreground transition-colors hover:text-foreground">
            Read the {passages.length === 1 ? "passage" : "passages"} again
          </summary>
          <div className="space-y-10 border-t border-border px-5 py-5">
            {passages.map((part, index) =>
              part.passage ? (
                <PassagePane
                  key={part.id}
                  partId={part.id}
                  title={part.title || `Reading Passage ${index + 1}`}
                  passage={part.passage}
                  highlight={
                    highlight?.where.partId === part.id
                      ? highlight.where.label
                      : null
                  }
                  highlights={marks}
                  className="max-w-none"
                />
              ) : null,
            )}
          </div>
        </details>
      )}
    </div>
  );
}

function scrollToQuestion(questionId: string) {
  document
    .querySelector(`[${Q_ANCHOR}="${questionId}"]`)
    ?.scrollIntoView({ behavior: "smooth", block: "center" });
}

/** Nothing went wrong, so there is nothing to break down. */
function CleanSheet() {
  return (
    <p className="mt-3 rounded-xl border border-correct/20 bg-correct/5 px-5 py-4 text-sm text-correct">
      Every answer right. Nothing to go back over — the questions are below if
      you want to check your working.
    </p>
  );
}

/** The page's shape, held open while it loads. Built from the real
 *  components' own class strings — `frontend/CLAUDE.md`. */
function ResultsSkeleton() {
  return (
    <SkeletonBlock label="Loading result" className="mx-auto max-w-3xl pb-24">
      <HeaderGround />
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 pt-2 pb-3">
        <Link
          to="/reading"
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" />
          Reading
        </Link>
        <h1 className="min-w-0 flex-1 text-2xl font-semibold">
          <Skeleton className="inline-block h-[0.8em] w-72 max-w-full" />
        </h1>
      </div>
      <Skeleton className="h-32 w-full rounded-xl" />
      <div className="mt-6 mb-1 h-8" />
      {[0, 1, 2].map((row) => (
        <div key={row} className="border-t border-border py-4">
          <p className="text-sm">
            <Skeleton className="inline-block h-[0.8em] w-2/3" />
          </p>
          <p className="mt-2 ml-9 text-base">
            <Skeleton className="inline-block h-[0.8em] w-40" />
          </p>
        </div>
      ))}
    </SkeletonBlock>
  );
}

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, RotateCcw } from "lucide-react";
import { cn } from "@/lib/utils";
import { useMediaQuery } from "@/hooks/use-media-query";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { HeaderGround } from "@/components/layout/HeaderGround";
import { HeaderSlot, useHeaderTask } from "@/components/layout/header-task";
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
import { SplitPanes } from "@/features/reading/components/SplitPanes";
import { ReviewLayers } from "@/features/reading/components/ReviewLayers";
import { loadHighlights } from "@/features/reading/highlights";
import {
  evidenceOverlays,
  wordOverlays,
  type LayerId,
  type Overlay,
} from "@/features/reading/layers";
import { ReviewVocabulary } from "@/features/vocabulary/components/ReviewVocabulary";
import { vocabularyApi, vocabularyKey } from "@/features/vocabulary/api";
import type { QuoteSource } from "@/features/paper/review";
import type { AttemptResult } from "@/features/paper/types";

/**
 * A marked reading paper, read back — beside the passage it was answered
 * from.
 *
 * ## The passage is the page
 *
 * The version this replaced put the text last and collapsed. It opened on a
 * score, listed the wrong answers, and then ran a hundred and one vocabulary
 * entries down a column that did not end — and the nine hundred words the
 * whole hour had been spent inside were behind a `<details>` at the bottom
 * called "Read the passage again".
 *
 * That is the wrong way round. Everything a review has to say is a statement
 * ABOUT the passage: this is where the answer was, this is the word you did
 * not know, this is the one you saved a fortnight ago and have just met
 * again. Each of those beside the text is a lesson. Each of them in a list
 * on its own is a row of data, and ten screens of rows is a page nobody
 * finishes.
 *
 * So the review is the take screen's own shape: passage on the left,
 * analysis on the right, two scrolls and a divider the reader can move. They
 * do not have to learn it — they were in it twenty minutes ago — and what
 * changes is only what is written on the passage. See
 * `features/reading/layers.ts`.
 *
 * ## Both panes point at each other
 *
 * Pointing at a mistake lights the sentence its answer was in; pointing at
 * that sentence lights the mistake. Same for a word and its entry. The link
 * is what turns two lists into one explanation, and it works in both
 * directions because a reader who found it going one way should not have to
 * discover that the other way exists.
 *
 * Pressing rather than pointing SCROLLS, which is a different and stronger
 * act — the passage is long and the sentence is usually off-screen. It
 * happens in two steps for the reason written all over this feature: the
 * layer holding that mark may be off, and switching a layer on and scrolling
 * into it in the same breath scrolls to an element React has not drawn yet.
 *
 * ## What the page does without any of it
 *
 * An attempt outlives its material's visibility, so `material` can be
 * missing: there is then no passage, no layers and no two panes, and the
 * analysis becomes the whole page. A material the vocabulary extraction
 * never reached has no word list and no Vocabulary tab. A paper with no
 * evidence has no marking and no jump links, and the mistakes still read
 * perfectly well without them — the answer and what was put instead is the
 * part that was always there.
 */
export default function ReadingResultsPage() {
  const { attemptId } = useParams<{ attemptId: string }>();
  const location = useLocation();
  const seed = (location.state as { result?: AttemptResult } | null)?.result;
  const { data, isLoading, isError } = useAttempt("reading", attemptId, seed);
  // Non-blocking: the review stands without it — an attempt outlives the
  // material's visibility — and what it adds is where each question sat and
  // the passage itself.
  const { data: material } = useTakeMaterial("reading", data?.material_id);

  const passages = useMemo(
    () => (material ? sorted(material.parts) : []),
    [material],
  );

  // The islands are this page's for as long as there is a PASSAGE in them:
  // the way out, the layer switch and the way back in. Same decision as the
  // take screen, and for the same reason — that page fills the window, so
  // there is nowhere else for its chrome to be. See
  // `components/layout/CLAUDE.md`.
  //
  // Conditional, because this page has an arrangement the take screen does
  // not: an attempt outlives its material's visibility, and with no passage
  // there are no layers, no two panes and nothing to put in the middle
  // island. Claiming it anyway would take the app's own navigation away and
  // hand back three empty pills. False while the material is still coming,
  // which is also right — the skeleton draws no islands either.
  useHeaderTask(passages.length > 0);

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

  // The passage's vocabulary, fetched HERE rather than inside the list that
  // prints it: the passage on the left is marked from the same rows, and two
  // components asking the cache the same question is one of them holding a
  // copy that stops agreeing with the other the first time somebody saves a
  // word.
  const { data: vocabulary } = useQuery({
    queryKey: vocabularyKey(data?.material_id ?? ""),
    queryFn: () => vocabularyApi.list(data!.material_id),
    enabled: Boolean(data?.material_id),
    // Refused with a 403 until the paper is submitted, and there is no
    // retrying past that: it is an answer, not a failure.
    retry: false,
  });

  // Which words were on the learner's list BEFORE this page opened.
  //
  // Taken once, and deliberately not kept up to date. "Saved earlier" is a
  // claim about a different day — you met this word a fortnight ago and here
  // it is again — and a badge that appeared on a word two seconds after it
  // was saved would be the page congratulating somebody on remembering what
  // they had just done.
  const [savedEarlier, setSavedEarlier] = useState<Set<string> | null>(null);
  useEffect(() => {
    if (!vocabulary || savedEarlier) return;
    setSavedEarlier(
      new Set(vocabulary.entries.filter((e) => e.saved).map((e) => e.lemma)),
    );
  }, [vocabulary, savedEarlier]);

  const saved = useMemo(
    () =>
      new Set(vocabulary?.entries.filter((e) => e.saved).map((e) => e.lemma)),
    [vocabulary],
  );

  // --- What is written on the passage --------------------------------------

  /** Every layer's marks, built once. Built for ALL of them rather than for
   *  the one that is on, because the toggle has to know which layers have
   *  anything in them before the reader presses anything — a button that
   *  turns on an empty layer is a button that appears not to work. */
  const layers = useMemo(() => {
    const evidence = evidenceOverlays(data?.results ?? []);
    const words = vocabulary
      ? wordOverlays(vocabulary.entries, (lemma) => saved.has(lemma))
      : [];
    return {
      mistakes: evidence,
      vocabulary: words,
      saved: words.filter((o) => o.tone === "saved"),
      marks: [] as Overlay[],
    };
  }, [data?.results, vocabulary, saved]);

  const counts: Record<LayerId, number> = {
    mistakes: layers.mistakes.length,
    vocabulary: layers.vocabulary.length,
    saved: layers.saved.length,
    marks: marks.length,
  };

  const [chosenLayer, setChosenLayer] = useState<LayerId>("mistakes");
  // The layer that is actually on. A chosen layer with nothing in it is a
  // passage with no marking at all, which is the take screen again — so the
  // page falls through to the first that has something. That is also what
  // decides the opening state on a clean sheet, with no second rule for it:
  // no mistakes, so the marking opens on the vocabulary.
  const layer: LayerId =
    counts[chosenLayer] > 0
      ? chosenLayer
      : ((["mistakes", "vocabulary", "saved", "marks"] as LayerId[]).find(
          (id) => counts[id] > 0,
        ) ?? "mistakes");

  /** What the pointer is on, wherever it is. One key, shared by both panes:
   *  a question id in the mistakes layer, a lemma in the other two. */
  const [lit, setLit] = useState<string | null>(null);

  // --- The two tabs --------------------------------------------------------

  const [chosenTab, setChosenTab] = useState<"mistakes" | "vocabulary">(
    "mistakes",
  );

  /** Pressing a tab takes the passage's marking with it.
   *
   *  The tab and the layer are the same question asked twice — *what did I
   *  get wrong* / *what is worth learning here* — and a page that answered
   *  it one way on the right and the other way on the left would be two
   *  half-answers side by side. Reading the vocabulary with the mistakes
   *  still marked is the list talking about words the passage is not
   *  pointing at.
   *
   *  One way only. The layer toggle does NOT move the tab back, because the
   *  layers are finer than the tabs — Saved and My marks have no tab of
   *  their own — and a control that silently undid itself from the other
   *  side would make the four buttons feel like two. */
  const showTab = useCallback((next: "mistakes" | "vocabulary") => {
    setChosenTab(next);
    setChosenLayer(next);
  }, []);
  const hasWords = (vocabulary?.total ?? 0) > 0;
  // Same fall-through as the layer, and the same two states it covers: a
  // clean sheet opens on the vocabulary, and a passage the extraction never
  // reached has no vocabulary tab to open on.
  const tab =
    chosenTab === "vocabulary" && !hasWords
      ? "mistakes"
      : chosenTab === "mistakes" && wrong.length === 0 && hasWords
        ? "vocabulary"
        : chosenTab;

  const [chosen, setChosen] = useState<ReviewScope>("mistakes");
  const scope: ReviewScope = wrong.length === 0 ? "all" : chosen;
  const shown = scope === "mistakes" ? wrong : rows;

  // --- Going to the place a row is about -----------------------------------

  /** A mark to scroll to once it is on the page.
   *
   *  Parked in STATE, not in a ref. Pressing "the answer is here" may have
   *  to switch the layer on first, and switching it on and scrolling in the
   *  same breath scrolls to an element React has not drawn yet — the same
   *  two-step the old page needed for a closed `<details>`. A ref nothing
   *  reads is a jump that silently never happens, which is what that was. */
  const [goingTo, setGoingTo] = useState<{ key: string; nth: number } | null>(
    null,
  );
  useEffect(() => {
    if (!goingTo) return;
    const found = document.querySelector(
      `[data-overlay="${goingTo.key}"], [data-overlay-also~="${goingTo.key}"]`,
    );
    found?.scrollIntoView({ behavior: "smooth", block: "center" });
    setLit(goingTo.key);
  }, [goingTo, layer]);

  const goToEvidence = useCallback((questionId: string) => {
    setChosenLayer("mistakes");
    // The counter is what makes pressing the same link twice work: the value
    // alone would not change, so the effect would not run again.
    setGoingTo((was) => ({ key: questionId, nth: (was?.nth ?? 0) + 1 }));
  }, []);

  /** The older route to the same place, for a paper with no evidence.
   *
   *  `passageQuote` finds the answer in the text by matching the string, and
   *  where the book letters its paragraphs the row can still offer to go to
   *  one. It says less — a paragraph rather than a sentence — and it is
   *  still the difference between a reader who can check whether NOT GIVEN
   *  really was not given and one who cannot. */
  const goToParagraph = useCallback((where: QuoteSource) => {
    document
      .getElementById(paragraphId(where.partId, where.label))
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);

  /** Jumping to a question the filter is hiding has to open the view holding
   *  it, or the click lands on nothing and the page appears not to work.
   *
   *  Two steps rather than one, exactly as the listening review does it:
   *  switching the view and scrolling in the same breath scrolls to a row
   *  React has not rendered yet. */
  const [pending, setPending] = useState<string | null>(null);
  useEffect(() => {
    if (pending == null) return;
    scrollToQuestion(pending);
    setPending(null);
  }, [pending]);

  const jumpTo = useCallback(
    (questionId: string) => {
      const row = rows.find((r) => r.result.question_id === questionId);
      const hidden = row?.result.is_correct && scope === "mistakes";
      if (tab !== "mistakes" || hidden) {
        showTab("mistakes");
        if (hidden) setChosen("all");
        setPending(questionId);
        return;
      }
      scrollToQuestion(questionId);
    },
    [rows, scope, tab, showTab],
  );

  const nextMistake = useCallback(() => {
    const first = wrong[0];
    if (first) scrollToQuestion(first.result.question_id);
  }, [wrong]);

  // --- How tall the panes are ----------------------------------------------
  //
  // Measured from where they actually start rather than computed from the
  // viewport and a guess at everything above them — the take screen's own
  // note, and the same failure it avoids: a container taller than the space
  // left makes the PAGE scroll, which is the one thing two panes exist to
  // stop.
  const paneRef = useRef<HTMLDivElement | null>(null);
  const [paneH, setPaneH] = useState<number | null>(null);
  useEffect(() => {
    const el = paneRef.current;
    if (!el) return;
    const measure = () => {
      const top = el.getBoundingClientRect().top + window.scrollY;
      setPaneH(Math.max(240, window.innerHeight - top));
    };
    measure();
    window.addEventListener("resize", measure);
    if (typeof ResizeObserver === "undefined") {
      return () => window.removeEventListener("resize", measure);
    }
    const observer = new ResizeObserver(measure);
    if (el.parentElement) observer.observe(el.parentElement);
    return () => {
      window.removeEventListener("resize", measure);
      observer.disconnect();
    };
  }, [data, material]);

  // Two panes need a width to be worth having. Below this the same content
  // is a pair of tabs — see SplitPanes.
  const wide = useMediaQuery("(min-width: 64rem)");

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

  const analysis = (
    <div className={PANE_TOP}>
      <ReviewScore data={data} rows={rows} onJump={jumpTo} />

      {wrong.length === 0 && <CleanSheet />}

      {/* Two tabs, and only where there are two things to hold. A single
          tab is a heading that has been made to look pressable. */}
      {hasWords && (
        <div
          role="tablist"
          aria-label="Mistakes or vocabulary"
          className="mt-5 flex gap-1"
        >
          <Tab
            on={tab === "mistakes"}
            onClick={() => showTab("mistakes")}
            label="Mistakes"
            count={wrong.length}
          />
          <Tab
            on={tab === "vocabulary"}
            onClick={() => showTab("vocabulary")}
            label="Vocabulary"
            count={vocabulary?.total ?? 0}
          />
        </div>
      )}

      {tab === "mistakes" ? (
        <>
          <div className="mt-4 mb-1">
            <ReviewFilter
              scope={scope}
              onScope={setChosen}
              mistakes={wrong.length}
              total={rows.length}
              onNextMistake={wrong.length > 1 ? nextMistake : undefined}
            />
          </div>

          <div>
            {shown.map((row) => {
              const spans = row.result.evidence ?? [];
              return (
                <ReviewItem
                  key={row.result.question_id}
                  row={row}
                  anchor={{ [Q_ANCHOR]: row.result.question_id }}
                  // No onPlay: a passage has nothing to play, and ReviewItem
                  // draws the button only where one is handed to it.
                  evidence={
                    spans.length > 0
                      ? {
                          label: evidenceLabel(passages, spans[0]),
                          onGoTo: () => goToEvidence(row.result.question_id),
                        }
                      : undefined
                  }
                  // The older route, for a paper the extraction never
                  // reached: the quote's own paragraph. Withheld where the
                  // evidence is known, or the row would offer two ways to
                  // go to two different places.
                  onGoTo={spans.length > 0 ? undefined : goToParagraph}
                  onPoint={
                    spans.length > 0
                      ? (on) => setLit(on ? row.result.question_id : null)
                      : undefined
                  }
                  lit={lit === row.result.question_id}
                />
              );
            })}
          </div>

          <ReviewMistakes groups={mistakes} skill="reading" className="mt-10" />
        </>
      ) : (
        vocabulary && (
          <ReviewVocabulary
            className="mt-4"
            materialId={data.material_id}
            data={vocabulary}
            lookedUp={looked}
            savedEarlier={savedEarlier ?? new Set()}
            lit={lit}
            onPoint={setLit}
          />
        )
      )}
    </div>
  );

  // No passage to put beside it. An attempt outlives the material's
  // visibility, and a review of a paper withdrawn since still has a score,
  // its mistakes and its vocabulary — it just has nothing to mark.
  if (passages.length === 0) {
    return (
      <div className="mx-auto max-w-3xl pb-24">
        <HeaderGround />
        <Crumb
          title={data.material_title}
          reference={data.material_reference}
        />
        {analysis}
      </div>
    );
  }

  const overlays = layers[layer];

  return (
    // The page itself does not scroll: the panes do. Full-bleed and pulled up
    // under the header exactly as the take screen is, so the paper reads at
    // the same size in the same place it was answered in — see the long note
    // on `ReadingTakePage`, which this deliberately matches rather than
    // reasoning about again.
    <div className="-mt-23 -mb-8 mx-[calc(50%-50vw)] flex w-auto flex-col overflow-hidden px-4 sm:px-6">
      <HeaderSlot side="left">
        <Link
          to="/reading"
          className="inline-flex items-center gap-1.5 rounded-full px-1 text-sm text-foreground/70 transition-colors duration-fast hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          <ArrowLeft className="size-4" aria-hidden />
          Reading
        </Link>
      </HeaderSlot>

      <HeaderSlot side="centre">
        <ReviewLayers layer={layer} onLayer={setChosenLayer} counts={counts} />
      </HeaderSlot>

      {/* The one thing somebody does after reading a review, in the place
          the take screen's clock was. Amber, like every other "this is the
          action" here. */}
      <HeaderSlot side="right">
        <Link
          to={`/reading/${data.material_id}`}
          className="mr-1 inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-sm text-primary transition-colors duration-fast hover:bg-primary/10 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          <RotateCcw className="size-3.5" aria-hidden />
          Take it again
        </Link>
      </HeaderSlot>

      <SplitPanes
        ref={paneRef}
        height={paneH}
        split={wide}
        leftLabel={passages.length > 1 ? "Passages" : "Passage"}
        rightLabel="Your result"
        left={
          <div className={PANE_TOP}>
            <div className="mb-5 text-center">
              <h1 className="text-[1.35em] leading-snug font-semibold text-foreground">
                {data.material_title}
              </h1>
              {data.material_reference &&
                data.material_reference !== data.material_title && (
                  <p className="mt-1 text-[0.8em] tabular-nums text-muted-foreground">
                    {data.material_reference}
                  </p>
                )}
            </div>
            <div className="space-y-10">
              {passages.map((part, index) =>
                part.passage ? (
                  <PassagePane
                    key={part.id}
                    partId={part.id}
                    title={part.title || `Reading Passage ${index + 1}`}
                    showTitle={passages.length > 1}
                    passage={part.passage}
                    // The reader's own marks are handed over as MARKS, not
                    // as overlays, so they keep the three colours they were
                    // made in — see `layers.ts`. Every other layer is an
                    // overlay the review drew.
                    highlights={layer === "marks" ? marks : undefined}
                    overlays={layer === "marks" ? undefined : overlays}
                    lit={lit}
                    onPoint={setLit}
                    className="max-w-none"
                  />
                ) : null,
              )}
            </div>
          </div>
        }
        right={analysis}
      />
    </div>
  );
}

/** What a pane leaves above its first line, and below its last — the take
 *  screen's own two measurements, for a layout that is the take screen's.
 *  The islands end at 60px and content that began there touched them. */
const PANE_TOP = "pt-19 pb-6";

/** Where the evidence is, said in the fewest words that are true.
 *
 *  "Paragraph C" where the book letters its paragraphs, because that is what
 *  the paper itself calls the place and two of Reading's tasks are answered
 *  by naming one. Most passages carry no letters at all, and inventing one
 *  from the position would name a paragraph no question can — so those say
 *  what the link DOES instead, which is the honest half of the same
 *  sentence. */
function evidenceLabel(
  passages: {
    id: string;
    passage?: { paragraphs: { label: string | null }[] } | null;
  }[],
  span: { part_id: string; paragraph_index: number },
): string {
  const part = passages.find((one) => one.id === span.part_id);
  const label = part?.passage?.paragraphs[span.paragraph_index]?.label;
  return label ? `The answer is in paragraph ${label}` : "Show me where it was";
}

function Tab({
  on,
  onClick,
  label,
  count,
}: {
  on: boolean;
  onClick: () => void;
  label: string;
  count: number;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={on}
      onClick={onClick}
      className={cn(
        "rounded-full px-3.5 py-1.5 text-sm transition-colors duration-fast focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
        on
          ? "bg-primary/15 text-primary"
          : "bg-surface-sunken text-muted-foreground hover:text-foreground",
      )}
    >
      {label}
      <span className="ml-2 tabular-nums opacity-60">{count}</span>
    </button>
  );
}

/** The crumb and title, for the one arrangement that has no passage over
 *  which to print them. */
function Crumb({
  title,
  reference,
}: {
  title: string;
  reference?: string | null;
}) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 pt-2 pb-3">
      <Link
        to="/reading"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" />
        Reading
      </Link>
      <h1 className="min-w-0 flex-1 truncate text-2xl font-semibold text-foreground">
        {title}
      </h1>
      {reference && reference !== title && (
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
          {reference}
        </span>
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
      Every answer right. Nothing to go back over — what the passage is worth
      learning is beside it.
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

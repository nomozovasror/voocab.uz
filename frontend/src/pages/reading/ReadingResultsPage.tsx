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
  numberWidth,
  passageQuote,
  reviewRows,
  reviewRuns,
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
import { ReviewMarks } from "@/features/reading/components/ReviewMarks";
import { loadHighlights } from "@/features/reading/highlights";
import {
  evidenceOverlays,
  wordOverlays,
  writtenDistractors,
  type LayerId,
  type Overlay,
} from "@/features/reading/layers";
import { ReviewVocabulary } from "@/features/vocabulary/components/ReviewVocabulary";
import { vocabularyApi, vocabularyKey } from "@/features/vocabulary/api";
import type { QuoteSource, ReviewRow } from "@/features/paper/review";
import { isFixedChoice, type AttemptResult } from "@/features/paper/types";

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
    const results = data?.results ?? [];
    // Every paragraph of the paper, flattened and carrying its part —
    // what a written answer is searched for in. Built here rather than
    // inside the search so three hundred questions do not each rebuild it.
    const prose = passages.flatMap((part) =>
      (part.passage?.paragraphs ?? []).map((one, index) => ({
        partId: part.id,
        index,
        text: one.text,
      })),
    );
    const answers = evidenceOverlays(results);
    const evidence = [
      ...answers,
      ...writtenDistractors(results, prose, answers),
    ];
    const words = vocabulary
      ? wordOverlays(vocabulary.entries, (lemma) => saved.has(lemma))
      : [];
    return {
      answers: evidence,
      vocabulary: words,
      saved: words.filter((o) => o.tone === "saved"),
      marks: [] as Overlay[],
    };
  }, [data?.results, vocabulary, saved, passages]);

  /** Every question the answers layer marks at all, in any colour.
   *
   *  What the corner marker is offered off, rather than the evidence: a NOT
   *  GIVEN statement has no evidence by definition and is nonetheless the
   *  one most worth going to look at, because what it has instead is the
   *  sentence that made somebody answer otherwise. */
  const marked = useMemo(
    () => new Set(layers.answers.map((one) => one.key)),
    [layers],
  );

  const counts: Record<LayerId, number> = {
    // How many QUESTIONS the layer marks, not how many marks it draws: a
    // question can be decided in two places, and "Answers 17" beside a paper
    // of thirteen is a count of something nobody asked about.
    answers: new Set(layers.answers.map((o) => o.key)).size,
    vocabulary: layers.vocabulary.length,
    saved: layers.saved.length,
    marks: marks.length,
  };

  const [chosenLayer, setChosenLayer] = useState<LayerId>("answers");
  // The layer that is actually on. A chosen layer with nothing in it is a
  // passage with no marking at all, which is the take screen again — so the
  // page falls through to the first that has something. That is also what
  // decides the opening state on a clean sheet, with no second rule for it:
  // no mistakes, so the marking opens on the vocabulary.
  const layer: LayerId =
    counts[chosenLayer] > 0
      ? chosenLayer
      : ((["answers", "vocabulary", "saved", "marks"] as LayerId[]).find(
          (id) => counts[id] > 0,
        ) ?? "answers");

  /** What the pointer is on, wherever it is. One key, shared by both panes:
   *  a question id in the mistakes layer, a lemma in the other two. */
  const [lit, setLit] = useState<string | null>(null);

  // --- The analysis beside it ----------------------------------------------
  //
  // There is no second control. The layer in the header decides both what is
  // marked on the passage and what is listed beside it, because they are the
  // same question — *how did the paper go* / *what is worth learning here* —
  // and asking it twice, in two places, in the same two words, left a reader
  // working out which of them to press.

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
    // The FIRST of this question's marks in the passage, which is the one
    // higher up the page — for a wrong answer that is usually the sentence
    // they were pulled by rather than the one that held the answer, and
    // landing on what they read before what they should have read is the
    // order the explanation is in.
    const found = document.querySelector(
      `[data-overlay="${goingTo.key}"], [data-overlay-also~="${goingTo.key}"]`,
    );
    found?.scrollIntoView({ behavior: "smooth", block: "center" });
    setLit(goingTo.key);
  }, [goingTo, layer]);

  const goToEvidence = useCallback((questionId: string) => {
    setChosenLayer("answers");
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
      if (layer !== "answers" || hidden) {
        setChosenLayer("answers");
        if (hidden) setChosen("all");
        setPending(questionId);
        return;
      }
      scrollToQuestion(questionId);
    },
    [rows, scope, layer],
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
    // `px-3` is not decoration: the rows inside reach OUT by the same three
    // to draw their hover state full-bleed, and without the gutter to reach
    // into they hung past the pane's right edge and gave the answers their
    // own horizontal scrollbar. A pane that scrolls sideways on a page built
    // out of two vertical scrollers reads as broken.
    <div className={cn(PANE_TOP, "px-3")}>
      <ReviewScore data={data} rows={rows} onJump={jumpTo} />

      {wrong.length === 0 && <CleanSheet />}

      {layer === "answers" && (
        <>
          <div className="mt-5 mb-1">
            <ReviewFilter
              scope={scope}
              onScope={setChosen}
              mistakes={wrong.length}
              total={rows.length}
              onNextMistake={wrong.length > 1 ? nextMistake : undefined}
            />
          </div>

          {/* Under what each run of questions IS. A paper is four or five
              TASKS rather than forty questions, and the task is the thing
              somebody is good or bad at — "I lose matching headings" is a
              sentence a candidate can act on.

              `--q-number` is set once for the whole list: the rows are
              separate grids and would otherwise each guess at how much room
              a question number needs. */}
          <div
            style={{ "--q-number": numberWidth(rows) } as React.CSSProperties}
          >
            {reviewRuns(shown).map((run, at) => (
              <div key={at}>
                {run.heading && (
                  // A rule that runs THROUGH the name, the way a fieldset
                  // legend sits in its own border: a short lead-in, the
                  // task, then the line carrying on to the edge.
                  //
                  // The words alone were not enough to say a different task
                  // had started — they sat between two rows that each carry
                  // a hairline of their own, so nothing about the space
                  // around them read as a boundary. Now the LINE says
                  // where, and the words only say which, which is why they
                  // can go back to being quiet.
                  //
                  // `-mx-3` and no padding of its own, so the rule starts
                  // exactly where the borders between rows start — those
                  // reach out by the same three to draw their hover state
                  // full-bleed. A divider inset from every line above and
                  // below it reads as a mistake rather than as a divider.
                  <h3
                    className={cn(
                      "-mx-3 mb-2 flex items-center gap-2.5",
                      at === 0 ? "mt-4" : "mt-7",
                    )}
                  >
                    <span aria-hidden className="h-px w-5 shrink-0 bg-border" />
                    {/* `muted-foreground` — the theme's secondary TEXT, and
                        the role every quiet label on this app already uses.
                        Not `secondary`, which is a surface: #2c2e31 on a
                        #323437 ground is a heading nobody can see, and in
                        the light theme it is a pale grey on white. */}
                    <span className="shrink-0 text-[0.72rem] tracking-caps text-muted-foreground uppercase">
                      {run.heading}
                    </span>
                    <span aria-hidden className="h-px flex-1 bg-border" />
                  </h3>
                )}
                {run.rows.map((row) => {
                  const here = marked.has(row.result.question_id);
                  return (
                    <ReviewItem
                      key={row.result.question_id}
                      row={row}
                      anchor={{ [Q_ANCHOR]: row.result.question_id }}
                      // No onPlay: a passage has nothing to play, and
                      // ReviewItem draws the button only where one is handed
                      // to it.
                      evidence={
                        here
                          ? {
                              where: whereabouts(passages, row),
                              onGoTo: () =>
                                goToEvidence(row.result.question_id),
                            }
                          : undefined
                      }
                      hint={hintFor(row)}
                      // The older route, for a paper the extraction never
                      // reached: the quote's own paragraph. Withheld where the
                      // evidence is known, or the row would offer two ways to
                      // go to two different places.
                      onGoTo={here ? undefined : goToParagraph}
                      onPoint={
                        here
                          ? (on) => setLit(on ? row.result.question_id : null)
                          : undefined
                      }
                      lit={lit === row.result.question_id}
                    />
                  );
                })}
              </div>
            ))}
          </div>

          <ReviewMistakes groups={mistakes} skill="reading" className="mt-10" />
        </>
      )}

      {(layer === "vocabulary" || layer === "saved") && vocabulary && (
        <ReviewVocabulary
          className="mt-5"
          materialId={data.material_id}
          data={vocabulary}
          // The Saved layer is the same list with everything else taken
          // out. Not a different panel: it is the same words, the same
          // meanings and the same passage — what differs is which of them
          // this reader had already met, which is a filter and reads like
          // one.
          only={layer === "saved" ? "saved" : undefined}
          lookedUp={looked}
          savedEarlier={savedEarlier ?? new Set()}
          lit={lit}
          onPoint={setLit}
        />
      )}

      {layer === "marks" && (
        <ReviewMarks
          className="mt-5"
          marks={marks}
          passages={passages}
          lit={lit}
          onPoint={setLit}
        />
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
      {/* Both ways out of this result, together, in the corner people look
          in when they want one — the same two the take screen puts there,
          and the same argument: one leaves the paper and one starts it
          again, so they are siblings and belong side by side.

          It was in the right island, opposite the account menu, which is
          where the take screen's CLOCK goes. A clock is a readout and this
          is a door; putting a door in the readout's place meant the one
          control on the page anybody presses after reading a review was the
          furthest thing from the link they arrived by. */}
      <HeaderSlot side="left">
        <div className="flex items-center gap-1">
          <Link
            to="/reading"
            className="inline-flex items-center gap-1.5 rounded-full px-1 text-sm text-foreground/70 transition-colors duration-fast hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            <ArrowLeft className="size-4" aria-hidden />
            Reading
          </Link>
          <span aria-hidden className="mx-1 h-4 w-px bg-border" />
          {/* Amber, like every other "this is the action" in the app. */}
          <Link
            to={`/reading/${data.material_id}`}
            className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-sm text-primary transition-colors duration-fast hover:bg-primary/10 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            <RotateCcw className="size-3.5" aria-hidden />
            Take it again
          </Link>
        </div>
      </HeaderSlot>

      <HeaderSlot side="centre">
        <ReviewLayers layer={layer} onLayer={setChosenLayer} counts={counts} />
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

/**
 * Where this row's marks are, in as few characters as say it.
 *
 * `¶C` where the book letters its paragraphs — that is what the paper calls
 * the place, and two of Reading's tasks are answered by naming one — and
 * `¶3` where it does not, counting from one because nobody counts
 * paragraphs from zero.
 *
 * The TRAP first where there is one, because that is where pressing the row
 * lands: the marks are gone to in the order the passage holds them, and the
 * sentence that pulled somebody is usually the one they should look at
 * first. A corner that named the answer's paragraph and then took them
 * somewhere else would be the page lying about its own control.
 */
function whereabouts(
  passages: {
    id: string;
    passage?: { paragraphs: { label: string | null }[] } | null;
  }[],
  row: ReviewRow,
): string {
  const spans = [
    ...(row.result.distractor ?? []),
    ...(row.result.evidence ?? []),
  ];
  const first = spans
    .slice()
    .sort(
      (a, b) => a.paragraph_index - b.paragraph_index || a.start - b.start,
    )[0];
  if (!first) return "";
  const part = passages.find((one) => one.id === first.part_id);
  const label = part?.passage?.paragraphs[first.paragraph_index]?.label;
  return `\u00b6${label ?? first.paragraph_index + 1}`;
}

/**
 * The one line of teaching a TRUE / FALSE / NOT GIVEN row carries, and
 * nothing for every other task.
 *
 * Everything else on this page explains itself — you picked C, the answer
 * was B, the passage is beside you. This one does not, and it is the task
 * candidates lose most, so the row says which of the three ways they got it
 * wrong:
 *
 * NOT GIVEN is the hardest of the three to learn and the reason is that the
 * passage ALWAYS mentions the subject. Saying so, on the row that goes to
 * the sentence, is the lesson.
 */
function hintFor(row: ReviewRow): React.ReactNode {
  const { result } = row;
  if (result.is_correct || !isFixedChoice(row.groupType)) return null;

  const said = (one: string) => one.trim().toLowerCase();
  const key = result.correct_answers.map(said);
  if (key.includes("not given")) {
    return "The passage mentions this — but never says it.";
  }
  if (said(result.given_answer) === "not given") {
    return "The evidence was there — it is marked on the passage.";
  }
  if ((result.keywords?.length ?? 0) > 0) {
    return "One sentence, and the answer turns on the words marked inside it.";
  }
  return null;
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

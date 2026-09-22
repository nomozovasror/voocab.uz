import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, RotateCcw } from "lucide-react";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { HeaderGround } from "@/components/layout/HeaderGround";
import { useClaimHeaderCentre } from "@/components/layout/header-center";
import { useMediaQuery } from "@/hooks/use-media-query";
import { PREFERENCES, usePreference } from "@/lib/preferences";
import { mediaUrl } from "@/features/listening/api";
import { QUESTION_TYPE_SHORT } from "@/features/paper/question-types";
import { useAttempt, useTakeMaterial } from "@/features/paper/queries";
import { PlayerSkeleton } from "@/features/listening/components/PaperSkeleton";
import {
  TakePlayer,
  useDockOpening,
} from "@/features/listening/components/TakeAudio";
import { ReviewScore } from "@/features/paper/components/ReviewScore";
import { ReviewMistakes } from "@/features/paper/components/ReviewMistakes";
import { ReviewItem } from "@/features/paper/components/ReviewItem";
import {
  ReviewFilter,
  type ReviewScope,
} from "@/features/paper/components/ReviewFilter";
import type { WavePart } from "@/features/listening/components/Waveform";
import {
  numberWidth,
  reviewRows,
  tallyMistakes,
  worstTask,
} from "@/features/paper/review";
import { Q_ANCHOR, goToQuestion } from "@/features/paper/take-focus";
import { sorted } from "@/features/paper/numbering";
import { PRACTICE } from "@/features/paper/take-config";
import { useAudioEngine } from "@/features/listening/use-audio-engine";
import { useWaveform } from "@/features/listening/use-waveform";
import type { AttemptResult } from "@/features/paper/types";

/**
 * What one attempt came to, and — the part that matters — why.
 *
 * ## This is not the paper again
 *
 * Sitting a paper, the question IS the form: the labels, the columns, the
 * sentence the gap is inside. All of it has to be on screen because the
 * candidate is filling it in. Afterwards none of it is being filled in, and
 * printing it back buries the four things they got wrong inside forty rows of
 * correct ones. Worse, it has nowhere to put the answer: threading
 * `(accepted: Preston, preston)` into the form's own sentence produced
 * "junction of Mill Street and 3 test (accepted: Preston, preston) Avenue" —
 * a line from which neither the question nor the answer can be read.
 *
 * So a review row quotes one line of the form with the gap written `___`, and
 * puts the answer on its own row underneath. Enough of the paper to be
 * recognised, and never enough to take the layout apart.
 *
 * ## The transcript is the point
 *
 * Word-level timestamps were taken, the transcript was kept, and the take
 * payload carries a segment per question, all for this: a candidate who
 * wrote "windscreen" where the answer was "wing mirror" was not mishearing.
 * They were pulled by a distractor, and the only thing on any screen that
 * shows them so is *"The windscreen was fine, luckily — but the wing mirror
 * is broken."* A percentage cannot say that and neither can a marked paper.
 *
 * Optional throughout: the ASR may have failed, the author may have removed
 * it, and a row without one prints the answer and stops. No empty box, no
 * "no transcript available" — a message about a missing feature is a row of
 * the page spent saying nothing.
 *
 * ## Everything else
 *
 * The player is the take screen's, in its shrunk arrangement (`settled`) from
 * the start. There is nothing continuous to listen to on a marked paper —
 * every play is somebody going back to one sentence — so the big state has
 * nothing to offer, and what is left is exactly what the take screen keeps
 * when it shrinks.
 *
 * It still docks into the header, by the same mechanism and the same sentinel
 * (`useClaimHeaderCentre`, `useDockOpening`): a control somebody needs the
 * whole way down a page of forty reviewed questions cannot be at the top of
 * it. The travel is shorter than the take screen's — the arrangement never
 * changes, so all that happens is the card narrowing to the width of the gap
 * between the islands and picking up the frost it needs to sit among them.
 * Nothing is re-parented, for the same reason as everywhere else: an element
 * that is re-parented arrives, and arriving is a cut.
 *
 * The material is fetched, and the page does NOT wait for it: it carries the
 * label a gap sat under and nothing else, so the review renders off the
 * attempt alone and the context lines fill in when the paper lands. That is
 * also what makes a review of a since-unpublished material work rather than
 * fall back to something worse.
 *
 * The URL is the attempt, which is what makes the page survive a reload. A
 * submit hands its result over through navigation state so nothing is fetched
 * twice on the way in; arriving any other way, it asks by id and gets an
 * identical object, because one function on the server answers both.
 */
export default function ListeningResultsPage() {
  const { attemptId } = useParams<{ attemptId: string }>();
  const location = useLocation();
  const seed = (location.state as { result?: AttemptResult } | null)?.result;
  const { data, isLoading, isError } = useAttempt("listening", attemptId, seed);
  const { data: material } = useTakeMaterial("listening", data?.material_id);
  const parts = useMemo(
    () => (material ? sorted(material.parts) : []),
    [material],
  );

  // The same engine the take page uses, with nothing restricted: the attempt
  // is already marked, so there is no measurement left to protect.
  const [autoSkip] = usePreference(PREFERENCES.skipSilence);
  const src = data?.audio_url ? mediaUrl(data.audio_url) : null;
  const shape = useWaveform(src);
  const engine = useAudioEngine({
    src,
    durationMs: data?.duration_ms ?? null,
    config: PRACTICE,
    silences: shape.silences,
    autoSkip,
  });
  // The same rule the take page uses: nothing for a single part, and nothing
  // unless every boundary was marked.
  const wave = useMemo<WavePart[]>(() => {
    if (parts.length < 2) return [];
    if (!parts.every((p, i) => i === 0 || p.audio_start_ms != null)) return [];
    return parts.map((part, i) => ({
      id: part.id,
      label: `Part ${i + 1}`,
      startMs:
        i === 0 ? (part.audio_start_ms ?? 0) : (part.audio_start_ms as number),
    }));
  }, [parts]);

  // Docking into the header's middle, and it is the catalogue's mechanism
  // down to the sentinel: a zero-height mark on the player's top edge, and
  // once that has gone under the header there is no player left on screen to
  // reach for.
  const landingMark = useRef<HTMLDivElement | null>(null);
  const [docked, setDocked] = useState(false);
  // Only where there is a middle to land in. Below `md` the nav is hidden and
  // the two remaining pills leave no room between them, so down there the
  // player is not sticky at all and scrolls away with the page.
  const hasIsland = useMediaQuery("(min-width: 48rem)");
  const inHeader = docked && hasIsland && !!src;

  useEffect(() => {
    const mark = landingMark.current;
    if (!mark || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      ([entry]) => setDocked(!entry.isIntersecting),
      // The mark sits on the player's top edge and the player pins at 12px,
      // so this fires at the moment it has nowhere further to climb.
      { threshold: 0, rootMargin: "-12px 0px 0px 0px" },
    );
    observer.observe(mark);
    return () => observer.disconnect();
  }, [src]);

  useClaimHeaderCentre(inHeader);
  // The ground stops short behind the docked pane, so the page is genuinely
  // moving under it — see HeaderGround.
  const opening = useDockOpening(inHeader);

  const rows = useMemo(
    () => reviewRows(data?.results ?? [], material),
    [data, material],
  );
  const mistakes = useMemo(
    () => tallyMistakes(data?.results ?? []),
    [data],
  );
  const wrong = useMemo(() => rows.filter((r) => !r.result.is_correct), [rows]);

  // A clean sheet has no "mistakes only" to show, so the control never offers
  // it — see ReviewFilter.
  const [chosen, setChosen] = useState<ReviewScope>("mistakes");
  const scope: ReviewScope = wrong.length === 0 ? "all" : chosen;
  const shown = scope === "mistakes" ? wrong : rows;

  /**
   * Go to a question that the filter may currently be hiding.
   *
   * Two steps rather than one, and it has to be two: switching the view and
   * scrolling in the same breath scrolls to a row React has not rendered yet.
   * So the id is parked, and the effect below runs it once the list it
   * belongs to is on the page. Both updates are batched into one render, so
   * by then the row exists.
   */
  const [pending, setPending] = useState<string | null>(null);
  useEffect(() => {
    if (pending == null) return;
    goToQuestion(pending);
    setPending(null);
  }, [pending]);

  const jumpTo = useCallback(
    (id: string) => {
      const row = rows.find((r) => r.result.question_id === id);
      if (row?.result.is_correct) setChosen("all");
      setPending(id);
    },
    [rows],
  );

  if (isLoading) return <ResultsSkeleton />;
  if (isError || !data) {
    return (
      <div className="mx-auto max-w-3xl space-y-4 py-10">
        <p className="text-sm text-destructive">
          Couldn&apos;t load this result.
        </p>
        <Link
          to="/listening"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          Back to listening
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl pb-24">
      <HeaderGround opening={opening} />

      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 pt-2 pb-3">
        <Link
          to="/listening"
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" />
          Listening
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

      {src && (
        <>
          {/* Zero-height, sitting on the player's top edge: the whole of the
              docking detection. */}
          <div ref={landingMark} aria-hidden className="h-0" />
          <TakePlayer
            engine={engine}
            shape={shape}
            parts={wave}
            settled
            docked={inHeader}
            // Sticky only where it has somewhere to go. Below `md` a player
            // that pinned would sit on the page forever, because there is no
            // header island for it to shrink into.
            className="z-sticky mb-4 md:sticky md:top-3"
          />
        </>
      )}

      {/* The strip is a jump as much as it is a picture, and a jump to a right
          answer has to open the view holding it — otherwise the click lands
          on a row the filter is hiding and the page appears not to work. */}
      <ReviewScore data={data} rows={rows} onJump={jumpTo} />

      {wrong.length === 0 && <CleanSheet />}

      <div className="mt-6 mb-1">
        <ReviewFilter
          scope={scope}
          onScope={setChosen}
          mistakes={wrong.length}
          total={rows.length}
          worst={worstTask(rows)}
        />
      </div>

      {/* One width for the whole list — the rows are separate grids and
          would otherwise each guess at how much room a question number
          needs. See `numberWidth`. */}
      <div style={{ "--q-number": numberWidth(rows) } as React.CSSProperties}>
        {shown.map((row) => (
          <ReviewItem
            key={row.result.question_id}
            row={row}
            anchor={{ [Q_ANCHOR]: row.result.question_id }}
            onPlay={
              data.audio_url && !engine.failed
                ? (start, end) => engine.playRange(start, end)
                : undefined
            }
          />
        ))}
      </div>

      {/* After the questions, not before them. It is the summary of what is
          above it, and a summary printed first is a block the reader scrolls
          past to reach what they came for. */}
      <ReviewMistakes groups={mistakes} className="mt-10" />

      <Actions data={data} />
    </div>
  );
}

/** Nothing went wrong, so there is nothing to break down. A sentence rather
 *  than a chart of no bars — and the filter above locks itself to "All
 *  questions", because "mistakes only" over none is an empty page. */
function CleanSheet() {
  return (
    <p className="mt-3 rounded-xl border border-correct/20 bg-correct/5 px-5 py-4 text-sm text-correct">
      Every answer right. Nothing to go back over — the questions are below if
      you want to check your working.
    </p>
  );
}

/**
 * What to do next.
 *
 * At the bottom, where somebody arrives having read the paper — not at the
 * top, where the only thing anybody wants is the score. `Next lesson` appears
 * only when this material sits in a course the reader has not finished, and
 * points at the course's own next unsat lesson rather than at whatever comes
 * after this one: the sequence is somebody's judgement about what to do when.
 */
function Actions({ data }: { data: AttemptResult }) {
  const course = data.course;
  // A drill and a course can never both be here: the server returns one or
  // the other, because a drill is not a lesson in anybody's sequence.
  const drill = data.drill;
  return (
    <div className="mt-8 flex flex-wrap items-center gap-2 border-t border-border pt-5">
      <Link
        // Back to the same drill, not to the paper it was cut from —
        // "Take it again" has to mean the thing that was just taken.
        to={
          drill
            ? `/listening/drills/${drill.group_id}`
            : `/listening/${data.material_id}`
        }
        className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-foreground transition-colors hover:bg-surface-hover focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        <RotateCcw className="size-3.5" aria-hidden />
        Take it again
      </Link>
      <Link
        to="/listening"
        className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-surface-hover hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        Back to listening
      </Link>

      {drill?.next_group_id && (
        <Link
          to={`/listening/drills/${drill.next_group_id}`}
          className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/80 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          {/* Named after the thing, not the machinery: "Next map" is an
              invitation and "Next drill" is a noun nobody came here for. */}
          Next {QUESTION_TYPE_SHORT[drill.type]}
          <ArrowRight className="size-3.5" aria-hidden />
        </Link>
      )}

      {course && (
        <Link
          to={`/listening/${course.next_material_id}`}
          className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/80 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          {/* Named, and numbered: "Lesson 4 of 8" is a place in something,
              which is the whole reason somebody chose a course over the
              list. */}
          Lesson{" "}
          <span className="tabular-nums">
            {course.next_position} of {course.total}
          </span>
          <ArrowRight className="size-3.5" aria-hidden />
        </Link>
      )}
    </div>
  );
}

/**
 * The review's shape while the attempt loads. Reached on a reload of the URL;
 * arriving from a submit skips it entirely, because the result travels with
 * the navigation.
 *
 * Built from the real components' own class strings rather than from measured
 * pixels — the only arrangement in which the two cannot drift.
 */
function ResultsSkeleton() {
  return (
    <SkeletonBlock label="Loading result" className="mx-auto max-w-3xl pb-24">
      <HeaderGround />

      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 pt-2 pb-3">
        <span className="text-xs">
          <Skeleton className="inline-block h-[0.85em] w-16" />
        </span>
        <h1 className="min-w-0 flex-1 truncate text-2xl font-semibold">
          <Skeleton className="inline-block h-[0.8em] w-64 max-w-full" />
        </h1>
      </div>

      <PlayerSkeleton settled className="mb-4" />

      {/* The score card, which is the first thing anyone looks for. */}
      <div className="rounded-xl border border-border bg-card px-5 py-4">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
          <p className="text-4xl leading-none font-bold">
            <Skeleton className="inline-block h-[0.8em] w-20" />
          </p>
          <p className="text-lg">
            <Skeleton className="inline-block h-[0.8em] w-12" />
          </p>
          <div className="ml-auto space-y-1 text-xs">
            <Skeleton className="h-[0.85em] w-40" />
            <Skeleton className="h-[0.85em] w-36" />
          </div>
        </div>
        <div className="mt-4 flex h-1.5 gap-0.5">
          {Array.from({ length: 10 }, (_, i) => (
            <Skeleton key={i} className="h-full min-w-0 flex-1 rounded-sm" />
          ))}
        </div>
      </div>

      {/* Three question rows: header, answer, transcript. Enough to reach the
          fold without claiming how many there are. */}
      <div className="mt-9">
        {Array.from({ length: 3 }, (_, i) => (
          <div key={i} className="border-t border-border py-4">
            <div className="flex items-baseline gap-3">
              <Skeleton className="h-[0.85em] w-6 shrink-0" />
              <Skeleton className="h-[0.85em] w-64 max-w-full" />
            </div>
            <div className="mt-2 ml-9 flex items-baseline gap-6">
              <Skeleton className="h-[0.9em] w-28" />
              <Skeleton className="h-[0.9em] w-24" />
            </div>
            <div className="mt-2.5 ml-9 flex items-start gap-3 rounded-lg bg-surface-sunken px-3 py-2.5">
              <Skeleton className="size-7 shrink-0 rounded-full" />
              <div className="min-w-0 flex-1 space-y-1.5">
                <Skeleton className="h-[0.85em] w-24" />
                <Skeleton className="h-[0.9em] w-full" />
              </div>
            </div>
          </div>
        ))}
      </div>
    </SkeletonBlock>
  );
}

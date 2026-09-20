import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, RotateCcw } from "lucide-react";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { fmtClock, timeAgo } from "@/lib/time";
import { getErrorMessage } from "@/lib/api";
import { useMediaQuery } from "@/hooks/use-media-query";
import { PREFERENCES, usePreference } from "@/lib/preferences";
import { useClaimHeaderCentre } from "@/components/layout/header-center";
import { HeaderGround } from "@/components/layout/HeaderGround";
import { mediaUrl } from "@/features/listening/api";
import {
  useDrillTake,
  useSubmitDrill,
  useSubmitAttempt,
  useTakeMaterial,
} from "@/features/paper/queries";
import { QuestionPaper } from "@/features/paper/components/QuestionPaper";
import {
  PaperSkeleton,
  PlayerSkeleton,
} from "@/features/listening/components/PaperSkeleton";
import {
  TakePlayer,
  useDockOpening,
} from "@/features/listening/components/TakeAudio";
import { QuestionNav } from "@/features/paper/components/QuestionNav";
import type { WavePart } from "@/features/listening/components/Waveform";
import {
  answeredIn,
  paperParts,
  paperRows,
  paperTotal,
} from "@/features/paper/take-paper";
import {
  goToQuestion,
  useQuestionSpy,
  Q_ANCHOR,
} from "@/features/paper/take-focus";
import {
  useAudioEngine,
  NUDGE_MS,
} from "@/features/listening/use-audio-engine";
import { useWaveform } from "@/features/listening/use-waveform";
import {} from "@/features/listening/queries";
import { PRACTICE } from "@/features/paper/take-config";
import { useActiveTime } from "@/features/paper/use-active-time";
import {
  MAX_SPANS,
  clearSession,
  loadSession,
  newSession,
  recordTouch,
  recordVisit,
  saveSession,
  toSubmit,
  type TakeSession,
} from "@/features/paper/take-session";

/**
 * Practice: the material, its recording, and nothing between the two.
 *
 * There is no mode switch here and there shouldn't be. Opening a material is
 * practice; the exam is somewhere a candidate goes on purpose, and choosing to
 * be there IS the consent to its rules. What that page will reuse is
 * everything below — the audio engine, the player, the groups, the
 * navigator — handed a different TakeConfig. Which is why no rule is written
 * into this file: the one place practice differs from an exam is the constant
 * it passes in.
 *
 * The paper is ONE SCROLL. Real computer-delivered IELTS has no tabs per
 * part — the parts are separated by pauses in the recording, not by screens —
 * and in practice a tab is worse than useless: the whole point of practising
 * is going back over what you missed, and a tab makes that a navigation.
 * Parts are section headings, and the strip along the bottom is how you get
 * anywhere quickly.
 *
 * The page also watches itself being used, quietly. None of it is shown (a
 * clock on the wall changes how people work) and none of it can change a
 * mark; it is collected because an attempt that has already happened can
 * never be measured afterwards.
 */

export default function ListeningTakePage() {
  // One page, two routes. `/listening/:id` is a whole paper;
  // `/listening/drills/:groupId` is one question group cut out of one, and
  // the payload it fetches is deliberately the same shape — a title, a
  // recording and a list of parts — so everything below this point is the
  // take screen it always was.
  //
  // Serving both from here rather than writing a second page is the whole
  // reason it is worth doing this way. Six hundred lines of this file are
  // rules with a reason written beside each: the docking, the keyboard
  // interception, where the reader is measured from, what a flag belongs to.
  // A drill page that copied them would be a page that drifts from them.
  const { id, groupId } = useParams<{ id?: string; groupId?: string }>();
  const drilling = groupId !== undefined;
  const navigate = useNavigate();
  const paper = useTakeMaterial("listening", drilling ? undefined : id);
  const drill = useDrillTake("listening", groupId);
  const { data: material, isLoading, isError } = drilling ? drill : paper;
  const attemptMut = useSubmitAttempt("listening", id ?? "");
  const drillMut = useSubmitDrill("listening", groupId ?? "");
  const submitMut = drilling ? drillMut : attemptMut;
  const config = PRACTICE;
  // The stretch of recording a drill is bounded to. `undefined` for a whole
  // paper, which is what leaves the player unbounded.
  const clip =
    drilling && drill.data
      ? { startMs: drill.data.clip_start_ms, endMs: drill.data.clip_end_ms }
      : null;
  // A drill's draft is keyed by its group, or two drills cut from the same
  // recording would share one — and the paper's own key must not collide
  // with either.
  const sessionKey = drilling ? `drill:${groupId}` : id;

  // Answers are state because they are on the screen. Everything else the
  // session accumulates — timings, played spans, backward seeks — is a ref:
  // it arrives several times a second while the audio runs, and none of it
  // changes a pixel.
  const restored = useRef(sessionKey ? loadSession(sessionKey) : null);
  const [answers, setAnswers] = useState<Record<string, string>>(
    () => restored.current?.answers ?? {},
  );
  const [flagged, setFlagged] = useState<Set<string>>(
    () => new Set(restored.current?.flagged ?? []),
  );
  const session = useRef<TakeSession>(restored.current ?? newSession());
  const [resumed, setResumed] = useState(() => restored.current !== null);

  // The same treatment reading has, and the same reasoning: the footer's
  // "5 of 13 answered" IS the restored work, so the offer to refuse it
  // belongs against that number rather than in a line of its own.

  const startOver = useCallback(() => {
    if (!sessionKey) return;
    clearSession(sessionKey);
    session.current = newSession();
    setAnswers({});
    setFlagged(new Set());
    setResumed(false);
  }, [sessionKey]);
  const [confirming, setConfirming] = useState(false);

  // Measured here and never shown. The recording is this page's clock —
  // it ends and the questions end with it — so a second one would be
  // counting something nothing depends on. What the measurement is FOR is
  // the statistics, and those have the same problem on both papers: a tab
  // left open for twenty minutes used to be recorded as twenty minutes of
  // study. See `use-active-time`.
  useActiveTime({
    startedAt: session.current.startedAt,
    activeFrom: restored.current?.activeMs ?? 0,
    onSample: (ms) => {
      session.current.activeMs = ms;
      if (sessionKey) saveSession(sessionKey, session.current);
    },
  });

  const parts = useMemo(
    () => (material ? paperParts(material) : []),
    [material],
  );
  const rows = useMemo(() => paperRows(parts), [parts]);
  const questionIds = useMemo(() => rows.map((row) => row.id), [rows]);

  const total = paperTotal(rows);
  const answered = rows.reduce(
    (n, row) => n + answeredIn(row, answers[row.id]),
    0,
  );
  const blank = total - answered;

  const current = useQuestionSpy(questionIds);

  // --- Keeping the draft ----------------------------------------------------

  // Whether the reader has written anything of their own since the draft
  // came back.
  //
  // A ref, not state, and that is deliberate: every caller of `persist` is
  // already calling a setter beside it, so the re-render that hides the
  // offer is the one the edit was going to cause anyway — and setting state
  // from inside another setter's updater is a rule this avoids having to
  // remember.
  const touched = useRef(false);

  const persist = useCallback(
    (next: Partial<TakeSession>) => {
      // The one funnel every real edit goes through — answers, flags,
      // timings — which is why the "you have been restored" offer is
      // retired here rather than in each handler. A fourth handler added
      // later inherits it instead of forgetting it. The active-time sampler
      // does NOT come through here: seconds passing is not the reader
      // writing something.
      touched.current = true;
      session.current = { ...session.current, ...next };
      if (sessionKey) saveSession(sessionKey, session.current);
    },
    [sessionKey],
  );

  const sinceStart = () => Date.now() - session.current.startedAt;

  const onAnswer = useCallback(
    (questionId: string, value: string) => {
      setAnswers((prev) => {
        const next = { ...prev, [questionId]: value };
        persist({
          answers: next,
          timing: recordTouch(
            session.current.timing,
            questionId,
            value,
            sinceStart(),
          ),
        });
        return next;
      });
    },
    [persist],
  );

  const onFlag = useCallback(
    (questionId: string) => {
      setFlagged((prev) => {
        const next = new Set(prev);
        if (next.has(questionId)) next.delete(questionId);
        else next.add(questionId);
        persist({ flagged: [...next] });
        return next;
      });
    },
    [persist],
  );

  // --- Focus time -----------------------------------------------------------
  //
  // Measured by watching focus move rather than by every group component
  // reporting it: the inputs carry a data-question attribute, focus events
  // bubble, and one listener here beats an onFocus/onBlur pair threaded
  // through three group components and the layout between them.

  const held = useRef<{ qid: string; at: number; was: string } | null>(null);

  const closeFocus = useCallback(() => {
    const open = held.current;
    held.current = null;
    if (!open) return;
    session.current = {
      ...session.current,
      timing: recordVisit(
        session.current.timing,
        open.qid,
        Date.now() - open.at,
        // The answer they leave behind against the one they arrived at. A
        // revision is per visit, not per keystroke — see recordVisit.
        (session.current.answers[open.qid] ?? "") !== open.was,
      ),
    };
  }, []);

  useEffect(() => closeFocus, [closeFocus]);

  // --- Listening ------------------------------------------------------------

  const onSpan = useCallback(
    (span: { start_ms: number; end_ms: number }) => {
      const spans = session.current.listened;
      // Stop collecting at the cap rather than post something the server will
      // refuse. Five hundred separate plays have already said what they had
      // to say.
      if (spans.length >= MAX_SPANS) return;
      persist({ listened: [...spans, span] });
    },
    [persist],
  );

  const onSeekBack = useCallback(() => {
    // Persisted on the spot and not left to the next save. A seek backwards
    // while the audio is paused emits no span, so nothing else was going to
    // write, and a reload would drop the count back to what it was.
    persist({ seeksBack: session.current.seeksBack + 1 });
  }, [persist]);

  const src = material?.audio_url ? mediaUrl(material.audio_url) : null;
  // Drawn over the clip, not the file. Two minutes of a seven-minute
  // recording drawn across the whole width is a picture claiming there is
  // far more left to hear than there is.
  const shape = useWaveform(
    src,
    undefined,
    clip ? { fromMs: clip.startMs, toMs: clip.endMs } : undefined,
  );

  /**
   * The parts as the waveform shows them: where each one starts.
   *
   * Nothing at all for a single-part material. "Part 1" written under a
   * recording that is entirely part 1 is a caption saying what the reader is
   * looking at — it divides nothing, and the strip exists to divide.
   *
   * And nothing unless the author marked EVERY boundary: three parts with two
   * marks would draw two lines and name the wrong stretches, and a name over
   * the wrong stretch is worse than none, because a learner uses it to decide
   * where to listen.
   */
  const wave = useMemo<WavePart[]>(() => {
    if (parts.length < 2) return [];
    if (!parts.every((p, i) => i === 0 || p.audioStartMs != null)) return [];
    return parts.map((p, i) => ({
      id: p.id,
      label: `Part ${i + 1}`,
      startMs: i === 0 ? (p.audioStartMs ?? 0) : (p.audioStartMs as number),
    }));
  }, [parts]);

  // Off unless the reader has said otherwise, in which case every silence is
  // stepped over and the button in the player has nothing left to offer.
  const [autoSkip] = usePreference(PREFERENCES.skipSilence);

  const engine = useAudioEngine({
    src,
    durationMs: material?.duration_ms ?? null,
    config,
    silences: shape.silences,
    autoSkip,
    clip,
    onSpan,
    onSeekBack,
  });

  // --- The player's journey to the header -----------------------------------
  //
  // The full player sits at the top of the paper and scrolls away with it;
  // the strip takes over in the header's middle. The mechanism is the
  // catalogue's, down to the sentinel: a zero-height mark above the player,
  // and once that has gone under the header's top edge there is no player
  // left on screen to reach for.
  const landingMark = useRef<HTMLDivElement | null>(null);
  const [docked, setDocked] = useState(false);
  // Only where there is a middle to land in. Below `md` the nav is hidden and
  // the two remaining pills leave no room between them — so down there the
  // player is not sticky at all and simply scrolls away with the page.
  const hasIsland = useMediaQuery("(min-width: 48rem)");
  const inHeader = docked && hasIsland && !!src;

  useEffect(() => {
    const mark = landingMark.current;
    if (!mark || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      ([entry]) => setDocked(!entry.isIntersecting),
      // The mark sits exactly on the player's top edge and the player pins at
      // 12px, so this fires at the moment it has nowhere further to climb —
      // the collapse and the last of the travel are one movement rather than
      // two events.
      { threshold: 0, rootMargin: "-12px 0px 0px 0px" },
    );
    observer.observe(mark);
    return () => observer.disconnect();
  }, [src]);

  useClaimHeaderCentre(inHeader);

  // The ground stops short behind the docked pane, so the paper is genuinely
  // moving under it — see HeaderGround.
  const opening = useDockOpening(inHeader);

  // --- The keyboard ---------------------------------------------------------

  const inField = (el: EventTarget | null) =>
    !!(el as HTMLElement | null)?.closest?.(
      "input, select, textarea, [contenteditable]",
    );

  // The engine is a fresh object every render — it carries the playhead, and
  // the playhead moves four times a second. Read through a ref so the window
  // listener is attached once instead of being torn down and rebuilt on every
  // tick of the audio.
  const latest = useRef({ engine, current, onFlag });
  latest.current = { engine, current, onFlag };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const { engine, current, onFlag } = latest.current;
      const typing = inField(e.target);

      if (e.code === "Space" || e.key === " ") {
        // A button under the pointer wants its own space bar, and so does a
        // field. Everywhere else it is the recording's.
        if (typing || (e.target as HTMLElement)?.closest?.("button")) return;
        e.preventDefault();
        engine.toggle();
        return;
      }

      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        // In a field the arrows are the caret's, and in a radio group they
        // are the selection's. Taking them would be taking something that
        // already has a job.
        if (typing) return;
        e.preventDefault();
        engine.nudge(e.key === "ArrowLeft" ? -NUDGE_MS : NUDGE_MS);
        return;
      }

      if ((e.key === "f" || e.key === "F") && !typing && current) {
        e.preventDefault();
        onFlag(current);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  /**
   * Tab moves between QUESTIONS, not between fields.
   *
   * That is how the real computer-delivered test behaves and candidates use
   * it hard. Left to the browser, Tab lands on every option of a
   * multiple-choice question and every letter of a matching row, so getting
   * from question 7 to question 8 is eight presses.
   *
   * It is intercepted only in the middle of the paper. From the last question
   * Tab is let through, and from the first Shift+Tab is — otherwise the paper
   * would be a trap with the navigator and the header on the outside of it.
   */
  const onPaperKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Tab") return;
    const anchor = (e.target as HTMLElement).closest?.(`[${Q_ANCHOR}]`);
    const from = anchor?.getAttribute(Q_ANCHOR);
    if (!from) return;
    const at = questionIds.indexOf(from);
    if (at === -1) return;
    const to = at + (e.shiftKey ? -1 : 1);
    if (to < 0 || to >= questionIds.length) return;
    e.preventDefault();
    goToQuestion(questionIds[to]);
  };

  // --- Room for the strip along the bottom -----------------------------------
  //
  // Measured rather than written down: the navigator wraps to a second row on
  // a forty-question paper and to one on a six-question one, and a number
  // typed in here would bury the last question on exactly one of them.
  const navRef = useRef<HTMLDivElement | null>(null);
  const [navH, setNavH] = useState(0);

  useEffect(() => {
    const el = navRef.current;
    if (!el) return;
    const measure = () => setNavH(el.getBoundingClientRect().height);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [material]);

  // --- Submitting -----------------------------------------------------------

  const send = () => {
    if (!sessionKey) return;
    closeFocus();
    setConfirming(false);
    submitMut.mutate(toSubmit(session.current, questionIds), {
      onSuccess: (result) => {
        clearSession(sessionKey);
        // The result travels with the navigation so the review paints
        // immediately; the page also knows how to fetch it by id, which is
        // what makes the URL survive a reload.
        navigate(`/listening/attempts/${result.attempt_id}`, {
          state: { result },
        });
      },
      onError: (e) => toast(getErrorMessage(e)),
    });
  };

  const onSubmit = () => {
    if (blank > 0 && !confirming) {
      setConfirming(true);
      return;
    }
    send();
  };

  if (!sessionKey) return null;
  if (isLoading) return <TakeSkeleton />;
  if (isError || !material) {
    return (
      <div className="mx-auto max-w-3xl space-y-4 py-10">
        <p className="text-sm text-destructive">
          This listening material couldn&apos;t be loaded.
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
    <div className="mx-auto max-w-3xl" style={{ paddingBottom: navH + 24 }}>
      <HeaderGround opening={opening} />

      {/*
        The title, the way out, and nothing else — in the flow, and it scrolls
        away.

        It used to be pinned to the top, and it could not stay there. That
        48px band is contested by four things already: the brand island, the
        account island, the app's own nav, and now the player, which lands in
        the middle of it. On a 1024px window that leaves about 680px between
        the two islands and the player takes 448 of it — so a page column
        pinned across the same band runs its title under the brand pill and
        its counter under the account menu, which is exactly what it did.

        Nothing here needs to stay. The title is orientation on arrival, and
        after that the paper IS the material. The way out is a rare action —
        scrolling back up brings both it and the header's own Listening link
        back. The one thing that is needed the whole way down is how much is
        answered, and that has moved to the strip along the bottom, where it
        is a summary of the very squares it sits beside.
      */}
      <div className="pt-1">
        {/* The two ways out of this attempt, together. Reading puts the same
            pair in its left header island; this page keeps its islands for
            the travelling player, so the pair sits where its back link
            already was. Either way it is the corner people look in when they
            want out of something, and `Start over` is the same kind of thing
            as the link beside it: one abandons the sitting by leaving, the
            other by beginning it again. */}
        <div className="flex items-center gap-1">
          <Link
            to="/listening"
            className="inline-flex items-center gap-1.5 rounded-md text-xs text-muted-foreground transition-colors duration-fast hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            <ArrowLeft className="size-3.5" aria-hidden />
            Listening
          </Link>
          {resumed && !touched.current && (
            <>
              <span aria-hidden className="mx-1 h-3 w-px bg-border" />
              <button
                type="button"
                onClick={startOver}
                title="Picked up where you left off — this throws that away and answers the paper again"
                className="inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-xs text-primary transition-colors duration-fast hover:bg-primary/10 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                <RotateCcw className="size-3" aria-hidden />
                Start over
              </button>
            </>
          )}
        </div>
        {/* The title and what the paper IS, on one line and on one baseline.
            Everything up here used to stack down the left edge — four rows of
            different lengths against an empty right half, which reads as a
            pile rather than as a heading. The facts were worth printing
            anyway: how long the recording is and how many marks are on the
            paper is what somebody decides to start with. */}
        <div className="mt-1.5 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
          <h1 className="text-2xl font-semibold text-foreground">
            {material.title}
          </h1>
          <p className="shrink-0 text-xs tabular-nums text-muted-foreground">
            {[
              // Which test this was cut from — see the reading take screen.
              // Withheld where it IS the title: a Part 3 the book printed no
              // heading over is named by its reference for want of anything
              // else, and the page would be saying it twice.
              material.reference !== material.title ? material.reference : null,
              // A drill is one group cut out of a part, so saying "1 part"
              // about it is describing the paper it came from rather than
              // the thing on screen. Which part it was is in the heading
              // below, where it belongs.
              drilling
                ? null
                : `${parts.length} ${parts.length === 1 ? "part" : "parts"}`,
              `${total} ${total === 1 ? "question" : "questions"}`,
              // The CLIP's length for a drill. The recording is seven
              // minutes and the drill plays three of them — printing the
              // seven beside a player counting to three is the page
              // disagreeing with itself about what it is about to play.
              clip
                ? fmtClock(clip.endMs - clip.startMs)
                : material.duration_ms != null
                  ? fmtClock(material.duration_ms)
                  : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
      </div>

      {/* The way back to a sitting they have already finished.
      
          Without it the only route to a review was to sit the paper again,
          which is exactly what somebody coming back to analyse their mistakes
          does not want: it writes a SECOND attempt, and every ability figure
          on the platform counts first attempts. Going back to study what you
          got wrong would quietly cost you the measurement of it.

          The whole row is the link. Two targets — a line of facts and a
          "review" beside it — is two things to aim at where there is only one
          thing to do. */}
      {material.last_attempt && (
        <Link
          to={`/listening/attempts/${material.last_attempt.attempt_id}`}
          className="mt-4 flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-lg border border-border bg-card px-4 py-2.5 transition-colors duration-fast hover:border-border-strong focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          <span className="text-sm text-foreground">You have sat this</span>
          <span className="text-sm tabular-nums text-muted-foreground">
            {material.last_attempt.score} /{" "}
            {material.last_attempt.total_questions}
            {" · "}
            {timeAgo(material.last_attempt.submitted_at)}
          </span>
          {/* The offer, and it names the thing rather than the page: nobody
              comes back to a finished paper to see a score again — they come
              back to find out what they got wrong. */}
          <span className="ml-auto inline-flex items-center gap-1 text-sm text-primary">
            See what you got wrong
            <ArrowRight className="size-3.5" aria-hidden />
          </span>
        </Link>
      )}

      {/* What the keyboard does. The resumed-draft notice used to share this
          row — hence the spacer that was here for whichever was missing —
          and has moved to where reading's went: the footer, beside the
          count of what was restored. Two papers must not say the same thing
          two ways. */}
      {src && (
        <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2">
          <KeyHints />
        </div>
      )}

      {src && (
        <>
          {/* Zero-height, sitting on the player's top edge: the whole of the
              docking detection. */}
          <div ref={landingMark} aria-hidden className="mt-2 h-0" />
          <TakePlayer
            engine={engine}
            shape={shape}
            parts={wave}
            docked={inHeader}
            // Sticky only where it has somewhere to go. Below `md` a player
            // that pinned would sit on the paper at full height forever,
            // because there is no header island for it to shrink into.
            className="z-sticky md:sticky md:top-3"
          />
        </>
      )}

      {/* One focus listener for the whole paper. React's onFocus/onBlur are
          focusin/focusout, so they bubble up from the inputs inside. */}
      <div className="mt-8" onKeyDown={onPaperKeyDown}>
        <QuestionPaper
          material={material}
          answers={answers}
          onChange={onAnswer}
          flagged={flagged}
          onFlag={onFlag}
          // Only where the rules let the playhead move. In an exam the
          // recording plays through and part 3 arrives when it arrives.
          onPlayPart={
            src && config.allowSeek
              ? (start, end) => engine.playRange(start, end)
              : undefined
          }
          disabled={submitMut.isPending}
          onFocus={(e) => {
            const qid = (e.target as HTMLElement).dataset?.question;
            if (!qid) return;
            closeFocus();
            held.current = {
              qid,
              at: Date.now(),
              was: session.current.answers[qid] ?? "",
            };
          }}
          onBlur={(e) => {
            if ((e.target as HTMLElement).dataset?.question) closeFocus();
          }}
        />
      </div>

      {submitMut.isError && (
        <p className="mt-6 text-right text-xs text-destructive">
          {getErrorMessage(submitMut.error)} — your answers are still here.
        </p>
      )}

      <QuestionNav
        ref={navRef}
        parts={parts}
        answers={answers}
        flagged={flagged}
        current={current}
        onGo={goToQuestion}
        onSubmit={onSubmit}
        submitLabel={config.submitLabel}
        answered={answered}
        total={total}
        submitting={submitMut.isPending}
        blank={blank}
        confirming={confirming}
        onKeepWorking={() => setConfirming(false)}
      />
    </div>
  );
}

/**
 * What the keyboard does, said once, above the controls it is talking about.
 *
 * Not a tooltip and not a help panel: these are three keys a candidate will
 * use every twenty seconds, and the cost of printing them is one quiet line.
 */
function KeyHints({ className }: { className?: string }) {
  return (
    <p
      className={cn(
        "flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-muted-foreground",
        className,
      )}
    >
      <span className="flex items-center gap-1.5">
        <Key>space</Key> play / pause
      </span>
      <span className="flex items-center gap-1.5">
        <Key>←</Key>
        <Key>→</Key> {NUDGE_MS / 1000} seconds
      </span>
      <span className="flex items-center gap-1.5">
        <Key>tab</Key> next question
      </span>
    </p>
  );
}

function Key({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded-sm bg-surface-sunken px-1.5 py-0.5 font-mono text-xs text-foreground">
      {children}
    </kbd>
  );
}

/**
 * The paper's shape, held open while it loads.
 *
 * The container, the band and the back link are the real ones — only what
 * depends on the material is a bar. That is what stops the page jumping: the
 * title sits at the same y before and after, and so does the player.
 */
function TakeSkeleton() {
  return (
    <SkeletonBlock label="Loading material" className="mx-auto max-w-3xl pb-32">
      <HeaderGround />

      <div className="pt-1">
        {/* A real link, not a bar. A page that hasn't loaded is exactly when
            somebody wants to leave it. */}
        <Link
          to="/listening"
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" aria-hidden />
          Listening
        </Link>
        {/* The bars sit INSIDE the real elements, so those elements' own
            line-heights set the rows and the player below starts at the same
            y before and after the words arrive. */}
        <div className="mt-1.5 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
          <h1 className="text-2xl font-semibold">
            <Skeleton className="inline-block h-[0.8em] w-80 max-w-full" />
          </h1>
          <p className="shrink-0 text-xs">
            <Skeleton className="inline-block h-[0.9em] w-40" />
          </p>
        </div>
      </div>

      {/* The keyboard row, held open — it is the same height loaded or not. */}
      <div className="mt-4 h-5" />
      <PlayerSkeleton className="mt-2" />

      <div className="mt-8">
        <PaperSkeleton />
      </div>
    </SkeletonBlock>
  );
}

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { toast } from "@/lib/toast";
import { timeAgo } from "@/lib/time";
import { getErrorMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useMediaQuery } from "@/hooks/use-media-query";
import { HeaderSlot, useHeaderTask } from "@/components/layout/header-task";
import {
  useDrillTake,
  useSubmitAttempt,
  useSubmitDrill,
  useTakeMaterial,
} from "@/features/paper/queries";
import { QuestionPaper } from "@/features/paper/components/QuestionPaper";
import { PaperSkeleton } from "@/features/listening/components/PaperSkeleton";
import { QuestionNav } from "@/features/paper/components/QuestionNav";
import {
  answeredIn,
  paperParts,
  paperRows,
  paperTotal,
} from "@/features/paper/take-paper";
import { goToQuestion, useQuestionSpy, Q_ANCHOR } from "@/features/paper/take-focus";
import {
  READING_PRACTICE,
  paperMs,
} from "@/features/paper/take-config";
import { TakeTimer } from "@/features/paper/components/TakeTimer";
import { useActiveTime } from "@/features/paper/use-active-time";
import {
  clearSession,
  loadSession,
  newSession,
  recordTouch,
  recordVisit,
  saveSession,
  toSubmit,
  type TakeSession,
} from "@/features/paper/take-session";
import {
  PassagePane,
  passageId,
} from "@/features/reading/components/PassagePane";
import { LEFT_PANE, SplitPanes } from "@/features/reading/components/SplitPanes";
import { PassageTools, useTextSize } from "@/features/reading/components/PassageTools";
import {
  loadHighlights,
  saveHighlights,
  withoutAt,
  type Highlight,
} from "@/features/reading/highlights";

/**
 * Practice: the passages, the questions, and the reader between them.
 *
 * The listening take screen is ONE SCROLL, and that rule does not come here.
 * A recording plays through whatever is on screen, so scrolling costs
 * nothing; a passage is read BACK against the question in hand, and one
 * scroll would mean moving nine hundred words out of the way to reach
 * question 9 and back again to answer it. So: two panes, each with its own
 * scroll, which is also the shape of the real computer-delivered paper.
 *
 * Everything else IS the listening page's, and deliberately the same objects
 * rather than the same idea — `QuestionPaper` draws the questions,
 * `QuestionNav` is the strip along the bottom, `take-focus` says where the
 * reader is, `take-session` keeps the draft, and `TakeConfig` carries the
 * rules. What is genuinely new here is the passage and the divider between
 * the two halves.
 *
 * The page watches itself being used, quietly, for the same reason the
 * listening one does: an attempt that has already happened can never be
 * measured afterwards. What it cannot collect is anything about a recording,
 * so `listened` and `seeksBack` stay empty — the server declares both
 * optional (see AttemptSubmit).
 */

/** What the strip along the bottom leaves under the panes, on top of its own
 *  measured height.
 *
 *  Nothing. There was 24px of it, and what it bought was a band of empty
 *  page where the prose stopped short of the strip and simply disappeared —
 *  a line vanishing a centimetre above the thing it should have slid under.
 *  The panes now run flush to the strip, which has its own background and
 *  covers what goes beneath it. */
const PANE_FOOT = 0;

export default function ReadingTakePage() {
  // One page, two routes. `/reading/:id` is a whole paper;
  // `/reading/drills/:groupId` is one question group cut out of one, and the
  // payload it fetches is the same shape — a title and a list of parts, the
  // passage among them — so everything below this point is the take screen
  // it always was.
  //
  // A reading drill carries no clip, which is the whole of what it does not
  // share with a listening one: there is nothing to play, and the passage is
  // already on the part. The server sends `clip_start_ms` and `clip_end_ms`
  // null for exactly this reason, and nothing here reads them.
  const { id, groupId } = useParams<{ id?: string; groupId?: string }>();
  const drilling = groupId !== undefined;
  const navigate = useNavigate();
  const paper = useTakeMaterial("reading", drilling ? undefined : id);
  const drill = useDrillTake("reading", groupId);
  const { data: material, isLoading, isError } = drilling ? drill : paper;
  const attemptMut = useSubmitAttempt("reading", id ?? "");
  const drillMut = useSubmitDrill("reading", groupId ?? "");
  const submitMut = drilling ? drillMut : attemptMut;
  const config = READING_PRACTICE;
  // A drill's draft is keyed by its group, or two drills cut from one paper
  // would share one — and the paper's own key must not collide with either.
  const sessionKey = drilling ? `drill:${groupId}` : id;

  const restored = useRef(sessionKey ? loadSession(sessionKey) : null);
  const [answers, setAnswers] = useState<Record<string, string>>(
    () => restored.current?.answers ?? {},
  );
  const [flagged, setFlagged] = useState<Set<string>>(
    () => new Set(restored.current?.flagged ?? []),
  );
  const session = useRef<TakeSession>(restored.current ?? newSession());
  const [resumed, setResumed] = useState(() => restored.current !== null);
  const [confirming, setConfirming] = useState(false);

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

  // --- What the reader marked ----------------------------------------------
  //
  // The real computer-delivered test lets a candidate highlight the passage
  // and they use it constantly — the sentence an answer came from gets
  // marked, and the marks are how they find their way back through nine
  // hundred words at the end. See `features/reading/highlights`.
  const [marks, setMarks] = useState<Highlight[]>(() =>
    id ? loadHighlights(id) : [],
  );
  const keep = useCallback(
    (next: Highlight[]) => {
      setMarks(next);
      if (id) saveHighlights(id, next);
    },
    [id],
  );
  const [textSize, setTextSize] = useTextSize();

  // The header works for this paper while it is open. Reading cannot dock a
  // control on scroll the way listening does — there is no scroll — so the
  // islands go over to the page from the first paint. See `header-task`.
  useHeaderTask();

  // --- Which paragraph the reader is looking at ----------------------------
  //
  // The most useful thing a reading screen can do, and the page was not
  // doing it: a candidate on "Paragraph C" wants to know which of the seven
  // that is, and was counting letters down the margin to find out.
  //
  // It runs both ways. Point at a question and its paragraph lights; point
  // at a paragraph and the questions about it light. Read off the DOM, the
  // way `take-focus` reads where the reader is, rather than threaded up out
  // of every group component — the two panes already write down what they
  // are (`data-paragraph` on an item, `passage-<part>-<letter>` on a
  // paragraph) and the page only has to ask.
  //
  // Only matching headings can say this before the paper is answered: its
  // ITEMS are the paragraphs. Every other task points the other way, and a
  // page that lit the paragraph an answer is in would be answering the
  // question. Nothing is drawn where nothing is known.
  const [lit, setLit] = useState<string | null>(null);

  const look = useCallback((target: EventTarget | null) => {
    const el = target instanceof Element ? target : null;
    const item = el?.closest<HTMLElement>("[data-paragraph]");
    if (item) {
      setLit(item.dataset.paragraph ?? null);
      return;
    }
    const paragraph = el?.closest<HTMLElement>('[id^="passage-"]');
    const letter = paragraph?.id.split("-").pop();
    setLit(letter && letter.length === 1 ? letter : null);
  }, []);

  // --- The clock ------------------------------------------------------------
  //
  // Reading is the paper that needs one. A recording is its own clock and a
  // passage has none, and pace is exactly the skill a reading candidate is
  // short of — the same person scores 35 with no limit and 25 in an hour.
  // Practice counts UP, against what the paper is worth, and says so in
  // amber rather than shouting: this is a measurement somebody can act on
  // afterwards, not a constraint to work under now.
  const banked = useRef(restored.current?.activeMs ?? 0);
  const { elapsedMs, activeMs, away } = useActiveTime({
    startedAt: session.current.startedAt,
    activeFrom: banked.current,
    onSample: (ms) => {
      session.current.activeMs = ms;
      if (sessionKey) saveSession(sessionKey, session.current);
    },
  });
  // What the paper is worth: ninety seconds a question, which is the real
  // paper's own arithmetic — forty questions in sixty minutes.
  const worth = config.durationMs ?? paperMs(total);
  const shown = config.timerMode === "countDown" ? worth - elapsedMs : activeMs;

  // --- The passage pane follows the question --------------------------------
  //
  // A paper is three passages of nine hundred words stacked in one scroll, so
  // a candidate on question 30 was being asked to scroll past two thousand
  // words they have finished with to reach the passage they are being asked
  // about. Two panes exist so that the text and the question in hand are in
  // view at the same time; side by side is only half of that.
  //
  // It moves when the reader crosses into another PASSAGE, and never between
  // questions of the same one. Inside a passage the reader is moving around
  // the text deliberately — that is what reading back IS — and a pane that
  // re-scrolled under them there would take away the paragraph they were in
  // the middle of.
  const wanted = useRef<string | null>(null);

  const showPassage = useCallback(() => {
    const partId = wanted.current;
    if (!partId) return;
    const pane = document.querySelector<HTMLElement>(`[${LEFT_PANE}]`);
    const passage = document.getElementById(passageId(partId));
    // `offsetParent` is null for the pane the tabs are hiding. Everything
    // about an element that is not laid out measures zero, and scrolling by
    // those numbers lands on the first passage — exactly the wrong place.
    if (!pane || !passage || pane.offsetParent === null) return;
    pane.scrollTo({
      top:
        passage.getBoundingClientRect().top -
        pane.getBoundingClientRect().top +
        pane.scrollTop,
      behavior: "smooth",
    });
  }, []);

  useEffect(() => {
    const partId = rows.find((row) => row.id === current)?.partId;
    if (!partId || partId === wanted.current) return;
    const opening = wanted.current === null;
    wanted.current = partId;
    // Not on the first paint. The reader has just opened the paper, the pane
    // is at the top of passage 1, and that is where they want it — a smooth
    // scroll on arrival would be the page moving for no reason.
    if (!opening && parts.length > 1) showPassage();
  }, [current, rows, parts.length, showPassage]);

  // --- Keeping the draft ----------------------------------------------------

  const persist = useCallback(
    (next: Partial<TakeSession>) => {
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
        (session.current.answers[open.qid] ?? "") !== open.was,
      ),
    };
  }, []);

  useEffect(() => closeFocus, [closeFocus]);

  // --- The keyboard ---------------------------------------------------------
  //
  // One key, where the listening page binds four. Space is the recording's
  // there and is a candidate's own here — a passage has nothing to play — and
  // the arrows belong to the caret. What is left is the one that is about the
  // PAPER rather than about the audio.

  const latest = useRef({ current, onFlag });
  latest.current = { current, onFlag };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const typing = !!(e.target as HTMLElement | null)?.closest?.(
        "input, select, textarea, [contenteditable]",
      );
      const { current, onFlag } = latest.current;
      if ((e.key === "f" || e.key === "F") && !typing && current) {
        e.preventDefault();
        onFlag(current);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  /** Tab moves between QUESTIONS, not between fields — the listening page's
   *  rule, unchanged, and for its reason: left to the browser, getting from
   *  question 7 to question 8 is eight presses. Intercepted only in the
   *  middle of the paper, or the paper is a trap. */
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

  // --- Room for the strip along the bottom ----------------------------------

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

  // Two panes need a width to be worth having. Below this the same content
  // is a pair of tabs — see SplitPanes.
  const wide = useMediaQuery("(min-width: 64rem)");

  // --- How tall the panes are ----------------------------------------------
  //
  // Measured from where the panes actually START, not computed from the
  // viewport and a guess at everything above them. What is above them varies:
  // the app's own header, the title, and a "you have sat this" row that is
  // there for some papers and not others. A number written down here was
  // wrong for whichever combination it had not been written for — and wrong
  // in the way that matters, because a container taller than the space left
  // makes the PAGE scroll, which is the one thing two panes exist to stop.
  const paneRef = useRef<HTMLDivElement | null>(null);
  const [paneH, setPaneH] = useState<number | null>(null);

  useEffect(() => {
    const el = paneRef.current;
    if (!el) return;
    const measure = () => {
      const top = el.getBoundingClientRect().top + window.scrollY;
      setPaneH(Math.max(240, window.innerHeight - top - navH - PANE_FOOT));
    };
    measure();
    window.addEventListener("resize", measure);
    if (typeof ResizeObserver === "undefined") {
      return () => window.removeEventListener("resize", measure);
    }
    // The block above the panes changes height when the material lands — the
    // title wraps, the "you have sat this" row appears — so the panes are
    // re-measured against it rather than against the frame it was first
    // drawn in.
    const observer = new ResizeObserver(measure);
    if (el.parentElement) observer.observe(el.parentElement);
    return () => {
      window.removeEventListener("resize", measure);
      observer.disconnect();
    };
  }, [navH, material]);

  // --- Submitting -----------------------------------------------------------

  const send = () => {
    if (!sessionKey) return;
    closeFocus();
    setConfirming(false);
    submitMut.mutate(toSubmit(session.current, questionIds), {
      onSuccess: (result) => {
        clearSession(sessionKey);
        navigate(`/reading/attempts/${result.attempt_id}`, {
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

  // --- Time is up -----------------------------------------------------------
  //
  // The real computer-delivered test locks the screen on the second and
  // takes what is there; this does the same. No confirmation — there is
  // nothing to confirm, the decision was made by the clock — and the ref
  // guards against the effect firing twice while the request is in flight.
  const finished = useRef(false);
  const out = config.timerMode === "countDown" && shown <= 0;
  useEffect(() => {
    if (!out || finished.current) return;
    finished.current = true;
    send();
    // `send` is rebuilt every render and this must run exactly once, which
    // the ref above is what guarantees.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [out]);

  if (!sessionKey) return null;
  if (isLoading) return <TakeSkeleton />;
  if (isError || !material) {
    return (
      <div className="mx-auto max-w-3xl space-y-4 py-10">
        <p className="text-sm text-destructive">
          This reading material couldn&apos;t be loaded.
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

  const sorted = [...material.parts].sort(
    (a, b) => a.order_index - b.order_index,
  );

  return (
    // The page itself does not scroll: the panes do. That is the whole of
    // what makes them two panes rather than two columns of one document.
    //
    // And it takes the whole window. `<main>` centres every page inside
    // `max-w-7xl` with a gutter each side, which is right for a page of
    // prose and wrong for this one: it left about a hundred and twenty empty
    // pixels down both edges of a screen where horizontal space is what the
    // two panes are dividing. `mx-[calc(50%-50vw)]` is the full-bleed
    // margin — the element stays in the flow and simply reaches past its
    // parent to the viewport — and `-my-8` gives back the vertical padding
    // main adds under a header that is already in the flow above it.
    //
    // Done here rather than in `Layout` because this is the only page that
    // wants it. The day a second one does, it moves up a level.
    // -mt-23 is main's own `py-8` (32px) plus the header's 60, so the panes
    // begin at the very top of the window and the paper scrolls UNDER the
    // islands rather than stopping below them. Each pane carries the header's
    // height back as padding, so at rest the first line sits clear of the
    // pills and only goes behind them once the reader has moved it there.
    //
    // No `HeaderGround` on this page, and that is the same decision: the
    // ground is a solid band whose whole job is to stop the page showing
    // through the gaps between the islands. Here the showing through is the
    // point — the pills are frosted, and prose sliding under frosted glass
    // is the one place in this app where that reads as depth rather than as
    // a rendering fault.
    <div className="-mt-23 -mb-8 mx-[calc(50%-50vw)] flex w-auto flex-col overflow-hidden px-4 sm:px-6">

      {/* Nothing above the paper at all.

          There was a row here: the crumb, the title, the meta line, the
          tools and the clock. Every one of them has gone somewhere better.
          The way out is in the header's left island where the wordmark was,
          the tools are the middle island, and the clock sits beside the
          account. What is left — the name of the passage and which test it
          is — belongs over the passage itself, which is the thing it names.

          The row was about forty pixels. On the screen where vertical space
          is the scarcest thing there is, that is two more lines of prose. */}
      <HeaderSlot side="left">
        <Link
          to="/reading"
          className="inline-flex items-center gap-1.5 rounded-full px-1 text-sm text-muted-foreground transition-colors duration-fast hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          <ArrowLeft className="size-4" aria-hidden />
          Reading
        </Link>
      </HeaderSlot>

      <HeaderSlot side="centre">
        <PassageTools
          marks={marks}
          onMarks={keep}
          size={textSize}
          onSize={setTextSize}
        />
      </HeaderSlot>

      {config.showTimer && (
        <HeaderSlot side="right">
          <TakeTimer
            mode={config.timerMode}
            ms={shown}
            targetMs={config.timerMode === "countUp" ? worth : null}
            away={config.pauseOnIdle && away}
            className="mr-1"
          />
        </HeaderSlot>
      )}

      <SplitPanes
        ref={paneRef}
        // On both panes, because it is the paper's size and not the prose's.
        // Set on the passage alone, the control made nine hundred words
        // bigger and left the questions beside them at the size somebody
        // had already said was too small.
        style={{ fontSize: `${textSize}%` }}
        height={paneH}
        split={wide}
        leftLabel={sorted.length > 1 ? "Passages" : "Passage"}
        rightLabel="Questions"
        // Switching to the passage on a narrow screen is somebody looking
        // something up about the question they are on, so it opens at that
        // question's passage rather than wherever it was left.
        onShowing={(side) => {
          if (side === "left") showPassage();
        }}
        left={
          <div
            className="space-y-10 pt-15"
            onMouseOver={(e) => look(e.target)}
            onFocusCapture={(e) => look(e.target)}
            onMouseLeave={() => setLit(null)}
          >
            {/* Over the passage, because that is what it names. One line:
                what the book calls it, and which test it came from. */}
            {/* An arrival note, not chrome. Both of these used to sit in the
                layout above the panes, where they cost every reader forty
                pixels of passage for something that is read once. Inside the
                pane they scroll away with the paragraph they are next to,
                which is what a note read once should do. */}
      {material.last_attempt && (
        <Link
          to={`/reading/attempts/${material.last_attempt.attempt_id}`}
          className="mb-4 flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-lg border border-border bg-card px-4 py-2.5 transition-colors duration-fast hover:border-border-strong focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          <span className="text-sm text-foreground">You have sat this</span>
          <span className="text-sm tabular-nums text-muted-foreground">
            {material.last_attempt.score} / {material.last_attempt.total_questions}
            {" · "}
            {timeAgo(material.last_attempt.submitted_at)}
          </span>
          <span className="ml-auto inline-flex items-center gap-1 text-sm text-primary">
            See what you got wrong
            <ArrowRight className="size-3.5" aria-hidden />
          </span>
        </Link>
      )}

      {resumed && (
        <p className="mb-4 flex items-center gap-2 text-xs text-muted-foreground">
          Picked up where you left off.
          <button
            type="button"
            onClick={() => {
              clearSession(sessionKey);
              session.current = newSession();
              setAnswers({});
              setFlagged(new Set());
              setResumed(false);
            }}
            className="rounded-md px-1.5 py-0.5 text-primary transition-colors duration-fast hover:bg-primary/10 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            Start over
          </button>
        </p>
      )}

            {/* Centred over the column it names, and larger than the prose
                under it — it is the passage's heading, and a heading set at
                the body's own size is a first line rather than a title. */}
            <div className="-mt-1 text-center">
              <h1 className="text-[1.35em] font-semibold text-balance text-foreground">
                {material.title}
              </h1>
              <p className="mt-1 text-[0.8em] tabular-nums text-muted-foreground">
                {[
                  material.reference !== material.title
                    ? material.reference
                    : null,
                  sorted.length > 1 ? `${sorted.length} passages` : null,
                  `${total} ${total === 1 ? "question" : "questions"}`,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </div>
            {sorted.map((part, index) =>
              part.passage ? (
                <PassagePane
                  key={part.id}
                  partId={part.id}
                  title={part.title || `Reading Passage ${index + 1}`}
                  showTitle={sorted.length > 1}
                  passage={part.passage}
                  highlight={lit}
                  highlights={marks}
                  onUnmark={(index, offset) =>
                    keep(withoutAt(marks, part.id, index, offset))
                  }
                />
              ) : null,
            )}
          </div>
        }
        right={
          <div
            className="pt-15"
            onKeyDown={onPaperKeyDown}
            onMouseOver={(e) => look(e.target)}
            onMouseLeave={() => setLit(null)}
          >
            <QuestionPaper
              material={material}
              partWord="Passage"
              litParagraph={lit}
              answers={answers}
              onChange={onAnswer}
              flagged={flagged}
              onFlag={onFlag}
              disabled={submitMut.isPending || out}
              onFocus={(e) => {
                // Tab lands on a question the same way a pointer does, and
                // the passage should follow either.
                look(e.target);
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
            {submitMut.isError && (
              <p className="mt-6 text-right text-xs text-destructive">
                {getErrorMessage(submitMut.error)} — your answers are still here.
              </p>
            )}
          </div>
        }
      />

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
 * The paper's shape, held open while it loads.
 *
 * Built from the real component's own class strings, never from measured
 * pixels — `frontend/CLAUDE.md`. The container, the back link and the two
 * columns are the real ones; only what depends on the material is a bar.
 */
function TakeSkeleton() {
  return (
    <SkeletonBlock
      label="Loading passage"
      className="-mt-23 -mb-8 mx-[calc(50%-50vw)] flex w-auto flex-col overflow-hidden px-4 sm:px-6"
    >
      {/* The real container, the real breakout, the real header clearance —
          so the page does not jump sideways or upwards when the paper
          lands. No back link and no title bar, because the real one has
          neither: they are in the header's islands, which are the app's own
          and are already there. */}
      <div className="flex gap-5 pt-15">
        {/* The passage: a title and its paragraphs, at the real leading so
            the column is the height it will be. */}
        <div className="w-1/2 space-y-4 pr-5 text-center">
          <h1 className="text-[1.35em] font-semibold">
            <Skeleton className="inline-block h-[0.8em] w-72 max-w-full" />
          </h1>
          <div className="space-y-4 text-left">
            {[0, 1, 2].map((block) => (
              <div key={block} className="space-y-2">
                {[0, 1, 2, 3].map((line) => (
                  <p key={line} className="text-[0.95em] leading-[1.72]">
                    <Skeleton
                      className={cn(
                        "inline-block h-[0.8em]",
                        // The last line of a paragraph is short, and a block
                        // of four full-width bars reads as a table rather
                        // than as prose about to arrive.
                        line === 3 ? "w-3/5" : "w-full",
                      )}
                    />
                  </p>
                ))}
              </div>
            ))}
          </div>
        </div>
        <div className="w-px shrink-0 bg-border" />
        <div className="min-w-0 flex-1 pl-5">
          <PaperSkeleton />
        </div>
      </div>
    </SkeletonBlock>
  );
}

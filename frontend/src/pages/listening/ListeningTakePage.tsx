import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Loader2 } from "lucide-react";
import { PageLoader } from "@/components/ui/spinner";
import { toast } from "@/lib/toast";
import { getErrorMessage } from "@/lib/api";
import { mediaUrl } from "@/features/listening/api";
import { useSubmitAttempt, useTakeMaterial } from "@/features/listening/queries";
import {
  PartChips,
  QuestionPaper,
} from "@/features/listening/components/QuestionPaper";
import {
  TakeAudio,
  type TakeAudioHandle,
} from "@/features/listening/components/TakeAudio";
import { questionSpan, sorted } from "@/features/listening/numbering";
import { usePartSpy } from "@/features/listening/use-part-spy";
import { PRACTICE } from "@/features/listening/take-config";
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
} from "@/features/listening/take-session";

/**
 * Practice: the material, its recording, and nothing between the two.
 *
 * There is no mode switch here and there shouldn't be. Opening a material is
 * practice; the exam is somewhere a candidate goes on purpose, and choosing to
 * be there IS the consent to its rules. What that page will reuse is
 * everything below — the audio control, the groups, the submit — handed a
 * different TakeConfig. Which is why no rule is written into this file: the
 * one place practice differs from an exam is the constant it passes in.
 *
 * The page also watches itself being used, quietly. None of it is shown (a
 * clock on the wall changes how people work) and none of it can change a
 * mark; it is collected because an attempt that has already happened can
 * never be measured afterwards.
 */

export default function ListeningTakePage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: material, isLoading, isError } = useTakeMaterial(id);
  const submitMut = useSubmitAttempt(id ?? "");
  const config = PRACTICE;

  const audio = useRef<TakeAudioHandle>(null);

  // Answers are state because they are on the screen. Everything else the
  // session accumulates — timings, played spans, backward seeks — is a ref:
  // it arrives several times a second while the audio runs, and none of it
  // changes a pixel.
  const restored = useRef(id ? loadSession(id) : null);
  const [answers, setAnswers] = useState<Record<string, string>>(
    () => restored.current?.answers ?? {},
  );
  const session = useRef<TakeSession>(restored.current ?? newSession());
  const [resumed, setResumed] = useState(() => restored.current !== null);
  const [confirming, setConfirming] = useState(false);

  const parts = useMemo(() => (material ? sorted(material.parts) : []), [material]);
  const activePart = usePartSpy(parts);

  /** Every question on the paper, with how many of the paper's NUMBERS it
   *  takes. Not just a list of ids, because "3 of 25 answered" over a test
   *  the server marks out of 26 is two different tests — a "choose TWO
   *  letters" is one row and two numbers, and the count in the header has to
   *  be the count the score is out of. */
  const paper = useMemo(() => {
    const rows: { id: string; span: number }[] = [];
    for (const part of parts) {
      for (const group of sorted(part.question_groups)) {
        const span = questionSpan(group.config.answers_per_question);
        for (const q of group.questions) rows.push({ id: q.id, span });
      }
    }
    return rows;
  }, [parts]);

  const allQuestionIds = useMemo(() => paper.map((r) => r.id), [paper]);

  const total = paper.reduce((n, row) => n + row.span, 0);
  // A "choose TWO" with one letter picked is half answered, and says so. It
  // is also the one case where a candidate can leave a number blank without
  // leaving a field empty, which is exactly what the warning is for.
  const answered = paper.reduce((n, row) => {
    const value = (answers[row.id] ?? "").trim();
    if (!value) return n;
    if (row.span === 1) return n + 1;
    return n + Math.min(row.span, value.split(",").filter(Boolean).length);
  }, 0);
  const blank = total - answered;

  // --- Keeping the draft ----------------------------------------------------

  const persist = useCallback(
    (next: Record<string, string>) => {
      if (!id) return;
      session.current = { ...session.current, answers: next };
      saveSession(id, session.current);
    },
    [id],
  );

  const sinceStart = () => Date.now() - session.current.startedAt;

  const onAnswer = useCallback(
    (questionId: string, value: string) => {
      session.current = {
        ...session.current,
        timing: recordTouch(
          session.current.timing,
          questionId,
          value,
          sinceStart(),
        ),
      };
      setAnswers((prev) => {
        const next = { ...prev, [questionId]: value };
        persist(next);
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
      session.current = { ...session.current, listened: [...spans, span] };
      if (id) saveSession(id, session.current);
    },
    [id],
  );

  const onSeekBack = useCallback(() => {
    session.current = {
      ...session.current,
      seeksBack: session.current.seeksBack + 1,
    };
    // Persisted here and not left to the next save. A seek backwards while
    // the audio is paused emits no span, so nothing else was going to write,
    // and a reload would drop the count back to what it was.
    if (id) saveSession(id, session.current);
  }, [id]);

  // Space plays and pauses — unless something that uses the space bar itself
  // has focus, in which case it is theirs.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== "Space" && e.key !== " ") return;
      const target = e.target as HTMLElement | null;
      if (target?.closest("input, select, textarea, button, [contenteditable]")) {
        return;
      }
      e.preventDefault();
      audio.current?.toggle();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // --- Submitting -----------------------------------------------------------

  const send = () => {
    if (!id) return;
    closeFocus();
    setConfirming(false);
    submitMut.mutate(toSubmit(session.current, allQuestionIds), {
      onSuccess: (result) => {
        clearSession(id);
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

  if (!id) return null;
  if (isLoading) return <PageLoader />;
  if (isError || !material) {
    return (
      <div className="mx-auto max-w-3xl space-y-4 py-10">
        <p className="text-sm text-destructive">
          couldn&apos;t load this listening material.
        </p>
        <Link
          to="/listening"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          back to listening
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl pb-24">
      {/* Header. Deliberately thin: the candidate's attention belongs to the
          audio and the questions, and everything here is a way out or a
          count. */}
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 pt-2 pb-4">
        <Link
          to="/listening"
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" />
          listening
        </Link>
        <h1 className="min-w-0 flex-1 truncate text-lg font-semibold text-foreground">
          {material.title}
        </h1>
        <span className="font-mono text-xs tabular-nums text-muted-foreground">
          {answered} of {total} answered
        </span>
      </div>

      {/* The sticky band is flush with the bottom of the app header — 12px of
          padding plus a 48px pill — so the strip of paper still visible above
          it is exactly the header's own strip. Left even a few pixels lower,
          the band cuts a line of the form in half, and half a table row
          scrolling past reads as a rendering fault rather than as the
          floating header it is. */}
      {material.audio_url && (
        <div className="sticky top-[3.75rem] z-20 -mx-1 bg-background/90 px-1 py-2 backdrop-blur-md">
          <TakeAudio
            ref={audio}
            src={mediaUrl(material.audio_url)}
            durationMs={material.duration_ms}
            config={config}
            onSpan={onSpan}
            onSeekBack={onSeekBack}
          />
          <PartChips parts={parts} active={activePart} />
        </div>
      )}

      {resumed && (
        <p className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          picked up where you left off.
          <button
            type="button"
            onClick={() => {
              clearSession(id);
              session.current = newSession();
              setAnswers({});
              setResumed(false);
            }}
            className="rounded-md px-1.5 py-0.5 text-primary transition-colors hover:bg-primary/10"
          >
            start over
          </button>
        </p>
      )}

      {/* One focus listener for the whole paper. React's onFocus/onBlur are
          focusin/focusout, so they bubble up from the inputs inside. */}
      <div className="mt-6">
        <QuestionPaper
          material={material}
          answers={answers}
          onChange={onAnswer}
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

      <div className="mt-12 border-t border-border pt-6">
        {confirming && (
          <p className="mb-3 text-sm text-warning">
            {blank} {blank === 1 ? "question is" : "questions are"} blank.
            submit anyway?
          </p>
        )}
        <div className="flex items-center justify-end gap-2">
          {confirming && (
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-foreground/8 hover:text-foreground"
            >
              keep working
            </button>
          )}
          <button
            type="button"
            onClick={onSubmit}
            disabled={submitMut.isPending}
            className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-60"
          >
            {submitMut.isPending && (
              <Loader2 className="size-4 animate-spin" aria-hidden />
            )}
            {confirming ? "submit anyway" : "submit"}
          </button>
        </div>
        {submitMut.isError && (
          <p className="mt-3 text-right text-xs text-destructive">
            {getErrorMessage(submitMut.error)} — your answers are still here.
          </p>
        )}
      </div>
    </div>
  );
}

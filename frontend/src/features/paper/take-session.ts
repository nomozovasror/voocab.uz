import type {
  AnswerTiming,
  AttemptSubmit,
  ListenedSpan,
} from "@/features/paper/types";

/**
 * Everything a half-finished attempt consists of, and how it survives the tab
 * being closed.
 *
 * A learner who reloads the page mid-test has not asked to start again. So
 * the whole session — the answers, when each one arrived, and what has been
 * played — is written to localStorage and read back on the way in. The
 * measurements travel with the answers rather than being dropped on reload,
 * because a statistic that quietly resets to zero every time someone hits F5
 * is worse than no statistic: it looks like data.
 *
 * localStorage and not the server: a draft is worth keeping, not worth a
 * round trip per keystroke, and the exam-mode session that WILL need the
 * server (so a refresh can't restart the recording) is a different mechanism
 * with a different reason to exist.
 */

/** Milliseconds. What a session is allowed to sit unfinished before it is
 *  treated as abandoned — three hours is a long IELTS listening test plus a
 *  lunch break, and a "resumed" draft older than that is a stranger's. */
const STALE_AFTER_MS = 3 * 60 * 60 * 1000;

/** The server refuses more than this (see AttemptSubmit), so the page stops
 *  collecting rather than posting something that will 422. A session with
 *  five hundred separate plays in it has already said what it had to say. */
export const MAX_SPANS = 500;

export interface TakeSession {
  /** Epoch ms. Wall-clock here and nowhere else: it is only ever used to
   *  subtract from another local reading, and the submit sends the resulting
   *  duration rather than either timestamp. */
  startedAt: number;
  answers: Record<string, string>;
  timing: Record<string, AnswerTiming>;
  listened: ListenedSpan[];
  seeksBack: number;
  /** How much of `startedAt`-to-now anybody was actually present for.
   *
   *  Banked here rather than recomputed, because it cannot be: a reload
   *  leaves `startedAt` intact and the clock keeps running, but the minutes
   *  somebody spent in another tab before the reload are gone unless they
   *  were written down. See `use-active-time`.
   *
   *  Absent in a draft written before this existed, which is why it is
   *  optional and why every reader defaults it. */
  activeMs?: number;
  /** Question ids the candidate marked to come back to.
   *
   *  Part of the draft rather than a piece of page state, for the same reason
   *  the answers are: somebody who reloads mid-paper has not asked to lose
   *  the note they made about question 12. Never submitted — it is a note to
   *  themselves about a paper in progress, and after grading there is nothing
   *  left to come back to. */
  flagged: string[];
}

export function newSession(): TakeSession {
  return {
    startedAt: Date.now(),
    answers: {},
    timing: {},
    listened: [],
    seeksBack: 0,
    activeMs: 0,
    flagged: [],
  };
}

const key = (materialId: string) => `voocab.take.${materialId}`;

/** The stored session for this material, or null — for any reason at all.
 *  Storage can be full, disabled, or holding something written by an older
 *  version of this page, and none of those is worth an error in front of
 *  someone who came here to do a listening test. */
export function loadSession(materialId: string): TakeSession | null {
  try {
    const raw = window.localStorage.getItem(key(materialId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<TakeSession>;
    if (typeof parsed?.startedAt !== "number") return null;
    if (Date.now() - parsed.startedAt > STALE_AFTER_MS) {
      clearSession(materialId);
      return null;
    }
    return {
      startedAt: parsed.startedAt,
      answers: parsed.answers ?? {},
      timing: parsed.timing ?? {},
      listened: parsed.listened ?? [],
      seeksBack: parsed.seeksBack ?? 0,
      flagged: parsed.flagged ?? [],
    };
  } catch {
    return null;
  }
}

export function saveSession(materialId: string, session: TakeSession): void {
  try {
    window.localStorage.setItem(key(materialId), JSON.stringify(session));
  } catch {
    // Full, or disabled. The test still works; only the draft is lost.
  }
}

export function clearSession(materialId: string): void {
  try {
    window.localStorage.removeItem(key(materialId));
  } catch {
    /* see above */
  }
}

/** Note that an answer was touched.
 *
 *  ``at`` is milliseconds since the session started, not a timestamp — see
 *  AnswerTiming. Clearing a field back to empty still counts as touching it,
 *  but it is not an answer arriving, so ``first_answered_ms`` stays where it
 *  was.
 *
 *  Note what is NOT counted here: revisions. Typing "engineer" is eight
 *  keystrokes and one answer, and a counter incremented per keystroke would
 *  measure word length. See `recordVisit`. */
export function recordTouch(
  timing: Record<string, AnswerTiming>,
  questionId: string,
  value: string,
  at: number,
): Record<string, AnswerTiming> {
  const prev = timing[questionId] ?? {};
  const answered = value.trim().length > 0;
  return {
    ...timing,
    [questionId]: {
      ...prev,
      first_answered_ms:
        prev.first_answered_ms ?? (answered ? at : undefined),
      last_changed_ms: at,
    },
  };
}

/** Close out one visit to a question: how long it held focus, and whether the
 *  answer is different now than when the visit began.
 *
 *  A revision is measured per VISIT rather than per keystroke, which is what
 *  makes it mean anything. "They came back to question 7 and changed it" is a
 *  fact about someone doubting an answer; "they pressed eight keys" is a fact
 *  about the word being eight letters long. */
export function recordVisit(
  timing: Record<string, AnswerTiming>,
  questionId: string,
  heldMs: number,
  changed: boolean,
): Record<string, AnswerTiming> {
  const prev = timing[questionId] ?? {};
  return {
    ...timing,
    [questionId]: {
      ...prev,
      focus_ms: (prev.focus_ms ?? 0) + heldMs,
      ...(changed ? { changes: (prev.changes ?? 0) + 1 } : {}),
    },
  };
}

/** The session as the submit endpoint wants it.
 *
 *  Every question gets a row, answered or not: a blank is an answer to a
 *  question, and the server writes a QuestionAttempt for each one either way.
 *  Timing is attached only where something was actually measured — sending
 *  ``{}`` for a question nobody touched would record zeros as if they were
 *  observations.
 */
export function toSubmit(
  session: TakeSession,
  questionIds: string[],
): AttemptSubmit {
  const elapsed = Math.max(0, Date.now() - session.startedAt);
  return {
    answers: questionIds.map((question_id) => {
      const timing = session.timing[question_id];
      return {
        question_id,
        given_answer: session.answers[question_id] ?? "",
        ...(timing ? { timing } : {}),
      };
    }),
    listened: session.listened.slice(0, MAX_SPANS),
    seeks_back: session.seeksBack,
    elapsed_ms: elapsed,
    // Never more than the wall clock, whatever the tab did to the interval
    // that accumulated it. A figure larger than the time the page was open
    // is one nobody can explain, and it would be the one the statistics use.
    active_ms: Math.min(elapsed, Math.max(0, session.activeMs ?? 0)),
  };
}

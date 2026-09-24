import type {
  ActiveLevel,
  ExerciseType,
  PassiveLevel,
  PracticeMode,
  WordStatus,
} from "@/features/vocabulary/types";

/**
 * Words in plain words — status, level and task, wherever they are printed.
 *
 * One table rather than four call sites spelling out "Set aside" versus
 * `suspended`, for the same reason `cefr.ts` is one table: the wire names a
 * VERB (`suspend`) or a state (`suspended`) and a learner is never shown
 * either — only what a teacher would call it out loud.
 */

export const STATUS_LABEL: Record<WordStatus, string> = {
  learning: "Learning",
  review: "Review",
  known: "Known",
  suspended: "Set aside",
  leech: "Leech",
};

/** A STATE and the ACTION that produces it are named differently on
 *  purpose, everywhere both appear (the words list's bulk bar, the word
 *  page's own buttons, the practice session's known-check reveal): a status
 *  line reads "Known" the way it reads "Learning" or "Leech" — a noun for
 *  what the word IS — and a button reads as a verb for what pressing it
 *  DOES. `STATUS_LABEL.known` already serves the state; these two are the
 *  buttons, and the ordinary (non-known, non-suspended) state that
 *  `WordStatus` has no name of its own for, because `learning`/`review` are
 *  both just "in rotation" to a learner deciding whether to leave a word
 *  alone. */
export const ACTION_LABEL = {
  markKnown: "Mark as known",
  returnToRotation: "Return to rotation",
} as const;

/** The state `ACTION_LABEL.returnToRotation` restores TO — not a
 *  `WordStatus` (a restored word could land in `learning` or `review`
 *  depending on its schedule), and not printed from `STATUS_LABEL` for that
 *  reason. Used wherever a status line needs to say "back to normal"
 *  without claiming to know which of the two it will be. */
export const IN_ROTATION_LABEL = "In rotation";

/** Never `correct`/`incorrect` — those are the review's verdict colours,
 *  and a status is not a grade. `known` borrows `correct` anyway, on
 *  purpose: it is the one status that IS an unambiguous win, unlike
 *  `learning`/`review`, which are just where a word happens to be. */
export const STATUS_TONE: Record<WordStatus, string> = {
  learning: "text-muted-foreground",
  review: "text-foreground",
  known: "text-correct",
  suspended: "text-muted-foreground",
  leech: "text-attention",
};

/** The three tasks, named the way the brief names them rather than by their
 *  wire value — "Fill the gap" is what a learner is doing, `recall` is what
 *  the ladder calls it. Shared between the home screen's mode picker and
 *  the settings page's default so the two screens never call one task two
 *  things. */
export const EXERCISE_LABEL: Record<ExerciseType, string> = {
  recognise: "Recognise",
  recall: "Fill the gap",
  produce: "Write",
};

export const MODE_LABEL: Record<PracticeMode, string> = {
  auto: "Mixed",
  ...EXERCISE_LABEL,
};

/** FSRS's own four grades, named the way the reveal never has to (the
 *  session shows a verdict — correct/close/wrong — never this) but the
 *  word page's history does, because a compact log of "Good, Good, Again,
 *  Hard" is exactly what somebody re-reading their own trail wants. */
export const RATING_LABEL: Record<1 | 2 | 3 | 4, string> = {
  1: "Again",
  2: "Hard",
  3: "Good",
  4: "Easy",
};

export const RATING_TONE: Record<1 | 2 | 3 | 4, string> = {
  1: "text-incorrect",
  2: "text-warning",
  3: "text-correct",
  4: "text-correct",
};

/** A direction's level, in a sentence rather than a wire token — the word
 *  page's "per-direction state in plain words" (the spec's §Frontend). */
export function passiveLevelLabel(level: PassiveLevel): string {
  return level === "recognise" ? "Recognising it" : "Recalling it";
}

export function activeLevelLabel(level: ActiveLevel | null): string {
  if (!level) return "Not started";
  return level === "recognise" ? "Recognising it" : "Producing it";
}

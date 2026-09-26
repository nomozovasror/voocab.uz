import type {
  ActiveLevel,
  ExerciseType,
  LeechChoice,
  PassiveLevel,
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

/** A STATE and the ACTION that produces it are named differently on
 *  purpose, everywhere both appear (the words list's row menu and bulk bar,
 *  the word page's own buttons, the practice session's known-check reveal):
 *  a status line reads "Known" the way it reads "In rotation" or "Leech" —
 *  a noun for what the word IS — and a button reads as a verb for what
 *  pressing it DOES. */
export const ACTION_LABEL = {
  markKnown: "Mark as known",
  returnToRotation: "Return to rotation",
  setAside: "Set aside",
} as const;

/** The state `ACTION_LABEL.returnToRotation` restores TO — not a
 *  `WordStatus` (a restored word could land in `learning` or `review`
 *  depending on its schedule), and not printed from a per-`WordStatus` table
 *  for that reason. Used wherever a status line needs to say "back to
 *  normal" without claiming to know which of the two it will be. */
export const IN_ROTATION_LABEL = "In rotation";

/**
 * The four chips a learner actually sees, per the fixes brief's §7 table —
 * `learning` and `review` are both just "in rotation" to somebody deciding
 * whether to leave a word alone, and showing them as two different chips
 * would be a distinction the FSRS engine cares about and a learner never
 * asked for.
 */
export type StatusChip = "known" | "in_rotation" | "suspended" | "leech";

export function statusChip(status: WordStatus): StatusChip {
  if (status === "learning" || status === "review") return "in_rotation";
  return status;
}

export const STATUS_CHIP_LABEL: Record<StatusChip, string> = {
  known: "Known",
  in_rotation: IN_ROTATION_LABEL,
  suspended: "Set aside",
  leech: "Leech",
};

/** Never `correct`/`incorrect` — those are the review's verdict colours,
 *  and a status is not a grade. A grey scale instead, ordered by how much
 *  attention the word wants: `known` is dim (done, nothing to see),
 *  `in_rotation` is the page's own text colour (ordinary), `suspended` is
 *  dimmer still (deliberately set aside, quietest of the four), and `leech`
 *  alone takes the accent — the one status that is genuinely asking for a
 *  decision. Never green/red (verdicts) and never a CEFR colour (those name
 *  difficulty, not standing). */
export const STATUS_CHIP_TONE: Record<StatusChip, string> = {
  known: "text-muted-foreground",
  in_rotation: "text-foreground",
  suspended: "text-muted-foreground/60",
  leech: "text-attention",
};

/** The settings page's single manual choice, named exactly as the fixes
 *  brief's §2/§9 want them said out loud — not the wire token, and not the
 *  stage 1 mode picker's "Fill the gap"/"Write" either, since that picker is
 *  gone and this is the only place these three names are said now. */
export const EXERCISE_LABEL: Record<ExerciseType, string> = {
  recognise: "Recognise",
  recall: "Recall",
  produce: "Produce",
};

/** The manual choice's fourth option — not an `ExerciseType`, so it is not
 *  part of `EXERCISE_LABEL`. */
export const AUTOMATIC_LABEL = "Automatic";

/** The three choices a `became_leech` reveal — or a leech word's own page —
 *  offers, named exactly as the fixes brief's §5 wants them said. Never a
 *  fourth "suspend forever": a leech word is only ever moved by one of
 *  these three, chosen by the learner. */
export const LEECH_LABEL: Record<LeechChoice, string> = {
  set_aside: "Set aside",
  see_context: "See it in context",
  keep: "Keep going",
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

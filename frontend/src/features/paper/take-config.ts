/**
 * What the person sitting the material is allowed to do.
 *
 * These are the exam rules, and they are a value rather than a build-time
 * fact about the page. Practice and exam are the same test, sat under
 * different constraints — a page hard-coded to "audio is free" would have to
 * be rewritten (or, worse, forked) the day exam mode arrives, and the two
 * copies would drift the way two copies always do. So the take page renders
 * whatever it is handed, and the rules live here.
 *
 * Nothing in here is a security boundary. A rule that only exists in the
 * browser is a rule a determined candidate can lift, so exam-mode enforcement
 * that actually matters (one attempt, the recording playing once, the clock
 * running whether or not the tab is open) belongs to the server session that
 * will hold the exam. What this type does is describe the page.
 */
export interface TakeConfig {
  /** Can the playhead be moved — dragged, nudged, sent back to a moment they
   *  missed? False leaves play/pause and nothing else. */
  allowSeek: boolean;
  /** Can the recording be stopped part-way? False is the exam hall: it plays,
   *  and you keep up. */
  allowPause: boolean;
  /** Can it be played again once it has finished? IELTS plays each recording
   *  exactly once, so this is the rule that makes an exam an exam. */
  allowReplay: boolean;
  /** Can the recording be slowed down or sped up? A rule like the others,
   *  and the one most obviously not an exam's: nobody gets to slow down the
   *  invigilator. */
  allowSpeed: boolean;
  /** What the button that ends the attempt is called.
   *
   *  A rule like the others, and one that changes what the page MEANS.
   *  Practice is somewhere you check your answers and then go back and work
   *  on them, so "Check answers" is the truth; "Submit" and "Finish" both
   *  promise a door closing behind you, which is the exam's promise and not
   *  this page's. */
  submitLabel: string;
  /** Is a clock shown at all? Separate from whether time is being MEASURED:
   *  every attempt is timed, and a paper can decline to say so.
   *
   *  Listening does decline. The recording is the clock there — it ends and
   *  the questions end with it — so a second one on screen would be counting
   *  something nothing depends on. Reading has nothing of the kind, and
   *  pace is the skill it is short of: the same candidate who scores 35 with
   *  no clock scores 25 in sixty minutes, and the gap between those two
   *  numbers is what a reading paper is actually for. */
  showTimer: boolean;
  /** Which direction it runs.
   *
   *  `countUp` is a measurement — how long this is taking, beside how long
   *  it ought to. `countDown` is a constraint, and it belongs to the exam:
   *  putting one on practice would say the opposite of what practice is for. */
  timerMode: "countUp" | "countDown";
  /** How long the paper is allowed to take, for `countDown`. Null means "work
   *  it out from the questions" — see `paperMs`. */
  durationMs?: number | null;
  /** Does the visible clock stop when nobody is there?
   *
   *  In practice it does: the number is a measurement, and a measurement
   *  that counts the twenty minutes somebody spent in another tab is a
   *  measurement of nothing. In an exam it does not, because the real one
   *  does not either — a candidate who looks away still loses the time.
   *
   *  What is collected for the STATISTICS is idle-adjusted either way; this
   *  is only about the number on screen. */
  pauseOnIdle: boolean;
  /** May the reader open a dictionary?
   *
   *  Not in an exam — there is none in the hall, and a paper worked with one
   *  measures comprehension-with-help. In practice there is a budget rather
   *  than a licence: three words a passage, which is what makes looking one
   *  up a decision instead of a habit. See `features/reading/lookups.ts`. */
  allowLookup: boolean;
}

/** What one question is worth, in the exam's own arithmetic.
 *
 *  An IELTS Reading paper is forty questions in sixty minutes, which is
 *  ninety seconds each. Every clock on this page is that number multiplied:
 *  the twenty minutes a three-passage paper allows per passage falls out of
 *  it, and so does the shorter allowance for a thirteen-question passage
 *  rather than a fourteen. A flat "twenty minutes" would be wrong for both
 *  ends of the corpus and right for nothing in particular. */
export const PER_QUESTION_MS = 90_000;

/** How long a paper of this many questions is worth, to the nearest minute. */
export function paperMs(questions: number): number {
  return Math.round((questions * PER_QUESTION_MS) / 60_000) * 60_000;
}

/** Everything free. Practice is for working out what you got wrong, and every
 *  restriction below is one that only makes sense when the point is to
 *  measure you instead. */
export const PRACTICE: TakeConfig = {
  allowSeek: true,
  allowPause: true,
  allowReplay: true,
  allowSpeed: true,
  showTimer: false,
  timerMode: "countUp",
  pauseOnIdle: true,
  allowLookup: true,
  submitLabel: "Check answers",
};

/** Practice, with the clock reading's practice needs and listening's does
 *  not. Everything else is `PRACTICE` — the audio flags are inert on a
 *  passage, and they are left alone rather than removed so the two configs
 *  can be read against each other. */
export const READING_PRACTICE: TakeConfig = {
  ...PRACTICE,
  showTimer: true,
};

/** The exam: a countdown, and it runs whether or not anybody is watching.
 *
 *  Not reachable from a route yet — there is no exam mode to enter. It is
 *  written here rather than later because the take screen has to know what
 *  it will be handed, and because a countdown built the day the route
 *  arrives is a countdown nobody has watched reach zero. */
export const READING_EXAM: TakeConfig = {
  ...PRACTICE,
  allowSeek: false,
  allowPause: false,
  allowReplay: false,
  allowSpeed: false,
  showTimer: true,
  timerMode: "countDown",
  pauseOnIdle: false,
  allowLookup: false,
  submitLabel: "Finish",
};

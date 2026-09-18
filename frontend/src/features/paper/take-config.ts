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
  /** Is a countdown shown? Separate from whether one is RUNNING: practice
   *  measures how long everything took and simply doesn't say so, because a
   *  clock on the wall changes how people work. */
  showTimer: boolean;
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
  submitLabel: "Check answers",
};

/**
 * Which numbers are worth stopping for.
 *
 * Publishing every material to confetti stops meaning anything by the third
 * one — a celebration that always fires is just a slower toast. So the
 * ordinary publish gets an ordinary confirmation, and the screen is only
 * taken over on the counts that actually mark progress: the first, then every
 * tenth.
 *
 * Kept apart from the editor on purpose. This is the same question the
 * achievements section asks — what has this author reached, and when does it
 * deserve to be shown — and when that is built the rule belongs with it,
 * probably computed by the server across every kind of material rather than
 * counted in a page. Until then this is the one place that decides, so moving
 * it is a matter of changing what calls it.
 */

export interface PublishMilestone {
  /** How many materials the author has published, including this one. */
  count: number;
  /** The headline for the moment. */
  title: string;
  message: string;
}

export function publishMilestone(count: number): PublishMilestone | null {
  if (count === 1) {
    return {
      count,
      title: "Your first material is live",
      message:
        "It's out there. Anyone with the link can take it — and you've done the hard part once, which is the part that gets easier.",
    };
  }
  if (count > 0 && count % 10 === 0) {
    return {
      count,
      title: `${count} materials published`,
      message: `That's ${count} of them out in the world. Learners are working through your questions right now.`,
    };
  }
  return null;
}

/** `app.models.lexicon.REVIEW_REASONS`, mirrored — kept as a small ordered
 *  list rather than read off whatever keys a queue response happens to
 *  carry, so the filter chips have a stable order even before any reason
 *  has a nonzero count. */
export const REVIEW_REASONS = [
  "pos_mismatch",
  "judge_different",
  "judge_unsure",
  "ngsl_conflict",
  "material_level_gap",
  "lemma_merge",
] as const;

export type ReviewReason = (typeof REVIEW_REASONS)[number];

/** Readable chip labels — the enrichment run's own vocabulary
 *  (`app.services.lexicon_enrich`), put into words a reviewer reads once and
 *  never has to look up. */
export const REASON_LABEL: Record<ReviewReason, string> = {
  pos_mismatch: "Wrong part of speech",
  judge_different: "Translators disagreed",
  judge_unsure: "Judge unsure",
  ngsl_conflict: "Frequency conflict",
  material_level_gap: "Level gap vs. material",
  lemma_merge: "Lemma merge",
};

/** The synthetic second bucket — not a real reason, but filtered and
 *  counted the same way in the queue (`app.services.lexicon_review
 *  .CORE_REASON`). */
export const CORE_REASON = "core";

/** The synthetic FIRST bucket: a sense with an open "this translation is
 *  wrong" report, sorted ahead of everything else, `needs_review` included
 *  — a learner who reported it has already done the finding a reviewer
 *  would otherwise have to do themselves (`lexicon_review.REPORTED_REASON`,
 *  `ReviewQueue.reported_pending`). */
export const REPORTED_REASON = "reported";

/** What "Fix" may set a sense's level to — independent of the reading
 *  scale's `CEFR_LEVELS` (`features/vocabulary/cefr.ts`, B1–C1 only): a
 *  lexicon sense is graded freely across the whole framework, and an
 *  editor that could only write three of six levels would silently refuse
 *  the other three. */
export const CEFR_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"] as const;

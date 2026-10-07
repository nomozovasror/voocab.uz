/** GET /api/admin/lexicon/review — Studio's admin review tab. See
 *  `backend/app/schemas/lexicon.py` for the wire contract this mirrors. */

export interface ReviewRow {
  sense_id: string;
  lexeme_id: string;
  lemma: string;
  pos: string;
  is_phrase: boolean;
  cefr: string | null;
  /** The dictionary's own level for this sense: set on EVERY sense that took
   *  a dictionary definition, equal to `cefr` where it was taken, different
   *  where it was 2+ bands away and therefore NOT taken (`cald_cefr_far`, or
   *  a reviewer's own grade). Null where the dictionary has no level. Show it
   *  only where it differs from `cefr`. */
  cald_cefr: string | null;
  frequency_band: string | null;
  sense_rank: number;
  definition_en: string;
  meaning_uz: string;
  /** The other translator's candidate — empty where the judge agreed or the
   *  sense was copied from a material rather than machine-translated. */
  meaning_uz_alt: string;
  /** The material's own Uzbek this sense's meaning was copied from — empty
   *  for a list-only, translated sense. */
  meaning_uz_material: string;
  review_reasons: string[];
  needs_review: boolean;
  provisional: boolean;
  approved_by: string | null;
  /** Who approved it, by display name -- "Claude review" for the AI pass. */
  approved_by_name: string | null;
  approved_at: string | null;
  /** What the AI review left for a person to look at ("" when nothing). */
  review_note: string;
  material_example_count: number;
  /** How many OPEN "this translation is wrong" reports this sense
   *  currently carries — zero for the ordinary row, and what puts a row in
   *  the "Reported" bucket ahead of everything else. */
  report_count: number;
  /** The non-empty notes those open reports carry. */
  report_notes: string[];
  /** The plain sum of `exposure_parts` — how many people this sense has
   *  actually reached, and the queue's own ordering within a reason bucket
   *  (see `backend/app/services/CLAUDE.md`'s A1). Optional only so a client
   *  built against a server that hasn't landed it yet doesn't have to
   *  fabricate a number. */
  exposure?: number;
  exposure_parts?: {
    /** Learners who submitted an attempt on a material carrying this
     *  sense. */
    attempters: number;
    /** Lookup events that resolved to this sense. */
    lookups: number;
    /** Learners with this sense on their saved-words list. */
    saves: number;
  };
  /** How many materials this sense appears in — the tie-break under equal
   *  exposure. */
  material_count?: number;
}

export interface ReviewQueue {
  total: number;
  reason_counts: Record<string, number>;
  /** Top-frequency lexemes' rank-1 sense, never flagged and never approved —
   *  the queue's second bucket, not a review reason. */
  core_pending: number;
  /** Senses with an open translation report — the queue's FIRST bucket,
   *  counted the same way as `core_pending` because "reported" isn't a
   *  review reason either. */
  reported_pending: number;
  rows: ReviewRow[];
}

export interface ReviewContext {
  material_id: string;
  material_title: string;
  surface: string;
  example: string;
}

export interface ReviewFixPayload {
  meaning_uz?: string;
  definition_en?: string;
  cefr?: string;
}

/** GET /api/licences — the public "Data sources and licences" page. */

export interface LicenceSource {
  key: string;
  title: string;
  authors: string;
  licence_name: string;
  licence_url: string;
  source_url: string;
  count: number;
  /** Shown under the licence badge where non-empty — e.g. Princeton
   *  WordNet's "sense ordering only, not stored as definitions". */
  usage_note: string;
}

export interface Licences {
  sources: LicenceSource[];
}

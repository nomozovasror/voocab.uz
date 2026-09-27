/** GET /api/admin/lexicon/review — Studio's admin review tab. See
 *  `backend/app/schemas/lexicon.py` for the wire contract this mirrors. */

export interface ReviewRow {
  sense_id: string;
  lexeme_id: string;
  lemma: string;
  pos: string;
  is_phrase: boolean;
  cefr: string | null;
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
  approved_at: string | null;
  material_example_count: number;
}

export interface ReviewQueue {
  total: number;
  reason_counts: Record<string, number>;
  /** Top-frequency lexemes' rank-1 sense, never flagged and never approved —
   *  the queue's second bucket, not a review reason. */
  core_pending: number;
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
}

export interface Licences {
  sources: LicenceSource[];
}

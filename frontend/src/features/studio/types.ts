/** GET /api/studio/stats — the Studio dashboard's data source. Anything not
 *  covered by this contract (subscribers, per-type saves, account level,
 *  achievements) has no backing data yet and must render as "—", never a
 *  fabricated or zeroed number (see StudioDashboardPage). */

export interface StudioTypeStat {
  type: string;
  total: number;
  public: number;
  private: number;
  completions: number;
}

export interface StudioRecentItem {
  id: string;
  title: string;
  type: string;
  visibility: "public" | "private";
  item_count: number;
  created_at: string;
  updated_at: string;
}

export interface StudioStats {
  materials_total: number;
  content_ms: number;
  learners: number;
  completions: number;
  by_type: StudioTypeStat[];
  recent: StudioRecentItem[];
}

/** GET /api/studio/listening — the Listening Studio list page's data source.
 *  `avg_score_pct`/`attempts` (and everything on a processing row) have no
 *  honest value yet and must render as "—", never a fabricated 0 (see
 *  StudioListeningListPage). */

export type TranscriptStatus = "pending" | "processing" | "ready" | "failed";

export interface StudioListeningItem {
  id: string;
  title: string;
  visibility: "public" | "private";
  duration_ms: number | null;
  transcript_status: TranscriptStatus | null;
  question_type: string | null;
  question_count: number;
  attempts: number;
  avg_score_pct: number | null;
  updated_at: string;
}

export interface StudioListeningList {
  total: number;
  duration_ms: number;
  items: StudioListeningItem[];
}

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

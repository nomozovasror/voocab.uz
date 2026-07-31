export type Visibility = "private" | "public";

export interface SegmentInput {
  start_ms: number;
  end_ms: number;
  reference_text: string;
}

export interface Segment extends SegmentInput {
  id: string;
  order_index: number;
}

export interface Material {
  id: string;
  author_id: string;
  type: string;
  title: string;
  audio_url: string | null;
  case_sensitive: boolean;
  punctuation_sensitive: boolean;
  visibility: Visibility;
  created_at: string;
  segment_count: number;
}

export interface MaterialDetail extends Material {
  segments: Segment[];
}

export interface MaterialCreate {
  title: string;
  type?: string;
  audio_url?: string | null;
  case_sensitive?: boolean;
  punctuation_sensitive?: boolean;
  visibility?: Visibility;
  segments: SegmentInput[];
}

export type MaterialUpdate = Partial<MaterialCreate>;

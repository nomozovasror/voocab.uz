/**
 * Domain types for the dictation feature. These mirror the backend data model
 * (materials → segments → attempts → segment_attempts). Filled in as the
 * feature is built; kept here so components/hooks/api share one source of truth.
 */

export interface Segment {
  id: string;
  orderIndex: number;
  startMs: number;
  endMs: number;
  referenceText: string;
}

export interface DictationMaterial {
  id: string;
  title: string;
  audioUrl: string;
  caseSensitive: boolean;
  punctuationSensitive: boolean;
  segments: Segment[];
}

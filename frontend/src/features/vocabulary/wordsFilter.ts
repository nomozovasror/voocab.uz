/**
 * The words list's four filters — status, CEFR, source material, direction —
 * as one rule rather than two copies of the same `.filter()`.
 *
 * `VocabularyPage` (the list itself) and the Browse page (`brief-vocabulary-
 * tuzatish-browse.md`'s §C: Browse is "the learner's saved words with the
 * words-list filters ... in the list's filtered order") both narrow the same
 * `GET /vocabulary/words` response by the same four questions, and Browse's
 * whole promise is that its deck is EXACTLY what the list would show —
 * pressing "Browse" from a filtered list must not turn up a card the list
 * itself was hiding. One function is what keeps that true after either side
 * is next touched.
 */

import { asLevel, type CefrLevel } from "@/features/vocabulary/cefr";
import { statusChip, type StatusChip } from "@/features/vocabulary/status";
import type { SavedWord } from "@/features/vocabulary/types";

export type StatusFilterValue = "all" | StatusChip;
export type CefrFilterValue = "all" | CefrLevel;
export type MaterialFilterValue = "all" | string;
export type DirectionFilterValue = "all" | "passiveOnly" | "active";

export interface WordsFilterState {
  status: StatusFilterValue;
  cefr: CefrFilterValue;
  material: MaterialFilterValue;
  direction: DirectionFilterValue;
}

export const ALL_WORDS_FILTER: WordsFilterState = {
  status: "all",
  cefr: "all",
  material: "all",
  direction: "all",
};

export function filterWords(
  words: SavedWord[],
  filter: WordsFilterState,
): SavedWord[] {
  return words.filter((word) => {
    if (filter.status !== "all" && statusChip(word.status) !== filter.status) {
      return false;
    }
    if (filter.cefr !== "all" && asLevel(word.cefr_level) !== filter.cefr) {
      return false;
    }
    if (
      filter.material !== "all" &&
      !word.contexts.some((c) => c.material_id === filter.material)
    ) {
      return false;
    }
    if (filter.direction === "passiveOnly" && word.active_level !== null) {
      return false;
    }
    if (filter.direction === "active" && word.active_level === null) {
      return false;
    }
    return true;
  });
}

/** `WordsFilterState` as a query string, dropping any field left at `"all"`
 *  — the same convention `VocabularyPage`'s own `status` param already
 *  uses, so a filter nobody narrowed never shows up as `?cefr=all` in a
 *  link somebody might read. Shared so the words list's "Browse" button and
 *  the Browse page's own reading of `useSearchParams` cannot describe the
 *  same four fields two different ways. */
export function filterToParams(filter: WordsFilterState): URLSearchParams {
  const params = new URLSearchParams();
  if (filter.status !== "all") params.set("status", filter.status);
  if (filter.cefr !== "all") params.set("cefr", filter.cefr);
  if (filter.material !== "all") params.set("material", filter.material);
  if (filter.direction !== "all") params.set("direction", filter.direction);
  return params;
}

export function paramsToFilter(params: URLSearchParams): WordsFilterState {
  return {
    status: (params.get("status") as StatusFilterValue | null) ?? "all",
    cefr: (params.get("cefr") as CefrFilterValue | null) ?? "all",
    material: params.get("material") ?? "all",
    direction: (params.get("direction") as DirectionFilterValue | null) ?? "all",
  };
}

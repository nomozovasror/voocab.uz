import type { SavedWord } from "@/features/vocabulary/types";

/**
 * A saved word's own headline meaning — moved out of `VocabularyPage.tsx` so
 * the Browse page's card back can read the same fallback chain rather than
 * writing a second copy that drifts the first time either is touched.
 *
 * Prefers `definition_en`/`meaning_uz`, read LIVE off the word's
 * `LexemeSense` (an admin's fix in Studio shows up here with no migration);
 * falls back to stage 1's frozen `meaning_core_en`/`meaning_core_uz`, then to
 * a context that has one — a word kept before any of these fields existed
 * has none, and this prints nothing rather than guessing.
 */
export function wordMeaning(word: SavedWord): { en: string; uz: string } {
  if (word.definition_en || word.meaning_uz) {
    return { en: word.definition_en, uz: word.meaning_uz };
  }
  if (word.meaning_core_en || word.meaning_core_uz) {
    return { en: word.meaning_core_en, uz: word.meaning_core_uz };
  }
  const core = word.contexts.find((c) => c.meaning_core_en) ?? word.contexts[0];
  return {
    en: core?.meaning_core_en || core?.meaning_en || "",
    uz: core?.meaning_core_uz || core?.meaning_uz || "",
  };
}

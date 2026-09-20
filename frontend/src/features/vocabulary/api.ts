import { api } from "@/lib/api";
import type {
  Lookup,
  SavedWords,
  VocabularyList,
} from "@/features/vocabulary/types";

/**
 * The vocabulary endpoints, addressed by material id rather than by skill.
 *
 * Same split as `features/paper/api.ts`, for the same reason written there: a
 * caller holding a material id does not know which router minted it. Only
 * reading passages are glossed today, and the day a listening transcript is
 * extracted the same way, none of this changes.
 *
 * Note what is missing. There is no "fetch this passage's vocabulary" call
 * that the take screen may use: `list` is refused by the server to anybody
 * who has not submitted the paper. One word at a time while the clock is
 * running; the whole list on the review page, which is what it is for.
 */
export const vocabularyApi = {
  /** One tapped word, in this passage's sense.
   *
   *  A POST rather than a GET, and not for tidiness: this call can CREATE a
   *  row. A word the frequency filter did not think was hard gets glossed on
   *  the spot and kept, so the list grows towards what readers actually find
   *  difficult.
   *
   *  `paragraphIndex` and `offset` are what make the answer exact — an entry
   *  whose span contains that point needs no string matching, and a phrase is
   *  recognised by the same test. Sent whenever the caller knows them, which
   *  is nearly always. */
  lookUp: (
    materialId: string,
    word: string,
    where?: { paragraphIndex: number; offset: number },
  ) =>
    api.post<Lookup>(`/api/materials/${materialId}/lookups`, {
      json: {
        word,
        paragraph_index: where?.paragraphIndex,
        offset: where?.offset,
      },
    }),

  /** Everything worth learning in one material. 403 until the paper is
   *  submitted. */
  list: (materialId: string) =>
    api.get<VocabularyList>(`/api/materials/${materialId}/vocabulary`),

  /** Put words on the learner's list, with the sense they had here.
   *
   *  Takes an array because the review offers "save all" and "save the ones
   *  I looked up" beside the per-row button, and one verb with three
   *  endpoints is three places for the rules to drift. */
  save: (materialId: string, lemmas: string[]) =>
    api.post<SavedWords>("/api/vocabulary/words", {
      json: { material_id: materialId, lemmas },
    }),

  saved: () => api.get<SavedWords>("/api/vocabulary/words"),

  forget: (lemma: string) =>
    api.delete<void>(`/api/vocabulary/words/${encodeURIComponent(lemma)}`),
};

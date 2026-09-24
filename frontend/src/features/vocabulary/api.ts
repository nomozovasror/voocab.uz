import { api } from "@/lib/api";
import type {
  Lookup,
  PracticeAnswer,
  PracticeAnswerRequest,
  PracticeSession,
  PracticeSummary,
  SavedWords,
  VocabularyList,
  VocabularySettings,
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
/** The cache key for one material's whole vocabulary.
 *
 *  Written once because two things now read it: the review's word list, and
 *  the passage beside it, which is MARKED from the same rows. Two components
 *  spelling the key out themselves is how one of them ends up reading a copy
 *  it did not know it had — and here that would show as a save that greys the
 *  button and leaves the word in the passage drawn as unsaved. */
export const vocabularyKey = (materialId: string) => ["vocabulary", materialId];

/** The cache key for the practice home screen's numbers, `tz`-scoped because
 *  the figures themselves are (a learner who changes time zone mid-session
 *  is a different "today"). Exported so the practice session page can
 *  invalidate exactly this on finishing — the end screen's "next session"
 *  line and the home screen's due count are the same fact and must update
 *  together, or going back to `/vocabulary` after a session shows the
 *  numbers it just made stale. */
export const practiceSummaryKey = (tz: string) =>
  ["vocabulary", "practice", "summary", tz] as const;

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
   *  is nearly always.
   *
   *  `context` says which screen asked. It buys nothing the caller can see
   *  and is not a permission — the budget is the browser's and always was —
   *  but it is the only way the platform can ever learn the difference
   *  between "this word stopped me mid-paper" and "I read straight past this
   *  word and found out afterwards that I had not understood it". The second
   *  of those is what says the extraction's filter is cutting in the wrong
   *  place, and it cannot be recovered later from anything else. */
  lookUp: (
    materialId: string,
    word: string,
    where?: { paragraphIndex: number; offset: number },
    context: "take" | "review" = "take",
  ) =>
    api.post<Lookup>(`/api/materials/${materialId}/lookups`, {
      json: {
        word,
        paragraph_index: where?.paragraphIndex,
        offset: where?.offset,
        context,
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

  // --- Practice (stage 1) ----------------------------------------------
  //
  // `tz` travels on every call that reasons about "today" — the daily time
  // budget resets at midnight in the LEARNER's own IANA zone, not the
  // server's, and not UTC (a session sat at 11pm and again at 1am must
  // count as two different days for someone in Tashkent and one day for
  // someone nine hours west of them). `Intl.DateTimeFormat().resolvedOptions
  // ().timeZone` is what every caller reads it from.

  /** The home screen's numbers: what's due, what fits in today's time
   *  budget, and the running totals. Cheap and side-effect-free — reading
   *  it never advances anything, unlike `session`. */
  practiceSummary: (tz: string) =>
    api.get<PracticeSummary>("/api/vocabulary/practice/summary", {
      params: { tz },
    }),

  /** Builds today's queue, now — reviews first, most overdue first, then as
   *  many new words as the remaining time budget buys. Not idempotent in
   *  spirit (the "remaining budget" it reads shrinks as the day's other
   *  answers land) but safe to call again: nothing is marked practised
   *  until an answer is posted, so reloading the practice page mid-session
   *  costs a re-plan, not a lost place. `materialId` narrows to one
   *  material's words; omitted for the home screen's "Start" button, which
   *  practises everything due. */
  practiceSession: (tz: string, materialId?: string) =>
    api.post<PracticeSession>("/api/vocabulary/practice/session", {
      params: { tz },
      json: materialId ? { material_id: materialId } : {},
    }),

  /** One card's answer. The verdict, the FSRS rating it produced, and
   *  whether the card returns before the session ends are the server's to
   *  decide — see the spec's rating table — so this call sends only what
   *  happened (`given`, `elapsed_ms`) and never a guess at the grade. */
  practiceAnswer: (payload: PracticeAnswerRequest) =>
    api.post<PracticeAnswer>("/api/vocabulary/practice/answers", {
      json: payload,
    }),

  settings: () => api.get<VocabularySettings>("/api/vocabulary/settings"),

  /** Stage 1 only ever changes `daily_minutes`; the other fields are read
   *  back from the server's response rather than round-tripped through
   *  this call, so a client that has never seen `direction` cannot send it
   *  back wrong. */
  updateSettings: (dailyMinutes: VocabularySettings["daily_minutes"]) =>
    api.put<VocabularySettings>("/api/vocabulary/settings", {
      json: { daily_minutes: dailyMinutes },
    }),
};

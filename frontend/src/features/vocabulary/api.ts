import { api } from "@/lib/api";
import type {
  BulkWordsRequest,
  BulkWordsResponse,
  LeechChoice,
  LeechChoiceResponse,
  Lookup,
  OnTheGoList,
  PracticeAnswer,
  PracticeAnswerRequest,
  PracticeItem,
  PracticeSession,
  PracticeSummary,
  SavedWords,
  SpeakCheckRequest,
  SpeakCheckResult,
  TranslationReportRequest,
  TranslationReportResult,
  VocabularyList,
  WordListDetail,
  WordListStarted,
  WordListSummary,
  VocabularySettings,
  WordDetail,
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

/** The words list's cache key — one row per lemma, read by the list page,
 *  the word page's own list-invalidation and `ReviewVocabulary`'s
 *  `savedEarlier` check nowhere near it (that one reads a material's own
 *  vocabulary, a different endpoint entirely — see `vocabularyKey`). */
export const vocabularyWordsKey = ["vocabulary", "words"] as const;

/** One word's own page, keyed by its id — a lemma stopped naming one row
 *  the moment two senses of it could each be saved. Kept apart from the
 *  list's key rather than a sub-key of it, because invalidating the list
 *  must NOT throw away a word page's `history`, which the list response
 *  never carries. */
export const wordDetailKey = (wordId: string) =>
  ["vocabulary", "words", "detail", wordId] as const;

/** Word lists: the index and each detail. Starting or stopping invalidates
 *  `["vocabulary","lists"]` (prefix), the practice summary and nothing else. */
export const wordListsKey = ["vocabulary", "lists"] as const;
export const wordListKey = (key: string) =>
  ["vocabulary", "lists", key] as const;

/** "On the go"'s list. Its own key, never a sub-key of the practice ones: it
 *  is independent of the daily queue and nothing a practice answer does
 *  changes it. */
export const onTheGoKey = ["vocabulary", "on-the-go"] as const;
/** The account's vocabulary settings (the same key the settings page uses). */
export const settingsKey = ["vocabulary", "settings"] as const;

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

  /** Every word this learner has kept, extended in stage 2 with status,
   *  the ladder's own state for both directions and the leech-lapse count
   *  — see `SavedWord`. Still one call for the whole list; filters are
   *  client-side (the spec's API summary), because the list is a few
   *  hundred rows at most and a server round trip per filter tap would be
   *  the slower page for no reason. */
  words: () => api.get<SavedWords>("/api/vocabulary/words"),

  /** One word's own page: the same row plus its review history, newest
   *  first. 404s for an id that is not this learner's — the server never
   *  says whose it is instead. */
  wordDetail: (wordId: string) =>
    api.get<WordDetail>(`/api/vocabulary/words/${wordId}`),

  /** By id, not by lemma — a lemma stopped naming one saved word the moment
   *  `bank` the finance term and `bank` the river bank became two rows,
   *  each with its own card. */
  forget: (wordId: string) =>
    api.delete<void>(`/api/vocabulary/words/${wordId}`),

  /** Mark known, set aside, restore or forget several words at once — the
   *  words list's and the word page's bulk actions share this one call,
   *  since a single word is just a `word_ids` array of one. */
  bulkWords: (payload: BulkWordsRequest) =>
    api.post<BulkWordsResponse>("/api/vocabulary/words/bulk", {
      json: payload,
    }),

  /** Browse (§C) marking one card shown — never a review log, never an
   *  FSRS write. Fire-and-forget, once per card a Browse session shows;
   *  the server treats it as idempotent, so a caller never has to check
   *  whether it already sent this before sending it again. */
  browsed: (wordId: string) =>
    api.post<void>(`/api/vocabulary/words/${wordId}/browsed`),

  /** Resolving a leech — the three choices of the spec's §5, offered from
   *  the session's reveal, the word page and the words list alike. */
  leech: (wordId: string, choice: LeechChoice) =>
    api.post<LeechChoiceResponse>(
      `/api/vocabulary/words/${wordId}/leech`,
      { json: { choice } },
    ),

  /** "This translation is wrong" — the word page and the practice reveal's
   *  quiet link, never the lookup popover. One open report per (learner,
   *  sense); a repeat is a 200 that changes nothing on the server, so the
   *  client never has to check before sending. */
  translationReport: (payload: TranslationReportRequest) =>
    api.post<TranslationReportResult>("/api/vocabulary/translation-reports", {
      json: payload,
    }),

  // --- Practice ----------------------------------------------------------
  //
  // `tz` travels on every call that reasons about "today" — the daily time
  // budget resets at midnight in the LEARNER's own IANA zone, not the
  // server's, and not UTC (a session sat at 11pm and again at 1am must
  // count as two different days for someone in Tashkent and one day for
  // someone nine hours west of them). `Intl.DateTimeFormat().resolvedOptions
  // ().timeZone` is what every caller reads it from.

  /** The home screen's numbers: what's due, what fits in today's time
   *  budget, and the running totals. Cheap and side-effect-free — reading
   *  it never advances anything, unlike `session`.
   *
   *  No `mode` param from this client any more — the addendum's manual
   *  choice lives in `VocabularySettings.exercise_types` now, a standing
   *  preference the server reads on its own rather than a per-call
   *  override, so what this returns already reflects it. The server still
   *  accepts a `mode` query param for a caller that has never heard of the
   *  setting; nothing here sends one. */
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
   *  practises everything due. No `mode` here either, for the same reason
   *  as `practiceSummary` above — the ladder task, when forced, comes from
   *  Settings, and the server reads it without being told twice. */
  practiceSession: (tz: string, opts: { materialId?: string } = {}) =>
    api.post<PracticeSession>("/api/vocabulary/practice/session", {
      params: { tz },
      json: {
        ...(opts.materialId ? { material_id: opts.materialId } : {}),
      },
    }),

  /** One card's answer. The verdict, the FSRS rating it produced, and
   *  whether the card returns before the session ends are the server's to
   *  decide — see the spec's rating table — so this call sends only what
   *  happened (`given`, `elapsed_ms`) and never a guess at the grade. */
  practiceAnswer: (payload: PracticeAnswerRequest) =>
    api.post<PracticeAnswer>("/api/vocabulary/practice/answers", {
      json: payload,
    }),

  /** "I know this", pressed on a new word's first appearance (the spec's
   *  §4). Swaps in a `recall` item for the one attempt that decides it —
   *  never the item already on screen, so a passive `recognise` turn does
   *  not have to pretend it was something else. */
  knownCheck: (ref: { word_id?: string; list_entry_id?: string }) =>
    api.post<PracticeItem>("/api/vocabulary/practice/known-check", {
      json: ref,
    }),

  /** "Did the recogniser hear the word?" — `speak` only. Writes nothing to
   *  FSRS; the answer that does is `practiceAnswer`, posted by the caller
   *  once this says `caught` (or the learner says "I don't know"). */
  speakCheck: (payload: SpeakCheckRequest) =>
    api.post<SpeakCheckResult>("/api/vocabulary/practice/speak-check", {
      json: payload,
    }),

  // --- On the go ----------------------------------------------------------

  /** The words in rotation, newest first, each as two audio files (word,
   *  definition). Independent of the daily queue. */
  onTheGo: () => api.get<OnTheGoList>("/api/vocabulary/on-the-go"),

  /** One row in the exposure log, sent once the WORD part of an item has
   *  finished playing. 204. It is a log, never an FSRS write: hearing a word
   *  is not recalling it. */
  onTheGoExposure: (wordId: string) =>
    api.post<void>("/api/vocabulary/on-the-go/exposures", {
      json: { word_id: wordId },
    }),

  // --- Word lists --------------------------------------------------------
  // Starting a list subscribes; it adds no words. See the module CLAUDE.md.

  lists: () => api.get<WordListSummary[]>("/api/vocabulary/lists"),

  listDetail: (key: string) =>
    api.get<WordListDetail>(`/api/vocabulary/lists/${key}`),

  startList: (key: string) =>
    api.post<WordListStarted>(`/api/vocabulary/lists/${key}/start`),

  stopList: (key: string) =>
    api.post<{ active: false }>(`/api/vocabulary/lists/${key}/stop`),

  settings: () => api.get<VocabularySettings>("/api/vocabulary/settings"),

  /** The settings page's one call. A plain replace, not a per-field patch —
   *  `daily_minutes` and `direction` are both required on the wire, because
   *  that is how the settings screen presents itself: one form with three
   *  fields, saved together, never a lone minutes picker sending its own
   *  value and leaving the other two for the server to guess at. */
  updateSettings: (
    settings: Pick<VocabularySettings, "daily_minutes" | "direction" | "exercise_types"> &
      // Optional: absent means unchanged, so only the Pronunciation, Accent
      // and On the go controls send them.
      Partial<
        Pick<
          VocabularySettings,
          "pronunciation" | "accent" | "on_the_go_order" | "on_the_go_pause_s"
        >
      >,
  ) =>
    api.put<VocabularySettings>("/api/vocabulary/settings", {
      json: settings,
    }),
};

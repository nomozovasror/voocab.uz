/**
 * A passage's words, as the three screens that show them see them.
 *
 * One shape for all three — the lookup panel mid-paper, the review's list,
 * the learner's saved words — because they are showing the same thing. What
 * differs is how much of it is drawn: the panel shows the meaning and not the
 * example (the reader is looking at the sentence), and the review shows the
 * example because by then they are not.
 *
 * What the wire deliberately does not carry is the frequency band. It is the
 * figure the difficulty arithmetic reads and it means nothing to a learner:
 * "NGSL rank 2400" is a fact about a corpus. `cefr_level` is the one that
 * travels, because B2 is a scale somebody already has a feel for.
 */

import type { Glossed } from "@/features/vocabulary/meaning";

export interface VocabularyEntry {
  id: string;
  lemma: string;
  /** The form as it stands in the passage. Not printed on its own — the
   *  reader can see it — and carried so a mark can be laid over the right
   *  occurrence without asking again. */
  surface: string;
  /** `n`, `v`, `adj`, `adv`, `prep`, `conj`, `phr`; empty where the model
   *  would not commit to one, which is better than a guess in italics. */
  pos: string;
  /** What the word USUALLY means — its commonest general sense, and the
   *  line every screen prints first. See `meaning.ts`, which owns the rule
   *  and the story of the gloss that made it necessary.
   *
   *  Empty on an entry written before the field existed; readers fall back
   *  to `meaning_en`. */
  meaning_core_en: string;
  meaning_core_uz: string;
  /** One line, in the sense THIS passage uses. Shown under the usual
   *  meaning, as `Here: …`, and only where `sense_differs`. */
  meaning_en: string;
  meaning_uz: string;
  /** Whether this passage's sense is genuinely not the usual one.
   *
   *  The switch that decides whether a reader sees one meaning or two, and
   *  the flag the `unusual sense` tag and its filter now read. It replaced
   *  a narrower one — a COMMON word in an unexpected sense, `bank` as the
   *  side of a river — which is still a column on the server and still what
   *  the arithmetic comparing passages uses, but is not what a reader wants
   *  pointed out: a rare word in an unexpected sense is just as much of a
   *  trap and was not being marked at all. */
  sense_differs: boolean;
  /** The sentence from the passage that contains it. What makes a saved word
   *  worth more than a word off a list: the learner met it here. */
  example: string;
  /** B1, B2 or C1 — for the word in this sense, so a common word used
   *  unusually is rated on the unusual use. */
  cefr_level: string;
  /** A multi-word expression rather than a word. `give rise to` is one
   *  entry over three words, which is what lets a tap on `rise` find it. */
  is_phrase: boolean;
  /** Where it stands, in the coordinates the reading highlights use — the
   *  part as well as the paragraph, because a reading paper can hold three
   *  passages and each letters its paragraphs from A. */
  part_id: string;
  paragraph_index: number;
  offset_start: number;
  offset_end: number;
  /** Everywhere else the same word stands in this passage, as
   *  `[paragraph_index, start, end]`.
   *
   *  One entry per lemma is what makes a tapped word have one answer;
   *  marking only one of its occurrences is what made the list look
   *  incomplete — `solutionism` appears twice and only the first carried a
   *  mark. Drawn more quietly than the first: see
   *  `features/reading/layers.ts`.
   *
   *  Empty where the gloss is about one USE rather than about the word. */
  also_at: number[][];
  /** The passage has been edited since this was glossed, so the offsets may
   *  no longer point at the right words. */
  stale: boolean;
  /** Whether THIS SENSE — `bank` the finance term, not `bank` the side of a
   *  river — is already on this learner's list. A saved word is one
   *  `LexemeSense` per learner now, so two rows sharing a lemma may disagree
   *  about this and each has to be asked on its own. */
  saved: boolean;
  /** The saved word this sense lives at, once `saved` is true — what the
   *  ✕ button removes. `null` while unsaved. */
  saved_word_id: string | null;
  /** A DIFFERENT sense of this lemma is already saved, this one is not.
   *  Drives the popover's and the review row's quiet line ("You've saved
   *  another meaning of this word.") — never a warning, since keeping a
   *  second sense of a lemma already on the list is an ordinary thing to
   *  do. */
  other_sense_saved: boolean;
}

/**
 * What one tap answers with.
 *
 * Both may be filled, and where they are the PHRASE comes first: somebody who
 * tapped `rise` inside `give rise to` is reading the phrase whatever their
 * finger landed on, and the word's own meaning underneath is there for the
 * case where the phrase was not what confused them.
 *
 * Both may be empty, which is an ordinary answer rather than an error — a
 * name, a number, or a morning the dictionary is unreachable.
 */
export interface Lookup {
  word: VocabularyEntry | null;
  phrase: VocabularyEntry | null;
}

/** A material's whole vocabulary — the review's list. */
export interface VocabularyList {
  material_id: string;
  total: number;
  levels: Record<string, number>;
  /** How many of them the passage uses in a sense that is not the word's
   *  usual one. */
  unusual: number;
  entries: VocabularyEntry[];
}

/** One place a saved word was met, with the sense it had there. */
export interface SavedContext {
  material_id: string;
  material_title: string;
  surface: string;
  pos: string;
  /** Filled in later where it was empty, and never written over — a saved
   *  word's gloss is a copy of what the learner MET, and the usual meaning
   *  is a field that did not exist when they met it rather than a
   *  correction to what they saved. */
  meaning_core_en: string;
  meaning_core_uz: string;
  meaning_en: string;
  meaning_uz: string;
  sense_differs: boolean;
  example: string;
  cefr_level: string;
  is_phrase: boolean;
  created_at: string;
}

/**
 * The practice module — stage 2 widens both of the axes stage 1 left fixed:
 * which direction a card is practised in, and which of three tasks its
 * current level asks for. Neither is derived on the fly — see the spec's
 * §1 — so the wire has to carry both rather than the client assuming
 * `passive`/`recall` the way it briefly could.
 */

/** Passive is read-only until it is not: `recognise` (pick the meaning) then
 *  `recall` (produce it from a gap). Active only exists once the passive
 *  card is strong enough to be worth the extra work — see the spec's §2 —
 *  so a word without one is `null`, not a third level. */
export type PassiveLevel = "recognise" | "recall";
export type ActiveLevel = "recognise" | "produce";

/** Which of a word's two cards is being asked about. Scheduled and levelled
 *  entirely separately — a learner may recognise a word for months before
 *  writing it, which is the whole point of splitting them. */
export type Direction = "passive" | "active";

/** The three tasks the ladder can ask for, in the order they get harder.
 *  `recognise` never differs between directions in KIND — four options,
 *  one right — only in what the options are (see `PracticeChoicePrompt`).
 *  `listen` is stage 3's; nothing here ever sends or expects it. */
export type ExerciseType = "recognise" | "recall" | "produce";

/** What a word IS right now, independent of either card's level.
 *  `learning`/`review` are FSRS's own phases; `known`, `suspended` and
 *  `leech` are states a learner or the leech rule put it in, and each takes
 *  it out of the ordinary queue for a different reason — see the spec's
 *  §5–§6. */
export type WordStatus = "learning" | "review" | "known" | "suspended" | "leech";

/** One word the learner is studying.
 *
 *  Deduplicated by SENSE, not by lemma, across every passage it was met in
 *  (P4) — `spring` the season met twice is one word, but `bank` the
 *  financial institution and `bank` the river are two, because what
 *  somebody is STUDYING is one meaning however many passages they met it
 *  in. Each meeting of the SAME sense is kept as a context, so the card
 *  carries two example sentences rather than two unrelated meanings.
 *
 *  The fields below `contexts` did not exist in stage 1, where this shape
 *  was the saved-words page's own and nothing else read it. Stage 2's words
 *  list, word page and the review's `savedEarlier` check all read the same
 *  `GET /vocabulary/words` now, so one interface has to answer for a list
 *  row, a leech choice and a card's schedule at once. */
export interface SavedWord {
  /** The saved word's own id — a `LexemeSense` per learner, unique on
   *  `(user_id, lexeme_sense_id)`. Routes, delete, leech and bulk actions
   *  all address a word by THIS now: a lemma stopped being unique the
   *  moment `bank` the finance term and `bank` the river bank became two
   *  rows. `lemma` below stays, denormalised, for display and search. */
  id: string;
  lexeme_id: string;
  sense_id: string;
  lemma: string;
  created_at: string;
  contexts: SavedContext[];
  status: WordStatus;
  pos: string;
  /** Read LIVE off the word's `LexemeSense` — an admin fixing a definition
   *  or a translation is visible here without the learner doing anything.
   *  `definition_en`/`meaning_uz` are the headline meaning wherever a saved
   *  word is shown; `meaning_core_en`/`meaning_core_uz` below are what
   *  stage 1 copied onto the row at save time and are now dead weight kept
   *  only for a word saved before either sense field existed. */
  definition_en: string;
  meaning_uz: string;
  /** The sense's own CEFR — the headline level on the word page and the
   *  list, sharper than `cefr_level` below (the newest CONTEXT's level,
   *  which can differ where the same sense was met at more than one
   *  difficulty). */
  sense_cefr: string;
  /** @deprecated Stage 1's copy, frozen at save time. Superseded by
   *  `definition_en`/`meaning_uz` above; kept only as a fallback for a word
   *  saved before those existed. */
  meaning_core_en: string;
  meaning_core_uz: string;
  /** The newest context's level. A word met in an easier passage after a
   *  harder one is still rated on the harder use it was originally saved
   *  for having been true of it once — this is a display convenience for
   *  the list, not a re-grading. */
  cefr_level: string;
  passive_level: PassiveLevel;
  /** `null` = active not started — see the spec's §2 for the stability
   *  threshold that starts it. */
  active_level: ActiveLevel | null;
  passive_due: string | null;
  active_due: string | null;
  /** FSRS stability, in days. `null` alongside a `null` level, and also
   *  before either card has been reviewed once. */
  passive_stability: number | null;
  active_stability: number | null;
  /** The combined, direction-agnostic lapse count the FSRS bookkeeping
   *  already kept — countable since `leech_reset_at`, not lifetime. This is
   *  the figure the leech threshold itself reads; the word page's own
   *  "lapses" under each direction (`passive_lapses`/`active_lapses` below)
   *  is a different, LIFETIME count and the two are not the same number. */
  lapses: number;
  /** Lifetime lapse counts, split by direction — the word page's §8
   *  per-direction figure, always true that
   *  `passive_lapses + active_lapses === lapses`. Counted per direction
   *  because the leech threshold itself is: a passive leech never stops the
   *  active card, and a shared counter would make one direction's trouble
   *  read as the other's. */
  passive_lapses: number;
  active_lapses: number;
  reps: number;
  /** Set for `suspended`, and past its date the word is already back in
   *  rotation server-side — resolved lazily, not by a worker. A stale
   *  `suspended_until` in a cached list is a display lag, not a wrong
   *  queue. */
  suspended_until: string | null;
  /** True while active practice exists for this word but the learner's own
   *  `direction` setting has it turned off — see `VocabularySettings.direction`
   *  and `active_in_progress` below. The card is not reset, only held: the
   *  list and the word page print "Paused" over the active direction's
   *  level while this is true, rather than a level that stopped meaning
   *  anything the moment nobody could be asked it. */
  active_paused: boolean;
  /** Set the moment a Browse card showing this word was displayed
   *  (`POST /vocabulary/words/{id}/browsed`) — `null` for a word never
   *  browsed. Browse writes nothing else: no FSRS field on this row ever
   *  moves from it, because browsing is reading, not practice. */
  browsed_at: string | null;
}

export interface SavedWords {
  total: number;
  words: SavedWord[];
}

/** One answer this word gave, for the word page's compact history — newest
 *  first, capped at 100 server-side. `given` is exactly what was typed or,
 *  for a `recognise` turn, the option id chosen; printed as-is rather than
 *  matched back to option text, which the word page does not have. */
export interface WordHistoryEntry {
  reviewed_at: string;
  direction: Direction;
  exercise_type: ExerciseType;
  rating: 1 | 2 | 3 | 4;
  given: string;
  elapsed_ms: number;
}

/** The word page's response: a `SavedWord` nested under `word` rather than
 *  flattened, plus the trail of answers behind today's level. Nested
 *  rather than spread because the server's own `SavedWordDetailOut` is —
 *  `_saved_word_out` builds the same row the list uses and wraps it once,
 *  and flattening here would be a shape this client invented rather than
 *  the one on the wire. */
export interface WordDetail {
  word: SavedWord;
  history: WordHistoryEntry[];
}

/** `POST /vocabulary/words/bulk`'s four verbs. `suspend` is "set aside for
 *  30 days" under its wire name; the UI never says `suspend`, only "set
 *  aside", which is why the label lives in `status.ts` and not here. */
export type BulkAction = "known" | "suspend" | "restore" | "forget";

export interface BulkWordsRequest {
  /** Saved word ids, not lemmas — a lemma no longer names one row. */
  word_ids: string[];
  action: BulkAction;
}

export interface BulkWordsResponse {
  changed: number;
}

/** The three choices a `became_leech` reveal — or a leech row anywhere else
 *  — offers. Never a fourth "suspend forever": leech words are never
 *  auto-suspended, only ever by one of these three, chosen by the learner —
 *  see the spec's §5. */
export type LeechChoice = "set_aside" | "see_context" | "keep";

/** Resolving a leech hands back the word's own row, in the same shape the
 *  list and the word page already read — the server's `leech_choice`
 *  returns `SavedWordOut` outright rather than a narrower ack, so a caller
 *  that wanted to patch its cache in place could without a refetch. Nothing
 *  here does that yet (every caller just invalidates), but the type
 *  matches the wire rather than a shape invented for this client. */
export type LeechChoiceResponse = SavedWord;

/**
 * The practice module proper — building and answering a sitting.
 *
 * A saved word is not yet a card. `/vocabulary/words` above is the list a
 * reader built by pressing Save on a passage; everything below is the
 * spaced-repetition engine that turns that list into something practised,
 * scheduled with FSRS on the server (`app/services/practice.py` owns the
 * only place that touches it) and rationed by TIME rather than by word
 * count — see the stage 1 spec for why a daily word quota is the thing that
 * makes people quit Anki.
 */

/** The home screen's numbers. Nothing here is a queue — `due_now` and
 *  `new_available` are what COULD be practised; `planned_reviews` and
 *  `planned_new` are what today's time budget actually fits, which is the
 *  figure worth putting on the Start button, not the raw due count. */
export interface PracticeSummary {
  due_now: number;
  new_available: number;
  planned_reviews: number;
  planned_new: number;
  daily_minutes: number;
  seconds_spent_today: number;
  avg_seconds: number;
  /** Null when nothing is scheduled — a learner with no saved words, or one
   *  who has already cleared every review there is. */
  next_due_at: string | null;
  totals: { total: number; learning: number; mastered: number };
  /** Words set aside and not yet due back — the home screen's "N words set
   *  aside" line reads this rather than counting the words list itself, so
   *  it costs nothing beyond what the summary already fetches. */
  set_aside: number;
}

/** What to show for a `recall` gap, in the ordinary case — the word's own
 *  context, found in `before`/`after`. `cue` is the first letter only; the
 *  fuller reveal (meaning, Uzbek, `Here: …`) is deliberately withheld until
 *  after the answer is submitted — see `PracticeAnswer`.
 *
 *  Split from `PracticeDefinitionPrompt` as two single-`kind` interfaces
 *  rather than one with `kind: "sentence" | "definition"` — the two read
 *  identically off the wire, but a shared literal-free discriminant is
 *  exactly the shape TypeScript's control-flow narrowing handles cleanly
 *  through an `if (kind === "sentence" || kind === "definition")` guard,
 *  and the one-interface version silently did not. */
export interface PracticeSentencePrompt {
  kind: "sentence";
  before: string;
  after: string;
  /** The answer's first letter — empty when the sense's own
   *  `needs_letter_hint` is false, in which case the gap shows no hint at
   *  all rather than a stand-in character. See `GapField`'s callers. */
  cue: string;
  /** The masked English definition, shown above the sentence as a dimmer
   *  cue — a sentence prompt can carry one now, same as the `definition`
   *  fallback below; `null` where masking left the definition unreadable
   *  in a way even the `recognise` fallback couldn't absorb, or where the
   *  sense has none. */
  definition: string | null;
  /** Set when the sentence is a corpus example, not the learner's own
   *  meeting with the word — every Word-list item has one of these or
   *  nothing. The practice page prints "Example from {title}"; it must
   *  never say the learner saw the word there. */
  example_source?: ExampleSource | null;
}

/** Where a practice sentence was borrowed from. */
export interface ExampleSource {
  material_id: string;
  material_title: string;
}

/** The fallback the spec describes: no usable context, so the gap stands
 *  beside the word's usual meaning instead and `before`/`after` are empty. */
export interface PracticeDefinitionPrompt {
  kind: "definition";
  before: string;
  after: string;
  cue: string;
  definition: string | null;
}

/** One option in a `recognise` turn. `id` is opaque (an HMAC truncated
 *  server-side, per the spec's §3) precisely so the right answer can never
 *  be read off which option looks different from the others — there is
 *  nothing to read, the id says nothing about the text behind it. */
export interface PracticeOption {
  id: string;
  text: string;
}

/** A `recognise` turn, either direction. Passive fills `before`/`target`/
 *  `after` with the context sentence and its marked word (or the lemma
 *  alone in `target` when there is no sentence) and offers English
 *  definitions; active leaves those empty, fills `shown_meaning_uz` with
 *  the Uzbek meaning to translate FROM, and offers English lemmas instead.
 *  One shape for both rather than two, because the only real difference is
 *  which fields are empty. */
export interface PracticeChoicePrompt {
  kind: "choice";
  before: string;
  target: string;
  after: string;
  shown_meaning_uz: string | null;
  options: PracticeOption[];
}

/** A `produce` turn: the Uzbek meaning to write FROM, the part of speech,
 *  and — exactly like `PracticeSentencePrompt.cue` — the answer's first
 *  letter and nothing more. */
export interface PracticeProducePrompt {
  kind: "produce";
  meaning_uz: string;
  pos: string;
  cue: string;
}

export type PracticePrompt =
  | PracticeSentencePrompt
  | PracticeDefinitionPrompt
  | PracticeChoicePrompt
  | PracticeProducePrompt;

/** One card, already the exercise it will be answered as. Both `direction`
 *  and `exercise_type` are now genuinely variable — stage 1's comment about
 *  a future stage widening them was about this stage. */
export interface PracticeItem {
  /** Exactly one of `word_id` / `list_entry_id` is set. A Word-list item
   *  has no SavedWord yet: it is created by the first answer. */
  word_id: string | null;
  list_entry_id?: string | null;
  context_id: string | null;
  lemma: string;
  pos: string;
  cefr_level: string;
  /** Never practised before. Drives the session's own new/reviewed tally at
   *  the end screen — the server doesn't report that split back, so the
   *  client counts it off this flag as each item is answered. It is also
   *  what gates "I know this" — see the spec's §4 — though the session only
   *  ever OFFERS the button on a `direction: "passive"` item, since that is
   *  the only case the spec describes. */
  is_new: boolean;
  direction: Direction;
  exercise_type: ExerciseType;
  /** What the ladder actually asked for. Always present — equal to
   *  `exercise_type` in the ordinary case, and different from it exactly
   *  on a fallback substitution (the spec's §3: too few distractors, or a
   *  definition too short to quiz on) that does not change the word's
   *  stored level. A fallback is `planned_exercise !== exercise_type`,
   *  never `planned_exercise == null` — the server's own definition. */
  planned_exercise: ExerciseType;
  prompt: PracticePrompt;
}

/** The queue for one sitting, built once when the session starts — not a
 *  live feed. A wrong answer is re-queued by the CLIENT, appending the same
 *  item to the end of what it already holds; the server only ever sees the
 *  session as a sequence of individually-graded answers. */
export interface PracticeSession {
  items: PracticeItem[];
}

export interface PracticeAnswerRequest {
  /** Exactly one of the two, copied from the item. */
  word_id?: string;
  list_entry_id?: string;
  context_id: string | null;
  direction: Direction;
  exercise_type: ExerciseType;
  /** What the learner actually did: the typed answer for `recall`/
   *  `produce`, or the chosen option's opaque id for `recognise`. One field
   *  for both rather than an `option_id` beside it, because the server
   *  already treats `given` as "what came back" and a second field would
   *  be a second place callers could send the wrong one. */
  given: string;
  elapsed_ms: number;
  /** Set only on the one attempt that follows pressing "I know this" — see
   *  the spec's §4. Never sent again for the same word even if that attempt
   *  comes back Again and the word is re-queued; the client clears this the
   *  moment it is used. */
  claim_known?: boolean;
  /** Echoed back from `PracticeItem.planned_exercise`, so the server can
   *  tell a genuine fallback apart from a client that answered the wrong
   *  task. Optional on the wire (defaults to `exercise_type` server-side)
   *  only because a caller that has never heard of the ladder should not
   *  be obliged to send it; this client always does, since every item it
   *  ever holds already carries one. */
  planned_exercise?: ExerciseType;
  /** True exactly when this is the SAME item re-shown at the end of the
   *  session after an Again — the spec's §1 requeue. It answers at the task
   *  it was served, is not a fallback, and changes neither the word's level
   *  nor its schedule beyond FSRS's own reaction to the rating; the demotion
   *  an Again earns is felt at the NEXT encounter, not this one. The client
   *  sets it the moment it pushes the same item onto the queue's end
   *  (`VocabularyPracticePage`'s `advance`), never on the item's first
   *  appearance. */
  requeued: boolean;
}

/** The word as this answer's context knew it — a `Glossed` (see
 *  `meaning.ts`) plus where it came from, for the "source material" link the
 *  reveal shows. */
export interface PracticeAnswerWord extends Glossed {
  /** The saved word this answer belongs to. For a Word-list item it is the
   *  row that answer just created. */
  word_id?: string;
  lemma: string;
  pos: string;
  cefr_level: string;
  /** The sense this card is practising — what the reveal's "This
   *  translation is wrong" link reports against. */
  sense_id: string;
  material_id: string | null;
  material_title: string | null;
}

/** What one answer comes back with. `rating` is never sent BY the client —
 *  it is the server's own translation of verdict + exercise type into an
 *  FSRS grade (see the spec's table), included here only so the client can
 *  log what happened without recomputing a rule it must never own a second
 *  copy of. */
export interface PracticeAnswer {
  verdict: "correct" | "close" | "wrong";
  rating: 1 | 2 | 3 | 4;
  /** The answer as it stood — the right definition for a passive
   *  `recognise` turn, the right lemma for an active one, the word as it
   *  stood in the sentence for `recall`/`produce`. Sent only now, never
   *  with the prompt. */
  answer: string;
  /** True exactly when `rating` is Again. The client appends this item
   *  to the end of the current queue when true, and does nothing extra
   *  otherwise — the server has already rescheduled the card either way. */
  returns_this_session: boolean;
  next_due_at: string;
  word: PracticeAnswerWord;
  /** Only meaningful on the one attempt sent with `claim_known: true` — see
   *  the spec's §4. `false` on every ordinary answer, which the session
   *  never reads. */
  known: boolean;
  /** True exactly when this answer tipped the word into `leech` — the
   *  signal that opens the three-choice panel (see the spec's §5). */
  became_leech: boolean;
  status: WordStatus;
  /** The level of the card just practised, AFTER this answer — what the
   *  ladder promoted or demoted it to, in the direction just played. */
  level: PassiveLevel | ActiveLevel;
  /** The word's newest context that has a sentence, sent whenever
   *  `became_leech` is true — "See it in context" reads this to print the
   *  sentence with the word marked, right in the session card, rather than
   *  sending the learner away to fetch it. `null` when the word has no
   *  context with a sentence to show (§5/§6 of the spec). Absent (not just
   *  null) outside a `became_leech` answer — nothing here needs it. */
  leech_context: PracticeLeechContext | null;
}

/** What "See it in context" prints: the sentence, the word marked inside it,
 *  and the material it came from. Mirrors the shape a `recognise` prompt's
 *  sentence fields already use (`before`/`target`/`after`) rather than
 *  inventing a second way to say "here is a marked sentence". */
export interface PracticeLeechContext {
  before: string;
  target: string;
  after: string;
  material_id: string;
  material_title: string;
}

/** `direction` dropped `"active"` on its own here — stage 1 offered it as a
 *  setting with nothing behind it yet. The spec's §2 makes `both` the only
 *  way to turn active practice on; there is no "active only". */
export interface VocabularySettings {
  daily_minutes: 5 | 10 | 15 | 20;
  direction: "passive" | "both";
  /** `null` = Automatic, the ladder picks. Otherwise a ONE-element array —
   *  still a list on the wire (`VocabularySettingsIn.exercise_types: list[Level]
   *  | None`, `min_length=1, max_length=1`), but never more than the one
   *  task the fixes brief's addendum makes this: a manual choice is
   *  "practise only this today", not "practise any of these". A word with
   *  nothing at that task simply has nothing to offer; see `EXERCISE_LABEL`
   *  and the settings/home/practice pages for the "No words are ready for
   *  this yet." case that follows from picking one nothing currently
   *  matches. */
  exercise_types: [ExerciseType] | null;
  /** Read back but never written from this settings page — stage 3's, and
   *  absent from the UI per the spec. */
  pronunciation: boolean;
  /** How many words currently have an active card, regardless of whether
   *  `direction` is `both` right now. Only meaningful for the warning under
   *  the toggle: turning it off doesn't reset any of these — it pauses them
   *  (`SavedWord.active_paused` goes true for each) — but a learner about
   *  to do that has no other way to know there is anything to pause. Zero
   *  the ordinary case for someone who has never turned it on. */
  active_in_progress: number;
}

/**
 * "This translation is wrong" — a quiet link on the word page and in the
 * practice reveal, never in the lookup popover (that screen is spending a
 * budget on a first look, not judging one). One report per (learner, sense)
 * stays open; asking twice is a 200 that changes nothing, which is why the
 * client never has to check first. `where` is the wire's own name for the
 * screen that filed it (`TranslationReportIn.where`), mapped server-side
 * onto `TranslationReport.source`.
 */
export type TranslationReportWhere = "word_page" | "practice";

export interface TranslationReportRequest {
  sense_id: string;
  where: TranslationReportWhere;
  note?: string;
}

export interface TranslationReportResult {
  id: string;
  sense_id: string;
  status: string;
}

// --- Word lists -----------------------------------------------------------

export interface WordListSummary {
  key: string;
  title: string;
  description: string;
  word_count: number;
  /** Entries whose sense the learner has as a saved word, from anywhere. */
  owned: number;
  active: boolean;
  /** A subscription row exists (active or stopped). */
  started: boolean;
}

export interface WordListSample {
  lemma: string;
  pos: string;
  cefr: string | null;
  definition_en: string | null;
  meaning_uz: string | null;
}

export interface WordListDetail extends WordListSummary {
  cefr: Record<string, number>;
  samples: WordListSample[];
  attribution: string;
  source_title: string;
  licence_name: string;
  licence_url: string | null;
  pending_saved: number;
}

export interface WordListStarted {
  active: true;
  pending_saved: number;
}

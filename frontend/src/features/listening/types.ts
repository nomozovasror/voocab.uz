export type Visibility = "private" | "public";

// --- Material (listening) ---------------------------------------------------

export interface ListeningMaterial {
  id: string;
  author_id: string;
  type: string;
  title: string;
  audio_asset_id: string | null;
  case_sensitive: boolean;
  punctuation_sensitive: boolean;
  visibility: Visibility;
  created_at: string;
  /** Bumped by every authoring write to this material or anything under it.
   *  Sent back in `X-Material-Version` on a write to be told (409) when
   *  someone else has changed it in the meantime. */
  version: number;
  segment_count: number;
}

export interface ListeningMaterialDetail extends ListeningMaterial {
  parts: ListeningPart[];
  audio_url: string | null;
  transcript_status: string | null;
  duration_ms: number | null;
}

export interface ListeningMaterialCreate {
  title: string;
  type: "listening";
  audio_asset_id?: string | null;
  visibility?: Visibility;
}

export type ListeningMaterialUpdate = Partial<
  Omit<ListeningMaterialCreate, "type">
>;

export interface AudioUpload {
  asset_id: string;
  blob_id: string;
  sha256: string;
  transcript_status: string;
}

/** An uploaded picture. `id` is what a group stores; the rest is what the
 *  editor needs to draw the thing it just sent — and the two dimensions are
 *  what let the page hold the right box for it before the bytes arrive. */
export interface ImageUpload {
  id: string;
  url: string;
  width: number;
  height: number;
  mime_type: string;
  size_bytes: number;
}

/** A picture as a group holds it: the id, which is the only part the server
 *  stores, plus what it takes to draw it. Assembled either from an upload
 *  response or from a group's resolved config — the same four things, under
 *  two sets of names, which is the reason to have one shape for them. */
export interface GroupImage {
  id: string;
  url: string;
  width: number;
  height: number;
}

// --- Authoring tree: Part -> QuestionGroup -> Question ----------------------

export interface ListeningPart {
  id: string;
  order_index: number;
  title: string;
  audio_start_ms: number | null;
  audio_end_ms: number | null;
  /** Where this part's numbering starts on the paper it came from, or null
   *  to carry on from the part before. See `groupNumbering`. */
  first_number?: number | null;
  question_groups: ListeningQuestionGroup[];
}

export interface PartCreate {
  order_index: number;
  title: string;
  audio_start_ms?: number | null;
  audio_end_ms?: number | null;
}

/** PATCH /api/parts/{id} — all fields optional, adjusts the range later
 *  without recreating the Part. */
export interface PartUpdate {
  title?: string;
  audio_start_ms?: number | null;
  audio_end_ms?: number | null;
}

/** Response shape of POST /api/materials/{id}/parts (PartOut) — no nested
 *  question_groups (empty at creation time); we always refetch the material
 *  tree afterwards rather than hand-merge this into cache. */
export interface PartOut {
  id: string;
  material_id: string;
  order_index: number;
  title: string;
  audio_start_ms: number | null;
  audio_end_ms: number | null;
  created_at: string;
}

/** The tasks answered by writing the missing words. One document, one
 *  payload, six names — because that is how the paper prints them and how an
 *  author thinks about them. What differs is the wording of the rubric and the
 *  shape the sheet takes; what doesn't is anything the server checks. */
export type CompletionType =
  | "form_completion"
  | "note_completion"
  | "sentence_completion"
  | "summary_completion"
  | "short_answer"
  | "table_completion"
  | "flow_chart_completion"
  | "map_labelling"
  | "diagram_labelling";

export type QuestionGroupType =
  | CompletionType
  | "multiple_choice"
  | "matching";

/** Whether this task is answered by writing words rather than by picking a
 *  letter — which is what decides which builder it gets. */
export function isCompletion(type: QuestionGroupType): type is CompletionType {
  return type !== "multiple_choice" && type !== "matching";
}

/** The two completion tasks answered on a picture. Everything else about them
 *  is a completion task — the document, the gaps, the payload — so this is the
 *  question "does this group draw a picture", asked wherever one would go. */
export function isLabelling(type: QuestionGroupType | null): boolean {
  return type === "map_labelling" || type === "diagram_labelling";
}

export interface ListeningQuestion {
  id: string;
  /** The question's place within its GROUP, always 1..N. What the candidate
   *  reads runs across the whole material and is worked out from the ordered
   *  tree — see `questionNumbering`. */
  number: number;
  correct_answers?: string[];
  /** Where in the recording this answer is said. Author-facing only — the
   *  take tree never carries it, since knowing where to listen is most of
   *  the question. */
  replay_start_ms?: number | null;
  replay_end_ms?: number | null;
  // --- the question's own text; absent for a gap in a form ----------------
  /** Multiple choice: the question. Matching: the item to be matched. */
  prompt?: string | null;
  options?: string[] | null;
  /** multiple_choice only. Where each answer is given, by option letter —
   *  one per right option, because a "choose two" is answered twice. */
  option_replay?: Record<string, [number, number]> | null;
}

export interface ListeningQuestionGroup {
  id: string;
  // Present on the direct create/update (QuestionGroupOut) response; omitted
  // when nested inside the material's author tree (GET /api/materials/{id}),
  // where the parent Part already provides the association.
  part_id?: string;
  order_index: number;
  type: string;
  instructions: string;
  word_limit: number | null;
  config: GroupConfig;
  questions: ListeningQuestion[];
}

export interface QuestionIn {
  number: number;
  correct_answers: string[];
  replay_start_ms?: number | null;
  replay_end_ms?: number | null;
}

/** One multiple-choice question as it is sent. `correct_answers` is the
 *  answer key in option letters ("b", or "a","c") — the set the candidate
 *  has to match exactly, not a list of acceptable phrasings. */
export interface ChoiceQuestionIn {
  number: number;
  prompt: string;
  options: string[];
  correct_answers: string[];
  /** Where each answer is given, by option letter. Absent entries are
   *  options nobody has marked, which for a distractor is every one. */
  option_replay: Record<string, [number, number]>;
}

/** IELTS uses a small closed set of rubrics, varying on two axes: how many
 *  words, and whether a number counts on its own. */
export type AnswerRubric =
  | "one_word"
  | "one_word_number"
  | "two_words"
  | "two_words_number"
  | "three_words"
  | "three_words_number";

/** What a group carries at group level. Form completion has the gap-fill
 *  template; matching has the box of options its items are answered from;
 *  multiple choice has only how many letters the candidate picks, since each
 *  of its questions holds its own prompt and options. All of them are
 *  optional on the shape that comes back for any of them. */
export interface GroupConfig {
  template?: string;
  answer_rubric?: AnswerRubric | null;
  /** multiple_choice only. Absent on anything written before it existed,
   *  which means one — see `DEFAULT_ANSWERS_PER_QUESTION`. */
  answers_per_question?: number;
  /** matching only: the box of options, in the order they are lettered. */
  options?: string[];
  /** matching only: "you may use any letter more than once". */
  allow_reuse?: boolean;

  // --- map/diagram labelling ------------------------------------------------
  /** The picture the labels go on, as the id of an uploaded image. The id is
   *  the only part of it the server stores. */
  image?: string | null;
  /** Whether to fit the picture to the page's colours rather than print it as
   *  uploaded. Almost every map is black line art on white, which in dark mode
   *  is a lit sheet punched into the page. */
  image_adapt?: boolean;
  /** How many letters are drawn on the picture. Zero is the form of the task
   *  where the candidate writes what they heard into numbered blanks. */
  image_letters?: number;
  /** Derived on every read, never stored: a URL stored beside the id would be
   *  a fact about which bucket the app pointed at that day. Absent until a
   *  picture is attached — and absent on a group that has one but doesn't draw
   *  it, which is what a labelling task renamed to notes is. */
  image_url?: string;
  image_width?: number;
  image_height?: number;
}

export interface FormConfig extends GroupConfig {
  template: string;
}

/** The instruction line states how many letters to pick, so the count sits
 *  beside it on the group rather than on each question under it. */
export interface ChoiceConfig {
  answers_per_question: number;
}

export interface FormGroupIn {
  type: CompletionType;
  instructions: string;
  word_limit?: number | null;
  config: FormConfig;
  questions: QuestionIn[];
}

export interface ChoiceGroupIn {
  type: "multiple_choice";
  instructions: string;
  /** Never set: how long an answer may be is not a question you can ask
   *  about a letter. Present so both payloads have the same shape. */
  word_limit?: null;
  config: ChoiceConfig;
  questions: ChoiceQuestionIn[];
}

/** One matching item as it is sent. `correct_answers` is at most one letter
 *  — the option it is matched to. Where that answer is given is the
 *  question's own replay range, the way a form gap's is: one item is one
 *  answer, said at one moment. */
export interface MatchingQuestionIn {
  number: number;
  prompt: string;
  correct_answers: string[];
  replay_start_ms?: number | null;
  replay_end_ms?: number | null;
}

/** The box every item in the group is answered from, and whether one option
 *  may answer more than one of them. Both are the group's because the paper
 *  prints them once, above the whole set. */
export interface MatchingConfig {
  options: string[];
  allow_reuse: boolean;
}

export interface MatchingGroupIn {
  type: "matching";
  instructions: string;
  /** Never set, for the same reason multiple choice never sets it. */
  word_limit?: null;
  config: MatchingConfig;
  questions: MatchingQuestionIn[];
}

export type QuestionGroupIn = FormGroupIn | ChoiceGroupIn | MatchingGroupIn;

// --- Consumption ("take") tree: no correct_answers anywhere (§3.4/§7) -------

export interface TakeQuestion {
  id: string;
  number: number;
  /** multiple_choice only. `options` is the option text, in order; which of
   *  them is right has no field here and never will. */
  prompt?: string | null;
  options?: string[] | null;
  /** How many options to pick. Public by design — "Choose TWO letters" is
   *  printed on the paper, and how many are right says nothing about which. */
  select_count?: number | null;
}

export interface TakeQuestionGroup {
  id: string;
  order_index: number;
  type: string;
  instructions: string;
  word_limit: number | null;
  config: GroupConfig;
  questions: TakeQuestion[];
}

export interface TakePart {
  id: string;
  order_index: number;
  title: string;
  audio_start_ms: number | null;
  audio_end_ms: number | null;
  /** Where this part's numbering starts on the paper it came from, or null
   *  to carry on from the part before. See `groupNumbering`. */
  first_number?: number | null;
  question_groups: TakeQuestionGroup[];
}

/** The caller's most recent finished sitting of a paper. Enough to say what
 *  happened and to link to the review, and nothing more — the whole record is
 *  one fetch away, and putting it here would mean the take payload carrying
 *  the answer key. */
export interface LastAttempt {
  attempt_id: string;
  score: number;
  total_questions: number;
  submitted_at: string;
}

export interface MaterialTake {
  id: string;
  title: string;
  audio_url: string | null;
  duration_ms: number | null;
  parts: TakePart[];
  /** Absent where the caller has never finished this paper. What lets them go
   *  and READ a sitting they already did rather than sit it again to find out
   *  how it went — which would write a second attempt, and every ability
   *  figure on the platform counts first attempts. */
  last_attempt?: LastAttempt | null;
}

/** One row of the learner's catalogue. Deliberately not `ListeningMaterial`:
 *  that is the author's view — visibility, the concurrency version — and
 *  pointing the practice list at it showed learners their own unfinished
 *  drafts labelled "private". */
/** Who wrote a material, as a catalogue row shows them: a byline, not an
 *  account. No email — that is not the public's business. */
export interface CatalogueAuthor {
  id: string;
  display_name: string;
  avatar_url: string | null;
  /** How many public listening materials they have written — the whole
   *  library, not the page. Counted on the server for exactly that reason:
   *  the client only ever has thirty rows, and "4 materials here" worked out
   *  from those is a number that is wrong every time it isn't one. */
  materials: number;
  /** How many of those the reader has sat. Theirs, like every other history
   *  on the row. */
  done: number;
}

/** How hard a material turned out to be, over everybody's answers.
 *
 *  `"new"` is not a fourth level of hard — it is the absence of a level, and
 *  it is what a material carries until enough people have answered enough of
 *  it to mean something. `correct_pct` is null exactly then. */
export type DifficultyBand = "new" | "easy" | "medium" | "hard";

export interface Difficulty {
  band: DifficultyBand;
  correct_pct: number | null;
  /** How many answers the band rests on. */
  answered: number;
}

export interface PracticeMaterial {
  id: string;
  title: string;
  part_count: number;
  /** WHICH parts, ascending — `[2]` for a Part 2 material, `[1,2,3,4]` for a
   *  full test. The filter chips read this; a count can't say it, because one
   *  part is Part 1 or Part 4 depending on where it sits. */
  part_numbers: number[];
  /** The kinds of question it asks, in the order it asks them. One entry is a
   *  named task with its own icon; several is "2 question types". */
  question_types: QuestionGroupType[];
  /** Numbers on the paper, which is what a score is out of. */
  question_count: number;
  duration_ms: number | null;
  created_at: string | null;
  author: CatalogueAuthor | null;
  difficulty: Difficulty;
  attempts: number;
  best_score: number | null;
  /** Their FIRST submitted score. The row prints the best — a record is
   *  somebody's best — but anything that MEASURES them reads the first, which
   *  is why both are here and why the collection grid colours by this one. */
  first_score: number | null;
  last_attempt_id: string | null;
  last_attempt_at: string | null;
}

/** One drill: a single question group, practised on its own.
 *
 *  Not a material. A map group is never alone in a paper — every one of the
 *  23 in the library sits beside another task — so the thing a learner
 *  practises when they want maps is a group cut out of a Part 2, and this is
 *  what a card has to say about it. */
export interface PracticeDrill {
  group_id: string;
  type: QuestionGroupType;
  material_id: string;
  material_title: string;
  /** Which of the paper's four parts it came from. */
  part_number: number;
  /** The numbers it carries on the printed paper — "Questions 15–20". Not
   *  1..N: the recording says these numbers aloud. */
  first_number: number;
  last_number: number;
  /** Numbers, not rows. A "Choose TWO letters" is two of both. */
  question_count: number;
  /** How long the clip runs — the promise the card makes, so it is the
   *  clip's length and not the whole recording's. */
  clip_ms: number | null;
  attempts: number;
  best_score: number | null;
  /** Their FIRST score. The card prints the best — a record is somebody's
   *  best — but anything that MEASURES them reads the first, which is why
   *  both are here and why the grid colours by this one. */
  first_score: number | null;
  last_attempt_id: string | null;
  last_attempt_at: string | null;
}

export interface DrillList {
  items: PracticeDrill[];
  total: number;
  done_hidden: number;
}

/** One card on the Drills tab: a kind of task, and what there is of it. */
export interface DrillType {
  value: QuestionGroupType;
  exercises: number;
  questions: number;
  done: number;
}

/** What a drill hands the take screen: a material's shape, plus the window
 *  of recording it is bounded to and the drill it is of. */
export interface DrillTake {
  id: string;
  title: string;
  audio_url: string | null;
  duration_ms: number | null;
  parts: TakePart[];
  last_attempt: LastAttempt | null;
  clip_start_ms: number;
  clip_end_ms: number;
  drill: PracticeDrill;
}

/** One option of a filter menu, with how many materials carry it.
 *
 *  Counted over the WHOLE catalogue by the server, not over the page and not
 *  over what the other filters have left: an option that appears and vanishes
 *  as you filter is an option you can't aim at. `value` is a
 *  `QuestionGroupType` or a `DifficultyBand` depending on which list it came
 *  from; the label is looked up here, because the server has no business
 *  knowing what we call things. */
export interface PracticeFacet {
  value: string;
  count: number;
}

/** One page of the catalogue, and the three things a page cannot say about
 *  itself. */
export interface PracticeCatalogue {
  items: PracticeMaterial[];
  /** How many match the filters — not how many came back. What the list
   *  header prints, and what says there is more below. */
  total: number;
  /** How many the "put finished materials away" default is holding back. Zero
   *  once the reader asks to see them. */
  done_hidden: number;
  types: PracticeFacet[];
  bands: PracticeFacet[];
}

/** Why a set of recommendations was made. Three genuinely different claims,
 *  not three phrasings of one:
 *
 *  - `start` — nothing finished yet, so this is Part 1 and nothing is being
 *    asserted about the reader.
 *  - `weak_part` — one part is clearly behind the others; `part` and
 *    `accuracy_pct` say which and how far.
 *  - `level` — nothing is clearly behind, so these suit their average.
 *
 *  The words live here rather than on the server, but WHICH of the three is
 *  the server's judgement — and each one had to prove something before it was
 *  allowed (backend/app/services/recommend.py). */
/** What the block above the list is saying, and every value a different
 *  claim:
 *
 *  - `none` — too little history. There is no block, and that is the honest
 *    state rather than a fallback.
 *  - `finished_course` — the attempt they just submitted completed a course.
 *  - `course` — part-way through one; `items` is the ONE next lesson.
 *  - `weak_part` — one part is clearly behind the others.
 *  - `steady` — none of them is, and all four are good.
 *  - `level` — nothing clear either way. */
export type NextUpReason =
  | "none"
  | "finished_course"
  | "course"
  | "weak_part"
  | "steady"
  | "level";

export interface NextUp {
  reason: NextUpReason;
  part: number | null;
  accuracy_pct: number | null;
  /** Only on `course`: which collection is being carried on with, which
   *  lesson comes next, and how many there are. Together they are the
   *  difference between carrying on and starting again. */
  collection: { id: string; title: string } | null;
  position: number | null;
  /** How many of the course are behind them. Counted, not read off
   *  `position` — somebody who skipped ahead has done more than their place
   *  in the queue suggests. */
  done: number | null;
  /** How many lessons are left. What the block prints beside the lesson
   *  number, because "2 left" cannot be subtracted against it and "4 of 6
   *  done" can — and that subtraction finds an off-by-one that is not there. */
  remaining: number | null;
  of: number | null;
  /** Started-and-unfinished courses, for the "My courses (3)" beside the
   *  action. */
  in_progress_count: number;
  /** May be empty: somebody who has sat everything gets the reason and no
   *  rows, and the block has to survive drawing that. */
  items: PracticeMaterial[];
}

// --- Collections ------------------------------------------------------------

/** How far the reader is through a collection.
 *
 *  Derived from attempts they had already made, never stored — opening a
 *  collection commits them to nothing, and there is no enrolment row that can
 *  come to disagree with what they have actually sat.
 *
 *  `next_material_id` is the first UNSAT one **in order**, which is the
 *  difference between a collection and a filter: the sequence is somebody's
 *  judgement about what to do when. `null` means finished. */
export interface CollectionProgress {
  total: number;
  done: number;
  next_material_id: string | null;
}

/** An ordered set of materials somebody put together on purpose — a course, a
 *  mock-test set, a route through the library. The catalogue says what exists;
 *  this says what to do in what order. */
export interface Collection {
  id: string;
  title: string;
  summary: string;
  visibility: string;
  /** What the cover is generated from, when it is not the id — sent to the
   *  learner too, or an author's re-covered course would be two different
   *  books with one name. */
  cover_seed: string | null;
  created_at: string | null;
  author: CatalogueAuthor | null;
  progress: CollectionProgress;
}

/** One page of collections, and how many there are.
 *
 *  A total rather than only the rows, for the same reason the catalogue
 *  carries one: a list quietly shorter than the library looks broken. */
export interface CollectionList {
  items: Collection[];
  total: number;
  /** What there is to filter by, counted over every published collection —
   *  never over the page and never over what the other filters left. With a
   *  dozen courses and three menus a list is one click from empty, and a
   *  count beside each option is what stops a menu being a set of dead ends. */
  covers: PracticeFacet[];
  lengths: PracticeFacet[];
}

/** How the reader has done across one collection.
 *
 *  `best_avg_pct` is null until something in it has been sat twice: with no
 *  retries it is the first-try average under a second name. */
export interface CollectionStats {
  first_try_avg_pct: number | null;
  best_avg_pct: number | null;
  time_spent_ms: number;
}

/** One collection, opened. `items` are the catalogue's own rows — same
 *  measured difficulty, same history, same byline — because a collection is a
 *  different route to the same thing, not a different thing. */
export interface CollectionDetail extends Collection {
  stats: CollectionStats;
  items: PracticeMaterial[];
}

/** A collection as its author sees it listed.
 *
 *  Two counts because they differ exactly when the course contains the
 *  author's own drafts: normal halfway through building one, confusing to
 *  discover later. `blocker` is why it cannot be published yet, in words the
 *  studio can print. */
export interface AuthorCollection {
  id: string;
  title: string;
  summary: string;
  visibility: string;
  /** What the cover is generated from, when it is not the id. See
   *  `coverKeyOf` — null means the collection has never been re-covered. */
  cover_seed: string | null;
  created_at: string | null;
  author: CatalogueAuthor | null;
  item_count: number;
  public_item_count: number;
  blocker: string | null;
}

// --- The learner's own statistics -------------------------------------------

/** One bar of a distribution.
 *
 *  `accuracy_pct` is null below the server's evidence threshold, and that is
 *  a value in its own right: the row draws a dash and stays muted. Never
 *  substitute a 0 — a 0 is a claim, and it would be false. */
export interface AccuracyRow {
  answered: number;
  accuracy_pct: number | null;
}

export interface PartAccuracy extends AccuracyRow {
  part: number;
}

/** The last thing the reader finished, and which try it was. The ordinal is
 *  the point: 83% on a first try and 83% on a third are different facts. */
export interface Resume {
  material_id: string;
  title: string;
  attempt_id: string;
  submitted_at: string;
  score_pct: number | null;
  attempt_number: number;
}

/** What a wrong answer was wrong ABOUT — the classification the whole panel
 *  turns on. See backend `app/services/mistakes.py` for the rules. */
export type MistakeKind =
  | "missed"
  | "word_limit"
  | "plural"
  | "format"
  | "spelling"
  | "wrong";

export interface MistakeGroup {
  kind: MistakeKind;
  count: number;
}

export interface Mistakes {
  /** Wrong answers counted, across first attempts. */
  total: number;
  /** Typed answers considered — the denominator behind the threshold. */
  answered: number;
  /** Biggest kind first. */
  groups: MistakeGroup[];
}

/** The last ten first attempts, and whether they are going up. */
export interface Trend {
  average_pct: number;
  delta_pct: number;
  from_pct: number;
  to_pct: number;
  /** Oldest first — the sparkline, exactly as drawn. */
  points: number[];
  since: string;
}

/**
 * The practice page's right-hand column.
 *
 * `first_try_avg_pct` is the headline and `best_avg_pct` the footnote, and
 * that order is a judgement rather than a layout choice: sitting a paper
 * until you score well on it measures memory of that paper, not listening.
 * Every analytical figure here — the mistakes, the trend, the part split —
 * counts first attempts only for the same reason.
 *
 * `mistakes` and `trend` are null below their evidence thresholds. The page
 * says so in a sentence; it does not draw a thin chart.
 */
export interface ListeningStats {
  materials_done: number;
  first_try_avg_pct: number | null;
  /** Absent until something has actually been sat twice. */
  best_avg_pct: number | null;
  time_spent_ms: number;
  resume: Resume | null;
  mistakes: Mistakes | null;
  trend: Trend | null;
  /** Not drawn in the sidebar; the material preview reads it. */
  by_part: PartAccuracy[];
}

// --- Consumption: submit + grade --------------------------------------------

/** How one answer was arrived at, as the page watched it happen.
 *
 *  Milliseconds since the session started, never wall-clock: the server
 *  distrusts the browser's clock (rightly) but is happy with the distance
 *  between two of its own readings. Every field is optional — none of this
 *  reaches grading, so a page that measures nothing is marked identically. */
export interface AnswerTiming {
  first_answered_ms?: number;
  last_changed_ms?: number;
  /** Visits that left the answer different than they found it. Per visit,
   *  not per keystroke: typing "engineer" is one answer. */
  changes?: number;
  /** Typed answers only. A letter or a radio button is chosen in one click,
   *  and the deciding was done while looking somewhere else. */
  focus_ms?: number;
}

export interface AnswerIn {
  question_id: string;
  given_answer: string;
  timing?: AnswerTiming;
}

/** One continuous run of playback: from where play started (or where a seek
 *  landed) to where the audio stopped.
 *
 *  Do NOT merge these before sending. Two identical spans mean the learner
 *  played that stretch twice, and the repetition is the entire signal — the
 *  server counts them against the moments the author marked to work out which
 *  answers were hard to hear. Merged, that is indistinguishable from playing
 *  it once. */
export interface ListenedSpan {
  start_ms: number;
  end_ms: number;
}

export interface AttemptSubmit {
  answers: AnswerIn[];
  listened?: ListenedSpan[];
  seeks_back?: number;
  /** How long the page has been open. A duration rather than a start time,
   *  so the server can subtract it from its own clock instead of trusting
   *  ours. */
  elapsed_ms?: number;
}

/** One line of the transcript across an answer's moment — the author's
 *  corrected text, not the ASR's raw guess. */
export interface TranscriptLine {
  start_ms: number;
  end_ms: number;
  text: string;
}

export interface QuestionResult {
  question_id: string;
  /** The number printed beside it on the paper — worked out by the server
   *  from the same walk the take page makes, so a results page opened on its
   *  own can name the questions without fetching the material. */
  number: number;
  /** How many of those numbers it takes: 2 for a "choose TWO letters". */
  marks?: number;
  /** Whether the answer is words or an option letter. Told by the server
   *  because "a" is both a plausible word and a plausible letter, and only
   *  the group knows which. */
  answered_by?: "words" | "letters";
  /** What the learner actually typed, kept raw. */
  given_answer: string;
  is_correct: boolean;
  correct_answers: string[];
  /** Released with the grading feedback, for the same reason the accepted
   *  answers are: the attempt is already committed, so pointing at the
   *  moment in the recording is feedback rather than a hint. */
  replay_start_ms: number | null;
  replay_end_ms: number | null;
  /** multiple_choice only: one moment per right option, since a "choose
   *  two" is answered in two places and sending back one of them would send
   *  the learner to half of why they were wrong. */
  option_replay?: Record<string, [number, number]>;
  /** Every transcript line this answer's moment touches, in playback order.
   *  Empty when the author marked no range, or when the recording has no
   *  transcript yet — practice doesn't wait for one. */
  transcript?: TranscriptLine[];
  /** What KIND of wrong this answer was — the same classification the
   *  practice page's "Where you lose marks" is counted from, so a review of
   *  one paper and a pattern across many cannot name the same slip two
   *  different things. Classified on the server
   *  (`backend/app/services/mistakes.py`) for exactly that reason.
   *
   *  Null twice over: a right answer has no kind, and neither has one given
   *  as a letter — there is no spelling in "b". */
  mistake?: MistakeKind | null;
}

/** Where this paper sits in a course, and what to do next in it. Absent when
 *  the material is in no published collection, and absent once the course is
 *  finished — there is then no next lesson to offer. */
export interface CourseNext {
  collection_id: string;
  collection_title: string;
  /** The first material in the course they have NOT sat, in the course's own
   *  order — which is not necessarily the one after this. */
  next_material_id: string;
  next_position: number;
  done: number;
  total: number;
}

/** What the review of a finished drill needs to offer the next one. */
export interface DrillDone {
  group_id: string;
  /** The kind of task, so the button can read "Next map" rather than "Next
   *  drill" — naming the thing is what makes it an invitation. */
  type: QuestionGroupType;
  /** The next undone drill of the same kind, from a different material.
   *  Null once they have done every one. */
  next_group_id: string | null;
}

export interface AttemptResult {
  attempt_id: string;
  material_id: string;
  material_title: string;
  /** The recording, so the review can replay a moment without also fetching
   *  the take payload for one string. */
  audio_url: string | null;
  duration_ms: number | null;
  score: number;
  total_questions: number;
  submitted_at: string | null;
  /** How long the paper took, where the page reported it. */
  time_spent_ms?: number | null;

  // --- what turns the score into a sentence --------------------------------
  /** Which try this is, counting submitted attempts at this material only. */
  attempt_no?: number;
  /** What the FIRST try came to, so a retake reads as progress rather than as
   *  a number on its own. Absent on a first try, where it would be the same
   *  number under a second name. */
  first_try_pct?: number | null;
  /** How everybody else does on this paper — the difficulty projection's own
   *  figure. Absent until enough people have answered it for an average to
   *  mean anything. */
  material_avg_pct?: number | null;
  course?: CourseNext | null;
  /** Present only when this attempt was a DRILL. Never alongside `course`:
   *  a drill is not a lesson in anybody's sequence, so the server returns
   *  one or the other. */
  drill?: DrillDone | null;

  results: QuestionResult[];
}

// --- Audio asset (transcript source for the editor's left pane) ------------

export interface AudioWord {
  word: string;
  start_ms: number;
  end_ms: number;
}

export interface AudioSegment {
  order_index: number;
  start_ms: number;
  end_ms: number;
  text: string;
  words: AudioWord[];
  /** The owner has corrected this line. Its word timings are still the ASR's
   *  and no longer line up with the text, so word-by-word rendering stops. */
  edited?: boolean;
}

export type AudioTranscriptStatus = "pending" | "processing" | "ready" | "failed";

/** GET /api/audio-assets/{asset_id}. `segments` populated only once
 *  `transcript_status === "ready"`; `transcript_error` only once `"failed"`.
 *  Poll while pending/processing. */
export interface AudioAssetDetail {
  asset_id: string;
  blob_id: string;
  title: string | null;
  sha256: string;
  transcript_status: AudioTranscriptStatus;
  duration_ms: number | null;
  created_at: string;
  transcript_error?: string | null;
  segments: AudioSegment[];
}

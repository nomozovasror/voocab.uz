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

// --- Authoring tree: Part -> QuestionGroup -> Question ----------------------

export interface ListeningPart {
  id: string;
  order_index: number;
  title: string;
  audio_start_ms: number | null;
  audio_end_ms: number | null;
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

export type QuestionGroupType = "form_completion" | "multiple_choice";

/** How many of a choice question's options are right. Stored rather than
 *  counted, so a question set to "several" and given one answer reads as
 *  unfinished instead of as a finished single-answer question. */
export type ChoiceMode = "one" | "multiple";

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
  // --- multiple_choice only; absent for a gap in a form -------------------
  prompt?: string | null;
  options?: string[] | null;
  mode?: ChoiceMode | null;
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
  mode: ChoiceMode;
  correct_answers: string[];
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
 *  template; multiple choice has nothing — each of its questions holds its
 *  own prompt and options — so `template` is optional on the shape that
 *  comes back for either of them. */
export interface GroupConfig {
  template?: string;
  answer_rubric?: AnswerRubric | null;
}

export interface FormConfig extends GroupConfig {
  template: string;
}

export interface FormGroupIn {
  type: "form_completion";
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
  config: Record<string, never>;
  questions: ChoiceQuestionIn[];
}

export type QuestionGroupIn = FormGroupIn | ChoiceGroupIn;

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
  question_groups: TakeQuestionGroup[];
}

export interface MaterialTake {
  id: string;
  title: string;
  audio_url: string | null;
  duration_ms: number | null;
  parts: TakePart[];
}

// --- Consumption: submit + grade --------------------------------------------

export interface AnswerIn {
  question_id: string;
  given_answer: string;
}

export interface AttemptSubmit {
  answers: AnswerIn[];
}

export interface QuestionResult {
  question_id: string;
  is_correct: boolean;
  correct_answers: string[];
  /** Released with the grading feedback, for the same reason the accepted
   *  answers are: the attempt is already committed, so pointing at the
   *  moment in the recording is feedback rather than a hint. */
  replay_start_ms: number | null;
  replay_end_ms: number | null;
}

export interface AttemptResult {
  score: number;
  total_questions: number;
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

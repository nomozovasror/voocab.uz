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
  /** Already on this learner's list. */
  saved: boolean;
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

/** One word the learner is studying.
 *
 *  Deduplicated by lemma across every passage it was met in — somebody
 *  studying `spring` is studying one word — with each meeting kept as a
 *  context, so the card carries two senses and two example sentences. */
export interface SavedWord {
  lemma: string;
  created_at: string;
  contexts: SavedContext[];
}

export interface SavedWords {
  total: number;
  words: SavedWord[];
}

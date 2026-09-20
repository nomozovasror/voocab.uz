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
  /** One line, in the sense THIS passage uses. */
  meaning_en: string;
  meaning_uz: string;
  /** The sentence from the passage that contains it. What makes a saved word
   *  worth more than a word off a list: the learner met it here. */
  example: string;
  /** B1, B2 or C1 — for the word in this sense, so a common word used
   *  unusually is rated on the unusual use. */
  cefr_level: string;
  /** A multi-word expression rather than a word. `give rise to` is one
   *  entry over three words, which is what lets a tap on `rise` find it. */
  is_phrase: boolean;
  /** Where it stands, in the coordinates the reading highlights use. */
  paragraph_index: number;
  offset_start: number;
  offset_end: number;
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
  entries: VocabularyEntry[];
}

/** One place a saved word was met, with the sense it had there. */
export interface SavedContext {
  material_id: string;
  material_title: string;
  surface: string;
  pos: string;
  meaning_en: string;
  meaning_uz: string;
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

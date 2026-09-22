import type { QuestionResult } from "@/features/paper/types";
import type { VocabularyEntry } from "@/features/vocabulary/types";
import { toneOf } from "@/features/vocabulary/cefr";

/**
 * The four things a finished passage can be marked with, and the rule that
 * only one of them is ever on.
 *
 * ## Why the passage comes back at all
 *
 * The review this replaced threw the text away. It printed a score, the
 * questions got wrong, and a hundred and one vocabulary entries in a list
 * that did not end — four lines each, so the page ran to about twelve
 * screens of words with no passage anywhere near them.
 *
 * But the passage is where the learning happened. Everything worth saying
 * afterwards is a statement ABOUT it: this is where the answer was, this is
 * the word you did not know, this is the one you saved a fortnight ago and
 * have now met again. Said beside the text, each of those is a lesson; said
 * in a list on its own, each is a row of data. So the review is the take
 * screen's own shape — passage on the left, analysis on the right — which
 * the reader already knows how to use because they spent an hour in it.
 *
 * ## One layer at a time, and that is not a limitation
 *
 * Four kinds of marking over nine hundred words at once is not four
 * findings, it is a page of colour with prose somewhere underneath. Every
 * sentence is inside something, so nothing stands out, and a reader who
 * cannot see which mark is which cannot act on any of them.
 *
 * One at a time makes each a QUESTION the reader asked: *where were the
 * answers?* — *what was worth learning here?* — *what have I already
 * saved?* — *what did I mark while I was reading?* The toggle is the
 * question; the marking is the answer.
 *
 * The default is Mistakes, because that is the question everybody arrives
 * with. On a clean sheet there are no mistakes to show, and the page opens
 * on the vocabulary instead — see the review page.
 *
 * ## The reader's own marks keep their own colours
 *
 * Three of the four layers are overlays with a colour each. The fourth is
 * not an overlay at all: "My marks" hands the passage the reader's own
 * `Highlight`s, drawn by the same code that draws them on the take screen.
 *
 * That is deliberate rather than convenient. The reader chose a fill or a
 * line for each mark while they were reading, and that choice MEANS
 * something — this is the thing, versus I am not sure about this.
 * Repainting them all one way here would throw away the only part of a mark
 * that carries information, on the one page whose whole purpose is to give
 * that information back.
 *
 * Both are amber, and that is the point rather than a compromise: the three
 * hues the pen used to offer included this scale's blue and something close
 * to its violet, and a reader who meets blue as "where the answer was" on
 * one layer and blue as "B1" on the next has been handed two colour systems
 * wearing one colour. See `features/reading/highlights.ts`.
 */

/**
 * Which marking is on the passage — and, because they are one control,
 * which analysis is beside it.
 *
 * It used to be two controls: four layers in the header for the passage, and
 * two tabs over the panel for the analysis, with "Mistakes" and "Vocabulary"
 * printed in both. Two places saying the same two words is a reader working
 * out which one they are meant to press, and the answer was "either" — the
 * tab already carried the layer with it. So there is one, it lives in the
 * header where the take screen's tools were, and the panel follows it.
 *
 * Exactly one is on, never none: a passage with nothing on it is what the
 * take screen already showed.
 */
export type LayerId = "answers" | "vocabulary" | "saved" | "marks";

export interface LayerDescriptor {
  id: LayerId;
  /** In the toggle, and in the empty line where the layer has nothing. */
  label: string;
  /** What it is, for the toggle's title. Three words, because a row of four
   *  coloured buttons over a passage is a legend nobody reads. */
  meaning: string;
}

/** In the order they are offered, which is the order they get further from
 *  this sitting: how the paper went, what it teaches, what you knew before
 *  it, what you did while you were in it. */
export const LAYERS: LayerDescriptor[] = [
  {
    id: "answers",
    label: "Answers",
    meaning: "Where every answer was, right and wrong",
  },
  {
    id: "vocabulary",
    label: "Vocabulary",
    meaning: "The words worth learning here",
  },
  {
    id: "saved",
    label: "Saved",
    meaning: "Words already on your list, met again",
  },
  { id: "marks", label: "My marks", meaning: "What you highlighted yourself" },
];

/**
 * One stretch of the passage, marked by the review rather than by the reader.
 *
 * The same anchor as a `Highlight` — a part, a paragraph and two offsets —
 * because it is the same claim about the same text, and a second coordinate
 * system for the same thing is a second set of off-by-ones.
 */
export interface Overlay {
  partId: string;
  index: number;
  start: number;
  end: number;
  /** How it is washed. Not the layer's id: the answers layer draws three
   *  verdicts, and both word layers draw the same one. */
  tone: "got" | "missed" | "chose" | "word";
  /** For a `word`, the CEFR level it is washed as — and null where the
   *  gloss never committed to one.
   *
   *  The wash says the LEVEL and nothing else, which is what makes the
   *  passage readable as a map of its own difficulty. It used to say
   *  "saved" in blue for a word already on the list, and that was a second
   *  meaning on the same channel: a saved C1 word and an unsaved B1 word
   *  came out the same colour, so the one thing the wash was for stopped
   *  being true wherever the reader had done some work. Saved-ness is what
   *  the Saved LAYER filters by; it is not a hue. */
  level?: string;
  /** For a `word`, one of the three this reader spent a look-up on.
   *
   *  Drawn as an underline UNDER the level's wash rather than as a colour
   *  of its own, because it is a fact about the reader and not about the
   *  word: `emergence` is C1 whether or not anybody looked it up, and a
   *  different colour would say otherwise. */
  lookedUp?: boolean;
  /** For a `word`, already on this learner's list. Carried so the page can
   *  build the Saved layer by filtering these rather than by walking the
   *  entries a second time with a different predicate. */
  saved?: boolean;
  /** What this mark is about, so hovering a row on the right can light the
   *  matching marks on the left and nothing else. A question id for
   *  evidence, a lemma for a word. */
  key: string;
  /** The keys of overlays this one swallowed — see `overlaysIn`. `give rise
   *  to` is one entry and `rise` inside it is another, and only one mark can
   *  be drawn over those three words; it has to answer to both, or the
   *  reader points at `rise` in the list and the passage does nothing. */
  also?: string[];
  /** What it says on hover. The passage's own words are under the pointer,
   *  so this says what the MARK means, not what the text says. */
  title?: string;
  /** What is printed in the margin of the mark — `Q12`, and both numbers
   *  where one mark stands for two questions.
   *
   *  Without it the answers layer is a passage striped red and green, and
   *  the reader has to guess which stripe belongs to the row they are
   *  reading. Seventeen coloured sentences is not an answer to "where was
   *  question 31"; `Q31` beside one of them is. */
  labels?: string[];
  /** Stretches INSIDE this mark to draw harder — the word a true/false
   *  statement turns on, within the sentence that settles it.
   *
   *  Carried on the outer mark rather than laid over it as a second
   *  overlay, because one run of prose gets one mark (`overlaysIn`) and a
   *  second one here would be swallowed by the first. The passage pane
   *  splits the mark's own text instead, which is the only way two marks
   *  can be nested at all. Offsets are the paragraph's, like everything
   *  else. */
  inner?: { start: number; end: number }[];
}

/**
 * Where every answer was — and, for one got wrong, where the answer they
 * gave instead came from.
 *
 * It began as the wrong ones only, on the reasoning that marking all forty
 * colours most of the passage and a candidate who answered question 12
 * correctly does not need to be shown where question 12 was. That is wrong
 * twice over.
 *
 * A passage worked through is a paper somebody wants to see MARKED, and half
 * a marking is not one: the reader who got eleven of thirteen wants to see
 * where the two they lost were AND that the eleven were where they thought.
 * And the red marks only mean "you missed this" if the green ones are there
 * to be compared with — alone on the page they read as "here are the hard
 * bits", which is a different and less useful claim.
 *
 * The passage does not drown in colour, because what carries the mark is the
 * NUMBER in its margin rather than the wash: `Q12` is legible against a tint
 * that would be invisible on its own. Green and red mean here what they mean
 * in the question map at the top of the same screen — the verdict — and not
 * what the reader's own three highlight colours mean, which is why those
 * three are never green or red.
 *
 * ## Three states, not two
 *
 * A question got wrong is marked TWICE: the sentence that held the answer,
 * in green, and the sentence that pulled them to the one they gave, in red.
 * Both carry the same number, because they are one explanation — *this is
 * what you read, and this is what it actually said.* Being shown the right
 * line says what was true; being shown the wrong one says why you believed
 * something else, and only the second of those is news to the reader.
 *
 * A question got RIGHT is marked once and quietly: a thin green rule under
 * the words, no wash at all. Two coloured blocks for every mistake plus a
 * coloured block for every success is a passage with no unmarked prose left
 * in it, and a page where everything is marked has marked nothing. The rule
 * still says "this was question 9" to anybody looking for it, and says
 * nothing to anybody who is not.
 */
export function evidenceOverlays(results: QuestionResult[]): Overlay[] {
  const out: Overlay[] = [];
  for (const result of results) {
    for (const span of result.evidence ?? []) {
      out.push({
        partId: span.part_id,
        index: span.paragraph_index,
        start: span.start,
        end: span.end,
        tone: result.is_correct ? "got" : "missed",
        key: result.question_id,
        labels: [`Q${result.number}`],
        // The deciding words, where they fall inside THIS sentence. A
        // statement answered in two places has its word in one of them,
        // and drawing it in both would be the page inventing a second
        // trap.
        inner: (result.keywords ?? [])
          .filter(
            (word) =>
              word.part_id === span.part_id &&
              word.paragraph_index === span.paragraph_index &&
              word.start >= span.start &&
              word.end <= span.end,
          )
          .map((word) => ({ start: word.start, end: word.end })),
        title: result.is_correct
          ? `Question ${result.number} — you got this one`
          : `Question ${result.number} — the answer was here`,
      });
    }
    for (const span of result.distractor ?? []) {
      out.push({
        partId: span.part_id,
        index: span.paragraph_index,
        start: span.start,
        end: span.end,
        tone: "chose",
        key: result.question_id,
        labels: [`Q${result.number}`],
        title: `Question ${result.number} — this is what pulled you`,
      });
    }
  }
  return out;
}

/**
 * Where a WRITTEN answer came from, found in the passage rather than sent
 * with the paper.
 *
 * A gap-fill's distractor is not a fact about the question. Nobody authored
 * it and no extraction can predict it: it is whatever word the learner
 * happened to write, and the only interesting thing about it is whether that
 * word is in the passage at all. If it is, they took it from somewhere and
 * the review can show them where; if it is not, they invented it, and there
 * is nothing to point at.
 *
 * Matched exactly and refused where the match is not unique — the same rule
 * `passageQuote` works under, and for the same reason. A word that appears
 * four times gives four candidate places and no way to know which one they
 * read, and a red mark over the wrong one teaches somebody they misread a
 * sentence they never looked at.
 *
 * A hit inside a sentence some question's answer already claims is dropped,
 * and that is the rule that decides most of them. Two reasons, and the
 * second is the one that matters:
 *
 * A learner who wrote the right word in the wrong form — `centre` for
 * `urban centres` — would have the answer's own sentence marked red as the
 * thing that misled them, which is exactly backwards.
 *
 * And a word inside ANOTHER question's answer cannot be drawn. One stretch
 * of prose gets one mark (`overlaysIn`), the longer wins, so the red word
 * would be swallowed by the green sentence around it and come back as part
 * of a mark that says the opposite of what it means. A mark whose colour
 * lies is worse than no mark, so the honest answer is to say nothing — the
 * row still names the answer they should have given, which is what it was
 * always for.
 */
export function writtenDistractors(
  results: QuestionResult[],
  paragraphs: { partId: string; index: number; text: string }[],
  /** Everything the answers layer has already claimed. */
  taken: Overlay[],
): Overlay[] {
  const out: Overlay[] = [];
  for (const result of results) {
    if (result.is_correct) continue;
    // Only where nothing better is known. A lettered answer's distractor
    // comes from the paper and is already in `evidenceOverlays`.
    if (result.answered_by === "letters" || result.distractor?.length) continue;
    const wrote = result.given_answer.trim();
    if (wrote.length < 3) continue;

    const hits: { partId: string; index: number; start: number }[] = [];
    for (const paragraph of paragraphs) {
      const hay = paragraph.text.toLowerCase();
      const needle = wrote.toLowerCase();
      for (
        let at = hay.indexOf(needle);
        at >= 0;
        at = hay.indexOf(needle, at + 1)
      ) {
        if (bounded(paragraph.text, at, needle.length)) {
          hits.push({
            partId: paragraph.partId,
            index: paragraph.index,
            start: at,
          });
        }
      }
    }
    if (hits.length !== 1) continue;

    const [hit] = hits;
    const claimed = taken.some(
      (span) =>
        span.partId === hit.partId &&
        span.index === hit.index &&
        hit.start < span.end &&
        hit.start + wrote.length > span.start,
    );
    if (claimed) continue;

    out.push({
      partId: hit.partId,
      index: hit.index,
      start: hit.start,
      end: hit.start + wrote.length,
      tone: "chose",
      key: result.question_id,
      labels: [`Q${result.number}`],
      title: `Question ${result.number} — you wrote this`,
    });
  }
  return out;
}

const WORDISH = /[\p{L}\p{N}]/u;

/** Whether a match stands as a whole word. `art` inside `particular` is not
 *  the reader's word, and marking it would be the page pointing at a
 *  coincidence. */
function bounded(text: string, at: number, length: number): boolean {
  const before = text[at - 1];
  const after = text[at + length];
  return (
    (before === undefined || !WORDISH.test(before)) &&
    (after === undefined || !WORDISH.test(after))
  );
}

/**
 * The passage's glossed words, as marks over the words themselves.
 *
 * **One tone, three colours.** Every word is washed in the colour of its
 * CEFR level, and nothing else changes the wash — so the passage is a map
 * of its own difficulty before a single entry on the right has been read.
 * A text with three orange words in it and one with thirty are two
 * different afternoons, and a reader can now see which they are in.
 *
 * Two other facts ride on top without taking the hue: a word the reader
 * spent one of their three look-ups on is UNDERLINED, and a word already
 * on their list is flagged for the Saved layer to filter by. Neither is a
 * property of the word — they are facts about this reader — and giving
 * either one a colour is what made the wash stop meaning "level" the first
 * time somebody saved anything.
 *
 * `stale` entries are dropped. The passage has been edited since it was
 * glossed, so the offsets may no longer point at the words they were
 * measured against — and a highlight two words off does not read as an
 * approximation, it reads as a broken page.
 */
export function wordOverlays(
  entries: VocabularyEntry[],
  saved: (lemma: string) => boolean,
  lookedUp: (lemma: string) => boolean,
): Overlay[] {
  const out: Overlay[] = [];
  for (const entry of entries) {
    if (entry.stale) continue;
    out.push({
      partId: entry.part_id,
      index: entry.paragraph_index,
      start: entry.offset_start,
      end: entry.offset_end,
      tone: "word",
      level: entry.cefr_level,
      lookedUp: lookedUp(entry.lemma),
      saved: saved(entry.lemma),
      key: entry.lemma,
      title: entry.meaning_uz || entry.meaning_en,
    });
  }
  return out;
}

/**
 * One paragraph's overlays, in order and without overlaps.
 *
 * `runsOf` cuts a paragraph on the assumption that its marks are sorted and
 * disjoint, and this layer's are neither by nature. Two vocabulary entries
 * genuinely overlap — `give rise to` is one entry and `rise` inside it is
 * another — and the evidence for two questions can be the same sentence.
 *
 * The LONGER one wins, and the shorter is dropped rather than clipped. A
 * clipped mark is a highlight that stops mid-word, which reads as a bug; and
 * where the two are a phrase and a word inside it, the phrase is the one the
 * reader needs told about, because it is the one they could not have worked
 * out from the parts.
 *
 * But the one that wins ANSWERS TO BOTH. `vogue` is in this passage's word
 * list — it was one of the three the reader spent a look-up on — and the
 * only mark over it belongs to `in vogue`, so without this, pointing at the
 * entry that beat them lights nothing and the page looks broken at exactly
 * the row that matters most.
 */
export function overlaysIn(
  all: Overlay[],
  partId: string,
  index: number,
): Overlay[] {
  const mine = all
    .filter((o) => o.partId === partId && o.index === index && o.end > o.start)
    .sort((a, b) => a.start - b.start || b.end - a.end);

  const out: Overlay[] = [];
  for (const overlay of mine) {
    const last = out[out.length - 1];
    if (last && overlay.start < last.end) {
      last.also = [...(last.also ?? []), overlay.key];
      // And its number. Two questions decided by one sentence is ordinary —
      // a TRUE/FALSE pair often turns on the same clause — and a mark
      // labelled `Q31` that is also where Q32 was is a mark lying by
      // omission to whoever is looking for Q32.
      if (overlay.labels?.length) {
        last.labels = [...(last.labels ?? []), ...overlay.labels];
      }
      continue;
    }
    // Copied, because the lines above write to it and these come from a
    // memo the page holds across renders.
    out.push({ ...overlay });
  }
  return out;
}

/** Whether a mark is the one being pointed at. See `Overlay.also`. */
export function points(overlay: Overlay, at: string | null): boolean {
  return (
    at != null && (overlay.key === at || (overlay.also?.includes(at) ?? false))
  );
}

/**
 * How each tone is washed over the prose.
 *
 * The same weight as the reader's own marks — see `PassagePane`'s `WASH`,
 * which arrived at two fifths by being wrong at a quarter — and never green,
 * because green means "you got this right" everywhere else on this page and
 * the evidence layer is marking what somebody got wrong.
 *
 * The lit state is the hover link between the two panes: a mistake under the
 * pointer on the right brightens its evidence on the left, and a word does
 * the same. Brighter rather than a different colour — it is the same mark
 * being pointed at, not a different kind of mark.
 */
export const WASH: Record<
  Overlay["tone"],
  { rest: string; lit: string; tag: string }
> = {
  /** What pulled them: the option or the word they actually gave. */
  chose: {
    rest: "bg-incorrect/20 decoration-incorrect/50 underline decoration-2 underline-offset-4",
    lit: "bg-incorrect/40 decoration-incorrect",
    tag: "text-incorrect",
  },
  /** The answer to a question they got wrong. A wash, because it is being
   *  read against the red one beside it and a rule alone would lose that
   *  comparison before it started. */
  missed: {
    rest: "bg-correct/18 decoration-correct/50 underline decoration-2 underline-offset-4",
    lit: "bg-correct/35 decoration-correct",
    tag: "text-correct",
  },
  /** The answer to one they got right: a rule and nothing else. Two washes
   *  per mistake plus a wash per success is a passage with no unmarked
   *  prose left in it, and a page where everything is marked has marked
   *  nothing. */
  got: {
    // `bg-transparent` is not redundant: a <mark> with no background of its
    // own falls back to the browser's, which is a block of highlighter
    // yellow — the one colour on this page that belongs to the vocabulary
    // layer. Every other tone happens to cover it.
    rest: "bg-transparent decoration-correct/45 underline decoration-2 underline-offset-4",
    lit: "bg-correct/20 decoration-correct",
    tag: "text-correct/70",
  },
  /** A glossed word. Only the shape of the mark lives here: the COLOUR is
   *  the word's level and comes from `cefr.ts`, which is why this one has
   *  no classes of its own — see `wordStyle`. */
  word: { rest: "", lit: "", tag: "text-foreground" },
};

/**
 * How one glossed word is drawn: its level's wash, plus whatever this
 * reader did to it.
 *
 * Three channels that cannot be confused for one another, because each is
 * a different KIND of mark rather than a different colour:
 *
 * - the **wash** is the level, and never anything else;
 * - an **underline** is one of the three look-ups this reader spent;
 * - a **ring** is the pointer, on the row opposite, right now.
 *
 * The ring is deliberately not a stronger wash. A stronger wash of the same
 * hue reads as a harder word, so hovering a row would appear to change what
 * the level is — the one thing the colour is there to say.
 */
export function wordStyle(overlay: Overlay, lit: boolean): string {
  const tone = toneOf(overlay.level);
  return [
    tone.wash,
    overlay.lookedUp
      ? // The reader's own underline, in the level's own colour: it marks
        // WHICH words they stopped on without claiming they are a
        // different kind of word.
        `underline decoration-2 underline-offset-4 ${tone.line}`
      : "",
    lit ? tone.lit : "",
  ]
    .filter(Boolean)
    .join(" ");
}

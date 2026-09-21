import type { QuestionResult } from "@/features/paper/types";
import type { VocabularyEntry } from "@/features/vocabulary/types";

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
 * That is deliberate rather than convenient. The reader chose amber, blue or
 * violet for each mark while they were reading, and those choices MEAN
 * something — the keyword, where the answer was, the line to come back to.
 * Repainting them one neutral colour here would throw away the only part of
 * a mark that carries information, on the one page whose whole purpose is to
 * give that information back. The swatch in the toggle is neutral because
 * the LAYER has no colour; its marks have three.
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
  /** How it is washed. Not the layer's id: `saved` and `vocabulary` are two
   *  layers and one of them draws a word in each of two states, and the
   *  answers layer draws two verdicts. */
  tone: "right" | "wrong" | "word" | "saved";
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
}

/**
 * Where every answer was, marked green where it was got and red where it
 * was not.
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
        tone: result.is_correct ? "right" : "wrong",
        key: result.question_id,
        labels: [`Q${result.number}`],
        title: result.is_correct
          ? `Question ${result.number} — you got this one`
          : `Question ${result.number} — the answer was here`,
      });
    }
  }
  return out;
}

/**
 * The passage's glossed words, as marks over the words themselves.
 *
 * Two tones out of one list. A word this reader has already saved is drawn
 * as `saved` wherever it appears, in both layers — which is the point of the
 * Saved layer existing at all: somebody who saved `deepen` a fortnight ago
 * and meets it again in a new passage is having the single most effective
 * vocabulary lesson there is, and it costs nothing but the marking.
 *
 * `stale` entries are dropped. The passage has been edited since it was
 * glossed, so the offsets may no longer point at the words they were
 * measured against — and a highlight two words off does not read as an
 * approximation, it reads as a broken page.
 */
export function wordOverlays(
  entries: VocabularyEntry[],
  saved: (lemma: string) => boolean,
  only?: "saved",
): Overlay[] {
  const out: Overlay[] = [];
  for (const entry of entries) {
    if (entry.stale) continue;
    const isSaved = saved(entry.lemma);
    if (only === "saved" && !isSaved) continue;
    out.push({
      partId: entry.part_id,
      index: entry.paragraph_index,
      start: entry.offset_start,
      end: entry.offset_end,
      tone: isSaved ? "saved" : "word",
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
  wrong: {
    rest: "bg-incorrect/20 decoration-incorrect/50 underline decoration-2 underline-offset-4",
    lit: "bg-incorrect/40 decoration-incorrect",
    tag: "text-incorrect",
  },
  // Quieter than the red, deliberately. Both are on the page at once and
  // they are not equally interesting: what a reader came here for is the
  // ones they lost, and green at the same strength turns the passage into
  // a stripe pattern with no figure in it.
  right: {
    rest: "bg-correct/12 decoration-correct/40 underline decoration-2 underline-offset-4",
    lit: "bg-correct/30 decoration-correct",
    tag: "text-correct",
  },
  word: { rest: "bg-mark-key/25", lit: "bg-mark-key/50", tag: "text-primary" },
  saved: {
    rest: "bg-mark-found/25",
    lit: "bg-mark-found/50",
    tag: "text-mark-found",
  },
};

/** The swatch a toggle wears, so the row of four says which colour means
 *  which without a legend under it. "My marks" has none of its own — its
 *  marks keep the colours the reader chose — so it wears the foreground. */
export const SWATCH: Record<LayerId, string> = {
  // Two colours, because the layer draws two verdicts and a swatch that
  // showed one of them would be the control claiming to mark only the
  // mistakes — which is what it used to do.
  answers: "bg-gradient-to-r from-correct to-incorrect",
  vocabulary: "bg-mark-key",
  saved: "bg-mark-found",
  marks: "bg-foreground/40",
};

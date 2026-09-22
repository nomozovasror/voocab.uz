import { cn } from "@/lib/utils";
import type { Passage } from "@/features/paper/types";
import {
  marksIn,
  runsOf,
  type Highlight,
  type MarkStyle,
} from "@/features/reading/highlights";
import {
  overlaysIn,
  points,
  wordStyle,
  WASH as LAYER_WASH,
  type Overlay,
} from "@/features/reading/layers";

/**
 * The text a reading paper is answered from.
 *
 * It is half the screen and it is the half that does not change, which is
 * what makes the two-pane layout right for reading where one scroll is right
 * for listening: a recording plays once through whatever is on screen, and a
 * passage is looked BACK at, sentence by sentence, against the question in
 * hand. A candidate on question 9 wants paragraph C and question 9 in view at
 * the same time, and nothing but two scrolls gives them that.
 *
 * Paragraph letters are printed where the passage has them, in the margin
 * rather than inline: two of Reading's own tasks are answered by naming one
 * ("which paragraph contains the following information"), so the letter has
 * to be findable at a glance down the edge, and it must not read as the first
 * word of the paragraph.
 */

interface PassagePaneProps {
  title: string;
  passage: Passage;
  /** Which part this passage belongs to. Part of every anchor it prints,
   *  because a paper has three passages and each one letters its paragraphs
   *  from A: without it a page carries three elements called `p-C` and every
   *  jump lands on the first of them. */
  partId: string;
  /** Whether to print the passage's own heading above it. False where it is
   *  the only passage on the page — see the comment where it is drawn. */
  showTitle?: boolean;
  /** What the reader marked. Drawn here and nowhere else — the passage is
   *  the only thing on either page there is anything to mark. */
  highlights?: Highlight[];
  /** Clicking a mark asks for it to go. Absent on the review, where the
   *  marks are a record of how the paper was read rather than a tool. */
  onUnmark?: (index: number, offset: number) => void;
  /** A paragraph to draw attention to — the review page points at the one an
   *  answer came from. Null while the paper is being sat: there is nothing to
   *  point at yet, and pointing would be telling. */
  highlight?: string | null;
  /** What the REVIEW has to say about this text: where the answers were,
   *  which words are worth learning, which of those are already saved. One
   *  layer's worth — see `features/reading/layers.ts` on why never four.
   *
   *  Absent while the paper is being sat, and that is not a matter of
   *  tidiness: every one of these is an answer. */
  overlays?: Overlay[];
  /** The overlay `key` currently being pointed at from the other pane, drawn
   *  brighter. One key rather than one overlay, because a question's
   *  evidence can be two sentences and lighting one of them lights half of
   *  why the reader was wrong. */
  lit?: string | null;
  /** Pointing at a mark from THIS side, which lights the row that belongs to
   *  it in the other pane. The hover link works both ways or it is a trick
   *  the reader has to learn the direction of. */
  onPoint?: (key: string | null) => void;
  /**
   * Asking what ONE word means — any word, not only a marked one.
   *
   * Absent while the paper is being sat, and that absence is the feature
   * rather than an omission: mid-paper a lookup costs one of three and goes
   * through the selection popover, because the budget exists to make
   * somebody choose. Afterwards there is no exam habit left to protect and
   * the passage becomes a text a learner can interrogate.
   *
   * It is what closes the hole this was built for. `appropriate` is NGSL
   * rank 1019, so the frequency filter calls it known and never glosses it;
   * a reader who did not know it, did not look it up during the paper and
   * did not highlight it had NO way to find out what it meant afterwards.
   * The extraction's edges were being handed to the learner as their own.
   */
  onWord?: (
    word: string,
    where: { paragraphIndex: number; offset: number },
    rect: DOMRect,
  ) => void;
  className?: string;
}

/** How each mark is drawn over the prose — one amber, two strokes.
 *
 *  The fill is a wash rather than a block, so the words underneath stay the
 *  foreground: a passage with six marks in it has to still read as a
 *  passage. It was a quarter of the colour and that was too little to read
 *  as a highlight at all — against a dark ground a 25% tint of amber is a
 *  change in shade, not a mark, and a reader scanning back through nine
 *  hundred words could not find what they had marked. Two fifths, with the
 *  padding and the small radius of a real marker stroke, which is what
 *  carries most of it: what says "highlighted" is the shape of the block
 *  around the words rather than the strength of the colour in it.
 *
 *  The line is the same amber with no ground at all, which is why the two
 *  are told apart across a page of prose at a glance where two tints of
 *  one colour would have to be compared. It is also what the doubt mark
 *  should always have looked like: an underline is what somebody draws
 *  when they are not sure, and a block is what they draw when they are. */
const WASH: Record<MarkStyle, string> = {
  fill: "bg-mark-key/40",
  // `bg-transparent` is load-bearing, and the same trap the `got` overlay
  // fell into: a <mark> with no background of its own falls back to the
  // BROWSER's, which is a block of highlighter yellow — so the line mark
  // came out as a solid amber block, which is the other mark. Every style
  // with no ground of its own has to say so.
  line: "bg-transparent decoration-mark-key underline decoration-2 underline-offset-4",
};

/** How a deciding word is drawn inside the mark around it. A stronger tint
 *  of the mark's own colour — see where it is used. Only the answers layer
 *  sets `inner` at all, so the word tone has nothing to say here and wears
 *  weight alone. */
const HARD: Record<Overlay["tone"], string> = {
  chose: "bg-incorrect/35",
  missed: "bg-correct/35",
  got: "bg-correct/25",
  word: "",
};

/**
 * One mark's text, split around the stretches to draw harder.
 *
 * Offsets arrive in the PARAGRAPH's coordinates and the text is the mark's,
 * so everything is measured from where the mark starts. Ranges outside it
 * are ignored rather than clamped: a word that is not in this sentence is
 * not this sentence's word, and clamping would draw it at the edge.
 */
function inside(
  text: string,
  at: number,
  ranges: { start: number; end: number }[] | undefined,
): { text: string; hard: boolean; at: number }[] {
  const mine = (ranges ?? [])
    .map((one) => ({ start: one.start - at, end: one.end - at }))
    .filter(
      (one) => one.start >= 0 && one.end <= text.length && one.end > one.start,
    )
    .sort((a, b) => a.start - b.start);
  if (!mine.length) return [{ text, hard: false, at }];

  // Every piece carries where it starts in the PARAGRAPH, not in the mark.
  // Nothing needed that until any word became clickable; now a word inside
  // a marked sentence has to report the same offset as the same word
  // outside one, or the server is asked about the wrong occurrence.
  const out: { text: string; hard: boolean; at: number }[] = [];
  let cut = 0;
  for (const one of mine) {
    if (one.start < cut) continue;
    if (one.start > cut) {
      out.push({ text: text.slice(cut, one.start), hard: false, at: at + cut });
    }
    out.push({
      text: text.slice(one.start, one.end),
      hard: true,
      at: at + one.start,
    });
    cut = one.end;
  }
  if (cut < text.length) {
    out.push({ text: text.slice(cut), hard: false, at: at + cut });
  }
  return out;
}

/**
 * What counts as a word somebody might want the meaning of.
 *
 * Letters and digits INSIDE, plus the two marks that live inside English
 * words — the apostrophe in both its shapes, because a passage read off a
 * printed page carries the typographic one and one typed by an author
 * carries the straight one, and `Earth's` has to be one word either way.
 *
 * But it must START with a letter, and that is not tidiness. `15-year-olds`
 * otherwise matches from the digit, and the offset sent is then three
 * characters before the `year-old` entry's span — so the server's
 * span-containment test finds nothing, the string match fails on a token
 * with a number in it, and a word the passage already has glossed gets
 * glossed a second time under a name nobody typed. Starting at the letter
 * puts the offset inside the entry, where one lookup answers.
 *
 * It also means a bare number is not a target, which is right on its own
 * terms: nobody wants the meaning of `15`.
 */
const WORD = /\p{L}[\p{L}\p{N}'\u2019-]*/gu;

/** What a word wears when it can be asked about.
 *
 *  A dotted underline on hover and a pointer, and nothing at rest. Nine
 *  hundred words each carrying a permanent hint is a passage nobody can
 *  read; the affordance only has to exist at the moment somebody is
 *  pointing at a word, which is the moment they are wondering about it.
 *
 *  Dotted rather than solid because solid is taken twice over on this page
 *  — the look-up underline under a glossed word, and the reader's own line
 *  mark — and a hover state that looks like a permanent mark is a page
 *  telling the reader they have already done something. */
const WORDABLE =
  "cursor-pointer hover:underline hover:decoration-dotted hover:decoration-muted-foreground hover:underline-offset-[0.25em]";

/**
 * One run of prose, with each word made a target.
 *
 * Plain text where nothing can be asked — the take screen — so the passage
 * there carries not one extra element. Where it can, every word becomes a
 * `<span>` carrying only its OFFSET, and the click is caught once on the
 * article by delegation. Nine hundred spans each closing over a handler is
 * nine hundred closures rebuilt on every render of a page that re-renders
 * on every hover; nine hundred spans carrying a number is a number each.
 *
 * The gaps between words stay bare text. Punctuation and spaces are not
 * things anybody wants the meaning of, and wrapping them would double the
 * element count to make the space between two words hoverable.
 */
function Words({ text, at, on }: { text: string; at: number; on: boolean }) {
  if (!on) return <>{text}</>;
  const out: React.ReactNode[] = [];
  let cut = 0;
  for (const found of text.matchAll(WORD)) {
    const start = found.index;
    if (start > cut) out.push(text.slice(cut, start));
    out.push(
      <span key={start} data-word={at + start} className={WORDABLE}>
        {found[0]}
      </span>,
    );
    cut = start + found[0].length;
  }
  if (cut < text.length) out.push(text.slice(cut));
  return <>{out}</>;
}

/** What every mark wears, whatever colour it is. `box-decoration-clone` is
 *  the one that matters: a mark that wraps across a line break would
 *  otherwise get its padding and rounding only at the two outer ends, and
 *  the middle lines would run flush into the margin. */
const STROKE =
  "rounded-[0.2em] px-[0.12em] py-[0.05em] [box-decoration-break:clone]";

/** The id a paragraph can be scrolled to by, so the review's "go to
 *  paragraph C" and the letter printed beside it name the same thing. */
export function paragraphId(partId: string, label: string): string {
  return `passage-${partId}-${label}`;
}

/** How one of the reader's own marks is named, so the list beside the
 *  passage and the mark on it agree about which is which. Its own START
 *  rather than the run's, because two touching marks are drawn as one shape
 *  and a key taken from the wrong half would light nothing. */
export function markKey(partId: string, index: number, start: number): string {
  return `${partId}:${index}:${start}`;
}

/** The id the whole passage can be scrolled to by. The take screen brings
 *  the passage pane to it when the reader crosses into the questions that
 *  are answered from it. */
export function passageId(partId: string): string {
  return `passage-${partId}`;
}

export function PassagePane({
  title,
  passage,
  partId,
  showTitle = true,
  highlights,
  onUnmark,
  highlight,
  overlays,
  lit,
  onPoint,
  onWord,
  className,
}: PassagePaneProps) {
  return (
    <article
      id={passageId(partId)}
      aria-label={title}
      // One handler for nine hundred words. Every word span carries its own
      // offset and nothing else, and the paragraph it is in is found by
      // walking up to the element that already had to know — so adding this
      // costs the passage one listener rather than one per word.
      onClick={
        onWord
          ? (e) => {
              // A drag to SELECT ends in a click, over whichever word the
              // mouse was released on. Without this, every reader copying a
              // sentence out of the passage gets a dictionary card for its
              // last word — and the selection they were making is what the
              // card's own arrival collapses.
              const picked = window.getSelection();
              if (picked && !picked.isCollapsed) return;
              const span = (e.target as HTMLElement).closest<HTMLElement>(
                "[data-word]",
              );
              const para = span?.closest<HTMLElement>(
                "[data-paragraph-index]",
              );
              if (!span || !para) return;
              onWord(
                span.textContent ?? "",
                {
                  paragraphIndex: Number(para.dataset.paragraphIndex),
                  offset: Number(span.dataset.word),
                },
                span.getBoundingClientRect(),
              );
            }
          : undefined
      }
      className={cn("max-w-prose", className)}
    >
      {/* No heading of its own where there is only one passage on the page.
          It said "Reading Passage 2" under a page already titled with the
          passage's name, beside a meta line already saying which passage of
          which test it is — four lines of the most expensive space on this
          screen spent on one fact, while the prose below them was cut off
          mid-sentence. `showTitle` puts it back for a paper that holds
          three, where the reader does need to know which one they are in. */}
      {showTitle && (
        <h2 className="mb-1 text-lg font-semibold text-foreground">{title}</h2>
      )}
      {passage.subtitle && (
        <p className="mb-5 text-sm leading-relaxed text-muted-foreground">
          {passage.subtitle}
        </p>
      )}

      <div className="space-y-4">
        {passage.paragraphs.map((paragraph, index) => (
          <div
            key={index}
            id={
              paragraph.label ? paragraphId(partId, paragraph.label) : undefined
            }
            className={cn(
              "flex gap-3 rounded-md transition-colors duration-slow",
              highlight &&
                paragraph.label === highlight &&
                "-mx-2 bg-primary/5 px-2 py-1",
            )}
          >
            {/* Only where the book prints one. A letter invented for a
                passage that has none would be a letter no question can
                name. */}
            {paragraph.label && (
              <span
                aria-hidden
                className={cn(
                  "w-4 shrink-0 pt-0.5 text-[0.8em] font-semibold tabular-nums",
                  highlight === paragraph.label
                    ? "text-primary"
                    : "text-muted-foreground",
                )}
              >
                {paragraph.label}
              </span>
            )}
            <p
              // The offsets a selection is measured against are offsets into
              // THIS element's text, so it is the one the page reaches for.
              data-paragraph-index={index}
              // `em`, not `rem`: the size control sets a percentage on the
              // pane, and an absolute size ignores it — which is what the
              // first version of the control did, silently.
              className="min-w-0 flex-1 text-[0.95em] leading-[1.72] text-foreground"
            >
              {/* Two kinds of marking, never both at once.

                  A paragraph carries either what the READER put on it — the
                  take screen, and the review's "My marks" layer, which is
                  the same data drawn the same way — or what the REVIEW has
                  to say about it. Laid over each other they would be two
                  systems of colour in one sentence, which is the thing
                  `layers.ts` exists to prevent one level up. */}
              {overlays
                ? runsOf(
                    paragraph.text,
                    overlaysIn(overlays, partId, index),
                  ).map((run, k) =>
                    run.mark ? (
                      <mark
                        key={k}
                        // What the other pane scrolls to. On the MARK rather
                        // than on the paragraph, because a paragraph is
                        // ninety words and the reader was promised a
                        // sentence — and because a question's evidence can
                        // be in two paragraphs, of which this names the
                        // first drawn.
                        data-overlay={run.mark.key}
                        // And the keys of whatever this mark swallowed, so
                        // two questions whose evidence is the SAME sentence
                        // can both be jumped to. Space-separated for the
                        // `~=` selector that reads it; only question ids are
                        // ever looked up this way, and those have no spaces
                        // in them.
                        data-overlay-also={run.mark.also?.join(" ")}
                        title={run.mark.title || undefined}
                        onMouseEnter={
                          onPoint ? () => onPoint(run.mark!.key) : undefined
                        }
                        onMouseLeave={onPoint ? () => onPoint(null) : undefined}
                        className={cn(
                          "text-foreground transition-colors duration-fast",
                          STROKE,
                          // A glossed word is coloured by its LEVEL and
                          // not by its layer, so it is the one tone whose
                          // classes are not in the table — see
                          // `wordStyle`.
                          run.mark.tone === "word"
                            ? wordStyle(
                                run.mark,
                                points(run.mark, lit ?? null),
                              )
                            : cn(
                                LAYER_WASH[run.mark.tone].rest,
                                points(run.mark, lit ?? null) &&
                                  LAYER_WASH[run.mark.tone].lit,
                              ),
                        )}
                      >
                        {/* The number, at the FRONT of the mark and in
                            the passage's own size.

                            It was a superscript on the end, which is where a
                            footnote goes — and a footnote is read after the
                            sentence, which is the wrong way round here. The
                            reader is looking FOR question 28, not reading a
                            sentence and wondering afterwards what it was
                            about: the number has to be the thing they meet
                            first, at the left edge where the eye already is.

                            Full size and bold rather than small and raised,
                            for the same reason. A 0.6em superscript is a
                            reference mark — something to notice once you
                            already care — and this is a label somebody scans
                            a page for.

                            Inside the <mark> so it travels with the wash and
                            cannot be separated from it by a line break, and
                            `select-none` so copying the passage does not
                            take "Q12" out with it: the text under these marks
                            is the book's, and somebody copying a sentence
                            into their notes should get the sentence. */}
                        {run.mark.labels?.length ? (
                          <span
                            className={cn(
                              "mr-1.5 font-bold select-none",
                              LAYER_WASH[run.mark.tone].tag,
                            )}
                          >
                            {run.mark.labels.join(" ")}
                          </span>
                        ) : null}
                        {inside(run.text, run.at, run.mark.inner).map(
                          (piece, n) =>
                            piece.hard ? (
                              // The word the statement turns on, inside the
                              // sentence that settles it. A mark within a
                              // mark, drawn by splitting the outer one's own
                              // text — the only way to nest two, since one
                              // run of prose gets one <mark>.
                              //
                              // Weight and a stronger tint of the SAME
                              // colour, never a different one: it is not a
                              // third kind of finding, it is the point of
                              // the one already drawn.
                              <strong
                                key={n}
                                className={cn(
                                  "rounded-[0.15em] font-semibold",
                                  HARD[run.mark!.tone],
                                )}
                              >
                                <Words
                                  text={piece.text}
                                  at={piece.at}
                                  on={Boolean(onWord)}
                                />
                              </strong>
                            ) : (
                              <span key={n}>
                                <Words
                                  text={piece.text}
                                  at={piece.at}
                                  on={Boolean(onWord)}
                                />
                              </span>
                            ),
                        )}
                      </mark>
                    ) : (
                      <span key={k}>
                        <Words
                          text={run.text}
                          at={run.at}
                          on={Boolean(onWord)}
                        />
                      </span>
                    ),
                  )
                : runsOf(
                    paragraph.text,
                    marksIn(highlights ?? [], partId, index),
                  ).map((run, k) =>
                    run.mark ? (
                      // `mark` rather than a span: it is literally what the
                      // element is for, and it is what a screen reader announces
                      // as marked text. A click takes it off again — the same
                      // gesture that put it on, which is how every highlighter
                      // in a document works.
                      <mark
                        key={k}
                        title={run.mark.note || undefined}
                        onClick={
                          onUnmark ? () => onUnmark(index, run.at) : undefined
                        }
                        // The reader's own marks join the hover link too,
                        // keyed the way `ReviewMarks` keys its rows: the
                        // merged mark's own start, since two touching marks
                        // are one shape here and must be one row there.
                        // Absent on the take screen, which hands in no
                        // `onPoint` and has no list to light.
                        onMouseEnter={
                          onPoint
                            ? () =>
                                onPoint(markKey(partId, index, run.mark!.start))
                            : undefined
                        }
                        onMouseLeave={onPoint ? () => onPoint(null) : undefined}
                        className={cn(
                          "text-foreground",
                          STROKE,
                          WASH[run.mark.style ?? "fill"],
                          // A note is a mark that says something, and it has to
                          // look like one or the reader cannot tell which of
                          // their own marks they wrote on. An underline rather
                          // than an icon: an icon inside running prose is a
                          // character the sentence did not have.
                          //
                          // Dotted, which is what keeps it apart from the
                          // line mark now that the line mark is also an
                          // underline — a note on a line mark is the one
                          // case where both are on the same words, and it
                          // reads as the dotted one winning, which is
                          // right: the note is the more specific claim.
                          run.mark.note &&
                            "decoration-mark-key decoration-dotted underline decoration-2 underline-offset-4",
                          onUnmark && "cursor-pointer",
                          lit === markKey(partId, index, run.mark.start) &&
                            "ring-2 ring-foreground/30",
                        )}
                      >
                        <Words
                          text={run.text}
                          at={run.at}
                          on={Boolean(onWord)}
                        />
                      </mark>
                    ) : (
                      <span key={k}>
                        <Words
                          text={run.text}
                          at={run.at}
                          on={Boolean(onWord)}
                        />
                      </span>
                    ),
                  )}
            </p>
          </div>
        ))}
      </div>

      {/* The acknowledgement line the book prints under the passage. Kept
          because it is part of the paper, and because a passage with no
          source reads as something the app wrote. */}
      {passage.source && (
        <p className="mt-6 border-t border-border pt-3 text-xs text-muted-foreground">
          {passage.source}
        </p>
      )}
    </article>
  );
}

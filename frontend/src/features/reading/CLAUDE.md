# Reading — what is only reading's

Almost nothing, which is the point. The catalogue, the question paper, the
navigator, the draft, the review and the grader are all
`features/paper/`; what lives here is the two things a paper that is READ has
that a paper that is HEARD does not.

## The passage, and why the take screen is two panes

`frontend/src/features/listening/CLAUDE.md` says the take screen is ONE
SCROLL, and that rule does not come here.

A recording plays through whatever is on screen, so scrolling costs nothing.
A passage is read BACK against the question in hand: a candidate on question
9 wants paragraph C and question 9 in view at the same time, and one scroll
would mean moving nine hundred words out of the way to reach the question and
back again to answer it. So the take screen is two panes with their own
scrolls and a divider between them — which is also the shape of the real
computer-delivered paper.

What DOES come here, unchanged: the strip along the bottom is the navigation,
Tab moves between questions, flags belong to the draft, and the submit button
is called what `TakeConfig` says.

- **The split is remembered, and it is not a preference.**
  `frontend/CLAUDE.md` says preferences default to off and exist because
  somebody asked for the behaviour; this is the position of a thing on
  screen, like a scroll position.
- **Below the breakpoint there is no split**, because two panes in 380px is
  two columns of four words. The tabs that replace it keep BOTH panes
  mounted: the questions carry typed answers and the focus timing that
  measures them, and unmounting to look something up would throw both away.
- **The passage pane follows the question, one passage at a time.** A paper
  is three passages of nine hundred words in one scroll, so a candidate on
  question 30 was being asked to scroll past two thousand words they had
  finished with. Side by side is only half of what two panes are for. It
  moves when the reader crosses into another PASSAGE and never between
  questions of the same one — inside a passage the reader is moving around
  the text deliberately, and a pane that re-scrolled under them there would
  take away the paragraph they were in the middle of. On a narrow screen the
  same thing happens when the passage tab is opened, so it opens at the
  question's own passage rather than wherever it was left.

## Paragraph letters come off the page, never from position

`Passage.paragraphs[].label` is the letter the book prints, and it is
nullable because most passages have none — a book letters its paragraphs only
where a task is answered by naming one. Deriving them from position instead
would break on any passage whose lettering starts at B or skips one, and
every "which paragraph contains…" answer on it would be off by one.

The letter is printed in the margin rather than inline, so it is findable at a
glance down the edge and does not read as the first word of the paragraph.

**Every anchor a passage prints carries its PART.** `paragraphId(partId,
label)` and `passageId(partId)` are the only two ways to name one. Three
passages each letter from A, so a page that anchored on the bare letter
carried three elements called `p-C` and every jump landed on the first.

## The review is the take screen again, with the passage marked

The review used to put the text last and collapsed: a score, the wrong
answers, a hundred and one vocabulary entries down a column that did not end,
and the nine hundred words the whole hour was spent inside behind a
`<details>` called *Read the passage again*.

That is the wrong way round, because **everything a review has to say is a
statement about the passage** — this is where the answer was, this is the
word you did not know, this is the one you saved a fortnight ago and have
just met again. Beside the text each of those is a lesson; in a list on its
own each is a row of data.

So `ReadingResultsPage` is `ReadingTakePage`'s shape: two panes, the header's
three islands, the same full-bleed pull under the chrome. The reader does not
have to learn it — they were in it twenty minutes ago. What is different is
what is written on the passage.

**One layer at a time, never four** (`layers.ts`). Every answer in green and
red, the vocabulary in the CEFR colours, the already-saved words as those
same words filtered, and the reader's own marks. Four kinds of marking over
nine hundred words at once is not four findings, it is a page of colour with
prose underneath it. One at a time makes each a QUESTION somebody asked.

**And one CONTROL, not two.** The toggle in the middle island decides both
what is marked on the passage and what is listed beside it. It was two — the
layers in the header and a pair of tabs over the analysis, with *Mistakes*
and *Vocabulary* printed in both — and they did one thing between them, since
pressing a tab already moved the layer with it. Two controls with one effect
is a reader working out which is the real one.

- **A layer with nothing in it is not offered.** No answers on a paper the
  extraction never reached, no vocabulary where it was never run, no marks
  from a reader who highlighted nothing. Absence reads as "not this paper";
  a disabled button reads as "not you". The same fall-through picks the
  opening layer, so a paper with no evidence opens on the vocabulary with no
  second rule written for it.
- **The score card belongs to the ANSWERS tab, not to the page.** It is the
  headline of how the paper was answered, which is one of the four
  questions this page can be asked — above the word list it was a card
  about something else taking the top of the pane, and its question map was
  forty numbered squares jumping into a panel that is not open. The one
  exception is a paper the evidence extraction never reached: there is no
  answers tab to put it on, so it stays where the page fell through to, or
  the score would be nowhere at all.
- **Every layer has an analysis.** Answers is the marked question list,
  Vocabulary the word list, Saved the same list filtered to what the reader
  had already met, My marks their own highlights grouped by what each stroke
  MEANS. A layer whose panel showed something else would be the page
  contradicting its own control — which is what happened to *My marks*
  before `ReviewMarks` existed.
- **The vocabulary layer's filter comes from the panel and reaches the
  passage.** See `features/vocabulary/CLAUDE.md`: pressing `C1` narrows both
  halves, and the layer's own count is deliberately NOT the filtered one, or
  a filter that matches nothing would read as an empty layer and switch the
  page to a different one.
- **The text size ZOOMS both panes; it does not set a font size.** The take
  screen sets `fontSize` on the split and its prose, written in `em`,
  follows — which works there because the prose is the thing being resized.
  Here the other half of the screen is the answers, and every size in them
  is a Tailwind utility in `rem`, measured from the ROOT and deaf to a font
  size set on a container: the passage grew and the answers beside it did
  not, which is the one thing a reader would never ask for, since the two
  halves are read against each other. Converting five shared components to
  `em` would fix it and bring a worse problem — `em` compounds, and those
  components nest and are also listening's. `zoom` scales a subtree the way
  the browser's own page zoom does, type and padding and rules together,
  with the layout reflowed rather than transformed. It goes on each pane's
  CONTENT and never on the split, whose height is measured in real pixels to
  keep the page itself from scrolling.
- **"My marks" is not an overlay.** It hands `PassagePane` the reader's own
  `Highlight`s and the existing code draws them, so they keep the stroke
  they were made with. That choice means something — *this is the thing*
  versus *I am not sure about this* — and repainting them all one way on the
  one page that exists to give that back would throw away the only part of a
  mark that carries information.

**No line on the review says that every word is clickable.** There was one
— "Click any word to look it up" — and the argument for it holds on paper:
the affordance only appears under the pointer, so nobody finds it by
accident. What it cost was a sentence of instructions over a passage
somebody has just spent twenty minutes inside, on every visit, when the
words that matter are already marked. The dotted underline teaches it once
to whoever sweeps the text and asks nothing of the rest.

**Every word in the passage is clickable, and only here.** `PassagePane`
takes an `onWord`; its absence on the take screen is the three-lookup budget,
and its presence here is that budget having finished. One delegated handler
on the article rather than nine hundred closures — each word span carries its
offset and nothing else — and a dotted underline on hover, at rest nothing,
because nine hundred permanent hints is a passage nobody can read. Said once
above the passages, since an affordance that only appears under the pointer
is one nobody finds by accident. See `features/vocabulary/CLAUDE.md` for what
it is for and what it writes down.

## Where the answer was: evidence, and its fallback

`questions.evidence` is reading's `replay_start_ms`: paragraph and offsets
rather than a moment in a recording, several spans rather than one, found by
`seed/read_evidence.py` and checked by being a real substring's real
position. Pointing at a mistake lights its sentence in the passage; pointing
at that sentence lights the mistake; pressing scrolls to it.

**A question got wrong is marked twice: what pulled you, and what was
true.** The sentence the chosen option came from is red, the sentence that
held the answer is green, and both carry the same number — they are one
explanation, not two facts. Being shown the right line says what was true;
being shown the wrong one says why you believed something else, and only the
second of those is news to the reader.

Where each comes from depends on the task, and only one of the three needs a
model:

- **Multiple choice** — extracted per option, stored on the question's own
  config beside `option_replay`, which is the same field for the listening
  half of the same idea. Usually empty: a distractor is normally invented
  whole, and `seed/read_evidence.py` spends most of its prompt saying so.
- **Matching, in every form** — arithmetic. The box is a shared pool and,
  where it may not be re-used, each option is the right answer to exactly
  one other item, so the distractor is that item's own evidence. No request,
  no column. An option that answers TWO items is not pointed at, because
  picking one of them would be picking a paragraph out of a hat.
- **Written answers** — searched for in the passage, here, at render time
  (`writtenDistractors`). It is not a fact about the paper; it is wherever
  the learner's own word happens to appear. Refused unless it appears
  exactly once and no other mark has claimed that stretch — one run of prose
  gets one mark, so a red word inside a green sentence would be swallowed
  and come back as part of a mark that says the opposite of what it means.
- **True/false and yes/no** — three different answers, because there are
  three different ways to get one wrong. See below; this is the one that
  teaches most.

## TRUE / FALSE / NOT GIVEN is three explanations, not one

NOT GIVEN is the hardest thing about IELTS reading to learn, and what makes
it hard is that **the passage always DOES mention the subject.** A candidate
finds a sentence about the right people doing the right thing, reads one
step past where it stops, and answers TRUE.

So which explanation a statement gets is decided by what the answer was and
what they put:

- **The key is NOT GIVEN and they answered otherwise.** There is no evidence
  — that is what the answer means — so nothing is green. What is drawn is
  the sentence that made them think there was, in red, and the row says *the
  passage mentions this — but never says it.* It is filed as a DISTRACTOR
  under BOTH wrong answers, because whichever of the two they chose, that
  sentence is what they read.

  This used to be filed as evidence, and the review drew it green under "the
  answer was here", which is the opposite of what NOT GIVEN means — on the
  one question type where being wrong about that is the whole difficulty.
- **They answered NOT GIVEN and the passage does say.** The evidence was
  there and they missed it: the ordinary green mark, and the row says *the
  evidence was here all along.*
- **TRUE and FALSE swapped.** One sentence, read with the wrong word in it,
  so pointing at the sentence points at something they had already found.
  The WORD is marked inside the sentence — `Overlay.inner`, drawn by
  splitting the outer mark's own text, since one run of prose gets one
  `<mark>` and a second overlay would be swallowed. A stronger tint of the
  same colour and never a different one: it is not a third kind of finding,
  it is the point of the one already drawn.

The deciding word is withheld from a RIGHT answer, like the trap is. The
sentence is drawn quietly there already, and underlining a word inside it
would be the page explaining something nobody got wrong.

**A question got RIGHT is marked once and quietly** — a thin green rule, no
wash. Two washes per mistake plus a wash per success is a passage with no
unmarked prose left in it, and a page where everything is marked has marked
nothing. (`bg-transparent` is load-bearing there: a `<mark>` with no
background of its own falls back to the browser's highlighter yellow.)

**Every answer is marked, not only the missed ones, and each carries its
number.** It began as the wrong ones alone, on the reasoning that a candidate
who answered question 12 correctly does not need to be shown where question
12 was. That is wrong twice: a passage worked through is a paper somebody
wants to see MARKED, and half a marking is not one; and red marks only mean
"you missed this" while the green ones are there to compare them with —
alone they read as "here are the hard bits", which is a different claim. The
green is drawn quieter than the red, because the two are not equally
interesting.

What keeps the passage from drowning in colour is the `Q12` at the FRONT of
each mark rather than the wash: seventeen coloured sentences is not an answer
to *where was question 31*, and `Q31` beside one of them is. Where one mark
stands for two questions — a TRUE/FALSE pair often turns on one clause — it
prints both numbers, because a mark labelled `Q31` that is also Q32's is
lying by omission to whoever is looking for Q32.

The number is at the front, in the passage's own size, bold. It was a small
superscript on the END, which is where a footnote goes — and a footnote is
read after the sentence, which is the wrong way round: the reader is looking
FOR question 28, not reading a sentence and wondering afterwards what it was
about. It has to be what they meet first, at the left edge where the eye
already is.

Green and red here mean what they mean in the question map at the top of the
same screen: the verdict. That is exactly why the reader's own highlights
are never green or red.

**The row points rather than quotes: `¶3` in the corner**, invisible until
the row is under the pointer, and pressing anywhere on the row goes there. A
sentence-long link inside the row ("The answer is in paragraph C") was the
same fact taking a whole line, on every one of forty rows, and it pushed
what the row exists for further down the page. The corner names the FIRST
mark in the passage, which is where pressing lands — usually the trap rather
than the answer — because a corner that named one paragraph and went to
another would be the page lying about its own control.

`passageQuote` is still here and is the FALLBACK for a paper the extraction
never reached: it finds the answer string in the text and, where the book
letters its paragraphs, the row offers *Paragraph C*. A row never carries
both, or it would offer two ways to two different places. Both are withheld
in silence where they cannot be had — no quote where the answer appears
twice, no paragraph where the book letters none, no mark where the model
could not place one. **A control that points at the wrong line is worse than
no control**, because a candidate uses it to decide what they misread.

**A phrase's mark answers to the words inside it.** `in vogue` and `vogue`
are two entries over three words and only one mark can be drawn, so
`overlaysIn` merges the loser's key into the winner's `also`. Without it,
pointing at `vogue` in the list — one of the three words this reader spent a
look-up on — lights nothing, and the page looks broken at the row that
matters most.

**Switching a layer on and scrolling into it are two renders, not one.** The
mark does not exist until React has drawn the layer, and
`requestAnimationFrame` is not that moment — it can run first. The scroll
belongs in an effect, and the target id is parked in STATE: parked in a ref,
nothing reads it, and the jump silently never happens. The same two-step
applies to jumping to a question the filter is hiding.

## The tools are the real test's, and the budget is ours

Computer-delivered IELTS gives a candidate a highlighter, a note, and the
ability to copy a word out of the passage. Those are not conveniences — they
are how the paper is actually worked, and a practice screen without them
teaches a technique the exam room will not support.

    Highlight · Note · Clear  │  A A A  │  Swap · Look up 3 · Help

Three groups with a rule between each: what MARKS the passage, what SETS it,
and what sits beside it. Nine buttons in one row is a row of nine buttons —
the reader scans all of them every time. Below 80rem the third group folds
into one `⋯`; the two it holds are the two reached for least often.

- **Select, then act.** Never a mode with a pen held down: a reader drags to
  select for half a dozen reasons, and a tool that marked every one of them
  fills the passage with colour by the third paragraph. It also gives every
  button somewhere honest to be disabled, which is how each says what it
  needs.
- **Two paths to the same few actions, on purpose.** The row in the header is
  the one a reader can SEE, before they have selected anything; the popover
  at the selection is the one they use once they know it is there. The
  popover carries only what is done to a STRETCH OF PROSE — two strokes, a
  note, a copy. Size, side and help are about the page, and a popover
  carrying those would be the row again, in the way.
- **One amber, two strokes, and never green or red.** A fill means *this is
  the thing*; an underline means *I am not sure about this*. Green and red
  mean right and wrong on the review page, where these same marks are shown:
  a line highlighted green while reading would come back as a verdict nobody
  made.

  The pen is `--pen` when a theme sets one, else `--primary` (dracula's pen
  is its own yellow, `#f1fa8c`, because its violet accent is the B2 wash).
  Text inside a pen mark is `text-mark-ink`, as inside every CEFR wash.

  It was three HUES — amber, `#5b9bd5`, a violet — until the CEFR scale
  needed colours of its own, and `#5b9bd5` is exactly B1. Blue meaning
  "where the answer was" on one review layer and "this word is B1" on the
  next is two colour systems wearing one colour. CEFR won on reach: it is
  printed on four screens and is a ladder learners already have a feel for,
  where the pen is one reader's annotation on one screen.

  The cost is named rather than hidden: two strokes carry two meanings, so
  "the keyword in the question" and "where the answer was" are now one mark
  between them. They were always the same gesture — *this matters, here* —
  differing only in which half of the screen the reader was looking at. "I
  am not sure" was never like those two, so it kept a channel of its own.

  A fill and a line, not two tints of amber: two strengths of one colour is
  a thing to compare, and a reader scanning back through nine hundred words
  has to RECOGNISE a mark, not measure it. The line needs an explicit
  `bg-transparent` — a `<mark>` with no ground of its own falls back to the
  browser's highlighter yellow, and it came out as a solid amber block,
  which is the OTHER mark. Any style with no background has to say so.

  Marks made before the change are RESTYLED on load, not dropped
  (`loadHighlights`): they live in the browser, so there is no migration and
  no moment at which the old ones are gone. Amber and blue become the fill,
  violet becomes the line.
- **A note IS a mark with words on it**, not a second kind of object beside
  one. Same anchor, same persistence, same click-to-remove — every one of
  which would otherwise be written twice — and an empty note removes the
  mark, because there is then nothing for it to be attached to.
- **Copy goes through the SELECTION.** `document.execCommand` first and
  `navigator.clipboard` second, which is the deprecated one winning on
  merit: the modern API refuses whenever the document is not focused, and
  the old call copies what is already selected, which needs no permission
  because the user chose it by selecting it.

## Look up is counted, and the count is the feature

Three words a passage — `features/reading/lookups.ts`. A reader who can look
anything up is reading with a dictionary, which is not the skill being
practised; a reader who can look up nothing stalls and stops. Three makes it
a DECISION, and somebody with three left spends them on the words the
questions turn on.

Unique words, not openings: looking the same word up again is free, or the
budget would be teaching people not to check their own memory. Sitting the
paper again resets the count and keeps the words — a second attempt is a
fresh three, and a word already explained is not a lookup any more. Absent
entirely in an exam rather than disabled: a greyed-out dictionary is the
page telling a candidate what they may not have, every minute of an hour.

The words are kept, not just the number, because the review page lists them.
"You looked up three words" with the words under it is a vocabulary list out
of a passage just read closely; a bare count is a score for something nobody
was being scored on.

## The popovers follow the word

The selection bar and the dictionary card are portalled to `document.body`
and `position: fixed` (inside a pane they would be clipped). Placed once,
they were left behind when the text scrolled, and a card too tall for the
screen could not be reached by scrolling — the one thing a reader does.
`anchor.ts` (`useFollow`) fixes it for both:

- **Anchor = the word's element, not the Range.** At open it hit-tests the
  rect's centre for `[data-word]` / `[data-paragraph-index]` and remembers
  the rect's offset from it. A Range does not survive the passage
  re-rendering its marks. If the element is gone the card keeps its last
  position.
- **Listen on `window` with capture** (`scroll` does not bubble; the pane,
  the review page and the window all scroll), plus `resize`; one rAF per
  frame, writing only `left`/`top` on the card via a ref. No transition, so
  `prefers-reduced-motion` has nothing to turn off.
- **Above/below is decided once, at open** (`opensAbove`). Re-deciding per
  frame made the card hop across the word. Only the horizontal edge clamp is
  live; vertically the card rides off-screen with its word, which is what
  lets a reader scroll to reveal a tall one. It is never closed by scrolling;
  Esc, the close button, or a press anywhere outside the dictionary card
  close it (`pointerdown`, so on the review page a tap on another word
  closes this card before the click opens the next one).
- Do not set `left`/`top` in the card's JSX style (except the no-rect
  fallback): the hook owns them.

## Help follows the group the reader is in

Three lines — the move, the thing marked wrong most often, one piece of
technique — and they change with the question type. Advice about matching
headings while somebody is filling a summary is worse than none: they asked
the page a question and it answered a different one.

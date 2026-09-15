# The learner's listening pages

The take screen's own rules (one scroll, the question strip, the travelling
player, the waveform) live in
`frontend/src/features/listening/CLAUDE.md` — read that too before changing
`ListeningTakePage.tsx`.

## The review is not the paper again

`ListeningResultsPage.tsx`. Sitting a paper, the question IS the form —
labels, columns, the sentence the gap is inside — because the candidate is
filling it in. Afterwards nothing is being filled in, and printing the form
back buries the four things they got wrong inside forty correct rows. It also
has nowhere to put the answer: threading `(accepted: Preston, preston)` into
the form's own sentence produced "junction of Mill Street and 3 test
(accepted: Preston, preston) Avenue", a line from which neither the question
nor the answer can be read.

- **A row quotes ONE line of the form, gap written `___`**, and puts the
  answer underneath on its own row (`questionContexts` in
  `features/listening/review.ts`). "Location — junction of Mill Street and
  ___ Avenue" is enough to be recognised and never enough to take the layout
  apart. What names a gap differs by shape: a form row's label, a table row's
  stub (or its column heading, where the gap IS the first cell), a flow-chart
  step, nothing at all for notes. A line that is only the gap is dropped —
  the label already said it.
- **The transcript is the reason the page exists.** Somebody who wrote
  `windscreen` where the answer was `wing mirror` did not mishear; they were
  pulled by a distractor, and the only thing on any screen that shows them so
  is *"The windscreen was fine, luckily — but the wing mirror is broken."* A
  percentage cannot say that and neither can a marked paper.
- **The answer is marked in the transcript by matching the TEXT, not the
  timing** (`markAnswer`). Authors snap marked ranges to segment boundaries
  almost every time, so highlighting by timing would light the whole sentence
  and claim all of it was the answer. Text matching is exact where it works
  and silent where it doesn't: `AC4471` said as "A C four four seven one"
  comes back unmarked, which is honest. A mark in the wrong place is worse
  than no mark, because a learner uses it to decide what they missed. Whole
  words, longest accepted phrasing first.
- **A transcript is optional and its absence is silent.** ASR fails, authors
  remove them. A row with none prints the answer and stops — no empty box and
  no "no transcript available".
- **The play button covers the SENTENCE on screen, not the phrase the author
  marked** (`spoken` in `review.ts`). Two different spans: the author marks
  where the answer is said, and the server quotes every transcript LINE that
  moment touches, because half a sentence is not a quotation. Playing the
  narrower under the wider stopped the recording partway through the last
  word on screen. A row whose text and audio disagree is the waveform-colour
  bug again — the reader will not work out which is honest, they will stop
  trusting the row. Widened to the lines the range TOUCHES, never to every
  line present: a "choose TWO" is answered in two places a minute apart, and
  the outer bounds of all of them would play the minute in between.
- **The kind of mistake comes from the server**, per question
  (`QuestionResultOut.mistake`), classified by the same `mistakes.classify`
  the practice page's "Where you lose marks" is counted from. One classifier,
  or a slip is called "Spelling" on one page and "Wrong answer" on the other.
  Null for a right answer and null for a letter — there is no spelling in "b".
- **No threshold on this panel**, unlike the sidebar's. Over a career four
  mistakes are not a pattern; over ONE paper four mistakes are the whole of
  what happened.
- **"Where the marks went" is at the BOTTOM**, after the questions. It
  summarises what is above it, and a summary printed first is a block the
  reader scrolls past to reach what they came for.
- **One category is a sentence, not a chart.** A single bar at 100% has
  nothing to compare against and carries no more than the words do — and the
  sentence carries more, because it names what to DO, which differs by kind:
  "listen again" is right for an answer that went past somebody and exactly
  wrong for one they heard and misspelled. Only the phrase's TAIL is written
  down (`MISTAKE_TAIL` + `mistakePhrase` in `practice.ts`) so the same
  sentence comes out in both numbers without two lists of six drifting, and
  every line of `MISTAKE_ADVICE` works for one mistake or twelve.
- **`Mistakes only` is the default**, and it locks to `All questions` on a
  clean sheet. A filter that can be switched to a view with nothing in it is
  a control that can be used to break the page.
- **The score gets context or it says nothing.** `43%` alone is unusable;
  "your 2nd try, the first was 14%, the average here is 61%" is three things
  somebody can act on. Each is **withheld rather than faked**: no first-try
  figure on a first try (the same number under a second name), and no
  platform average below `difficulty.MIN_ANSWERS` — that guard, not a second
  one invented for this page.
- **The score's context is four columns, not a sentence.** Run together as
  prose the four facts have to be parsed apart before any can be read, and
  three of the four are numbers. The first try is printed as a MOVEMENT
  (`52% → 70%`), because two numbers with an arrow between them are one fact
  where the same two in two places are an arithmetic problem set for the
  reader — and green only where it IS growth, or the page is congratulating
  somebody on going backwards.
- **The question strip has two shapes and `MAP_AT` (12) chooses.** Up to a
  dozen, a row of bars is the paper at a glance. Past that the bars are three
  pixels wide — a texture, not a picture, and clicking one is aiming at a
  hairline. A long paper gets numbered squares in a grid instead: the take
  screen's navigator and a collection's grid are the same object, so it needs
  no learning.
- It is a picture AND a jump. On a forty-question paper the alternative to
  clicking a cell is scrolling past thirty right answers, so jumping to one
  the filter is hiding **switches the view first and scrolls on the next
  render** — both in one batch, so the row exists by the time the effect runs.
- **The player is the take screen's, `settled` from the start** — its shrunk
  arrangement, at the column's width. There is nothing continuous to listen
  to on a marked paper; every play is somebody going back to one sentence.
- **It still docks into the header**, same mechanism and sentinel as the take
  screen. A control somebody needs the whole way down forty reviewed
  questions cannot be at the top of it. `settled` and `docked` are different
  questions and both flags are passed: `settled` says which ARRANGEMENT,
  `docked` says whether it is travelling. So the movement is only the card
  narrowing to the gap between the islands and picking up the frost it needs
  to sit among them — and the frost is on `docked` alone, because glass is
  about being IN the band.
- `next_material_id` for `Next lesson` is the **course's** next unsat one,
  not the one after this — same rule as everywhere else collections are
  counted.

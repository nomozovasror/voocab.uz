# The learner's listening pages

## These pages serve BOTH papers

`PracticePage` takes a `Skill` descriptor and reading renders the same
component (`features/paper/skill.ts`). So nothing under here may write
`/listening` into a link, a label or a count — it will be read by somebody
on the reading page, where it is simply false.

It was, in the one place hardest to see: the right-hand column's links.
`PracticeStats` showed reading's own figures — the API was always right —
under `See your answers` → `/listening/attempts/<a reading attempt id>`,
`Sit again` → `/listening/<a reading material id>`, and `Full statistics`
→ listening's. A reader on the reading page pressed a card about the
passage they had just sat and arrived in the other paper. It also offered
`Start with Part 1` where a reading paper has passages.

The column takes `basePath` and `partWord` now, from the same descriptor
everything else does. The rule to keep: **a route or a part word in this
directory comes from the skill, never from a string.**

It was in six more places, all of them the same sentence written before
there was a second paper: every drill row and every grid cell
(`DrillRows`, `DrillGrid`) opened `/listening/drills/...`, so the whole
Question types tab on the reading page led into listening; `NextUp`'s
`Continue`, its suggestion tiles and its results link did the same, in a
component that was already being handed `basePath` and using it three
lines above; and both studio "see it as a learner does" previews. The
sweep that finds them is

    grep -rn 'to={`/listening\|to="/listening\|href={`/listening\|navigate(`/listening' frontend/src

and it should come back with nothing outside `pages/listening/`, whose
own pages really are listening's. `CollectionPage` lives there and is
NOT one of them — reading routes to it too.

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
- **The sentence before and after the answer is shown too, dimmer** —
  `features/paper/review-context.ts`, drawn either side of the marked answer
  in `ReviewItem`'s one flowing quote. Half of why somebody missed a question
  is what led them to it, and that is very often the QUESTION rather than
  the answer's own sentence — a different speaker's turn entirely, in a
  Part 1 dialogue. Withholding a neighbour for belonging to someone else
  would cut the one case — a change of speaker — where showing it matters
  most, so it is shown regardless of who says it.

  The data is `grading.transcript_with_context` (backend): every line the
  question's own range touches (`role: "answer"`, unchanged from before)
  plus the ONE line immediately either side (`role: "before"`/`"after"`),
  each carrying its own word-level timings. Three rules, in this order, over
  the sentence adjacent to the answer within that neighbour line:

  1. **Never cross into another question's evidence span.** A neighbour
     line sits between two questions, and showing the other one's answer as
     "context" would be showing an answer. Trimmed from the far end inward,
     stopping at the first word that collides — a collision at the very
     first word drops the neighbour entirely rather than showing nothing
     useful. A line with no word timings at all is checked as a WHOLE
     against the collision (no per-word precision to trim finer than that)
     and dropped outright rather than partially.
  2. **Longer than 20 words (`MAX_NEIGHBOUR_WORDS`) is cut on the side AWAY
     from the answer**, in three stages, each searched from the natural
     20-word point outward so it keeps as many words as the limit allows:
     a pause of 350ms or more between two words (`PAUSE_MS`, most speech has
     one within twenty words, and a cut there is inaudible as a cut); failing
     that, the nearest comma/semicolon/colon/dash; failing both, a hard cut
     to 12 words (`FALLBACK_WORDS`), marked with "…" because — unlike the
     other two — it does not land on anything a reader recognises as a stop.
     A line whose segment has no word timings skips stage one outright: there
     is no gap to measure without one.
  3. **The sentence adjacent to the answer, not the whole neighbour line.**
     Only relevant on the rare line holding more than one sentence — the
     LAST sentence of the "before" line, the FIRST of the "after" one.

  Pure and untested by any runner: `frontend/package.json` has no test
  framework (no vitest, no jest). Written as small, independently callable
  functions for exactly that reason.
- **Two replay buttons, not one.** The larger plays only the answer's own
  moment (`row.startMs`/`row.endMs`, unchanged); the smaller plays the whole
  shown passage — the context sentences' own bounds through to the answer's,
  from `contextSpanOf` (`row.contextStartMs`/`row.contextEndMs`). Drawn
  smaller because it is the less common thing to reach for: most of the
  time the answer alone is the moment worth hearing again. `aria-label`s say
  exactly that — "Play the answer" / "Play with context" — rather than
  repeating the question number a screen reader already has from the row's
  own `aria-label`.
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
- **The card is two rows and both are full width.** The score on the left
  and its context on the right share the first baseline; the map has the
  second line to itself. Sharing a line with the map gave it whatever width
  the score left over, which is a different width on every paper and never
  the one the squares wanted.
- **The context is a row and is still not a sentence.** Every value keeps
  its own label in front of it, so four facts stay four facts to be picked
  out rather than prose to be parsed. The first try is printed as a MOVEMENT
  (`52% → 70%`), because two numbers with an arrow between them are one fact
  where the same two in two places are an arithmetic problem set for the
  reader — and green only where it IS growth, or the page is congratulating
  somebody on going backwards.
- **One map, numbered, filling the width.** `repeat(N, 1fr)`: the squares
  divide the width they are given rather than being packed into it at a
  fixed size, so thirteen questions and forty both reach edge to edge. Past
  twenty across it takes more rows and divides the questions EVENLY between
  them — 26 is two rows of thirteen, not twenty and a ragged six.

  There was a second shape for short papers, a row of unnumbered bars, on
  the argument that up to a dozen the pattern is the whole point. It is not:
  the map is the fastest route to a mistake, and a bar you cannot name is
  one you have to count along to.
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

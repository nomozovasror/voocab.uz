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

## The review's quote says which paragraph, and goes there

Listening places its quote in TIME — a clock above it, a play button beside
it. A page has no clock, and reading's counterpart is the paragraph:
`passageQuote` returns the line AND where it came from, the row prints
*Paragraph C*, and pressing it opens the passages, marks that paragraph and
scrolls to it. Somebody who answered NOT GIVEN wrongly has to read around the
line, not just see it — that is the whole of what the play button was for.

Both halves are withheld together and for the same reason as everywhere else
here: no quote where the answer appears twice, and no paragraph where the
book letters none. A control that points at the wrong paragraph is worse than
no control, because a candidate uses it to decide what they misread.

**Opening a panel and scrolling into it are two renders, not one.** A closed
`<details>` does not lay its contents out, so the paragraph has no position
until React has committed the open panel — and `requestAnimationFrame` is not
that moment, it can run first. The scroll belongs in an effect. The same
two-step applies to jumping to a question the filter is hiding, which is why
the parked id lives in STATE: parked in a ref, nothing reads it, and the jump
silently never happens.

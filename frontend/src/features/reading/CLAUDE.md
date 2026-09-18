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

## Paragraph letters come off the page, never from position

`Passage.paragraphs[].label` is the letter the book prints, and it is
nullable because most passages have none — a book letters its paragraphs only
where a task is answered by naming one. Deriving them from position instead
would break on any passage whose lettering starts at B or skips one, and
every "which paragraph contains…" answer on it would be off by one.

The letter is printed in the margin rather than inline, so it is findable at a
glance down the edge and does not read as the first word of the paragraph.

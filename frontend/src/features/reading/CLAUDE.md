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
  popover carries only what is done to a STRETCH OF PROSE — three colours, a
  note, a copy. Size, side and help are about the page, and a popover
  carrying those would be the row again, in the way.
- **Three colours, and never green or red.** Amber is a keyword in the
  question, blue is where the answer was found, violet is a line to come
  back to — three different reasons somebody marks something, and they have
  to stay apart at a glance twenty minutes later. Green and red mean right
  and wrong on the review page, where these same marks are shown: a line
  highlighted green while reading would come back as a verdict nobody made.
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

## Help follows the group the reader is in

Three lines — the move, the thing marked wrong most often, one piece of
technique — and they change with the question type. Advice about matching
headings while somebody is filling a summary is worse than none: they asked
the page a question and it answered a different one.

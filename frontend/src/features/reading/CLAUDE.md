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
red, the vocabulary in amber, the already-saved words in blue, and the
reader's own marks. Four kinds of marking over nine hundred words at once is
not four findings, it is a page of colour with prose underneath it. One at a
time makes each a QUESTION somebody asked.

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
- **Every layer has an analysis.** Answers is the marked question list,
  Vocabulary the word list, Saved the same list filtered to what the reader
  had already met, My marks their own highlights grouped by what each colour
  MEANS. A layer whose panel showed something else would be the page
  contradicting its own control — which is what happened to *My marks*
  before `ReviewMarks` existed.
- **"My marks" is not an overlay.** It hands `PassagePane` the reader's own
  `Highlight`s and the existing code draws them, so they keep the three
  colours they were made in. Those colours mean something — the keyword,
  where the answer was, the line to come back to — and repainting them one
  neutral colour on the one page that exists to give that back would throw
  away the only part of a mark that carries information.

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

What keeps the passage from drowning in colour is the `Q12` in the margin of
each mark rather than the wash: seventeen coloured sentences is not an answer
to *where was question 31*, and `Q31` beside one of them is. Where one mark
stands for two questions — a TRUE/FALSE pair often turns on one clause — it
prints both numbers, because a mark labelled `Q31` that is also Q32's is
lying by omission to whoever is looking for Q32.

Green and red here mean what they mean in the question map at the top of the
same screen: the verdict. That is exactly why the reader's own three
highlight colours are never green or red.

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

# The paper — what both exams share

A "paper" is the thing a candidate sits: parts, question groups, questions,
one attempt, one mark out of its numbers. Listening and reading are two of
them, and almost everything about them is the same object rather than the
same idea. This directory is that object; `features/listening/` and
`features/reading/` hold only what is genuinely one exam's.

## The split is the server's split

`backend/app/api/papers.py` builds ONE router and mounts it twice, at
`/api/listening/*` and `/api/reading/*`. This layer mirrors that exactly:

- **Addressed by a material id** — `/take`, submitting an attempt, reading one
  back — is one set of endpoints whichever paper the material is, because a
  caller holding an id does not know which. Those live in `paperApi`
  (`api.ts`) and in `useTakeMaterial`/`useSubmitAttempt`/`useAttempt`
  (`queries.ts`).
- **Addressed by skill** — the catalogue, the recommendation, the statistics,
  the drills — is `paperEndpoints(skill)`, so a filter added once reaches
  both papers and there is no second copy to forget.

**Cache keys are skill-FIRST** (`["reading", "practice"]`, not
`["practice-reading"]`), so invalidating one paper's whole cache is a prefix
match. Sitting a reading passage must not invalidate the listening catalogue,
and `useSubmitAttempt` relies on exactly that.

## What a skill is, and what it is not

`skill.ts` holds the descriptor: where the pages live, what one part is
called, how many parts make a whole paper. **A page takes it rather than
being written twice.** Where a component prints "Part 1" or links to
`/listening/…`, it takes `partWord` or `basePath` instead — a reading paper
headed "Part 1" is the app calling the thing something the page beside it
doesn't.

`fullParts` is 4 for listening and 3 for reading, and the same number lives
in `listening_service.full_test_parts`. One number for both would call every
complete reading paper an excerpt, which is the one thing the "full test"
filter exists to tell apart.

## The take engine

- **`TakeConfig` is the rules as a value** (`take-config.ts`). Practice and
  exam are the same test under different constraints; no rule is written into
  a button. The audio flags are listening's extension of it — there is no
  "seek" on a passage.
- **`take-session.ts` keeps the draft** — answers, flags, timing. `listened`
  and `seeksBack` are filled only by a paper with a recording; the server
  declares both optional.
- **`take-paper.ts` walks the paper exactly once.** Header count, navigator
  and submit all read that walk — three walks are three chances to contradict
  each other about what question 24 is.
- **Where the reader is comes from the DOM** (`take-focus.ts`), never a
  register of refs. It queries the document and does not care what scrolls,
  which is why it works unchanged in a two-pane layout.
- **One control per NUMBER, not per question.** A "choose TWO letters" is two
  boxes carrying two marks.

## Question types are the exam's vocabulary

`question-types.ts` names every type once — label, blurb, short noun, icon —
so the header, the menu and the chooser cannot drift into calling one thing
three things. WHICH types belong where is editorial and lives per skill
(`listening/parts.ts`, `reading/parts.ts`): a form belongs in Listening Part
1 and matching headings belongs to a passage.

Two families are worth knowing:

- **Matching is one task under five names** (`MatchingType`), exactly as the
  nine completion types are one document under nine. What differs is the
  instruction line and how the box is lettered — `label_style: "roman"` for
  matching headings, whose ITEMS are lettered paragraphs, so its box cannot be
  lettered too or an answer of "C" would name a heading and a paragraph at
  once.

  **An answer is stored as its label and has to be read back in the same
  alphabet.** `matchLabel` writes them and `matchIndex` reads them, and both
  take the style. `sayAnswer` used to do arithmetic on the first character
  instead, which is right for letters and silently wrong for numerals: `i`
  and `iii` both begin with `i`, so the review printed one heading beside two
  different answers and told a candidate they had chosen something they never
  chose. `ReviewRow.labels` carries the style for exactly this.
- **A true/false set stores no options.** Its three words come from its TYPE,
  on the server (`FIXED_CHOICE_OPTIONS`) and here. Storing them would let two
  groups of one type disagree, and — because a group with options in its
  config is a LETTERED group — would silently switch grading to set-matching
  letters against the word "TRUE".

## The review quotes; it does not redraw

`review.ts` and the four `Review*` components are shared whole. The rule that
matters is where the quote comes from:

- listening quotes the transcript across the moment the answer is said, which
  the server sends with the attempt;
- reading quotes the sentence in the passage, found by `passageQuote` — the
  passage came down with the paper.

Both are **text-matched and silent when the match is not unique**. A quote
pointing at the wrong occurrence teaches a candidate they misread something
they never read, which is worse than no quote at all.

The play button is drawn only where an `onPlay` is handed in. A disabled one
beside a reading quote would be a control that exists to be greyed out.

**Reading quotes nothing when it can POINT instead.** `QuestionResult.
evidence` is where in the passage the answer is — reading's counterpart to
`replay_start_ms`, in paragraphs rather than milliseconds — and the reading
review draws the passage beside the rows. `ReviewItem` takes an `evidence`
prop there and replaces the quote box with a link: the same sentence copied
into a box under the answer would be the words on screen twice, cut out of
the paragraph that gives them their meaning. `passageQuote` stays as the
fallback for papers the extraction never reached.

One component either way, because it is one object under different
conditions: where you were, what you put, and where the answer was. A second
"review row" for reading would be two files that have to agree about what a
marked question looks like.

## A completion row quotes its own SENTENCE, never the document

`lineAround` cuts the line holding a gap down to the sentence that gap is
in. A sentence completion is one sentence a line already; a SUMMARY
completion is a paragraph of prose carrying three or four gaps on one line,
and without this each of those questions quoted the whole paragraph — three
rows of the review, identical to one another, a hundred and twenty words
each, with the answer to one of them somewhere inside.

Another gap in the same sentence prints as `___ (33)`, named rather than
blank. A second bare `___` makes two rows look alike again at the one place
they most need telling apart, and an ellipsis ran into the punctuation
beside it (`…have ….`). The number comes off `paperParts`, the same walk
everything else here numbers by.

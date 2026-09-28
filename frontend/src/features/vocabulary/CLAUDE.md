# Vocabulary — invariants

Three screens show words, and they are three different moments. Keeping them
apart is most of what this module is.

## Mid-paper: three lookups, and the number is the feature

A reader who can look anything up is reading with a dictionary, and the exam
does not have one — a passage worked through that way measures
comprehension-with-help, which is neither the skill being practised nor the
one being scored. A reader who can look up nothing stalls and stops. Three is
the compromise, and the count is what makes it teach something: somebody with
three left spends them on the words the questions turn on rather than on the
first unfamiliar noun in paragraph A.

- **The extracted list has no edges the reader can see.** Which words the
  seed pipeline happened to prepare is an optimisation, not a boundary
  anybody is entitled to be told about. Never "this word is not in the
  list", never "that one is easy", and never a control greyed out for a
  reason they cannot see. Whatever they select is answered — from the table
  where a row exists, from a model where it does not — and the only
  difference they may notice is that one of them takes a moment. **The
  system's own ignorance is never handed to the learner as theirs.**
- **The budget lives in the browser** (`features/reading/lookups.ts`), and
  that is right for a rule whose purpose is to make somebody choose. It is
  also the ONLY reason a look-up control is ever disabled. What is enforced
  on the server is the thing that would make the budget a formality: the
  whole-list endpoint is refused until the paper is submitted.
- **Unique lemmas, not openings.** Looking the same word up again is free.
  Charging twice for one choice teaches people not to check their memory.
- **A fresh sitting is a fresh three; the WORDS are never reset.** Somebody
  sitting a passage again has already been told what `vogue` means, and
  charging them again is the app pretending not to remember.
- **The word is charged, never the phrase around it.** A tap on `rise` inside
  `give rise to` shows both; the phrase came free, as context. Charging the
  phrase would file the lookup under a string the reader never touched, and
  the review would then name a word they did not ask about.
- **An empty answer costs nothing.** A name, a number, a morning the
  dictionary is unreachable. Being charged one of three to be told nothing is
  the kind of small unfairness people remember.
- **"Already looked up" is decided from the returned LEMMA**, not from the
  selected text. Tapping `proponents` charges `proponent`; a check against
  the raw selection reads "not free" for ever on a word the budget is
  quietly treating as free. This was a real bug.
- **No lookup at all in exam mode.** Not disabled — absent. A greyed-out
  dictionary is a page telling a candidate, every minute of the hour, what
  they are not allowed to do.

## After the paper: any word, no budget

On the review page every word in the passage is clickable and nothing is
rationed. That is not the rule being relaxed, it is the rule FINISHING.
Three lookups exist to protect an exam habit — a candidate who can look
anything up is reading with a dictionary, which is not the skill being
scored. Once the paper is submitted there is no habit left to protect, and
rationing a learner's own curiosity after the fact teaches nothing.

**It closes a hole, and the hole is the extraction's edges showing.**
`appropriate` is NGSL rank 1019, so the frequency filter calls it known and
never glosses it. A reader who did not know it, did not spend one of three
on it during the paper and did not highlight it had NO way to find out what
it meant afterwards — on the one screen built for learning. The system's own
ignorance was being handed to the learner as theirs, which is the thing the
first rule in this file forbids.

- **The same popover, not a second panel.** It is the same question, so it
  is the same four lines and the same Save button. `LookupPopover` takes an
  optional `budget`; with none there is nothing to charge, nothing to ask
  whether a word was free, and no counter printed.
- **What is generated JOINS the material's vocabulary at once.** The page
  invalidates `vocabularyKey` on a fresh gloss, so the reader closes the
  card and the word is there in its level's colour, marked on the passage
  and listed beside it. Not doing that would make them look it up twice to
  see it.
- **And filed under `review_lookup`**, apart from `extracted`. Both are
  machine-made and both may be replaced by a later seed run; the
  distinction costs nothing and answers a question nothing else can — which
  words the extraction declined to offer and a learner went looking for
  anyway.
- **`lookup_events.context` says which screen asked.** A `take` lookup means
  *this word stopped me badly enough to spend one of three.* A `review`
  lookup means something the platform cannot otherwise learn at all: *I did
  not know this word, and I did not know that I did not know it.* Words
  many readers look up in review which the extraction never offered are the
  evidence for where the frequency cut is wrong.
- **A word must START with a letter.** `15-year-olds` otherwise tokenises
  from the digit, and the offset sent is three characters before the
  `year-old` entry's span — so the server's span-containment test finds
  nothing, the string match fails on a token with a number in it, and a word
  the passage already has glossed is glossed a second time under a name
  nobody typed. It also means a bare number is not a target, which is right
  on its own terms.
- **Not reachable by keyboard, and deliberately not.** Nine hundred tab
  stops between the top of the passage and the questions would be worse
  than the gap they close. The spans carry no role and no label, so a screen
  reader reads the passage as a passage; what a keyboard user has instead is
  the word list beside it, which is every word the extraction knows with its
  meaning, reachable in one tab. What they do not have is the words the
  extraction MISSED — the very hole this closes for a mouse. Worth fixing
  the day there is a shape for it that is not 900 tab stops.
- **A caveat worth watching.** The budget is what used to bound how much a
  curious reader could add to a SHARED list. With it gone, every casual
  click on a common word can add a row that every future learner then sees
  in "106 words worth learning here". `whether` came back B1 and joined the
  list on the first test click. If the list starts drifting, the guard is
  `MaterialVocabulary.hidden`, which exists for exactly this — keeping an
  entry without showing it.

## Two ways in, and the popover is the one they use

The tool row is where somebody LEARNS the feature exists; the popover at the
selection is where they use it, because it arrives under their finger at the
moment they have just selected a word they do not know. The remaining count
travels with it — a reader deciding whether this word is worth one of three
cannot be made to look at the top of the screen to find out.

A selection longer than `LOOKUP_WORDS` drops the control rather than
greying it out. Absence reads as "not this"; disabled reads as "not you".

## Two meanings, and the usual one leads

**Every entry carries the sense the word USUALLY has and the sense this
passage gives it.** The usual one is printed first, everywhere; the
passage's follows it under `Here:`, and only where `sense_differs` says the
two are genuinely not the same — which is a small minority of entries.
`features/vocabulary/meaning.ts` owns that rule and all three screens ask
it rather than each writing it out.

The contextual meaning is still the reason this feature exists and none of
that argument is undone: `spring` is a season in one passage and a coil in
the next, and a dictionary answering with five senses is exactly what a
band 5 reader cannot use. What a contextual meaning ALONE cannot do is
teach the language. A passage about artificial intelligence glossed `learn`
as "a computer process of finding patterns in data", marked `n` — a
faithful reading of `machine learning`, a false statement about the verb,
and the only line the learner who saved it would ever see.

**A missing usual meaning falls back rather than blanking the card.** It is
empty on an entry written before the field existed and on one whose model
would not answer for it; readers then print the contextual line as though
it were the word's own. Narrower help beats none.

**On the saved-words page the usual meaning is said once, above all the
meetings.** A word met in two passages is one word; repeating "a season of
the year" over each meeting would be the card arguing with its own
headline. Each meeting then carries only what is its own — the `Here:` line
where the sense differed, the sentence, and the way back to the passage. A
word saved before the field existed and not yet enriched has no headline,
and each meeting prints its own meaning as it always did.

**Compound terms are entries in their own right.** `machine learning`,
`climate change`, `public sector` — the seed stage asks about terms BEFORE
it builds the word list, and a COMMON word standing only inside terms is
left to them (`seed/vocabulary.py`, `candidates(claimed=…)`). A hard one
keeps its own entry beside the term: `sedentary` and `sedentary lifestyle`,
`indignation` and `righteous indignation`, the way `rise` has always stood
beside `give rise to`. Surrendering those cost 485 of the corpus's hardest
words before the rule was split — the measurement is in `seed/README.md`. The live lookup does
the same thing from the other end: `dictionary.Gloss.term` lets a model
answer about something wider than what was tapped, and the entry is stored
over the term's span. A term the passage already has is not written again —
the reader is already being shown it as the phrase.

**A word is marked everywhere it stands, and the repeats are quiet.** One
entry per lemma per material is what makes a tapped word have one answer,
so the other places ride on the row (`also_at`) rather than becoming rows.
The first occurrence gets the full wash; the rest get a hairline rule in the
level's colour and nothing else — until the reader points at the row on the
right, when every one of them lights at once. Before this, 17% of entries
had occurrences with no mark on them, and an unmarked `solutionism` two
paragraphs below a marked one reads as the list being incomplete.

**An entry about one USE does not repeat.** `address` glossed as "deal
with", and anything marked `unusual`, stands alone where it was found: the
same passage may use the word ordinarily four paragraphs later and the scan
cannot tell them apart. A mark that puts one sense over the other is worse
than no mark, because it is confidently wrong.

**Part of speech belongs to the lemma.** `learning` the noun is its own
entry, not `learn` wearing an `n`.

## The panel: what it shows and what it refuses to

Lemma, part of speech, CEFR, the word's usual meaning, the meaning in THIS
passage where that differs, Uzbek and English. Nothing else.

**No example sentence.** It looks like an omission and is not: the reader is
looking at the sentence, six inches to the left. **No etymology, no other
senses, no synonyms.** Each lookup has about two seconds to pay for itself,
and a panel that reads like a dictionary page is a panel somebody closes and
goes back to guessing, having spent one of three for the privilege.

**Saving is a toggle, in both places it is offered.** The row's `＋` and
the card's `Save` both become a tick, and pressing the tick takes the word
off the learner's whole list — the icon changes to `✕` under the pointer,
because a button that says `Saved` and removes on press is one nobody
presses twice on purpose.

**`forget` is per SENSE now, not per lemma (P4).** It used to be: a saved
word was deduplicated by lemma, so ✕ meant "the same word wherever they met
it," full stop. That broke the day `bank` (the river) and `bank` (the
financial institution) turned out to be two things somebody could save from
two different passages — one FSRS card trying to teach both taught neither,
because a "usual meaning" and a schedule are properties of a MEANING, not a
spelling. A saved word is now one `LexemeSense` per learner
(`saved_words.lexeme_sense_id`, unique per user), so the popover and the
review row's Save/✕ each act on the sense THAT ROW is showing
(`VocabularyEntry.saved`/`saved_word_id`, both per sense) — pressing ✕ on
the `bank` you met as a river leaves the financial `bank` you saved last
month untouched. Where a different sense of the same lemma is already
saved, the card and the row both say so in one quiet line ("You've saved
another meaning of this word.") rather than a warning: keeping two senses
of one spelling is the ordinary case this rule exists to support, not an
edge case to flag.

In the words list this is also why the same lemma can legitimately appear
twice — two rows, two meanings — and why the MEANING, not the lemma, is
what a learner has to read to tell them apart; see "A saved word is one
word with several contexts" below, which this section supersedes for what
"one word" now means.

**The card has to say what the list says.** Its Save button is a question
about the learner's list, and the lookup endpoint was answering it from a
field nobody filled in — so a reader saved a word, closed the card, opened
the same word again and was offered Save a second time. It reads back
`saved` now, and it tells the page (`onSaved`) so the row beside the
passage moves too. A save whose only visible effect is on the thing about
to be closed is a save the reader has no reason to believe happened.

**The row has no disclosure control.** The example was behind an
`Example ▸` button on a line of its own, then behind a chevron beside the
save button; it is behind the row itself now. A chevron on every one of a
hundred rows is a hundred things to look at for a disclosure the pointer
already announces, and the column beside the entry is for the button.

**Pressing a row takes the passage to the word.** Hover lights the mark,
which is worth nothing when the word is four screens down — and in a list
of a hundred, most of them are. The press scrolls through the same
`goingTo` two-step the evidence links use.

**A word in an unexpected sense says so in words, not with a badge.** It is
a word used in a sense the reader would not expect — `bank` as the side of a
river — and a badge would say "this one is special" and leave them to work
out how. What helps is the `Here:` line, which gives the sense itself.

The flag both that line and the `unusual sense` tag read is `sense_differs`,
not the older `unusual` column. `unusual` is narrower — a COMMON word in an
unexpected sense, which is the disagreement between the two difficulty
measures — and it still exists on the server, where the arithmetic
comparing passages uses it. It is not what a reader wants pointed out: a
rare word in an unexpected sense is just as much of a trap and was not being
marked at all. Two nearly-identical flags on one row is how one of them
quietly stops being maintained, so only one of them reaches the wire.

**CEFR is printed; the frequency band never is.** `C1` is a scale a learner
already has a feel for. "NGSL rank 2400" is a fact about a corpus. The band
exists and stays on the server, where the arithmetic is.

## The level is a colour, and the colour is a system

`features/vocabulary/cefr.ts` is the one place it is decided: B1 blue, B2
violet, C1 orange, cool to warm, which is the ordering people read as a
scale without being told. Every screen that shows a level reads that table —
the lookup popover mid-paper, the review's list, the saved-words page, the
passage header's spread — because the whole value of a colour system is that
the orange in the popover and the orange in the review an hour later are the
same claim. Four private implementations of a badge is four things that
drift on the first afternoon somebody adjusts one.

- **Never green and never red.** They are the verdict on the review page —
  right and wrong — and the vocabulary list sits on that same page, inches
  from a passage striped in both. A learner shown their C1 words in red
  reads the hardest words in the text as forty mistakes.
- **The colour never travels alone.** Every use prints the letters beside
  it, which is what `CefrTag` exists to make unforgettable. About one man in
  twelve cannot separate the violet from the orange, and a scale he cannot
  read is worse than none: it is a page that looks organised and is not.
- **An unrated word gets no chip, not a grey one.** A grey chip in a row of
  coloured ones reads as a fourth, easiest level; what it actually means is
  that nobody said.
- **It took the pen's blue and violet, on purpose.** The reader's highlight
  tool used to offer amber, `#5b9bd5` and a violet — and `#5b9bd5` is
  exactly B1. On the review page those two systems land on the same passage
  one layer apart. The scale won on reach and the pen now separates by
  STYLE; see `features/reading/CLAUDE.md`.

## The passage's marking says the level, and only the level

The wash over a glossed word is its CEFR colour **and its CEFR strength** —
24 / 34 / 40%, faint to firm, easy to hard.

The strength is not decoration. Hue alone was 20/22/24% and measured
1.34–1.48:1 on every theme: three levels drawn at one weight, so the whole
scale rested on fifty degrees of hue between a blue and a violet, at a fifth
of its strength. It failed first on dracula, whose background is itself a
dark blue-violet — both washes sank into the ground they were laid on and
the hue channel carried nothing at all. Two ordered channels instead of one
is what makes it survive a coloured ground, and a reader who cannot separate
the violet from the orange can still see which mark is louder.

C1 stops at the weight of the reader's OWN highlighter, because nothing the
page says about a passage should shout louder than what the reader said
about it. The numbers and the derivation are in `globals.css`.

Two other things ride on top without taking the hue, because neither is a
property of the word:

- **an underline** — one of the three this reader spent a look-up on;
- **a ring** — the entry opposite is under the pointer right now. A ring
  rather than a stronger wash, because a stronger wash of the same hue reads
  as a harder word, and hovering a row must not appear to change the level.

The wash used to say "saved" in blue for a word already on the list, which
meant a saved C1 word and an unsaved B1 word came out the same colour — the
one thing the wash was for stopped being true the moment the reader did any
work. Saved-ness is what the Saved LAYER filters by. It is not a hue.

## The review: the words, not the number

"You looked up three words" is a score for something nobody was being scored
on. The three words, with what they mean in the passage that defeated them,
is homework — and it is the homework an IELTS teacher actually sets after a
passage a student struggled with.

- **The opened words come first.** Every other word in the list is one the
  frequency lists think is hard; those two or three are the ones that
  stopped THIS reader badly enough to spend one of three on. Nothing else on
  the platform knows which they were. They carry that in a tag on the row
  and a toggle in the filter card — it used to be a heading over a block,
  which said the same thing and could not be asked for.
- **They come from the ATTEMPT, not from `lookups.ts`.** That list remembers
  across sittings on purpose, so on a retake it holds words from a paper
  that is over, and the review is about one sitting.
- **The rest is sorted by LEVEL**, which is the opposite of the lookup
  panel's passage order and right for the opposite reason: mid-paper the
  question is what this one means, and here it is which to learn first.
- **One bar does what three headings did.** The list used to be cut into
  sections — look-ups, then the rest, then the B1 words folded into a
  `<details>`. Each cut was defensible; together they were four headings and
  one opinion, none of which could be UNDONE. The proportional bar is a
  legend, a distribution (*this passage is half B2* — before a word is read)
  and the filter, in one object. Chips would be the same control minus the
  distribution, which is the part nothing else on the page says.
- **Nothing selected shows everything.** A filter that starts by hiding
  things is a page that looks broken until it is understood.
- **The filter lives on the PAGE and governs both halves**
  (`features/vocabulary/filter.ts`). Press `C1` and the list shows the C1
  words while the passage keeps only their marks — a list filtered under a
  passage that was not is the page answering half the question. Both sides
  call the same `keeps()`; two implementations of one rule is one rule and a
  bug waiting for the first entry they disagree about.
- **The layer's COUNT is what the layer holds, not what the filter lets
  through.** Otherwise narrowing to a combination that matches nothing reads
  as an empty layer and the page falls through to a different one — the
  control doing something nobody pressed.
- **One save button, and it saves exactly what is on screen.** There were
  three — all, just C1, just my look-ups — answering three questions the
  filter now answers better, because the reader can see what they are about
  to save before they press it.
- **Every entry carries its sentence from the passage, one press away.** It
  is the passage's own sentence, cut from the text rather than written by a
  model, and it is the whole argument for saving words from a paper instead
  of from a list. Folded, because two extra lines on a hundred entries is
  the wall of words this panel was rebuilt to stop being — and the ROW is
  the control, with only a chevron beside the save button. An `Example ▸`
  button on its own line cost the very line the folding was for. `＋` stops
  the press reaching the row: saving a word and reading its sentence are two
  intentions, and the buttons are a centimetre apart.
- **Hover still means WHERE.** Pointing at a row lights the word in the
  passage and vice versa; the press means what it meant there. The
  disclosure must not spend the hover.
- **It sits beside the passage, marked.** It used to be a bordered panel at
  the bottom of a page, and a hundred and one entries of four lines each is
  ten screens of words with no text anywhere near them — a dictionary with
  the one thing that made it worth reading taken out. It is now one of the
  review's layers, opposite the passage, the passage is washed over the
  words it is talking about, and pointing at either lights the other.
- **The Saved layer is this same panel filtered, never a second one.** A
  word met again a fortnight after it was saved is not a different KIND of
  entry — it is the same entry with a history — so `only="saved"` hides the
  rest and changes the heading — and takes the save button away with it: a
  "Save all 85" inside a panel showing only what is already saved would be
  offering to save nothing. The bar there is counted off the SAVED words
  rather than off `data.levels`, which is the whole passage's: a picture of
  a list that is not on screen.
- **The list is fetched by the PAGE, not by the list.** The marking on the
  passage comes from the same rows, and two components asking the cache the
  same question is one of them holding a copy that stops agreeing with the
  other the first time somebody presses Save. `vocabularyKey` is written
  once for that reason.
- **"Saved earlier" is taken once, when the page opens, and never updated.**
  It is a claim about a DIFFERENT DAY — you met this word a fortnight ago
  and here it is again. A badge that appeared on a word two seconds after
  somebody saved it would be the page congratulating them on remembering
  what they had just done. `entry.saved` is the live fact and drives the
  button; this is the other one.
- **The row's three flags are outlined, never filled.** `looked up`, `saved
  earlier`, `unusual sense` are facts about the READER's history with the
  word; the one filled chip in that line is the level. A second filled chip
  would read as a second level. Each is named in the words the filter card
  uses, or pressing a toggle appears to do nothing.

  (The mid-paper panel still says `unusual` in a sentence rather than a
  badge — see above. That rule is about the two seconds a look-up has to pay
  for itself, and it does not reach a review where the same word now sits
  beside a filter with that name on it.)

## A saved word is one SENSE with several contexts

`spring` met twice in two passages about the season is ONE word: the list
deduplicates by sense and hangs each meeting off it, and both example
sentences survive, which makes a better card than either alone. `spring`
the season and `spring` the coil are a DIFFERENT pair now (P4) — two
`LexemeSense`s, two saved words, two FSRS cards — which is the fix for the
bug the lemma-only version of this rule used to be: one card trying to
carry two unrelated meanings taught neither properly, and there was no way
to be "3/4 done learning `bank`" when the two `bank`s a learner had met
had nothing to do with each other. See the forget/✕ section above for why
and what it changed.

The gloss is **copied** at the moment of saving, never read back through the
material — except the word's own headline meaning (`definition_en`/
`meaning_uz`/`sense_cefr`), which is read LIVE off the sense so an admin's
fix in Studio reaches everybody already studying the word. Each CONTEXT's
own gloss stays a copy: a passage can be edited and re-glossed, and a
saved word's sentence changing underneath somebody is worse than one that
has aged.

`/vocabulary` is the list and not the spaced-repetition module — no
scheduling, no queue, no "next due". That is its own brief, and inventing an
interval here would be guessing at a design from outside it and then having
to migrate away from the guess. What the page must do today is smaller and
not optional: a Save button whose result cannot be looked at is a button that
quietly does nothing.

## Where the meanings come from

Not from a dictionary API, and not at the moment of the tap. `seed/
read_vocabulary.py` glosses every passage once, at seed time, against the
NGSL and NAWL candidate list — so 95% of what a reader taps is already a row
with its sense, its Uzbek and its example. The remaining 5% is generated
live and kept, which makes the list grow towards what readers actually find
hard rather than what a frequency table predicts.

The consequence worth protecting: the site does not stop teaching vocabulary
on a morning when Groq is down.

**Two providers, in a chain.** "Any word a learner selects is answered"
cannot rest on one API, and that is not hypothetical — the seed run hit
Groq's spend limit at the 174th passage and every live look-up in the app
began returning nothing for ordinary words, to readers with no way to know
why. Gemini stands behind Groq on a separate account with a separate quota.
A provider that RAISES is out of action and the next is tried; a provider
that returns nothing has ANSWERED, and asking the next model about the same
name would spend a request to be told the same thing.

## Every look-up is logged

`lookup_events`, written with the feature rather than after it, because a
table added in three months starts empty and the three months worth knowing
about are gone. `source` is the column that cannot be recovered later: a
live answer is saved into `material_vocabulary` and is indistinguishable
from an extracted one within milliseconds.

It answers four questions — what share comes from the extraction, which
words go live (if they are `people` and `water`, the filter's cut is in the
wrong place), how long a live one makes somebody wait, and whether three is
the right number, which was a judgement and not a measurement.

`attempt_id` is filled at SUBMIT, because no attempt exists while a paper is
open. What stays null afterwards is a passage somebody looked words up in
and never finished — a fact worth counting rather than a gap to apologise
for.

## A fourth screen: practising the words, not just keeping them

`/vocabulary` (home), `/vocabulary/practice` (session + end) and
`/vocabulary/words` (the list above, moved here unchanged) are stage 1 of a
separate module built on top of `SavedWord`/`SavedContext` — the server
calls them `UserWord`/`UserWordContext` in the brief, same tables (dedup by
SENSE since P4, not by lemma — see above). A saved word used to be inert; this is what turns it into
something scheduled, with FSRS on the server (`app/services/practice.py`
owns the only place that touches it) and rationed by TIME rather than by
word count — see the stage 1 spec for why a daily word quota is the thing
that makes people quit Anki.

- **The queue is built once, client-side after that.** `POST
  /vocabulary/practice/session` runs on mount of the practice page and its
  `items` become local state; every answer pops the front and, when the
  server's `returns_this_session` says Again, pushes the same item onto the
  END. The server is never asked "what's next" a second time — the queue's
  order past the first requeue is a client fact, and asking again would
  re-plan a budget that has since been partly spent.
- **`tz` travels on every call that reasons about "today"** — the daily
  budget resets at midnight in the LEARNER's zone, not the server's.
  `lib/time.ts`'s `localTimeZone()` is the one place that reads it
  (`Intl.DateTimeFormat().resolvedOptions().timeZone`, falling back to the
  server's own default), so a page that forgets to pass it and one that
  spells the fallback differently can't disagree about what day it is.
- **The gap field is shared with the take screen, not reimplemented.**
  `features/paper/components/GapField.tsx` is the same `<input>`
  `FormCompletionGroup` uses for a sentence/summary completion gap, pulled
  out so both can use it byte-for-byte. Sharing it is not tidiness — it is
  the whole argument for the stage 1 exercise being "fill the gap in a
  sentence" rather than "type the translation": it is asking for the exact
  skill a completion task already asks for.
- **The cue is the first letter, and nothing else, until the answer is
  submitted.** `PracticePrompt.cue` goes in as the field's `placeholder`;
  the fuller reveal — verdict, the answer as it stood in the sentence, the
  word's usual meaning, Uzbek, `Here: …` where the sense differs (via
  `meaning.ts`, exactly as the review and the saved list read it), and the
  source material — only exists in `PracticeAnswer`, which the server never
  sends before the learner has answered.
- **The gap keeps what the learner typed, coloured by the verdict, rather
  than being overwritten with the right answer.** Same rule
  `FormCompletionGroup` follows on the take screen: the field says what you
  wrote, its border says whether that was right, and the correct form is
  printed in the reveal panel instead of substituted into the box.
- **Enter submits on the field; it advances on the document.** Stage 1 did
  both from the field's own `onKeyDown`, which stopped working the moment
  `recognise` arrived with no field to attach it to. Now the field's Enter
  only calls `submit()`, and a single document-level listener does
  `advance()` once a result exists — one rule reachable whichever of the
  three prompts is on screen, rather than three components each guessing
  whether they are the one with focus. The two never double-fire: the
  field's own handler only acts while `!result`, so by the time the
  document listener would also see the same keypress there is nothing
  there yet for it to act on. Esc is a document-level listener as well as
  the field's own handler, because after a reveal the learner may have
  moved focus to the source-material link, and exiting has to work from
  there too.
- **The end screen's joke is picked from what happened, never at the
  learner.** `jokes.ts` takes a small stats shape (how many words, how many
  struggled, which one struggled most) and returns one line from a pool —
  interpolating the hardest word rather than a generic "well done", and
  never a line that could read as mocking whoever just sat here. That rule
  is the brief's, verbatim, and it is the whole reason the joke is a
  function of session stats and not a static string.
- **`practiceSummaryKey(tz)` is exported from `api.ts` and shared** between
  the home screen's query and the practice page's post-session refetch — the
  session that just finished invalidates exactly that key, so returning to
  `/vocabulary` shows the due count and next-review time the session just
  changed, not the ones that were true when the page first opened. Two
  separate keys computed the same way in two files is how one of them ends
  up stale.

## Stage 2: the ladder, both directions, and the words that fight back

Stage 1 shipped one exercise (`recall`, `passive`) because that was enough
to prove the module worked. Stage 2 is what makes it the thing the plan
actually describes: a card that gets HARDER as a learner proves themselves,
a second direction for writing rather than only reading, and the two
screens (`/vocabulary/words`, `/vocabulary/words/:id`) that let somebody
ask about a word instead of only being asked one.

- **The level is stored, not derived.** `SavedWord.passive_level` and
  `active_level` say which TASK the ladder is currently asking for
  (`recognise`/`recall`, `recognise`/`produce`); FSRS still schedules WHEN,
  the level only ever picks WHAT. Promotion and demotion are the server's
  own arithmetic (the spec's §1) — the client only ever renders whichever
  `exercise_type` a `PracticeItem` arrives with, and never infers one from
  a stability number itself.
- **`PracticePrompt` is four shapes behind one field, and each got its own
  interface rather than a shared one with an optional-everything grab bag.**
  `PracticeSentencePrompt` and `PracticeDefinitionPrompt` look almost
  identical to `PracticeChoicePrompt` and `PracticeProducePrompt` on the
  wire, but keeping each `kind` a SINGLE literal (rather than, say, one
  interface answering to `"sentence" | "definition"`) is what lets
  `VocabularyPracticePage.tsx`'s `if (kind === "sentence" || kind ===
  "definition") … else if (kind === "choice") … else …` narrow cleanly — the
  one-interface version compiled, but TypeScript quietly stopped narrowing
  the FINAL branch, and `ProducePrompt` was typed to accept a shape it
  could never actually receive nor coincidentally the recall one.
- **`recognise` is one component for both directions, not two.** Passive
  fills `before`/`target`/`after` and offers English definitions; active
  leaves those empty, fills `shown_meaning_uz`, and offers English lemmas.
  `ChoicePrompt` branches on `shown_meaning_uz !== null` rather than being
  told the direction directly, because that is the one fact that actually
  decides what to draw — a second `direction` prop would be a second way
  the two could disagree.
- **Keys 1–4 answer; they do not merely select.** There is no "highlight,
  then confirm" step on a `recognise` turn — pressing `2` or clicking the
  second option submits it, same as Enter submits a typed answer. A
  confirm step would be a second decision for a task that is already the
  easiest of the three.
- **"I know this" is a swap, not a second item.** Pressing it (`0` — chosen
  because it can never collide with the four option keys, and because it
  is never captured while a text field has focus, so a `produce` answer
  that happens to start with a digit still types normally) calls
  `POST /practice/known-check` and replaces `queue[0]` in place. The next
  `submit()` carries `claim_known: true` and clears the flag immediately
  afterward — one attempt, exactly as the spec's §4 says, even if that
  attempt comes back Again and the SAME word is later requeued as an
  ordinary `recall` turn with no claim attached.
- **A `became_leech` reveal blocks Enter until one of its three buttons is
  pressed.** `LeechPanel`'s choices are not a courtesy dismiss — a leech is
  the app surfacing a real decision (the spec's §5), and falling through to
  the next word by reflex would be the one screen that most needs a
  deliberate answer offering none. "See it where you met it" is the one
  choice that LEAVES the session (`navigate` to the word page) rather than
  continuing it; the other two call `advance()` themselves once the mutation
  lands, rather than waiting for the ordinary Enter path.
- **The reveal's meaning order flips for exactly one case.** Passive
  `recognise` shows the right English definition first and the Uzbek
  meaning under it, per the spec — the opposite of every other exercise's
  reveal, where Uzbek leads because it is what the learner was writing
  FROM. `Reveal` computes this from `exerciseType === "recognise" &&
  direction === "passive"` rather than from anything server-sent, since
  nothing else about the payload distinguishes it.
- **The words list rebuilds `VocabularyPage.tsx` on the SAME endpoint**
  (`GET /vocabulary/words`), not a new one — stage 1's saved list and
  stage 2's practice-aware list are the same rows, extended. Filters
  (status, CEFR, source material, direction) are client state; only
  `status` lives in the URL, because it is the one filter the home
  screen's "N words set aside" line needs to LINK to
  (`/vocabulary/words?status=suspended`) rather than describe in words.
- **Deleting ONE word never asks; deleting several always does — two
  different answers to "are you sure", each sized to what it is answering
  for.** A single word gets `pendingDelete.ts`: the row becomes "Removed ·
  Undo" at once (`RemovedRow`), and the DELETE itself waits about six
  seconds, sent only if nobody presses Undo — cheaper than a dialog for a
  mistake that costs nothing to reverse in the window where it can still be
  reversed. More than one word opens `DeleteWordsDialog` (the
  `components/studio/DeleteMaterialDialog.tsx` pattern, named to a count)
  and calls the ordinary `bulkWords("forget")` at once on confirming — a
  batch a reader cannot see all of on screen needs the question asked
  before anything happens, not an undo they would have to notice six things
  disappeared to use.
  - **The timer lives in a module, not a component's state**, because the
    word page's own Delete button has to survive the very thing it does:
    navigate to the list. A `setTimeout` in a hook dies with the component
    that set it; one held in `pendingDelete.ts` keeps counting down
    whichever of the two pages — or neither — is on screen, and the list
    picks the same pending lemma back up from there rather than from a prop
    it was never handed.
  - **Both pages register as a place "Removed · Undo" could still be
    shown** (`useFlushPendingDeletesOnLeave`), and the DELETE is sent
    early — before the six seconds are up — the moment neither is mounted.
    Leaving the words list for the word page (or back) doesn't trigger
    this: both are registered at once for the beat the router takes to
    swap them, which is what tells the flush apart from someone leaving
    the pages that could ever offer Undo at all.
- **The word page (`/vocabulary/words/:id`) is `WordDetail`: a
  `SavedWord` plus `history`.** It is reached from the list, and — per the
  spec's §5 — is also "See it where you met it"'s destination from a
  leech's reveal, so a learner sent there mid-session lands on the exact
  page the list would have taken them to, not a special mid-session view
  of the same information.
- **Daily minutes moved from `/vocabulary` to `/vocabulary/settings`.**
  Stage 1's home screen carried its own minutes picker; the fixes brief's
  F1 list of what the home screen shows (today's amount, Start, the
  set-aside line, links to the words list and Settings) does not mention
  it, and the settings screen lists it as one of its three fields. One
  control for it rather than two that would have to agree on every write.
- **There is no mode picker any more — see "Stage 2 fixes" below.** This
  paragraph described a per-session Mixed/Recognise/Fill the gap/Write
  picker on the home screen; the fixes brief's F1 removed it outright once
  the addendum made the settings choice a single exercise type rather than
  a subset, which left nothing for a second, per-session override to mean.
- **A STATE is a noun; an ACTION is a verb, and the two are never the same
  word.** `STATUS_CHIP_LABEL.known` ("Known") is what a row's chip says a
  word IS; the button that puts it there says what pressing it DOES
  (`ACTION_LABEL.markKnown`, "Mark as known"). Same split for the other
  direction — the known-check reveal's outcome line says "Known" (and, per
  the fixes brief's F4, says NOTHING at all on a failed check — see below)
  never "Marked as known", which is the BUTTON's words appearing on a line
  that is reporting a fact, not repeating an instruction.
  `ACTION_LABEL.returnToRotation` ("Return to rotation") replaced "Restore"
  for the same reason: "Restore" names the wire verb,
  "Return to rotation" names what a learner would say happened.
- **A set-aside date is always in days, on purpose.** `daysUntil` (not
  `timeUntil`) is what the words list reads for `suspended_until` — "back
  in 12d", never "tomorrow" or "in 40m". `timeUntil`'s reach for a finer
  unit close up is right for a next-review estimate, read minute to minute
  while a session is live; a set-aside date is set weeks out and read once,
  and switching units as it counts down would make one date read as three
  different clocks.
- **`active_paused` is a display fact, not a fourth level.** Turning off
  `direction: "both"` in Settings does not reset an active card already in
  progress — it pauses it, server-side, no confirmation asked here because
  none is needed for something reversible with one click back. The list
  and the word page print "Paused" over whichever level the active card was
  actually at (`activeLevelLabel`/`"also active"` otherwise), and Settings'
  own toggle prints `active_in_progress` under itself while it is nonzero
  and the toggle is on — the one number that tells a learner there is
  anything to pause before they find out by pausing it.

## Stage 2 fixes: aligning with the written brief

A first pass at stage 2 shipped ahead of a full read of the brief, in a few
places. The fixes brief (F1–F8) corrected these; this section is what
changed and, more importantly, why the earlier shape was wrong rather than
merely different.

- **The home screen lost its mode picker outright, not just its wiring.**
  `PracticeMode`, `MODE_LABEL` and the `?mode=` query param are gone from
  the client entirely — the addendum's single manual exercise type in
  Settings (below) replaced the whole idea of a per-session override, and a
  picker for a choice that no longer varies per session is a control with
  nothing left to decide. The server still accepts a `mode` query param on
  `summary`/`session` for a caller that has never heard of the setting;
  nothing here sends one.
- **The progress row stays: total / learning / mastered.** "Only today's
  amount and Start" was said about the daily-minutes control, not about
  progress, which stage 1's brief asks for and stage 2 never removes. It
  was taken out once on that misreading and put back at the user's word.
- **The settings screen's exercise type is ONE choice, not a subset — but
  still a one-element ARRAY on the wire, not a bare string.**
  `VocabularySettings.exercise_types` is `[ExerciseType] | null`
  (`VocabularySettingsIn.exercise_types: list[Level] | None`, server-side
  `min_length=1, max_length=1`) — a scalar type here would have been a
  client invention that drifted from what actually lands in a request body.
  Automatic / Recognise / Recall / Produce are the exact labels
  (`AUTOMATIC_LABEL`, `EXERCISE_LABEL`) — stage 1's "Fill the gap"/"Write"
  wording for the old mode picker is gone along with the picker itself.
  When the choice leaves nothing to practise, Home, the practice page's
  "nothing to do" state and its end screen all say the same sentence,
  "No words are ready for this yet." — never "All caught up", which is true
  of nothing left to LEARN, a different claim than "nothing at this one
  task right now."
- **Passive `recognise` shows the bare word, the same prominent way active
  shows its Uzbek meaning** — `ChoicePrompt` branches on whether
  `before`/`after` are empty (`hasSentence`) rather than always drawing a
  `<mark>` around `target`, because the server sends an empty sentence on
  purpose (`resolve_mark` no longer builds this prompt) and a lone `<mark>`
  sitting in nothing read as an accident rather than "the word, alone."
- **All four `recognise` options are the SAME height, whatever the text
  behind them.** `OptionButton` carries `min-h-16` and clamps its text to
  two lines (`line-clamp-2`) — a long definition stretching only its own
  row is a visible tell for which option is correct, on a task whose whole
  point is that the four should look interchangeable until chosen.
- **A failed "I know this" says NOTHING.** `Reveal`'s claimed-outcome line
  now only renders when `claimed && result.known` — the "In rotation" line
  it used to print on a failed claim was a small verdict on a guess that
  was never meant to be graded out loud (the spec's §5: it "just continues
  as a normal item"). `IN_ROTATION_LABEL` still exists (the words list's
  status chip reads it) but the known-check reveal no longer does.
- **Leech resolution never leaves the session, and the three buttons are
  named `LEECH_LABEL`'s way everywhere: "Set aside", "See it in context",
  "Keep going".** The session's own reveal used to `navigate` to the word
  page on "See it in context"; it now reads `PracticeAnswer.leech_context`
  — sent by the server at the moment `became_leech` fires, the word's own
  newest sentence with the word marked — and shows it in a panel right
  under the leech choices, exactly the shape `ChoicePrompt`'s marked
  sentence already uses. Enter still advances once a choice is made; it was
  never blocked on leaving the page, only on picking one of the three.
- **`requeued` travels with the answer that follows an Again**, not
  invented by guesswork: `VocabularyPracticePage`'s `advance()` marks the
  item it pushes onto the queue's end (a client-only `QueueItem.requeued`
  field, never part of the wire `PracticeItem` shape), and `submit()` echoes
  it as `PracticeAnswerIn.requeued`. The server verifies this against the
  word's own last log rather than trusting the client outright (a stale or
  fabricated claim is a 422) — see `backend/app/services/practice.py`'s
  `record_answer` docstring for the window and the reasoning.
- **Status is a four-chip system, not the five-value wire enum.**
  `learning`/`review` collapse into one "In rotation" chip everywhere a
  status is shown — the row, the word page's header, and the status
  filter's own pills — because a learner deciding whether to leave a word
  alone has never once needed to know FSRS's own name for its phase.
  `features/vocabulary/components/StatusChip.tsx` is the one place this is
  decided (mirroring `CefrTag`'s reasoning exactly): a grey scale ordered by
  how much attention a word wants — `known` dim, `in_rotation` the page's
  own text colour, `suspended` dimmer still, `leech` alone in the accent —
  never green/red (verdicts) and never a CEFR hue (those name difficulty,
  not standing). `status.ts`'s old `STATUS_LABEL`/`STATUS_TONE` (keyed by
  the five wire values) are gone; `statusChip()` maps one onto the other.
- **The words list's actions moved into a per-row menu, and the row no
  longer resolves a leech itself.** `Word`'s trailing `DropdownMenu`
  (`Mark as known` / `Return to rotation` / `Set aside` / `Delete`, each
  shown only where it applies) replaced the inline "Set aside 30
  days"/"Keep practising" buttons a leech row used to grow beneath it — the
  fixes brief's own two-column table (state chip vs. action label) reads
  oddly if the row ALSO carries a third kind of button that is neither, and
  the word page (linked from every row) already carries the full three-way
  leech choice. The menu's own Delete goes through the same
  `pendingDelete.ts` "Removed · Undo" window a single selected row always
  used — a menu is the trigger, not a second confirmation surface — and
  bulk delete (more than one word) still opens `DeleteWordsDialog`
  unchanged.
- **The word page prints every context's date, and lapses per direction.**
  `Context` now shows `timeAgo(context.created_at)` beside the sentence,
  and `DirectionState` takes a `lapses` prop — `word.passive_lapses`
  always, `word.active_lapses` only once the active card has started
  (`null` before that, printed as nothing rather than "0 lapses", which
  would claim a card that doesn't exist yet has a clean record). These are
  LIFETIME counts (`SavedWord.lapses` is the separate leech-window figure
  the threshold itself reads, still on the wire, unused by any screen) —
  see `lapse_counts_for`'s own docstring in `practice.py` for why a reader
  looking at their own history has no reason to have that number reset out
  from under them the moment a leech is resolved.

## Browse: reading the list, not practising it

`/vocabulary/browse` (`VocabularyBrowsePage.tsx`) turns the saved list into
cards — front the word, back its meaning, an example and the way back to
where it was met — and it is worth being explicit about why this is not a
fourth exercise beside recognise/recall/produce.

- **Nothing here is graded, so nothing here can teach the ladder anything.**
  A card shown proves someone LOOKED, not that they knew it; grading that
  as an answer would let a learner walk `passive_level` up simply by paging
  through their own list, which is a promotion the ladder's own evidence
  (an actual recall, a chosen `recognise` option) never earned. So Browse
  calls no FSRS function, writes no `vocabulary_review_logs` row, and moves
  no card's due date — the one thing it writes anywhere is
  `saved_words.browsed_at`, a timestamp with no opinion attached, set when
  a card is shown (`POST /vocabulary/words/{id}/browsed`, fire-and-forget,
  once per card a session actually displays — see the page's own comment
  for why that is a `Set` keyed on id rather than a request per render).
  It is also why Browse is not counted in the daily time budget
  `practice.py`'s plan reads: that budget is spent on cards FSRS is
  scheduling, and a page with no schedule of its own has nothing to spend
  it on.
- **No shuffle, and that is the same argument from the other direction.**
  A practice queue is allowed to reorder (most-overdue-first, new words
  budgeted last) because the ORDER is part of what FSRS is deciding. Browse
  decides nothing, so the order is whichever the caller already chose: the
  words list's own filtered order when opened from there, or a material's
  saved-words panel's own (material-scoped) order when opened from a
  review page. Reordering either would be Browse quietly making a judgement
  call that belongs to a page with a spaced-repetition engine behind it.
- **No end screen, no stats, no joke.** `jokes.ts` and the end screen's
  new/reviewed tally exist because a PRACTICE session has something to
  report on — what got answered, what came back wrong. A Browse pass has
  no such thing to say about itself; reaching the last card simply stops
  (`→` at the end is a no-op, not a dead end presented as one), and closing
  it (Esc, or the header's own close button) returns to wherever it was
  opened — never a page of its own with a "you're done" of its own to say.
- **"Wherever it was opened" is a `from` query param, never
  `navigate(-1)`.** Both entry points (the words list's Browse button, and
  `ReviewVocabulary`'s Browse link from a material's saved-words panel) set
  `from` to their OWN current path when they build the link; the page
  reads it back on exit and falls back to `/vocabulary/words` when `from`
  is missing or is not a same-app relative path (`isSafeInternalPath`,
  rejecting a bare `//host/…` alongside a full URL, since an open redirect
  is not a smaller bug for living behind a "close" button). History is not
  the caller here: a bookmark, a link shared into a chat, or a tab whose
  back-stack reaches further than the entry that opened Browse would all
  send `-1` out of the app rather than back to the list or the material's
  review page.
- **The document keydown handler steps aside for a focused control.**
  Space/←/→ are withheld whenever `document.activeElement` is a button,
  link, or form field (`isInteractiveElement`) — otherwise Tab-ing to
  "Close Browse" and pressing Space to activate it flips the card
  underneath instead of closing anything. Esc is exempt and keeps firing
  from anywhere, including from the close button itself, because nothing
  reachable by Tab on this page answers to Esc on its own. The card's own
  face stays a `role="button"` `<div>` rather than a real `<button>` for
  exactly this reason — Space flipping it while IT is the focused element
  is the documented behaviour ("Space flip", below), not the bug this
  guards against.
- **It shares the words list's OWN filters** (`wordsFilter.ts`'s
  `filterWords`), not a second implementation of "which of my saved words
  match" — the whole point of the "Browse" button next to a filtered list
  is that the deck it opens is exactly what the list was just showing, and
  two copies of that rule is how they end up disagreeing about one row the
  first time either is touched. `savedWordMeaning.ts`'s `wordMeaning` is
  the same story one level down: the list's row and Browse's card back read
  the same fallback chain for a word's own headline meaning, rather than
  each guessing at it separately.

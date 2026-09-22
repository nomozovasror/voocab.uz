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
it builds the word list, and a word standing only inside terms is left to
them (`seed/vocabulary.py`, `candidates(claimed=…)`). The live lookup does
the same thing from the other end: `dictionary.Gloss.term` lets a model
answer about something wider than what was tapped, and the entry is stored
over the term's span. A term the passage already has is not written again —
the reader is already being shown it as the phrase.

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

## A saved word is one word with several contexts

`spring` met in a passage about seasons and again in one about coils is ONE
word with two meanings. The list deduplicates by lemma and hangs each meeting
off it; both meanings and both example sentences survive, which makes a
better card than either alone.

The gloss is **copied** at the moment of saving, never read back through the
material. A passage can be edited and re-glossed, and a saved word changing
meaning underneath somebody is worse than one that has aged.

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

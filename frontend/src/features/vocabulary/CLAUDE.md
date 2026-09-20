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

## Two ways in, and the popover is the one they use

The tool row is where somebody LEARNS the feature exists; the popover at the
selection is where they use it, because it arrives under their finger at the
moment they have just selected a word they do not know. The remaining count
travels with it — a reader deciding whether this word is worth one of three
cannot be made to look at the top of the screen to find out.

A selection longer than `LOOKUP_WORDS` drops the control rather than
greying it out. Absence reads as "not this"; disabled reads as "not you".

## The panel: what it shows and what it refuses to

Lemma, part of speech, CEFR, the meaning in THIS passage, Uzbek first and
English under it. Nothing else.

**No example sentence.** It looks like an omission and is not: the reader is
looking at the sentence, six inches to the left. **No etymology, no other
senses, no synonyms.** Each lookup has about two seconds to pay for itself,
and a panel that reads like a dictionary page is a panel somebody closes and
goes back to guessing, having spent one of three for the privilege.

**A word marked `unusual` says so in words, not with a badge.** It is a
common word in a sense the reader would not expect — `bank` as the side of a
river — and a badge would say "this one is special" and leave them to work
out how. What helps is the sentence.

**CEFR is printed; the frequency band never is.** `C1` is a scale a learner
already has a feel for. "NGSL rank 2400" is a fact about a corpus. The band
exists and stays on the server, where the arithmetic is.

## The review: the words, not the number

"You looked up three words" is a score for something nobody was being scored
on. The three words, with what they mean in the passage that defeated them,
is homework — and it is the homework an IELTS teacher actually sets after a
passage a student struggled with.

- **The opened words come first and separately.** Every other word in the
  list is one the frequency lists think is hard; those two or three are the
  ones that stopped THIS reader badly enough to spend one of three on.
  Nothing else on the platform knows which they were.
- **They come from the ATTEMPT, not from `lookups.ts`.** That list remembers
  across sittings on purpose, so on a retake it holds words from a paper
  that is over, and the review is about one sitting.
- **The rest is collapsed and sorted by LEVEL**, which is the opposite of the
  lookup panel's passage order and right for the opposite reason: mid-paper
  the question is what this one means, and here it is which to learn first.
- **Every entry carries its sentence from the passage.** It is the passage's
  own sentence, cut from the text rather than written by a model, and it is
  the whole argument for saving words from a paper instead of from a list.

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

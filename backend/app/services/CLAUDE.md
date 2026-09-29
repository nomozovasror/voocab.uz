# Listening services — invariants

Rules here are load-bearing: each records a decision that was got wrong once.
Keep the rule and the reason together when editing.

## The catalogue is a query, not a list

`GET /api/listening/practice` returns **one page**, filtered, ordered and
counted in SQL (`listening.py`). Nothing about the list is decided in the
browser: at a thousand materials, sending the library so the page can hide
most of it is half a megabyte of JSON to show somebody thirty titles.

- **Add a filter in two places or not at all.** `catalogueParams`
  (`frontend/src/features/listening/practice.ts`) turns control state into
  query params; `_catalogue_where` turns them into SQL. One without the other
  narrows the page but not the count.
- **Facets are counted over the whole library**, never the page and never
  what the other filters left. An option that appears and vanishes as you
  filter is one nobody can aim at.
- **`done` has three states, not two.** Off with nothing typed, materials
  the caller has sat are put away and `done_hidden` says how many — never
  hide rows without saying so. **On, the list is ONLY the finished ones**;
  it used to mean "and the done ones as well", which made the chip a way of
  clearing a filter rather than applying one, and left "what have I already
  sat" the one question the catalogue could not be asked. Off **while
  something is typed**, they come back and sort BELOW everything unsat: a
  search is somebody naming the thing they want, and "no results" for a
  paper they sat last week — which they can see is on the shelf — is the
  page refusing the question. `done_hidden` is then zero, because nothing is
  being hidden.
- The same three states, with the same reasoning, in `drills.list_drills`.
  Two lists with one chip over them cannot mean different things by it.
- Anything a row prints that is a fact about the LIBRARY rather than the
  material must come from the server. The byline's "4 materials here" was
  counted in the browser and became a lie the day the browser stopped having
  the library.
- Paging is offset-based on purpose. Keyset survives six figures; at four,
  filters narrow before depth does, and one order per sort key beats a cursor
  that has to encode which key it is on.

## A recommendation has to say why

`GET /api/listening/next` returns three materials and a `reason`
(`recommend.py`). The reason is the contract, not decoration: a
recommendation that cannot justify itself is a shuffle with a confident label
on it.

- **Silent until three materials are done** (`MIN_MATERIALS`). A
  recommendation off one paper is a guess in a confident voice.
- **One slot, three shapes** — carrying on, just finished, suggested — at
  about the same height, so changing state does not make the page jump.
- **`finished_course` lasts exactly as long as it is true**: the most recent
  submitted attempt must be the FIRST attempt at a material that completed a
  course. A retake is not a completion, and a month-old "well done" is a page
  that has stopped paying attention.
- **The two columns have different jobs.** Left is what to do (carry on,
  suggested, the list); right is how it is going (last result, mistakes,
  trend, totals) — which is why the sidebar opens with "Your last result",
  not "Pick up where you left off". Two invitations to continue on one screen
  leave the reader guessing. The sidebar also steps back from whatever course
  the block above is carrying on, so one material is never named in both
  columns.
- **A course in progress outranks everything else.** Somebody four papers
  into a six-paper course was being handed three unrelated ones. They chose
  the course, and its order is a person's judgement; band-fit over a
  first-try average is a guess, and a guess does not overrule a judgement.
- The course carried on with is the one holding their **most recent**
  attempt, not the one they are furthest through — furthest-through keeps
  pointing at a course abandoned in March.
- A loose suggestion **never jumps a course queue**
  (`sequenced_material_ids`). Offering lesson five to somebody on lesson
  three denies the one thing a collection claims.
- **`weak_part` is guarded, and stays guarded.** Naming the lowest-scoring
  part outright did not survive being looked at — 62% against 66% over a few
  dozen answers is noise. A part is named only when it is scored at all,
  below `WEAK_CEILING`, and clear of the next-weakest by `DECISIVE_GAP`.
  Otherwise fall through to `level`. Loosening those constants means making a
  claim about somebody's ability on evidence that doesn't carry it.
- **The ladder never opens with `hard`** — except for `steady`, the one
  reader for whom it is right rather than a discouragement. `new` is always
  last: "might be anything" is not a recommendation.
- **`steady` is the exact inverse of `_weak_part`, over the same two
  constants**, so the block can never tell somebody both that they have a
  weak part and that they haven't.
- Never recommend a material with no questions, or one already sat.
- Shown only over an **unnarrowed** list. A filter is the reader saying what
  they want; suggesting past it is the page talking over them.

## Collections are references, and progress is derived

A collection (`collections.py`) is an ordered list of material ids. It owns
nothing, so deleting one cannot lose a material.

- **There is no enrolment.** Progress is counted from attempts already made,
  so opening a collection commits nobody to anything and no state can rot.
  Cheap enough (ten materials, not a library) to compute per request.
- **`next_material_id` is the first UNSAT one in order**, not the nearest.
  The sequence is somebody's judgement; nearest would make a collection a
  filter with a progress bar.
- **The item list is written whole** (`PUT .../items`), never patched a row
  at a time. Reordering through a unique index on `(collection_id,
  order_index)` one row at a time is a sequence of temporary states that all
  have to be legal; replacing the list has no intermediate state to get wrong.
- An author may include their own drafts; a learner sees only published ones.
  Both counts go to the author (`item_count` vs `public_item_count`) rather
  than the difference being hidden.
- **Emptying a published collection withdraws it** rather than the save being
  refused. The author's work is never rejected to protect a flag — but a
  published course with nothing in it is a promise onto a blank page.
- The rows a learner sees are the catalogue's own (`_catalogue_rows`). A
  collection is a different route to the same thing, not a different thing.

## Layering: `answers.py` is below both graders

`normalize_answer` lives in `answers.py` and nowhere else. Grading owns what
makes an answer right; `mistakes` owns what kind of wrong a wrong one was;
both must compare the same two strings the same way or the second contradicts
the first. While the rule sat in `grading`, `mistakes` had to import
`grading` — putting the two lowest modules in a cycle with everything above
them, which is why `attempt_result` could not classify anything. `grading`
re-exports the name; the split is about who may import whom.

## The review's transcript carries its neighbours, and its word timings

`grading.transcript_with_context` (§71's follow-up) is what
`attempt_result` actually sends, not `transcript_across`. The two share one
definition of "touches" (`_touching_indices`, itself built on `_touches`) on
purpose — a review whose neighbour lines used a looser or stricter rule than
its answer line would show a boundary that disagrees with itself line by
line.

- Every line sent carries a `role`: `"answer"` for a line the question's
  marked range actually touches, `"before"`/`"after"` for the one line
  immediately either side of that touching set. Nothing further out — a
  review is quoting the moment, not the paragraph.
- **A neighbour is added regardless of who says it.** The recording's speaker
  changes are not the review's business; the frontend cuts these lines into
  sentences by pause length on its own, and a neighbour withheld for
  belonging to someone else would break exactly the case — a change of
  speaker — where showing it matters most.
- **Found per contiguous run of touching lines, not once over the overall
  span.** A "choose TWO letters" question can be answered a minute apart;
  treating the whole stretch between as "inside" would hand back most of the
  recording. Neither neighbour exists past the first/last line of the
  material — there is no "before" it starts.
- **`words` rides on every line** — the same `{word, start_ms, end_ms}`
  triples `apply_overrides` already puts on each segment, copied through
  unchanged. This is what lets the frontend's second replay button (the
  whole shown passage) and its own pause-based sentence cuts work from
  timings the server already computed, rather than asking for a second
  transcription pass.
- Still keyed on the question's marked ranges alone: no ranges, or no
  transcript at all, sends `[]`. This is also why a **reading** question —
  which never has audio lines to hand this from — always gets `[]` back
  unaffected; `EvidenceSpanOut` is its counterpart into the passage instead.
- **A DRILL never lets a neighbour leak another group's answer.**
  `attempt_result` still transcribes off the whole material's lines when
  `attempt.group_id` is set — a drilled question's evidence can sit next to
  a turn that belongs to a question nobody has sat yet. `hidden` is the set
  of line indices any OUT-OF-SCOPE question's marked range (`replay_start`/
  `replay_end_ms`, or an option replay) touches; a neighbour landing on one
  of them is left out entirely rather than widened past it. A full sitting
  passes nothing — there is no out-of-scope question to leak.

## Difficulty is measured, never stored

A material's `Easy`/`Medium`/`Hard`/`New` band is a function of
`QuestionAttempt` rows (`difficulty.py`), never anything an author declares.
**Do not add a `difficulty` column to `materials`.** Stage 1 is a classic
proportion correct; stage 2 is a Rasch/1PL estimate correcting for *who* sat
the paper. As long as difficulty stays a function, that swap touches one
module — an authored column would make it a migration, a backfill and a
re-education of everyone who set one.

**The projection is not that column.** The tally lives in a
`material_difficulty` table that `difficulty.recompute()` refills, because
the aggregate scans every answer on the platform. The line: nothing authored
ever reaches that table, every column in it is derived, and dropping the
whole thing costs one `recompute()`. Stage 2 changes the computation and the
table refills — still no migration.

- The worker refreshes it every `DIFFICULTY_REFRESH_INTERVAL_S` (default
  900), beside transcription (`worker.py`). A failed refresh is logged and
  swallowed: nobody waits on a band, and people wait on audio.
- **A band is only as fresh as the last refresh**, with one exception: the
  first crossing of `MIN_ANSWERS` happens on the submit that causes it
  (`refresh_if_unrated`, from the attempts endpoint). A paper a class has
  just worked through, still saying nobody has answered it, is the catalogue
  contradicting itself. Anything writing attempts outside a request — the
  seed script — calls `recompute()` itself.
- **A skipped question is still an answer.** Grading writes a row for every
  question on the paper, so an untouched one counts toward the evidence and
  counts as wrong. That is what makes "missed entirely" classifiable at all.
- The read path derives the band from the stored *tally*, not the stored
  `band` column. Move a threshold and the API is right immediately while the
  column catches up; the column exists so a paginated catalogue can filter
  and sort by difficulty in SQL.

Two constants guard against inventing numbers, and are separate on purpose —
"is this paper hard" and "is this person weak here" are different questions,
so one moving must not drag the other:

- `difficulty.MIN_ANSWERS` — below it, a material is `New` with no percentage.
- `learner_stats.MIN_ANSWERS` — below it, a distribution row reports
  `accuracy_pct: null` and the UI draws a dash with no bar. **Never
  substitute 0** — over four answers a zero is a false claim.

## First attempts are the measurement

Every sidebar figure describing *ability* — average, mistake breakdown,
trend, part split — counts each material's **first** submitted attempt and
nothing else (`learner_stats.py`). Somebody who sits a paper three times and
finishes on 95% has learned that paper, not listening.

- `first_try_avg_pct` is the headline; `best_avg_pct` sits under it and is
  **absent entirely** until something has been sat twice, because with no
  retries it is the same number under a second name.
- "Materials done" counts materials with at least one *submitted* attempt.
  Started-and-abandoned doesn't count.
- Percentages round half **up** (`_pct`), not Python's half-to-even — two
  figures on one panel disagreeing by one is a bug nobody reports and
  everybody notices.

## Mistakes are classified, not counted

`mistakes.py` turns a wrong answer into a *kind* — spelling, missed entirely,
singular/plural, over word limit, number/date format, wrong answer — by
comparing raw `given_answer` against the accepted ones. Only possible because
grading normalises for the comparison and never writes the normalised form
back: **keep storing `given_answer` exactly as typed.**

The distinction the sidebar rests on is *spelling* against *missed
entirely*: one is a proof-reading problem, the other a listening problem, and
"you got 62%" tells a candidate neither. The rules lean towards **not**
claiming spelling — see the threshold notes in that module.

Letter-answered groups (multiple choice, matching, boxed summaries) are
excluded: there is no spelling in "b". Distractor analysis is the equivalent
question there, and belongs on the full statistics page.

## Vocabulary is per material, and that is not a duplication bug

`material_vocabulary` stores one row per word per material, so `analysis` is
glossed forty times across the catalogue. That is deliberate and the shape is
the whole feature. `spring` is a season in one passage, a coil in the next
and a source of water in a third; a global `words` table has to pick one
sense and is then wrong for most of the passages that use the word — which is
exactly the failure that makes a plain dictionary API useless to a band 5
reader shown five senses. Forty rows cost four kilobytes; a global table
costs the feature.

Deduplication happens once, where it means something: `saved_words` is per
**sense** (P4 — it was per lemma before, and that was wrong: see below),
because what somebody is STUDYING is one MEANING however many passages they
met it in. Each meeting is a `SavedWordContext` and **copies** the
contextual gloss rather than pointing at it — a material can be re-glossed,
and a saved word changing meaning underneath somebody is worse than one that
has aged.

### A saved word is a sense, not a spelling (P4)

`bank` (the river) and `bank` (the financial institution) are two things to
learn, not one. Deduplicating by lemma alone — the design from stage 1 —
gave them one FSRS schedule and one "usual meaning" slot between them,
which is a card that cannot teach either meaning honestly: the ladder
promotes them together though a learner may know one cold and have never
seen the other, and the "usual meaning" line has to pick one of two
unrelated answers and is wrong about the other. `spring` (the season) met
twice is genuinely one word and belongs on one card; the two cases look
identical from the lemma alone and are told apart only by *sense* —
`MaterialVocabulary.sense_id`, the row's own link into the global lexicon
(`app.models.lexicon.LexemeSense`) that P3's `link_row` already guarantees
on every row.

So `saved_words.lexeme_sense_id` — not `lemma` — is the key: unique per
`(user_id, lexeme_sense_id)`. `lemma` stays as a plain denormalised column
for display and search (two rows may now legitimately share it) but answers
nothing about identity any more. Saving a word from a passage
(`vocabulary.save`) resolves THE SENSE THAT MATERIAL ROW HAS
(`entry.sense_id`) and keys on that, not on `entry.lemma`: two materials
glossing the same lemma with the same sense still merge into one saved word
with two contexts, exactly as before; two materials glossing it with
*different* senses now correctly produce two saved words, which they never
could before.

The word's usual meaning/definition/CEFR are read LIVE from that
`LexemeSense` (`SavedWord.meaning_core_en`/`meaning_core_uz` are dead
columns — kept, never written or read, past this phase) rather than copied
onto the row at save time: an admin fixing a wrong translation in Studio's
review tab now reaches every learner already studying the word, not only
the next one who saves it. `SavedWordContext` is unaffected by any of this
— it keeps copying the CONTEXTUAL gloss and sentence exactly as before, for
exactly the reason above (a re-glossed material must not change what
somebody already saved); only its own `meaning_core_en`/`meaning_core_uz`
snapshot changed WHERE it reads from (the entry's sense, live, since the
entry itself stopped carrying that copy in P3) — never whether it is
snapshotted at all.

Every route that used to address a saved word by lemma (`DELETE
/vocabulary/words/{lemma}`, the word page, the leech choice, the bulk
action) now addresses it by `id`, for the same reason: a lemma can no
longer name one row on its own.

- **`entries` is gated on having submitted** (`may_see_all`). The budget of
  three lookups lives in the browser, where a rule meant to make somebody
  choose has to be visible to work; a list endpoint serving eighty-six
  glosses mid-paper would make it a formality, and the network tab is not a
  difficult place to look. `look_up` answers about one word and is always
  allowed.
- **No lemmatiser on this side of the fence.** The search space is not
  English, it is the eighty lemmas of one material, so the tapped word is
  matched by span, then surface, then lemma, then by reducing it until it
  hits one of the eighty. A second copy of `seed/vocabulary.py`'s rules would
  be two implementations that have to agree for ever.
- **The span match is how a phrase is recognised.** `give rise to` is one
  entry over three words; a tap on `rise` lands inside it. Nothing else
  would ever surface it — every word in it is NGSL rank one hundred. It
  tests `also_at` as well as the entry's own span, or a tap inside the
  SECOND `give rise to` in a passage misses the phrase entirely and the
  word is answered on its own, which is the one answer the phrase exists
  to prevent.
- **`also_at` carries every other place the word stands**, so the passage
  can be marked at all of them off one row. One row per lemma is what makes
  a tapped word have one answer; a row per occurrence would duplicate a
  gloss fourteen times for `revolution`. Empty where the gloss is about one
  USE rather than about the word — an unusual sense, or one that differs
  from the word's ordinary meaning.
- **`source` is never overwritten unless it is `extracted`.** The column
  exists from the first day so that nobody discovers, months later, that a
  re-run reverted their correction.
- **An entry carries TWO meanings, and the usual one leads.**
  `meaning_core_*` is what the word means wherever it is met;
  `meaning_en`/`meaning_uz` keep their old job and are shown under `Here:`
  only where `sense_differs`. The per-material argument above is unchanged
  and still right — what it could not do alone is teach the language. A
  passage about artificial intelligence glossed `learn` as "a computer
  process of finding patterns in data", marked `n`: a faithful reading of
  `machine learning` and a false statement about the verb somebody then had
  on their list. Empty is legal and readers fall back to the contextual
  line; a missing usual sense is narrower help, a missing contextual one is
  none.
- **A live lookup may answer about something wider than the word.**
  `dictionary.Gloss.term` names the compound the tapped word stands inside,
  as the paragraph writes it, and `_generate` stores the entry over the
  term's span — accepted only where the term is FOUND and actually contains
  the tap, because a model asked a leading question finds one. A term the
  material already has is not written again: the caller is already showing
  it as the phrase.
- **`enrich_saved_contexts` is the one thing allowed near a saved gloss, and
  it only fills.** The copy rule stands — a re-glossed material must not
  change somebody's saved word underneath them — but a field that did not
  exist when they saved is a gap rather than a correction. It writes only
  where empty, never over a meaning, an example or a level, and it re-points
  the `vocabulary_id` the re-extraction nulled. Idempotent by construction,
  because it runs on every import.

## Every writer of `material_vocabulary` is find-or-create

`material_vocabulary` and the global lexicon (`Lexeme`/`LexemeSense`,
`app/models/lexicon.py`) answer different questions — see that model's own
docstring for why a second table exists at all — and a row of the first is
never allowed to be unlinked from the second, not even for the length of one
request (`brief-lexicon.md` §8, `lexicon-spec.md` D6). `replace_extracted`
(the seed import path) and `_generate` (a live lookup, above) are the two
places this table is written, and both call `app.services.lexicon.link_row`
on every row they create, before it is committed:

- **Find**, by `(lemma, pos)` — and where nothing matches, by the SAME
  inflectional merge rule `scripts/build_lexicon.py`'s one-off P1 rebuild
  uses (`descend`/`descending`, not `digest`/`dig` — see that script's own
  docstring for the rule and why it is this narrow), applied one row at a
  time against whatever the database already holds rather than the
  whole-corpus graph P1 can afford to build at once. The rule itself lives in
  `app.services.lexicon` now, imported by `build_lexicon.py` rather than the
  other way round, so P1's batch rule and P3's incremental one cannot drift
  apart.
- **Create**, when nothing is found: a PROVISIONAL `LexemeSense` built from
  the row's own wording, `source_id="model"`, `cefr` copied from the row's
  own `cefr_level` — UNLESS an existing sense of that lexeme already has the
  identical `normalise_meaning`d text, the exact grouping key P1's own
  clustering uses, in which case the row joins that sense instead of buying
  a near-duplicate one P1 would only merge away on its next rebuild.
- **No model call in the request path, ever.** Everything above is a lookup
  against tables this project already has, or arithmetic over the row it was
  given. Grading a provisional sense for real is `app.services.lexicon_enrich`'s
  job, run continuously by `app.worker`'s lexicon loop against whatever is
  `Lexeme.enriched_at IS NULL` — including a sense `link_row` just added to a
  lexeme P2 had already finished, which is exactly why creating one clears
  `enriched_at` back to null rather than leaving it enriched-but-stale.
- **`meaning_core_en`/`meaning_core_uz` are no longer written to
  `material_vocabulary`**, by either writer, from this point on (the brief's
  own §3: the column is the one deliberate exception to "no columns are
  dropped in this phase", kept for existing readers but dead for writes).
  That "usual meaning" now lives on the row's `LexemeSense` instead — both
  writers still set it on the in-memory row before calling `link_row` (so
  the provisional sense is built from the real usual-sense answer, not a
  fallback to the CONTEXTUAL gloss) and clear it back to `""` immediately
  after, before the row is ever added to the session. `enrich_saved_contexts`
  and `vocabulary.save`'s initial fill still read the row's
  `meaning_core_en` and will therefore see nothing on a freshly written row
  until a later phase moves them onto `LexemeSense` — a known, accepted gap,
  not a bug to chase inside this phase.

## The lexicon: what goes in, and how it is flagged

- **Proper nouns are not vocabulary.** Three gates keep them out: the seed
  candidate filter (`seed/vocabulary.is_name`: capitalised mid-sentence),
  the extraction prompts (`seed/read_vocabulary.WORDS_PROMPT` answers a name
  with an empty lemma; `PHRASES_PROMPT` never offers one) -- the filter
  cannot see a name that only ever opens a sentence, and ~100 got in that
  way -- and the OEWN loader (below). The live-lookup prompt already
  refused names. A name that still arrives is MARKED, not refused:
  `Lexeme.is_proper_noun`, set by `lexicon.link_row` for a new lexeme
  (`looks_like_name`: capitalised, mid-sentence in its own example, noun or
  phrase, not an acronym, on no frequency list -- deliberately narrow) or
  when the lemma is already a known name. A proper noun's CEFR is NULL on
  the lexeme and every sense -- a real state, never "not graded yet";
  enrichment never grades one -- and it is out of practice: every queue and
  count in `practice.py` (`_practisable_clause`) and the distractor pool.
  The API sends `cefr_level: ""` for a finished sense with NULL CEFR
  (`api/vocabulary._no_level`), so the material row's own seed level never
  stands in for it; the UI draws no chip for an empty level (`CefrTag`).
  Days, months, languages and nationalities are words, not names.
- **The rule is by KIND, not by row.** `lexicon.link_row` sets
  `MaterialVocabulary.hidden = True` on ANY row whose lexeme turns out to be
  a proper noun (or a function word, below) -- not just at classification
  time. `scripts/lexicon_cleanup.py hide-proper-nouns` is the one-off
  backfill for the material rows written before this rule existed,
  including the ~100 the seed's own filter missed and the handful a
  learner's live lookup generated on the spot: a lookup still ANSWERS the
  learner (the definition, no level, not practisable) and the
  `lookup_events` row is kept -- "someone looked this up" is not "this is
  glossed in this text", and one learner's curiosity must not add a gloss
  to the passage for everybody else. `vocabulary.look_up`'s own search for
  an existing answer therefore reads `entries(..., hidden=True)` -- the
  ONE place a hidden row is looked at again -- so a second tap on the same
  name finds the row already there rather than colliding with it on a
  fresh insert; the whole-list review endpoint keeps filtering it out as
  before.
- **Single-letter tokens and NGSL's own closed-class top ~100 are not
  vocabulary either** (`lexicon.FUNCTION_WORDS`/`is_excluded_word` --
  articles, pronouns, prepositions, conjunctions, auxiliaries/modals,
  "not", and the quantifier-determiners and focus particles that behave
  the same way; content words just as frequent, `say`/`go`/`know`/`one`/
  `now`, are deliberately left in). Unlike a proper noun this is REFUSED,
  not marked: `vocabulary._generate` and `.replace_extracted` (`link_row`'s
  two writers) never build a `MaterialVocabulary` row for one at all, and
  `build_lexicon.py`'s list-only lemma selection never mints one either.
  `link_row`/`_find_or_create_lexeme` still mark `Lexeme.is_function_word`
  as a backstop if one somehow arrives regardless, exactly mirroring
  `is_proper_noun` (no CEFR is not part of the treatment here -- these
  never had one worth grading). The 65 that had already gotten into the
  lexicon before this rule (all of NGSL's top ~100, list-only-loaded like
  every other lemma on a frequency list) were found and fixed by
  `scripts/lexicon_cleanup.py function-words --apply`: the 59 nothing
  pointed at were deleted outright, and the 6 with a material row (`do`,
  `be`, `can`, `that`, `have`, `should` -- all from a learner's live
  lookup, since the seed candidate filter's `ASK_RANK` already keeps every
  one of these off the extraction) were kept, marked, and had their
  material rows hidden the same way a proper noun's are.
- **A capitalised OEWN entry is not the lower-case word**
  (`lexicon_enrich.load_oewn`). The extract lower-cases lemmas, and `Song`
  (a dynasty), `Town` (an architect), `He` (helium) sorted first and became
  rank 1. The lower-case entry's senses lead; a capitalised entry's follow
  only where SemCor tagged them (`March` the month) or where OEWN has no
  lower-case entry at all (`Monday`, `DNA`).
- **A list-only lexeme's pos and definition are chosen together**
  (`lexicon_enrich.top_sense_any_pos`): the lemma's most-tagged OEWN sense
  across every pos (Princeton WN 3.1 SemCor counts, carried in the extract).
  No counts to decide between two or more pos: a model picks among each
  pos's top sense. Not in OEWN: one model request gives pos + definition.
  Moot for a function word or a single letter now -- excluded before this
  step ever sees the lemma (above).
- **`ngsl_conflict` is one test**: rank-1 sense graded C1/C2 on an NGSL top
  1 000 word. "A1/A2 while off-list" was dropped -- off-list only means "on
  none of five lists", and almost every hit was a plain word.
- **The judge runs twice; a pair is flagged only if neither run says
  `same`** (`combine_verdicts`). One run alone moves ~13% of pairs between
  `same` and `unsure`. A reply in any shape the judge actually sends (bare
  k-map, arrays) is parsed (`parse_judge_reply`); an unparseable one is
  retried once and then is NO verdict -- it never becomes `judge_unsure`.
- **A re-translation never overwrites before it is proven.** The old pair
  is stashed in `meaning_uz_prev`/`meaning_uz_alt_prev`, old and new are
  judged twice in the same run, and the new pair is kept only if the
  `different` share falls by >= 30% relative
  (`scripts/lexicon_cleanup.py retranslate`). Those `_prev` columns are
  cleared to `""` the moment `--decide` runs, whichever way it decided --
  they hold the OLD pair only until the decision, not for ever -- so the
  trial's own 94 (sense, old pair, new pair, both verdicts) rows are copied
  into the repo as their durable way back,
  `app/data/lexicon_trials/retranslate-2026-09-29.json` (see that
  directory's README), and `scripts/lexicon_cleanup.py
  restore-retranslation` re-reads it to put a sense's OLD pair back, for
  all 94 or a listed few.
- **Princeton WordNet 3.1's SemCor tag counts are not a definitions
  source, and the licences page has to say so from data, not from a
  hand-written row.** `LexemeSense.oewn_rank` persists the ACTUAL rank a
  sense was chosen/ordered by (`apply_work`, backfilled once for senses
  written before the column existed by `scripts/lexicon_cleanup.py
  wordnet-provenance`); `lexicon_licences.sources` shows the
  "Princeton WordNet 3.1" entry only because `oewn_rank IS NOT NULL` on
  senses this deployment actually has, carrying its own `usage_note`
  ("sense ordering only, not stored as definitions") so the card cannot be
  mistaken for a second source of Uzbek text. The WordNet 3.1 licence's own
  "no advertising" clause is noted in the registry's docstring, the one
  place in the codebase that decides how Princeton is credited.

## Vocabulary practice (stage 1) — `practice.py` is the only module that imports `fsrs`

`saved_words` carries two independent FSRS cards (`passive_*`, `active_*`,
mirroring `fsrs.Card` field for field) plus `status`, `lapses`, `reps` — see
that model's own docstring for why `{direction}_state` is nullable rather
than defaulted to `fsrs.State.Learning`: null means "never practised", which
is a different fact from a fresh card's starting state. `_load_card`/
`_store_card` are the only translation between those six columns and an
actual `Card`, in either direction.

- **The rating is computed from `exercise_type` + `verdict`, never asked.**
  `RATING_TABLE` is the whole rule, shaped for all four exercises though
  stage 1 issues only `recall`. Self-graded ease (Anki's "easy/good/hard")
  is exactly what this refuses to copy — a learner mid-sentence has no real
  basis for that judgement, and *which exercise this was* is a fact the
  system already knows and does not need to ask about twice.
- **Verdict reuses `mistakes.classify`, not a second opinion on spelling.**
  `normalize_answer` decides `correct`; only `spelling`/`plural` count as
  `close`; everything else, including empty, is `wrong`. One classifier,
  used to explain a reading mistake and to grade a vocabulary card alike.
- **No interval halving on a wrong answer, ever.** FSRS already does the
  right thing on `Rating.Again` — stability drops, difficulty rises — and
  a second penalty on top would double-count what the library did and hide
  a struggling word behind a deceptively short interval. The only thing
  layered on top of FSRS's own judgement is the plan's 10-minute
  learning/relearning step, which is FSRS's own feature
  (`learning_steps`/`relearning_steps`), not a bypass of it.
- **A lapse is a REVIEW-state card answered Again**, checked on the card
  BEFORE `Scheduler.review_card` is called. A Learning-state card failing a
  step is ordinary progress, not a lapse. `reps` increments on every answer
  regardless of direction — it is one fact about the WORD, not two.
- **The gap's answer never reaches the client before the answer is
  submitted.** `resolve_gap` is a pure function of the word and the chosen
  context, so it is called once to build the prompt (dropping the
  `answer` field) and again, identically, when the submitted answer comes
  back — no session state is kept between the two requests. It searches for
  the context's `surface` (the inflected form, e.g. "Undertaken") in the
  sentence first, then the lemma, then falls back to a bare definition
  (`meaning_core_en`, else the context's `meaning_en`) with the lemma as
  the answer — still `recall` either way.
- **Context rotation and "the newest context the first time" are one rule,
  not two.** A context with no entry in `_last_used_map` sorts as though
  used at the start of time, so "never used" and "everything tied" hit the
  same tie-break: newest `created_at` wins. Computed once per session over
  every queued word's contexts (`_last_used_map`), not once per word.
- **The daily limit is TIME, and the new-word intake is what actually
  shrinks.** `_avg_seconds` is the median of the last 200 `elapsed_ms`
  logs, clamped to [4s, 60s], defaulting to 12s under 20 logs. Reviews are
  filled first (most overdue — smallest `due` — first), capped by
  `budget/avg`; whatever is left buys new words at `2×avg` each
  (`NEW_WORD_COST_FACTOR`), because a new word is normally answered twice
  before it settles. This is the whole fix for the Anki failure the brief
  names: reviews crowd out new words automatically, with no cap the learner
  has to pick.
- **`forget` (`vocabulary.forget`) keeps every log a word ever produced.**
  `vocabulary_review_logs.saved_word_id` is `ON DELETE SET NULL`, same
  reasoning and same mechanism as `saved_word_contexts.vocabulary_id`: a
  training signal is not owed a favour to the row it came from, and
  `lemma` is copied onto the log so it still means something once the
  pointer goes null.
- **`vocabulary.save` fills a new word's `pos`/`lexeme_sense_id` once, at
  creation, from the entry that caused it** (P4: `meaning_core_*` are dead
  and no longer filled at all — see "A saved word is a sense, not a
  spelling" above). A second save of the SAME SENSE from another material
  never touches the word row again; only the context list grows. A save of
  a DIFFERENT sense sharing the lemma is a different word entirely.
- **`Mastered` and `Learning` are a partition, computed in Python over one
  query** (`_totals`), not three separate counts — `known` status OR
  `passive_stability ≥ 21` days (`MASTERED_STABILITY_DAYS`) is `mastered`;
  `suspended` is its own bucket; everything else is `learning`. The one
  case that needs the two columns looked at together is a suspended word
  stable enough to also qualify as mastered, which counts as mastered.

## Vocabulary practice (stage 2) — the ladder, leech, and the distractor pipeline

Stage 2 adds the remaining exercises, both directions, and everything that
follows from a learner actually using the module for weeks: a leech, a
30-day set-aside, "I know this". `practice.py` stays the only importer of
`fsrs` — everything below that builds a recognise item's four OPTIONS lives
in `distractors.py` instead, because that pipeline touches no card at all
and is exactly the piece expected to be re-tuned once real sessions are
watched.

- **The ladder is a stored level, not a derived one, named `PASSIVE_LADDER`/
  `ACTIVE_LADDER`** (`app.models.vocabulary`) — `("recognise", "recall")`
  and `("recognise", "produce")`, in TEXT matching `EXERCISE_TYPES` exactly,
  never a bare integer: the brief's addendum replaced an earlier single
  shared "level 2" for exactly this reason, since one number would mean
  "recall" for one direction and "produce" for the other. `passive_level`/
  `active_level` (null = not started) say which TASK is currently served;
  FSRS still schedules the card exactly as stage 1 does, with no penalty of
  its own. `_apply_ladder` moves a word by ONE STEP OF THE LADDER'S OWN
  INDEX (`_ladder_for(direction).index(planned_exercise)` ± 1), not a
  hand-written floor/top special case, so a ladder gaining a middle rung
  later is a one-line change to the list. Promotion at the floor needs 2
  consecutive corrects — or 1, if the word has ever been at the top rung
  before (a re-promotion after a demotion should not cost what the first
  promotion cost). Demotion is a single Again at the top rung; `close`
  (Hard on `recall`, Good on `produce`) never demotes, because a demotion
  is the ladder's judgement about the TASK, not FSRS's about the schedule,
  and a spelling slip is not evidence the task is too hard. Both are read
  from `vocabulary_review_logs.planned_exercise`
  (`_promotion_streak`/`_has_reached_level`), which is what the ladder
  actually asked for, not `exercise_type` (what was served) — so a
  distractor-pipeline fallback answered correctly still counts as evidence
  for promotion, and a fallback answered wrong still counts as a miss at
  the floor. A `planned_exercise IS NULL` row — a known-check answer or a
  verified same-session requeue, neither of which is the ladder's own
  evidence about a level — is SKIPPED by both functions rather than read as
  "a different level": skipping it neither breaks a genuine streak sitting
  either side of it nor ever counts as "reached".
- **Passive `recognise` is the bare English word, never a marked
  sentence.** `_choice_item` sends empty `before`/`after` for BOTH
  directions and `target = word.lemma` for passive only (active leaves
  `target` empty too, since it shows only `shown_meaning_uz`) — the brief's
  "ingliz so'zi, ostida 4 ta ta'rif" has no sentence in it at all.
  `resolve_mark` (surface, then lemma, in the sentence — the same search
  `resolve_gap` uses) still exists and is still used, but only for the
  leech card's `leech_context` below; it no longer builds the recognise
  prompt.
- **A same-session requeue is verified against the log, not trusted, and
  earns the ladder nothing a second time.** After an `Again` the client
  re-shows the SAME item at the end of the session rather than jumping to
  whatever the ladder now serves (`PracticeAnswerIn.requeued`). `_last_log`
  must show an `Again` at exactly this `exercise_type`, within
  `REQUEUE_WINDOW` (6 hours) — otherwise 422, since a client that could
  claim `requeued` freely could dodge the ordinary "exercise_type matches
  the planned level" check on any answer. A verified requeue logs
  `planned_exercise = NULL` — never `exercise_type`, which would forge the
  same "this word has reached that level" evidence a genuine ladder
  serving leaves, for a level this answer never actually earned — and
  skips `_apply_ladder` entirely: it is graded by FSRS exactly like any
  other answer (a genuine new lapse still counts towards leech), but it is
  not fresh evidence about the TASK, because it is the SAME task the
  learner already failed once this session. `_promotion_streak` and
  `_has_reached_level` both skip a null-planned row rather than reading it
  as a different level, and null also keeps it out of the fallback metric
  below (`planned_exercise IS NOT NULL AND planned_exercise !=
  exercise_type`) — a requeue is neither the ladder's plan nor a fallback,
  so it is measured as neither.
- **The active card starts only once the passive one has earned it.**
  `direction: "both"` AND passive stability ≥
  `ACTIVE_UNLOCK_STABILITY_DAYS` (21, the same number as
  `MASTERED_STABILITY_DAYS` for a different reason, kept as its own name so
  a future change to either does not silently move the other) — a learner
  can only produce from nothing what they can already recognise without
  hesitation.
- **Turning `direction` back to `passive` PAUSES every active card, not
  only new unlocks.** `_gather_candidates` is the one place that decision
  is made: `active_enabled` (`direction == "both"`) gates BOTH
  `_active_due_words` and `_active_unlock_candidates`, so while it is false
  no active card — running or not — enters `due` or `new`, and none can be
  answered this session. Nothing is written to pause one: no FSRS field,
  no `active_level`, no reset, which is what makes resuming (`direction`
  back to `both`) restore a card exactly where it was rather than from
  wherever a pause routine last saved it. `_active_due_words` and
  `_active_unlock_candidates` themselves stay unconditional on purpose —
  they answer the plain fact "which active cards exist/qualify" for every
  caller, including `active_in_progress_count` (the settings screen's own
  "N words are being practised actively — they'll pause, not reset," and
  `SavedWordOut.active_paused` on the words list and word page, both true
  exactly when an active card has started and `direction` is currently
  `passive`). `record_answer` does not add this gate: a card already
  fetched before a mid-session settings change may still be answered: the
  gate is about what a NEW queue offers, not about refusing an answer the
  client already holds.
- **A word never appears twice in one session.** `_gather_candidates`
  de-duplicates by word across passive-due, active-due, active-unlock and
  passive-new in one pass; when both directions are due for the same word,
  the more overdue one wins. Order is reviews (most overdue first), then
  new active unlocks, then brand-new words — the brief's own ordering,
  because an unlocked active card is closer to being forgotten than a word
  never met at all.
- **A forced `mode` filters candidates by their CURRENT level, before the
  budget runs.** It never skips the ladder — asking for `produce` shows
  nothing for a word still at active `recognise` — and it is exactly as
  forceful as the settings screen's own exercise type
  (`_effective_mode`), because the brief's "bugun faqat yozish" is meant to
  work either way.
- **The settings screen's exercise type is ONE choice, enforced at the
  schema.** `VocabularySettingsIn.exercise_types` is null (`Automatic`) or a
  list of exactly one of `recognise`/`recall`/`produce`
  (`min_length=1, max_length=1`) — never a subset, so two or zero entries
  are a 422 at the door rather than silently narrowed to the first. The
  mapping onto candidates needs no separate table: `recognise` matches a
  `recognise`-level candidate in EITHER direction, `recall` only ever
  matches passive (the active ladder has no `recall` rung) and `produce`
  only ever matches active, which falls straight out of the two ladders'
  own shapes.
- **Distractors come only from `material_vocabulary`, never from the
  learner's own list** — two learners' vocabularies would otherwise leak
  into each other's multiple-choice options, and a learner's list is
  exactly the words they do NOT know well, the worst possible source of a
  plausible wrong answer. The filter, in order: same `pos`; CEFR within one
  level (unrated only against unrated); the word's own source material(s)
  sort first, then the public/unhidden catalogue; the word's own lemma is
  excluded, and so is any candidate sharing a `learning`-status lemma's
  FAMILY (first 5 characters, shorter lemmas compare exactly — `emerge`
  excludes `emergence`, because being quizzed on telling apart a word
  family you are mid-way through teaches confusion, not the word); the
  similarity guard drops a candidate whose definition shares ≥ 2 content
  words with the right one (two phrasings of the same idea is a second
  correct answer, not a wrong one) and drops exact duplicates of an
  already-chosen option. All five thresholds are named constants in
  `distractors.py` on purpose — they are expected to move once fallback
  frequency is actually measured.
- **A fallback is a substitution forward, never a worse prompt.** Too
  short a right definition (< `MIN_DEFINITION_WORDS`) or too few surviving
  distractors (< `MIN_DISTRACTORS`) serves this encounter as `recall`
  (passive) or `produce` (active) instead — the stored ladder level does
  not change. It is measurable on the wire and in the log for exactly this
  reason: `PracticeItemOut.planned_exercise != exercise_type` on the item,
  `planned_exercise IS NOT NULL AND planned_exercise != exercise_type` on
  the logged row, IS the definition of a fallback, not a second flag that
  could drift from it — the `IS NOT NULL` matters once a row can be logged
  with no plan at all (a known-check answer, a verified requeue: neither
  is a fallback, and neither is the ladder's plan either), and
  `logger.info` at session build carries the reason
  (`short_definition`/`too_few_candidates`) so the guard's thresholds can
  be raised once fallbacks turn out to be frequent.
- **`record_answer` trusts nothing about the ladder that the client sent.**
  `planned_exercise` is accepted on the wire but its VALUE is never read —
  a client that could name its own would be able to plant a fabricated log
  row claiming a word "has already reached" its top rung
  (`_has_reached_level`), buying every later real promotion the cheap
  1-correct re-promotion price. It is recomputed from the word's own
  stored level every time, and `exercise_type` is checked against THAT:
  the only exercise accepted is the level itself, or — at the floor
  (`recognise`) only — the one fallback `FALLBACK_EXERCISE` names for this
  direction; anything else is a 422. `direction: "active"` is refused
  unless the active card has already started or the unlock gate is met
  RIGHT NOW, and `claim_known` is refused unless the word's passive card
  has never been practised — both are the server re-checking, at answer
  time, exactly the gates a forged request would otherwise skip past.
- **An option's id gives nothing away.** `HMAC-SHA256(app secret,
  f"{word_id}:{text}")`, truncated to 16 hex — deterministic in the word
  and the option's own text, so grading a choice is recomputing the RIGHT
  option's id and comparing (`grade_choice`), with nothing about which four
  were shown ever stored server-side, and nothing about which is correct
  derivable from the four ids themselves.
- **"I know this" is a bypass of the ladder, not a step on it.** Offered
  only on a brand-new word (never practised); the one follow-up is always
  `recall`, regardless of what level the ladder would otherwise be at (it
  is not asked yet), and is logged with `planned_exercise = NULL` and skips
  `_apply_ladder` entirely — pass OR fail, since a wrong known-check answer
  is still an answer AT `recall` and would forge the same "reached the top
  rung" evidence a correct one would. Correct rates the card `Easy` and sets
  `known` outright — a stronger signal than an ordinary correct answer, because
  the learner asked for it by pressing a button rather than the scheduler
  inferring it. Anything else grades exactly as an ordinary recall answer
  and the word stays in rotation: an unreliable self-assessment ("I know
  `bank`" from someone who only knows the financial sense) must cost
  nothing if it turns out to be wrong.
- **A lapse, for leech purposes, is reconstructed from the log's state
  chain, not stored as its own flag.** `VocabularyReviewLog` keeps the
  POST-answer state; a card's state entering answer N is exactly what
  answer N−1 left it in, so walking the log in order and remembering the
  previous row's `state` recovers "was this a Review-state Again" with no
  extra column (`_lapses_since_reset`). Only genuine lapses count —
  learning-phase misses never do, per stage 1's own rule.
- **Leech trips on EITHER of two thresholds, since the last reset:** 6
  lapses ever, or 4 within 14 days. Two separate constants on purpose — a
  word wrong six times over a year and one wrong four times in a fortnight
  are different problems, and the second is the one actually costing a
  learner their week; one threshold would miss it for months. A leech word
  is never auto-suspended — it is excluded from every queue
  (`EXCLUDED_STATUSES`) until the learner makes one of three choices
  (`resolve_leech`): "set aside" is the only one that actually leaves
  rotation (`suspended`, `suspended_until = now + 30d`); "see it where you
  met it" and "keep practising" are the SAME mutation (status recomputed,
  `leech_reset_at = now`, level UNCHANGED — seeing the sentence again is a
  reminder, not practice) because the difference between them is only which
  screen asked, not a fact the server needs to remember.
- **`became_leech` carries its own `leech_context`, built once, at the
  moment it fires.** The word's newest `SavedWordContext` that actually has
  a sentence (`_newest_context_with_sentence`; `None` when it has none, per
  the brief's "null if none") is marked with `resolve_mark` — the same
  before/target/after shape `PracticeChoiceOut` would have used for a
  sentence-marked prompt, so the client has one rendering rule for "the
  word, marked, inside a sentence" — plus the material's id and title. This
  is the ONE place in stage 2 a leech word's context is resolved for the
  client; the leech-choice endpoint that follows does not repeat it.
- **Per-direction lapse counts are a lifetime count, not the leech
  window's.** `lapse_counts_for` walks the same log state-chain as
  `_lapses_since_reset` but with no `leech_reset_at` cutoff, because the
  word page reports the word's whole history and a reader has no reason for
  that number to reset out from under them the moment a leech is resolved.
  `passive_lapses + active_lapses` on one word therefore always adds back
  up to `SavedWord.lapses`, the column that already combines both
  directions. Batched over every word a listing needs in one query (the
  words list calls it once, not once per row) for the same reason
  `titles_for` is batched.
- **"Set aside" resolves lazily, in every query that would otherwise touch
  the word — no worker.** `_reap_suspensions` runs at the top of `summary`
  and `build_session` and fixes up anything whose `suspended_until` has
  passed before the rest of either function reads `saved_words`, which is
  what makes a 30-day return "automatic" without anything sweeping for it
  on a timer.
- **Bulk actions are scoped to the caller by the query itself, not by a
  check afterwards.** `known`/`suspend`/`restore` are a plain column write
  over whichever of the requested lemmas `SavedWord.user_id == user_id`
  actually matches; `forget` is delegated to the stage-1 function one lemma
  at a time because it has its own contexts-then-word delete order to
  preserve. A lemma someone else owns is silently not theirs to change,
  the same shape as the word page's 404: neither confirms that a word
  exists for anyone but its owner.

## The admin review queue orders by exposure, not by flag type (A1)

2,476 `needs_review` senses is twenty hours of one person's work -- a queue
that never empties. `app.services.lexicon_review` orders it by how many
learners have actually MET a sense rather than by which flag it carries: a
wrong meaning nobody has read is free; one a thousand students have already
seen is the whole reason the tab exists.

- **Reported still leads, unconditionally.** A learner who filed "this is
  wrong" has already done the finding a reviewer would otherwise have to
  do, which outranks any exposure count.
- **Everything else is ONE list**, `needs_review` senses and the unapproved
  core bucket together, ordered by `exposure` descending; a `needs_review`
  sense breaks a tie ahead of an unflagged one, and `material_count` breaks
  anything still tied after that. `reason=` still narrows which rows are IN
  the list; it no longer changes how the list sorts.
- **`exposure` is a plain, unweighted sum of three counts** -- distinct
  users who submitted an attempt on a material glossing the sense, how
  many `lookup_events` resolved to it (a plain count, not distinct users:
  repeats say something too), and how many `saved_words` point at it
  (already one per learner). No weights: the three are added, not scored
  against each other. `material_count` (distinct materials glossing the
  sense) is a SEPARATE column, never folded into `exposure` -- "how many
  materials" and "how many people" are different questions, and the second
  is what the ordering is for.
- Computed as grouped subqueries joined once per page (`lexicon_review
  .queue`) or once per sense (`exposure_for`, used by `approve`/`fix`'s own
  response) -- never once per row. `ix_attempts_material_id_status` keeps
  the attempters subquery's join+filter an index lookup, and
  `ix_lookup_events_material_id_lemma` does the identical job for the
  lookups subquery's own join on `(material_id, lemma)` -- both alongside
  `needs_letter_hint` in the same migration.

## Recall's definition cue: masked, sometimes a fallback, sometimes hinted (B)

`practice.resolve_gap`'s `Gap` now always carries an English definition
cue, shown above the sentence, smaller and dimmer than it -- a cue, not the
question. Grading, the ladder and the direction are all unchanged; only
what the PROMPT shows moved.

- **The cue is masked on BOTH kinds** (`practice._mask_definition`)
  wherever it would otherwise write the answer out: the lemma, the
  sentence's own inflected surface, and (`practice._matches_lemma_family`)
  any word sharing a 5-character-or-more lemma's first five characters --
  deliberately wide enough to over-mask a derivational relative
  (`state`/`statement`) rather than under-mask a real giveaway. A lemma
  UNDER five characters uses the narrower "exact or plain inflectional
  ending" rule instead, so `run` masks `runs`/`running` but not
  `rune`/`rung`, which merely start the same way (including the `y` ->
  `ies`/`ied` case the plain suffix table misses on its own: `cry` masks
  `cries`/`cried`, not only `cries`/`crying`). A `definition`-kind gap (no
  sentence at all -- the definition IS the whole prompt) is masked too, the
  answer there being the bare lemma -- a dictionary gloss commonly contains
  the very headword it defines ("to undertake..." defining `undertake`),
  and leaving that ONE kind unmasked would write the answer out beside the
  gap asking for it exactly as surely as an unmasked sentence-kind cue
  would. A PHRASAL or hyphenated lemma/surface (`give rise to`,
  `tip-of-the-tongue`) is masked twice over: as a whole phrase, wherever it
  is named that way in the definition, AND word by word
  (`practice._phrase_components`, split on whitespace or a hyphen) against
  every OTHER family match in the text -- `_matches_lemma_family` has only
  ever known how to judge one word at a time, so a phrase is nothing more
  than asking it that question once per word it is made of, on top of the
  whole-phrase pass.
- **The readability guard is a fallback, not a refusal, and runs on EITHER
  kind now.** Masking a passive `recall` item's definition down to fewer
  than `READABILITY_MIN_REMAINING_WORDS` words, or past
  `READABILITY_MAX_MASKED_WORDS` masked, serves this ONE encounter as
  `recognise` instead (`practice._passive_recall_or_readability_fallback`)
  -- the ladder's own plan stays `recall`, which is what makes the
  substitution measurable the identical way a distractor-pipeline fallback
  already is (`planned_exercise != exercise_type`), and what
  `record_answer`'s authority check accepts it as
  (`READABILITY_FALLBACK_EXERCISE`, the mirror image of `FALLBACK_EXERCISE`
  -- that one only ever substitutes something HARDER, this one only ever
  substitutes something EASIER). If the distractor pipeline can't build a
  `recognise` item either (too few candidates), this falls all the way back
  to serving `recall` with the masked definition anyway -- a fallback is a
  substitution forward when one is available, never a reason to refuse the
  encounter. The SAME thing happens in the other direction: when a
  `recognise`-level item's OWN distractor pipeline comes back empty and
  `_build_item` falls back to passive `recall` (`FALLBACK_EXERCISE`, the
  harder substitution), the guard is still checked against that `recall`
  prompt's masked definition and logged if it would have tripped -- there
  is nowhere further forward to fall to (recognise already failed), but the
  reason is worth counting all the same. Logged through the identical
  mechanism a distractor-pipeline fallback already uses (`logger.info(
  "vocabulary distractor fallback", ... reason=...)`), with its own reason,
  `definition_unreadable`, so all four fallback shapes are counted the same
  way.
  **`record_answer` re-verifies this ONE fallback, unlike the harder one.**
  A `recognise` claim against a word planned at `recall` is accepted on the
  wire only after the server recomputes `resolve_gap` for this word and
  context and checks `_needs_readability_fallback` on it again, 422ing if
  the guard would not actually have fired -- the harder distractor-pipeline
  fallback needs no such re-check (forging it buys a client nothing, since
  it only ever asks for something harder), but this one moves to an EASIER
  exercise, and trusting the claim alone would let a client serve itself
  `recognise` any time the ladder asks for `recall`. Same shape as the
  `requeued` re-verification below it.
- **The first-letter cue is conditional on `LexemeSense.needs_letter_hint`**
  (`app.services.lexicon_hints`) -- true when another LEXEME's sense shares
  this one's `oewn_synset_id`, or carries a near-identical `definition_en`
  (token-set Jaccard >= `lexicon_hints.NEAR_IDENTICAL_DEFINITION_JACCARD`,
  a named constant on purpose). A hint only narrows a genuine guess; a word
  with nothing else in the catalogue to be confused with has no guess to
  narrow, and showing the letter anyway only leaks the answer.
  `sense=None` (a caller with no sense loaded) reads as "unknown, so no
  hint" -- the safer default. Computed by a full backfill
  (`scripts/backfill_letter_hint.py`, `lexicon_hints.recompute_all`) and,
  incrementally, by the worker's own enrichment loop
  (`app.worker._lexicon_enrich_once`, `lexicon_hints.recompute_for_lexemes`)
  for whichever lexemes it just re-enriched. The incremental call does NOT
  load the whole catalogue to judge a handful of lexemes: it loads their
  own senses (the seed rows) and then only OTHER senses that could
  possibly match one of them (`lexicon_hints._load_candidate_rows`) --
  sharing one of the seeds' own OEWN synsets, or containing one of their
  definitions' own (stemmed) content words as a substring, run as a query
  rather than the in-memory inverted index `_compute_flags` builds for a
  full backfill. Nothing outside that candidate set could have flipped
  either check for a seed row (a Jaccard match cannot exist without a
  shared content word, and a stem -- `app.services.distractors._stem`
  only ever strips a suffix -- is always a literal prefix of the surface
  form it came from), so the touched senses' own flags come out identical
  to what a full backfill would give them. It still only WRITES the senses
  it was asked about, the same documented gap `app.services.lexicon
  .link_row` already accepts for its own one-row-at-a-time merge rule: the
  OTHER side of a newly-formed match is caught by the next full backfill,
  not this call.
- **"I know this" still always shows the definition too** -- it is an
  ordinary `recall` item under the bypass (`practice
  .build_known_check_item` calls the same `resolve_gap`), never routed
  through the readability guard, because its one follow-up must always
  BE `recall` (`record_answer` refuses anything else for a `claim_known`
  answer) -- there is no easier exercise for it to fall back to.

## Browse is not practice, and writes exactly one column (C)

Browse (`POST /vocabulary/words/{id}/browsed`, `app.services.vocabulary
.mark_browsed`) is flipping through saved words with nothing to grade --
the stage-1 decision against self-graded FSRS ratings holds, and a
flashcard mode that fed one back in would be exactly the "I know it / I
don't" the brief already refused. It writes `SavedWord.browsed_at` and
NOTHING else: no `VocabularyReviewLog` row, no FSRS card touched, no `due`
moved, nothing counted in daily minutes. Owner-only, 404 for a word id that
is not the caller's -- the same shape as every other by-id word route.
Filtering, ordering and the card UI all live in the frontend, over the
saved-words list this module already serves; the backend's only new
surface for Browse is this one column and this one endpoint.

## Two difficulty measures, and they do not merge

`cefr_level` is the model's, sees the context, and is the better figure for
ONE word — `bank` is B1 financially and C1 geologically. It is what the
learner is shown. It also drifts from material to material, so an average of
it cannot be compared with another average of it.

`frequency_band` is from the lists alone, identical across the whole
catalogue, and never shown to anybody: "NGSL rank 2400" is a fact about a
corpus. It is what the arithmetic uses.

**Do not average them into one "difficulty".** The two disagreeing is itself
the signal worth having: a frequent word rated C1 is being used in an unusual
sense, and unusual senses are where an IELTS passage lays its traps. That
disagreement has its own column, `material_vocabulary.unusual`, rather than
being derived at read time — `frequency_band == "core" AND cefr_level ==
"C1"` identifies exactly those rows today, but only because the candidate
filter drops everything under NGSL rank 2000, so it is a rule holding by
accident of one constant.

It stays on the server. What a client is shown instead is `sense_differs`,
which asks the same question of EVERY entry rather than only of the common
ones: a rare word in an unexpected sense is just as much of a trap and
`unusual` was never marking it. Two near-identical flags on the wire is how
one of them stops being maintained, so only one travels.

`material_difficulty.vocabulary_load` is the one column in that table that is
not a function of the attempts — it is a function of the TEXT, written by the
passage importer, and `recompute` reads it and never writes it. Listing it in
that upsert's `set_` would blank it on the worker's next pass. Below
`MIN_ANSWERS` it gives a band instead of `New`; at twenty answers the
measured proportion correct takes over and the estimate is gone.

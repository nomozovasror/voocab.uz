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
- **A live lookup has three outcomes, and they are not interchangeable.**
  `dictionary.look_up` returns a `Gloss`; returns `None` only when a model
  replied `{"lemma": ""}` ("no meaning" -- ends the chain); and RAISES
  `Unanswered` when every provider raised or sent an `UnusableReply`
  (logged, chain moves on). The scale is A1-C2 (`dictionary.LEVELS`); on
  `Unanswered`, `_generate` falls back to `_from_lexicon`: lemma or the
  tapped form reduced as `_by_string` does, never a proper noun/function
  word, the most-used sense (`oewn_count`, any POS) with both meanings and a
  level, written through the same path (`link_row`, then pinned to THAT
  sense) and logged `source="lexicon"`. `_generate` returns
  `(entry, source)`. Rows at A1/A2 (`dictionary.EASY`) are written
  `hidden`; `entries_for_reader` adds back, for the tapper only, hidden
  A1/A2 rows of lemmas in their `lookup_events` for the material (not
  proper nouns/function words). `meaning_core_*` stays unwritten (P3):
  they are set only to feed `link_row` and cleared before the add.
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
- **A referenced sense is never deleted by a re-run.** `load_works` fills
  `LexemeWork.referenced` with the sense ids a `word_list_entries` row or a
  `saved_words` row points at; `plan_senses` keeps one like OEWN's top
  sense instead of deleting it as an unused deep OEWN sense (the FK has no
  ON DELETE: the delete failed, and the worker re-ran the same batch for
  ever). When a sense IS merged into another, `apply_work` repoints
  `word_list_entries.sense_id`/`lexeme_id` (`_repoint_word_list_entries`)
  along with material rows, translation reports and saved words.
- **One failing lexeme never stalls the queue.** `worker._lexicon_enrich_once`
  retries a failed batch lexeme by lexeme, and backs a failing lexeme off
  (1h doubling to 24h, in-memory `_enrich_failures`, logged at ERROR); the
  selection skips backed-off ids.
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
- **A prefix-share threshold was measured on 2026-10-07 and rejected.** The
  five-character rule over-masks words that merely begin alike (`after` in the
  definition of `afternoon`), so requiring the shared prefix to be a share
  (60%) of the word was tried on the whole dev lexicon. Against the SHORTER
  word it changes little and cannot help `after`/`afternoon` (the start of the
  lemma is 100% of the shorter word) while unmasking real relatives
  (`abolition`/`abolishing`, `organisational`/`organization`). Against the
  LONGER word it unmasks genuine giveaways (`creativeness`/`create`,
  `waterproof`/`water`). The documented over-masking is the safer error, and the
  readability guard below already covers the extreme cases, so the rule stays
  as it is.
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

## Word lists: a source, not a store

Five curated lists (`word_lists`: core, business, academic, medical, toeic),
their cards (`word_list_entries`) and who started which (`user_word_lists`).
`services/word_lists.py` reads and feeds them; `practice.py` consumes them.
A list is NOT a `Deck` (a deck is the learner's own grouping of words they
already hold).

- **Subscribing is not adding.** `start` writes one `user_word_lists` row and
  nothing else. A 1,700-word list as 1,700 `SavedWord`s would put every
  never-practised word in the queue, make the time-budget's new-word maths
  meaningless (the thing it exists to prevent) and leave the learner feeling
  they cannot go back. A `SavedWord` is created only when the learner first
  ANSWERS a list item (`record_answer(list_entry_id=...)`): any answer, with
  "I know this" passed = created `known`, failed = created in rotation. A card
  that is merely shown creates nothing. `stop` (`active=false`) is safe: owned
  words stay, unpresented entries stop coming.
- **The session** (`_gather_candidates`): the learner's own saved-never-
  practised words take the new slots first; the rest go round-robin over
  ACTIVE lists (earliest started first), each in `rank` order; an exhausted
  list's turns go to the others; a sense the learner already owns (any route)
  or another list already took in this batch is skipped. Candidates are
  capped at what today's time could buy (`_list_limit`), so `new_available`
  never reads "1,700". Not offered in a material-narrowed session or in a
  mode other than `recognise`/`auto`. A list entry's `SavedWord` is
  TRANSIENT until answered; its id is `list_word_id(user, sense)` (uuid5) so
  option ids hashed before the word exists grade correctly after. Later
  answers (requeue, leech) name the word by `word.word_id`.
- **Why the sense is per list.** `discharge` is the end of someone's
  employment to Business, the release of a patient from hospital to Medical,
  and "pour forth or release" to Academic; `equity` is shareholders'
  ownership to Business and `proxy` their voting document, where the
  lemma's usual first sense is a property's value and a person acting for
  another. (The domain lists leave out NGSL words by design, so `security`,
  `interest` or `culture` are Core-only, with Core's one sense.)
  `word_list_entries.sense_id` is the sense THIS list means; Core takes the
  lemma's most SemCor-tagged synset across parts of speech (`lexicon_enrich
  .top_sense_any_pos`; a model picks the pos when the counts tie -- among
  each pos's top sense, else over every sense as the domain lists do -- and
  the rank-1 sense of the primary lexeme stands only where OEWN lacks the lemma),
  domain lists choose by a model request (the build job,
  `word_lists_build`; every decision is in `app/data/word_lists/decisions.jsonl`).
  Progress `owned / total` therefore counts entries whose SENSE the learner
  holds by any route (a material save, another list, this one).
- **An example is not a meeting.** A word with no `SavedWordContext` of its
  own (every list word, and any context-less saved word) may be practised on
  a sentence from a non-hidden `material_vocabulary` row of a PUBLIC material
  (`_corpus_example`). It is built as a transient context
  (`_fallback_contexts`), never added to a session: never a
  `SavedWordContext`, never `vocabulary_review_logs.context_id`, never
  `word.material_id` on the reveal (that is "You saw this in"). The prompt
  carries `example_source` ("Example from <title>") instead. The choice is
  deterministic so the answer re-derives the very sentence the prompt showed.
  No sentence anywhere = the existing masked-definition path.
- `origin_list_id` is analytics only; nothing reads it to decide anything
  except that a list-origin word with no sentence still gets its sense's CEFR
  for distractor selection.
- Refusals (`entry_for_answer`): 404 unknown entry, 403 list not active for
  this learner, 409 sense already owned; a refused answer (e.g. 422) creates
  no word, because the row is flushed but committed only with the answer.

## Every sense of the word: lookup and word page (`lemma_senses.py`)

The popover and `/vocabulary/words/:id` list EVERY `LexemeSense` we hold for
the lemma, so a wrong pick reads as an ordering instead of a wrong answer.
Practice, the saved list, `needs_review` and "this translation is wrong" are
unchanged (one sense).

- **Which senses:** every lexeme of the lemma (all POS), minus
  `is_proper_noun` / `is_function_word` lexemes (the anchor's own too) and
  senses with neither definition nor Uzbek. Not every OEWN synset: we have
  no Uzbek for those.
- **Order:** the anchor sense first overall (`used_here` in the lookup, the
  learner's `saved` sense on the word page); then the anchor's POS group,
  then other groups (best SemCor count first, then n/v/adj/adv); inside a
  group by our `sense_rank`, which IS the easiest-first order (next bullet).
  `lemma_senses._sense_key` no longer re-sorts by SemCor: two orders in two
  places was how `college` listed "faculty and students" (C1) above the
  institution (A2).
- **Sense order is easiest first, in ONE function**
  (`lexicon.sense_order_key` / `order_senses`): CEFR A1..C2 ascending (none
  last), then SemCor `oewn_count` descending (none after any count), then the
  sense more material rows use, then the rank it had. `sense_rank` stores it and
  `Lexeme.cefr` copies rank 1, so a word's level is its basic meaning's. A
  lexeme none of whose senses has a level (a name) is left in its order. Every
  writer that adds or reorders senses uses it, and ONE helper keeps it true:
  `lexicon.rerank_lexemes(session, lexeme_ids)` orders by the rule from the
  senses' current order (`tie_ordered`: rank, creation, id), renumbers 1..n,
  sets `Lexeme.cefr` from rank 1 (a name keeps none) and brings the RANK-1
  property `ngsl_conflict` in line (the old rank 1 loses a stale flag, the new
  one is evaluated). Called by: the CALD apply/restore (`_recompute_lexeme_cefr`,
  hence the worker hook too), Studio's `fix_and_approve` when a level changed
  (after the approval stamp), the AI review's `undo`, `word_lists_build
  .write_new_sense`, and every restructure op that adds, moves, drops or
  re-levels a sense (`_rerank`; journaled, `_capture_lexeme` holds all the
  senses) plus `rerank_senses`. `lexicon_enrich.rank_senses` applies the same
  key to a freshly planned lexeme (`clone()` copies `sense_rank`, so the old
  order is the tie-break; the older used/OEWN/model rule only when nothing is
  graded).
- **The flag follows rank 1, and approvals are never touched.** A reason is
  added to an approved sense too, but `needs_review` is raised only on an
  unapproved one. A stale reason is removed from an UNAPPROVED sense only (on an
  approved one it is the audit trail `status` counts, as everywhere else); when
  the last reason goes, `needs_review` is cleared unless a learner's report is
  open. Consequence to know: a CALD restore or an AI-review undo gives the
  levels back but not the old ORDER -- the lexeme is re-ranked by the rule.
- **What else reads the order**, checked: the review queue's core bucket and
  `fix_and_approve` (rank 1 = `Lexeme.cefr`; follow the rule), `word_lists_build`
  (display sort by `sense_rank`), export/heteronym/recording scans (order only
  for stable output). NOT changed on purpose: `vocabulary._from_lexicon` (the
  lookup fallback picks the most-used sense by SemCor count: a selection, not
  a display order), `lemma_senses` POS-group order and labels (counts),
  practice and distractors (they take the saved sense, not a rank), and
  `apply_work`'s fallback target for a dropped deep OEWN sense, which is the
  most SemCor-tagged sense (rank 1 is the easiest now, not the commonest).
- **Labels come from COUNTS, never ranks** (`LexemeSense.oewn_count`, a
  persisted copy of the extract's SemCor `count`; rank 2 can be 20 against
  25 or 1 against 25). Relative to the word's top count across the lemma's
  held senses: equal -> `most common`; `count*4 >= top` -> `common`; else
  `less common`. NO label (null) when the sense has no count (model sense,
  not backfilled) or the whole word has top 0. The label is still sent on the
  anchor sense; the client shows `used here` instead. No number or
  percentage ever reaches the wire.
- **Every writer of `oewn_rank` writes `oewn_count` beside it**
  (`lexicon_enrich`, `word_lists_build`, `lexicon_cleanup`). Rows written
  before the column: `uv run python -m scripts.backfill_oewn_count`
  (`--dry-run` first); idempotent.
- **One query per request** (`senses_for`): the lemma set is a subquery over
  the anchors' lexeme ids. Never call it per entry. Wire: `senses` on
  `VocabularyEntryOut` (lookup + `GET /materials/:id/vocabulary`, items
  `used_here`) and on `SavedWordOut` (word detail only, items `saved`;
  empty on the list/practice rows).

## CALD definitions (`lexicon_cald.py`, `scripts/cald.py`)

English definitions, CEFR and a fresh Uzbek come from the Cambridge Advanced
Learner's Dictionary where it has the meaning. The engine is
`app/services/lexicon_cald.py` (its docstring has the reasoning); the command
line is `scripts/cald.py`.

- **CALD text is NEVER committed.** The repository is public. Everything
  derived from the source -- index, match table, decision log, usage,
  reports -- lives in `app/data/private/cald/` (gitignored as a directory) and
  is backed up with `scripts/cald.py backup` to `~/voocab-dev-backups/`.
  Tests use invented entries only. A database dump now holds CALD text too:
  treat it as private.
- **The rules (agreed 2026-10-07).** A sense mapped `high`/`medium` takes the
  CALD definition (cross-reference markup cleaned), `low`/`none` keeps ours.
  A pointer-only CALD sense is followed one hop, else `none`. Two of our senses
  on one CALD sense both take it; `lemma_senses.arrange` lists an identical
  definition once WITHIN one part of speech (the anchor wins; nothing is
  relinked). A CALD per-sense level replaces ours (`cefr_source='cald'`, else
  `'ours'`), and the material
  rows of that sense take it too (`cefr_level_pre_cald` keeps theirs);
  `SavedWordContext` is untouched.
- **Far levels are checked twice (agreed after the full run).** (1) A
  mapping whose CALD level is 2+ bands from ours, either way
  (`VERIFY_BANDS`), is RE-VERIFIED: `JUDGE_MODEL`, twice with the two senses
  swapped, "is this the same meaning?" (`VERIFY_PROMPT`). `different` in
  either run, or `unsure` in both, makes it `none` -- old definition, Uzbek
  and CEFR stay, the reason is in the log; one run missing is `unverified`
  (not applied, asked again). The owner found narrower senses chosen
  (`crash` "cause to crash" -> a business failing). (2) The CEFR CAP:
  CALD's level is taken only within one band of ours (`CEFR_CAP_BANDS`) or
  where we have none; further away OURS stays (`cefr_source='ours'`),
  `cald_cefr` keeps CALD's beside it and the review reason `cald_cefr_far`
  sends it to Studio's queue (English Vocabulary Profile levels describe
  what learners PRODUCE: `glue`, `nest`, `tractor` come out C1/C2). Material
  rows follow the APPLIED level: untouched where the sense kept ours. An
  applied sense the plan later says `none` for is restored by `apply`.
- Every changed sense gets translation v2 and
  the comparison judge (`JUDGE_MODEL`, `gemini-3.7-flash`, twice, swapped);
  **loose keep: the old pair stays if EITHER run says old is better or new is
  wrong**, and when no run answered; identical text is not judged.
  `meaning_uz_material` is never touched.
- **A human decision LOCKS the sense (review fix, 2026-10-07).** A sense with
  `approved_at` set -- Studio's approve or fix, before or after the first
  apply -- is skipped by `apply` (also its re-apply branch, which has no drift
  check) and by `restore` (`--all` or `--sense-id`), reported as `locked by
  review`; the dry run counts it too. The check reads the ROW, not the
  plan's item: the approval may be newer than the plan. Its `needs_review` is
  never set either (an approved sense is not re-opened); for senses apply does
  write, `needs_review_pre_cald` keeps the old flag and `restore` puts it back.
  `fix_and_approve` on a CALD sense: a REWRITTEN definition makes
  `definition_source = 'human'` (`cald_ref` and the `cald` licence stay -- it
  began as dictionary text; locked like `cald`; the licences page still does
  not count it as OEWN); an approval or an Uzbek-only fix leaves it `cald`; a
  changed level turns `cefr_source` to `ours` (`cald_cefr` still shows the
  dictionary's, and the Studio chip appears only when it differs from `cefr`).
- **`definition_source` is whose TEXT the definition is** (`oewn`/`model`/
  `cald`/`human`); `source_id` stays where the SENSE came from (the synset still orders
  it and drives the letter hint). A CALD sense has licence `cald`. The
  licences page counts OEWN as `source_id='oewn'` minus CALD-defined senses,
  and has no Cambridge card (the owner's choice). Every writer that sets
  `source_id` sets `definition_source` beside it.
- **Nothing drifts back.** `lexicon_enrich` never touches a locked sense
  (`definition_source in LOCKED_DEFINITION_SOURCES` = `cald`/`human`;
  `Sense.locked`): not its definition, CEFR or Uzbek (`step_cefr`/translate
  skip it), not its `oewn_synset_id`/`oewn_rank`/`oewn_count`/`source_id`
  (restored in `plan_senses` step 5, so a matcher label cannot relabel it),
  never absorbed into another sense nor deleted as an unused deep OEWN sense
  (step 4: a locked sense that lost its rows STAYS, empty, `Sense.lost_rows`,
  and `apply_work` adds `lemma_merge` unless a human approved it), and
  `apply_work` writes neither its `review_reasons` nor `needs_review`. The
  one-off `scripts/lexicon_cleanup.py` commands skip or refuse such senses
  with a message (`retranslate`/`restore-retranslation`, `list-only`,
  `delete_lexeme`, `mark_proper`). `word_lists_build._held_sense` and
  `lexicon._find_or_create_sense` also match a sense by its
  `definition_en_pre_cald` -- the logs and the materials hold OUR wording --
  or every rebuild / new row would mint a duplicate.
- **The worker hook (`run_hook`, `run_sweep`).** After each enrichment pass
  the worker runs `lexicon_cald.run_hook` on the lexemes it finished (same
  decision log, nothing asked twice), and each loop `run_sweep`. Only where
  the private index exists (else one log line). Policy, all in
  `lexicon_cald._guarded`, all `settings.cald_*`: `cald_map_new_lexemes`
  (ON by default -- new lexemes are mapped automatically; also switches the
  sweep off; `tests/conftest.py` does for the whole suite, no test may reach
  the real API or the private log); a **hard failure** (HTTP 402/401/403, or
  a 429 that outlasted the client's own retries: `Gemini.hard_status`) stops
  the pass before the next request (`HookBudget.check`, so the per-item
  re-asks of `ask_map` are refused too), applies nothing, and pauses the hook:
  `cald_hook_cooldown_s` (300), doubling to `cald_hook_cooldown_max_s` (6 h),
  one log line entering the pause and one leaving it; a wall-clock timeout
  `cald_hook_timeout_s` (300; counts as a failure); a per-pass
  `cald_hook_pass_budget_usd` (0.50) and a per-day `cald_hook_daily_budget_usd`
  (3.00, UTC, from `usage.jsonl`'s `worker*` records) cap, logged when they
  stop it (not a failure). A mapped sense whose Uzbek no translator answered
  is NOT applied (`deferred (untranslated)`): applied, the hook would never
  revisit it. Approved senses are never asked about.
- **The sweep** (`sweep_unmapped`, every `cald_sweep_interval_s` = 30 min,
  `cald_sweep_batch` 25 lexemes, each tried at most `cald_sweep_max_tries` 3
  times per worker process, same cooldown/caps/timeout) retries what the hook
  left: map answers recorded as unanswered, mappings not yet applied, and
  senses nothing ever asked about -- a `word_lists_build.write_new_sense`
  sense goes into a lexeme whose `enriched_at` is already set, so the
  enrichment hook never sees it. An empty scan is remembered by a signature
  (candidate lexemes + decision-log mtime): the next sweep loads nothing until
  one changes.
- **Memory.** The index (~0.45 GB resident while loaded; its raw dict and the
  `pron` table are NOT kept, only the lookups) and the decision log (27 MB of
  JSONL, much more as Python objects) are loaded for ONE hook/sweep call and
  dropped when it ends (`gc.collect()`); nothing is cached between calls. The
  allocator keeps part of it afterwards (~0.15 GB measured on macOS) until it
  is reused. Loading takes under a second, which is why dropping is cheaper
  than keeping it resident in a long-lived worker.
- **What a re-levelled sense does NOT reach.** A NEW `material_vocabulary`
  row linked (`lexicon.link_row`) to a sense with `cefr_source = 'cald'` takes
  that level at link time (its own level in `cefr_level_pre_cald`, restored by
  `restore`). `hidden`, `unusual` and `vocabulary_load` are left as they are on
  new and old rows alike: they were derived from the row's own level and the
  apply never recomputed them.
- **Every answer is logged, keyed by what was asked** -- the candidates'
  CONTENT, not just their refs (a ref is a position in the source file).
  Items are built from a sense's `*_pre_cald` values once applied, so a re-run
  asks the same questions and `apply` is idempotent.
- **Everything old is restorable**: the first apply copies `definition_en`,
  `cefr`, `meaning_uz`, `meaning_uz_alt`, `licence`, `review_reasons`,
  `needs_review` into
  `*_pre_cald` (+ `cald_applied_at`); `restore` puts them back.
- **Commands** (from `backend/`): `index --source ~/Desktop/vocabulary`,
  `match`, `map --all`, `translate --v2 --all` (pointers, re-verify,
  translate, compare; `verify --all` runs the re-verification alone and
  writes `verify_report.txt`), then `apply` (a read-only dry
  run printing the summary) and `apply --confirm-db <name>` (writes; refuses
  unless `<name>` is the database `DATABASE_URL` points at). `restore --all |
  --sense-id <uuid> ... --confirm-db <name>` undoes it (never a locked
  sense). `recordings [--confirm-db <name>]` (phase 2b, "The audio layer"
  below): the human word recordings -- the index's per-block `pron` is read
  from the index file; the source directory must be on the machine. Model commands stop at
  `--budget` (USD, CALD total in `usage.jsonl`, default 25). Back up the
  database before `apply`, and `restore --all` before downgrading the
  migration.

## AI-assisted review of flagged senses (`lexicon_ai_review.py`, `scripts/lexicon_ai_review.py`)

2,619 `needs_review` senses are more than a person can read, so Claude reviews
them in batches (agreed 2026-10-07; pilot of 100 first). The module docstring
has the reasoning; the rules a later change can silently break:

- **Exports and reports are private.** Batches hold definitions: they live
  ONLY in `app/data/private/review/` (gitignored; the repo is public).
  `export` writes `<tag>_NNN.jsonl`, `<tag>_manifest.json` and
  `REVIEW_RUBRIC.md` there -- the rubric (a constant in the module, no
  dictionary text) is the reviewing agents' instruction sheet and the
  decision schema's documentation. Tests use invented senses.
- **A decision may change only** `cefr`, `meaning_uz` / `meaning_uz_alt` and
  (behind `--allow-material-fixes`) a material row's pos/sense link. Never a
  definition: it is not an accepted key. Unknown keys are rejected so a typo
  is not a silent no-op. Unsure -> `human`: nothing changes, the sense stays
  flagged and `LexemeSense.review_note` carries "Claude review (conf): note"
  (shown on Studio's row, `ReviewRowOut.review_note`).
- **Writes go through `lexicon_review.approve` / `fix_and_approve`** (they
  gained `commit=False`, and `fix_and_approve` a `meaning_uz_alt`), so a
  decision is exactly what Studio's button does: reasons kept as history,
  lexeme CEFR kept in step, `cefr_source` -> `ours` when a dictionary level is
  changed -- and `approved_at` set, which LOCKS the sense against
  `scripts/cald.py apply`/`restore` (`tests/test_lexicon_ai_review.py` proves
  it against `lexicon_cald.apply_plans`).
- **The approver is a system account** (`models.user.REVIEW_BOT_EMAIL`,
  display name "Claude review"), created by `apply` (never a dry run),
  idempotently. Inert: no password, no `auth_identities`, not admin, and
  `is_system_account` makes `get_current_user` and `/auth/refresh` refuse it
  even for a minted token. Studio shows `approved_by_name`.
- **Refuse rather than guess.** Rejected: not `needs_review` anymore ("already
  decided" -- a re-run is idempotent), approved by a person, `low` confidence
  outside `human`, and **a sense with an open learner report** (approving
  closes it; a learner is owed a person's answer -- only `human`, report
  stays open). Invalid decisions are skipped and listed; valid ones apply.
- **One transaction per run; every decision logged.** `lexicon_ai_reviews`
  keeps BEFORE and AFTER snapshots (sense fields, lexeme CEFR, moved rows).
  `undo` reverts a decision only if the sense still equals AFTER and (for an
  approval) is still approved by the account -- a person's later edit wins and
  is reported. The log row survives (`undone_at`); the sense can be decided
  again. `status` prints reason x outcome (`--list OUTCOME` names the senses).
- **Material fixes are off by default.** Studio has no action on a material
  row; the only existing mechanisms are pointer writes (`lexicon_enrich
  .apply_work`'s re-pointing, `link_row`). Two kinds only: `relink_sense`
  (another sense of the SAME lexeme) and `relink_lexeme` (an EXISTING lexeme
  of the same lemma; the row takes its pos). Nothing is created or deleted; a
  row's level follows `link_row`'s dictionary-level rule; undo needs every
  moved row to be as the run left it.
- **Where `lemma_merge` is recorded:** nowhere as such (the build script's
  merge map is in memory). The export derives it: the lexeme's material rows
  whose written `lemma` differs from the headword, with surfaces and whether
  that form has a lexeme of its own.
- **`export` is read only** (the connection is `READ ONLY`) and works on a
  database not yet migrated to `review_note` (the pilot was exported from one);
  `apply`/`undo`/`status` need the migration (`b1c4e7a09d52`).
  `lexicon_enrich` does not skip an approved sense by `approved_at` alone (only
  a `cald`/`human` definition source): a later re-enrichment of a
  non-dictionary sense can still re-translate it -- unchanged by this work.
- **Commands** (from `backend/`): `export [--reason R] [--sample N --seed S]
  [--exclude-file F] [--batch-size 150] [--tag T]`; `apply --decisions F
  [--confirm-db NAME] [--allow-material-fixes]` (dry run without
  `--confirm-db`); `undo (--all | --ids ...) [--confirm-db NAME]`; `status`.
  `--exclude-file` reads a JSONL's own `sense_id` per line (a batch names other
  senses of the lexeme; they are not excluded).

## Structural clean-up of the lexicon (`lexicon_restructure.py`, `scripts/lexicon_restructure.py`)

The AI review changes a sense's level or Uzbek; this changes the SHAPE: which
senses exist, which lexeme owns them, which material row points where. That is
destructive in a way a CEFR fix is not (a dropped sense takes saved words,
recordings and reports with it), so the engine is built around being exactly
reversible. The module docstring has the full reasoning; the rules a later
change can silently break:

- **Ops** (JSONL, `op` + `note`; unknown keys rejected, `_x` keys ignored):
  `merge_senses`, `delete_sense`, `delete_lexeme`, `merge_lexeme`,
  `rename_lexeme`, `mark_function_word`, `create_phrase` (alias
  `create_entry`; `pos` default `phr`, a word pos makes a single-word lexeme),
  `add_sense`, `relink_rows`, `delete_rows`, `set_sense` (cefr / Uzbek / `needs_review` of one sense; a
  change approves it as the review account, `needs_review: true` alone flags it
  for a person), and the no-ops `keep`, `skip`,
  `human` (the AI review's human path: `needs_review` + `review_note`).
  Files live in `app/data/private/restructure/` (gitignored: they hold lexicon
  data and the repo is public), next to the `run_<id>.jsonl` reports.
- **A dry run IS the run, rolled back.** Every op executes for real in one
  transaction, each in a savepoint, and the caller rolls it all back. Ops must
  be validated against the state EARLIER ops of the file leave (rows moved,
  then the now row-less lexeme deleted; a relink, then a merge); the only
  exact way is not to model it. Never give the dry run a separate code path,
  and never "optimise" it into a read-only one. A refused op is rolled back
  to its savepoint with its reason (`removed by op #N earlier in this file`
  for an id an earlier op deleted); later ops go on.
- **Stop the worker during a real apply.** `Journal.capture` takes
  `SELECT ... FOR UPDATE` on every row it records, which stops a concurrent
  writer from changing a row between the snapshot and the change, but not a
  worker from starting an enrichment or CALD sweep on a lexeme the file is about
  to rewrite. Run `apply --confirm-db` with the worker stopped.
- **One transaction per op, journal before commit.** `Journal` captures the
  rows an op may touch BEFORE it changes anything (by pk), and a
  `before_flush` hook raises `UncapturedWrite` for any ORM update or delete of
  a row not captured, so the snapshot can never be incomplete. Consequently
  every op touches rows through the ORM and does the database's own
  `ON DELETE` cascades and `SET NULL`s by hand first (recordings, AI-review
  logs, `vocabulary_id`, review logs' `saved_word_id`): an invisible cascade
  is an unrecoverable one. The record (before-images of updated/deleted rows,
  after-images of all, ids created) is appended to the run report and fsynced,
  then the op commits, then a `commit` marker follows.
- **Undo is per op, newest first, and refuses to trample.** An op reverses
  only if every row it wrote still equals its after-image and every row it
  deleted is still absent; otherwise that op is reported `skipped` (a person's
  later edit wins) and the rest go on. Order inside an op: per table, parents
  first, restore updates THEN re-insert deletes (a saved word moved back
  before the word it displaced returns: unique per learner and sense), delete
  what it created children-first. Rules-file edits are reverted too.
- **Saved words: more progress wins** (`_merge_saved_words`; deliberately not
  `lexicon_enrich._repoint_saved_words`, which keeps the survivor's word and
  its history). One learner on both senses: more `reps`, then the later last
  review, wins and ends up on the surviving sense; a tie keeps the survivor's.
  The loser's contexts move over (one per material: a duplicate is dropped).
  Its review LOGS are kept as history but detached (`saved_word_id` NULL, and
  `context_id` NULL where the context was dropped): the winner's schedule and
  lapse chain are built from its own logs and must not be extended by another
  card's answers. Exposures, speak misses and deck memberships fold into the
  winner. DROPPED with the loser row: its `status`, FSRS state/due/stability,
  `lapses`, ladder levels and leech/suspension marks. Reports and word-list
  entries use the existing repoint helpers. `create_phrase`'s `drop_sense`
  sends dependants to the new sense.
- **Deleting saved words needs consent.** `delete_lexeme` rejects when saved
  words hang on its senses unless the line says `"allow_saved_words": true`;
  its result line always states how many saved words of how many learners.
  (`delete_rows` only unlinks contexts and `delete_sense` without `into`
  refuses anything referenced, so neither can delete a saved word.)
- **Person-approved senses are untouchable** (`approved_at` set by anybody but
  the review account): not dropped, not absorbed, not overwritten, not
  re-opened by `human`. Every sense the tool writes is approved by the review
  account and has a `cald`/`human` definition, so the CALD apply and
  `lexicon_enrich` leave it alone; text not from CALD is `human` (locked),
  never `model` (enrichment would rewrite it).
- **Easiest first** (`rerank_senses` {lexeme_id, order}: exactly a
  permutation of the lexeme's senses, renumbered 1..n, `Lexeme.cefr` from the
  new rank 1, the rank-1 `ngsl_conflict` flag in line; no approval is touched).
  `plan-rerank --out F` (read only; default
  `app/data/private/restructure/rerank.decisions.jsonl`) writes one line per
  lexeme that is wrong in ANY of: order, ranks not exactly 1..n, `Lexeme.cefr`
  not the new rank 1's, a stale rank-1 flag (that line carries the order the
  lexeme already has). It prints the counts, `Lexeme.cefr` by old->new level
  and the flag adds/removes. Every op that adds, moves, drops or re-levels a
  sense re-ranks the lexeme in the same op.
- **Nothing is re-enriched.** `Lexeme.enriched_at` is never cleared (a new
  phrase lexeme gets it set): clearing it sends the lexeme back through
  enrichment, which re-translates its unlocked senses.
- **CALD text is normalised as `plan_items` does** (`normalise_definition`:
  `clean_definition`, then `strip_label_lost_prefix`) so an added sense equals
  the existing CALD senses. `add_sense` needs an Uzbek meaning: `translate`
  runs first and uses production's `step_translate` (two translators, the
  judge twice), writes `<file>.translated.jsonl` with `judge`, and a verdict
  that is not `same` sets `needs_review` + `judge_unsure|different`, which
  `apply` carries onto the sense. It stops on the spend cap, an account-level
  HTTP error, or two empty chunks, leaving the rest empty.
- **Deleted lemmas and merged headwords must stay that way:
  `app/data/lexicon_rules.json`** (committed; keyed by lemma, never by id, so
  it replays on any database). Entries carry the run id and op number ONLY,
  never the reviewer's note (the repo is public; a note may quote dictionary
  text).
  * `refused` lemmas are refused by `lexicon.is_refused_lemma`, used by the
    WRITERS and builders only: `replace_extracted`, `word_lists_build`
    (`exclusion_reason` -> `refused`), `build_lexicon`'s list-only selection.
    `is_excluded_word` keeps its old meaning and is the only one the learner's
    lookup path (`_generate`, `_from_lexicon`) asks: a reviewer's clean-up must
    never turn a tapped word into "no answer". `delete_lexeme` refuses a lemma
    only if no other lexeme (any pos) has it, it does not reduce by the
    inflection rule to an existing lexeme, and CALD does not list it as a
    headword; if the CALD index cannot be loaded the op is REJECTED (a
    refusal that was not checked must not be written; `"refuse": false`
    deletes without refusing). Otherwise the result line says `not refused: <why>`.
  * `aliases` `(lemma, pos) -> (lemma, pos)` are consulted by
    `_find_or_create_lexeme` and `build_lexicon.canonical_key` only when NO
    lexeme has the exact `(lemma, pos)`: a real lexeme beats an alias, and
    `merge_lexeme`/`rename_lexeme` skip sources that have a lexeme of their
    own. One alias per distinct row lemma too (rows keep their own `lemma`:
    unique per material); chains collapse; an alias keyed by a real target is
    dropped.
  * Reading never raises (`lexicon_rules`, on the request path): a malformed
    file is logged once and the last good rules stay; entries are validated.
    The TOOL's `read_rules_file` raises instead, so it never overwrites a file
    it could not read.
  * Written only AFTER the op's commit, from a fresh read under a lock
    (`rules_lock`), recorded as a `rules` record in the run report so `undo`
    reverses exactly what was written, even for an op with no commit marker.
    The file is mtime-checked, so a long-lived worker notices an edit.
- **What the rows keep.** `material_vocabulary.lemma`/`surface`/spans are never
  rewritten; a moved row takes the target's `pos` and, for a phrase lexeme,
  `is_phrase`, and a CALD-levelled sense's level by `link_row`'s rule.
  `saved_words.lemma` and the review logs keep what the learner met.
- **Commands** (from `backend/`): `translate --decisions F [--max-usd N]`;
  `apply --decisions F [--confirm-db NAME] [-v]` (dry run without it);
  `undo --run ID [--ops N ...] [--confirm-db NAME]` (ID: 12 hex characters); `status`. Tests run ONLY
  against a throwaway database named `voocab_restructure_test` (its fixture
  truncates and refuses any other name; the whole suite refuses any database
  without "test" in its name, `tests/conftest.py`).

## The audio layer: a word is a recording or TTS (vocabulary stage 3)

What a learner hears for a word is made in advance, never inside a request.
`word_audio.py` is the one door the rest of the app uses; `tts.py`,
`pronunciation.py`, `audio_pcm.py` and `word_recordings.py` are what stands
behind it. **Live clips cut from listening recordings were dropped on
2026-10-07** (the owner heard fragments of neighbouring words and the
sentence's emotion and pitch): there is no `word_clips`, no clip worker loop,
no `clips`/`verify-clips` seed step, and `AudioOut` is `{url}` only. What came
back, agreed with the owner, is the dictionary's own recording OF THE WORD
(next bullet); do not add a third source of word audio without the owner.
Definitions are ALWAYS Kokoro.
Design decisions are in `brief-vocabulary-stage3-decisions.md`; the rules
below are the ones a later change can silently break.

- **The learner chooses who says a word** (`vocabulary_settings.word_voice`:
  `recorded` default | `synthetic`; `accents.WordVoice`, optional on `PUT`,
  absent = unchanged). `recorded` + a row in `word_recordings` for (sense,
  accent) -> that file's URL, immediately, nothing queued; anything else ->
  the TTS path exactly as before. Every caller passes both `accent` and
  `word_voice` from ONE settings read (session build, the reveal, the speak
  reveal, the word page, On the go). `word_audio_many` asks the table ONCE
  (`WHERE lexeme_sense_id IN (...) AND accent = :a`; `test_a_list_is_resolved
  _without_a_query_per_word`) and builds TTS specs only for the senses that
  have no recording.
- **`word_recordings` is per (sense, accent)** -- UNIQUE, `ON DELETE CASCADE`
  with its sense -- not per CALD block: resolution is one indexed lookup on
  the learner's own sense ids, and the block decision (below) is made ONCE, at
  import. Columns: `accent` (OUR `british`/`american`, not the source's
  `uk`/`us`), `storage_key` (`rec/<sha256>.m4a`, the hash of the normalised
  bytes: senses on one block share one file), `duration_ms`, `source_file`
  (the file name, what makes the import resumable and lets a changed ref
  replace the row), `basis` (`ref`|`pos`), `created_at`. **No transcription is
  stored**: it stays in the private index.
- **Which recording a sense takes** (`word_recordings.plan_sense`; the
  docstring has the reasoning). A sense WITH `cald_ref` takes the recording of
  THE BLOCK its ref points into (heteronyms are right by construction: `record`
  n and v are two files). Without one, and the lexeme matched a headword
  (`exact`/`variant`, or a headword CALD lists without defining): a lemma that
  is NOT a heteronym in either accent takes the first block of its pos with a
  recording; a heteronym is Kokoro with our decided phonemes. No headword:
  Kokoro. A block's recording is of its OWN headword, so `speaks()` refuses a
  ref into another word's block (`went` -> `go`, a plural -> its singular, a
  phrase sense inside `account`'s page, `amount to sth`): Kokoro, reason
  `block-is-another-word`. A sense's own `pron` (a weak form, an abbreviation spoken
  as its full word) is NEVER used: it is another word. A missing accent
  falls back for that accent only.
- **Recordings are normalised like a TTS render** (`word_recordings.normalise`:
  decode -> `tts.trim_edges` -> `audio_pcm.normalise_rms` -> `encode_m4a`; 24
  kHz mono AAC): the source mixes 16 and 44.1 kHz at unrelated levels, and On
  the go plays a recording and a synthetic definition back to back. Stored
  through `storage` under `rec/` (own prefix). Bump nothing: a change of
  trimming/levelling means re-running the import with the table emptied.
- **The import** is `scripts/cald.py recordings` (dry run by default;
  `--confirm-db NAME` must be the database `DATABASE_URL` names;
  `--limit N` lexemes with work, `--lemma w` repeatable, `--workers`). A
  window of 64 source files at a time goes through a process pool (CPU), then
  `storage.put`, then ONE upsert-and-commit per window, so a kill loses one
  window and the re-run (`plan` skips a row already holding the planned
  `source_file`) resumes. Failures are results (`UNDECODABLE`), not crashes.
  The report (coverage per accent, fallbacks by reason with example lemmas,
  levels and durations) goes to `app/data/private/cald/recordings_*.json`.
  Never write the real media root from a trial: set `MEDIA_ROOT`.
- **Stale rows are deleted, files never.** `plan()` lists the rows of senses
  it covered that no longer have a pick (`Plan.stale`: a `restore`d sense, a
  heteronym now without a ref) and `run_import` deletes them in their own
  transaction first; a pick that fell back only as `file-missing` (a source
  directory partly unavailable) is NOT stale. `lexicon_cald.restore_senses`
  (hence `apply`'s undo too) drops the restored senses' rows itself, since the
  block a ref pointed into is no longer theirs; `recordings` re-plans them.
  Storage files are content-addressed and shared: nothing deletes one.
- **More guards in `plan_sense`.** A heteronym never takes a block's audio
  when `pron_from == 'entry'` (the block borrowed the page's first
  pronunciation, maybe the other part of speech's): `no-recording-for-accent`.
  A redirect page's key counts as the block's word only when it is a variant of
  the headword (`redirect_is_variant`, the matcher's `alias_is_same`); the
  report counts the redirect blocks refused. On the `pos` basis ONE block with
  both accents is preferred over per-accent picks, so switching accent keeps
  the same block.
- **Retry: the recordings sweep** (`word_recordings.sweep`, called from
  `lexicon_cald.run_sweep` on `cald_sweep_interval_s`, WITHOUT the model
  cooldown/switch -- it asks no model). It plans EVERY sense and lets `plan`
  say what is missing or stale, so it covers lexemes with no refs,
  no-definition headwords, approved senses, a source directory set later and a
  changed ref -- the same answer `scripts/cald.py recordings` gives. A scan is
  skipped while a cheap signature (sense / recording / ref / approval counts,
  source path, index mtime) is unchanged. `attach_for_lexemes` (the hook) is
  the fast path for the lexemes it just finished.
- **`CALD_SOURCE_DIR` for the worker.** `settings.cald_source_dir` is any path
  on the machine the process runs on; in the worker container it is wherever
  the source is mounted read-only (e.g. `CALD_SOURCE_DIR=/cald`), and the
  private index (`app/data/private/cald/`, from the bind-mounted backend dir)
  must be readable there too -- both or nothing (one log line). Never a host
  path in a committed file: the mount and the variable live in a local,
  gitignored `docker-compose.override.yml` (compose merges it on its own).
  `cald_recordings_workers` (2) sizes the sweep's process pool.
- **`recordings --check-files [--confirm-db NAME]`** lists the stored
  recordings the CONFIGURED storage does not hold and, with `--confirm-db`,
  deletes those rows (serving falls back to Kokoro; the import puts them
  back). It is the only existence check: a request never asks storage.
- **Importer robustness.** The pool recycles its processes
  (`POOL_RECYCLE`), a `BrokenProcessPool` ends the run with the files not yet
  done reported as failed (a re-run resumes), it shuts down with
  `wait=False, cancel_futures=True` (never blocking the event loop), and the
  thread path is bounded (`THREAD_LIMIT`).
- **On the go's `_failed_words`** skips the TTS word key of a word whose word
  part is already answered (`word_ready`): a recording-served word must not be
  hidden by an old failed render of its TTS key.
- **New senses** (`lexicon_cald._map_and_apply` -> `word_recordings
  .attach_for_lexemes`): after the CALD hook/sweep applies a pass it attaches
  the recordings of those lexemes' senses -- only when `settings
  .cald_source_dir` names the source directory (empty = ONE log line, nothing
  attached; the sweep above picks them up once it is set). It never raises
  into the hook.
- **A request only reads and enqueues.** `word_audio` answers a URL or `None`
  ("not ready, and already queued"); synthesis happens in the worker (`app/worker.py`:
  the render loop) or the seed
  script (`scripts/seed_tts.py`). Nothing in `word_audio` may call Kokoro
  or PyAV. `tts.enqueue` runs on its **own transaction** and commits at
  once: a GET never commits its session, and a request that rolls back must
  not lose the work it asked for. It only inserts specs with NO row
  (`ON CONFLICT (key) DO NOTHING`): a `failed` render is not retried by every
  page view -- `tts.requeue_failed` is the lever. The rows go in **sorted by
  `key`**: a multi-row insert locks in VALUES order, so two overlapping
  enqueues in different orders deadlock (`test_overlapping_enqueues...`).
  The own transaction costs a second pooled connection while the request's
  is open -- cheap at this scale, and the alternative is a GET that commits.
- **One resolution, no order.** A word is the TTS render of its sense in the
  learner's accent (below); a heteronym sense carries its own phonemes. Ready ->
  its URL; no row -> enqueued and `None`. Resolve through `word_audio_many`; a
  list endpoint calling `word_audio` per row is the N+1 the `*_many` functions
  exist to prevent. On the go calls `word_audio_many` and
  `definition_audio_urls` -- the same two renders the reveal and `speak` play --
  and nothing composes them.
- **Heteronym-ness** is `is_heteronym(lemma, accent)`: exact and per lemma, and
  means two or more candidates that differ once stress is ignored -- misaki's table also holds stress-only variants (`be`)
  that are NOT heteronyms. Its data is `app/data/tts/` (see the README there),
  in **misaki's phoneme alphabet, not IPA**; `tests/test_heteronyms.py`
  checks every string against misaki's alphabet -- the British one for the
  British table and extras' `ps`, the AMERICAN one (`O` not `Q`, no `ː`, plus
  `æ ɾ ᵻ ʔ`) for `misaki_us_pos_entries.json` and the extras' `us`. The extras
  items are `{ps (British), us (American), note}`; they only choose phonemes.
- **Which pronunciation a sense takes is decided once and kept in the repo.**
  `scripts/decide_heteronyms.py` asks a model per lemma and appends to
  `heteronym_decisions.jsonl`, keyed by lemma + pos + synset (or definition)
  and never by a database id, so the log replays onto any database
  (`apply` writes `lexeme_senses.pronunciation`; `--accent american` uses
  `heteronym_decisions_us.jsonl` and writes `pronunciation_us` -- a phoneme
  string is only right in its own alphabet, so the two accents never share a
  log or a column; an answer that is no longer a current candidate is
  reported as stale AND its column is set back to NULL). A heteronym sense with no
  decision is NOT guessed into the column: serving falls back to misaki's own
  entry for the part of speech (`DEFAULT` if none) and logs it
  (`pronunciation.sense_pronunciation`). A wrong pronunciation is the one
  defect that raises no error, so a new heteronym lemma means: run `decide`,
  read the new lines, commit them.
- **A render's key is the hash of its INPUT** (`tts.render_key`: kind + exact
  synthesis string + voice + model, canonical JSON, `KEY_VERSION` inside), so
  a row exists before its audio does and one word is synthesised once in the
  whole system. A corrected definition or a newly decided pronunciation is a NEW key and a new render -- never an edit of
  an old row. Storage keys are `tts/{key}.m4a`. Bump `KEY_VERSION` to re-render
  everything after changing trimming or levelling.
- **The accent is the learner's: it picks the Kokoro voice and, under
  `recorded`, which of the two recordings plays.**
  `vocabulary_settings.accent` (`british` default | `american`;
  `app/services/accents.py` is THE table: British `bf_emma`/`'b'`, American
  `af_heart`/`'a'`). Every `word_audio` function, `tts.word_spec`,
  `definition_spec` take `accent` (default British) and every
  caller passes `settings.accent` (practice session build -- one settings read
  -- the reveal, the speak-check reveal, the word page, On the go). The VOICE is
  inside every render key (word and definition), so accents never collide and
  a render row carries the voice the worker must use.   The accent also chooses `pronunciation` vs `pronunciation_us`
  (`word_audio.decided_pronunciation`) and misaki's fallback table.
- **The voices: Kokoro-82M `bf_emma` (British) and `af_heart` (American).** A
  heteronym sense is spoken from `[word](/phonemes/)`, anything else from the
  lemma as plain text. Kokoro is imported ONLY inside `KokoroSynth._load` (one `KPipeline` per `lang_code`, all sharing ONE `KModel`
  -- later pipelines are built with `model=<the first's KModel>`; the `Synth`
  signature is `(text, voice)`); on
  macOS its `espeakng-loader` wheel kills the interpreter, so never import it
  at module level and never from a test -- tests inject a fake `Synth`. It
  lives in the worker image only (`ARG EXTRAS=tts`; weights baked in at build,
  `HF_HUB_OFFLINE=1`); the render loop disables itself with ONE log line
  where `kokoro` is not installed.
- **A definition is spoken exactly as recall shows it, with the headword as a
  silence.** `tts.masked_definition` calls `practice._mask_definition` (one
  definition of masking; imported inside the function, because `practice`
  will import the audio service and a top-level import closes the cycle); the
  text is cut at the masks, each piece is synthesised on its own, and a run of
  masks (a masked phrase is one blank per word) is ONE `MASK_PAUSE_MS`
  silence. The text with its `_____` is the render's `input` and key.
  **The plain definition is a second render of the same kind**
  (`definition_spec(..., masked=False)`, `definition_audio_urls(...,
  masked=False)`): input = the definition as written. Masking hides the answer
  only when the definition is heard BEFORE the word; On the go's `word_first`
  has said the word already, so it plays this one. Where masking changed
  nothing the two inputs are identical, hence ONE key and one render. A plain
  definition is speakable when the masked one is not (a definition that is only
  the headword).
- **An On the go item is NOT a render.** Until 2026-10-07 the server composed
  one file per word (definition + 3 s + word + 1.5 s, `RenderKind.ITEM`,
  `word_offset_ms`); the owner rejected it because a baked file cannot be
  reversed or re-timed (decision 13, superseded). The client sequences the
  word's render and the definition's render, so `RenderKind` is `word` and
  `definition` only and the claim order is word, definition. The migration
  `e7b2c4d9a315` deleted the `item` rows and dropped `word_offset_ms`; the files
  under `media/renders/` are orphans removed by hand.
- **Levelling is capped.** `normalise_rms` never amplifies by more than
  `MAX_GAIN_DB` (+20): near-silence brought to -20 dBFS is hiss.
- **Everything stored is 24 kHz mono AAC in MP4, faststart** (`audio_pcm`; the
  recordings too):
  Kokoro's native rate, small files, `moov` first so the browser can start
  playing. FFmpeg's native `aac` encoder only (always compiled in); PyAV is a
  main dependency and there is no `ffmpeg` binary anywhere.  `audio_pcm.decode` reads a stored render back (the seed doctor's
  readability check).
- **The queue is `audio_renders`, claimed `FOR UPDATE SKIP LOCKED`**, the same
  contract as `audio_blob.transcript_status`: `pending` -> `processing` ->
  `ready`. `process_render` never raises, and a failure is one of two kinds
  (`infra_errors`): the render's OWN (bad input, a synth error) bumps
  `attempts` and sets `next_attempt_at` (`tts_retry_backoff_s`, doubling) --
  `failed` at `tts_max_attempts`; an INFRASTRUCTURE fault (storage down via
  `GuardedStorage`, Kokoro failing to load) spends NO attempt and only waits
  `tts_infra_backoff_s`. `claim_render` skips rows still in back-off (the
  database's clock, never a worker's), so a systemic outage walks the queue
  once per back-off instead of burning every row's attempts in seconds.
  Recovery is by AGE inside the loop (`maintain_renders` every minute): a
  `processing` row whose `updated_at` -- claiming is the heartbeat -- is older
  than `tts_stale_after_s` goes back to `pending`; never "everything
  processing", which would take a row another live worker is making. `failed`
  rows older than `tts_failed_requeue_h` are requeued with attempts reset.
  Maintenance never raises out of `asyncio.gather`. The seed script drains
  the same queue in-process (`tts.drain`) -- the 3060 has no worker -- so
  seeded and worker-made audio are the same rows under the same keys.
- **`drain` is one synthesis stream with everything else overlapped.** Up to
  `--concurrency` (default 8, `tts.MAX_CONCURRENCY` 12 = the DB pool) renders are
  in flight, but every synthesis runs on ONE dedicated thread
  (`_in_synth_thread`, a ContextVar the worker never sets) because Kokoro is not
  safe concurrently; encoding, `storage.put` and the commit overlap it, so the
  GPU never waits on an SMB/tunnel round trip. Claims are batches
  (`claim_renders`, `SKIP LOCKED`, committed as `processing` before any work),
  so a second drainer (the dev worker) never gets the same row; a claimed row
  waits seconds, far inside `tts_stale_after_s`. Cancelling releases unresolved
  claims to `pending` (`_release`, no attempt spent). Do not add a shared
  `AsyncSession` across the tasks, and do not raise the cap without the pool.
- **A word misaki cannot pronounce fails the render.** `KokoroSynth` runs
  `pipeline.g2p` itself and checks the tokens (`unknown_words`) before
  `generate_from_tokens`; Kokoro's own `unk=''` plus its swallowed espeak-load
  failure would leave a silent gap. It sets `g2p.unk = UNKNOWN_MARK` so an
  unknown half of a hyphenated compound survives the merge and is seen. This is
  the render's own failure (`UnknownPronunciation`, spends an attempt); a
  voice file that will not load is `InfrastructureError` (preloaded in
  `_load_voice`). `seed_tts doctor` proves espeak works on the machine first.
- **`LocalStorage.put` is atomic** (temp + `os.replace`): `exists` is the
  idempotency check, so a half-written file after a kill would be "stored" for
  ever. An unavailable media root (unmapped drive) is a plain `OSError`
  (retryable), never `FileNotFoundError` (which fails the row for good).
- **Files are copied, rows are not.** When the seed runs on another machine its
  rows say `ready` as soon as the file is written THERE; until the files are
  copied to the serving machine the site gets no audio for them (treated as
  none). `seed_tts check-files --requeue` finds and requeues any
  that never arrived. See `scripts/SEED_TTS_WINDOWS.md`.
- **Exposure and speak-miss tables exist and are written by the practice
  layer, not here** (`on_the_go_exposures`, `speak_misses`). An exposure is
  never an FSRS review: hearing a word is not recalling it. Both keep their
  history when a word is forgotten: `saved_word_id` is `ON DELETE SET NULL`
  and `lemma` is copied onto the row (default `""` for a writer that does not
  set it), like `vocabulary_review_logs`.
- **Seed order**: `words` -> `definitions` -> `definitions --full`, each with
  `--accent british|american|both` (default both). `words` makes TTS for every
  sense; `--full` the plain definitions that differ from the masked text (the
  doctor counts them); the worker makes either on demand meanwhile.
  `seed_tts doctor` checks the machine first; whisper is not needed.

## Vocabulary practice (stage 3): the third rung, `listen`, `speak`, On the go

`practice.py` still owns every rating; the audio comes from `word_audio.py`
(above). What stage 3 added to the rules:

- **The passive ladder is `recognise -> recall -> listen`** (`PASSIVE_LADDER`);
  the active one is unchanged. `_apply_ladder` is one index walk: Again at any
  rung above the floor goes back one (Hard never demotes), enough corrects go
  forward one. **2 consecutive corrects, or 1 if the word has been at the NEXT
  rung before** -- `_has_reached_level` is asked about `ladder[index + 1]`, not
  `ladder[-1]`, which stopped meaning "the next rung" with three. A word
  already at `recall` with a streak in the log promotes on its next correct
  with no backfill: the streak is read from the log either way.
- **A `recognise` answer to a plan above the floor (the readability fallback)
  is never promotion evidence.** With two rungs it could not promote anything;
  with `recall` in the middle a correct choice-of-four would otherwise count as
  recalling the word. Wrong, it still demotes, as before.
- **A SPOKEN `speak` answer is on no ladder and the ladder cannot see it.**
  Logged as `exercise_type="speak"`, `planned_exercise="speak"`;
  `_promotion_streak` skips it, `_has_reached_level` never matches it,
  `_apply_ladder` is not called. A spoken answer between two typed ones must
  not reset a streak. It IS an FSRS answer on the passive card and counts as a
  lapse like any (Again on a Review card).
- **`speak`'s typing fallback is NOT `speak`.** The card becomes the recall
  prompt (decision 19) and the answer is an ordinary typed `recall`; the
  client's `planned_exercise="speak"` on it is accepted on the wire and never
  read. The plan is the word's own level -- at `recall` a normal recall answer
  with full ladder effect, at `listen` the `listen`-plan recall fallback -- and
  that is what is logged. (A claim that skipped the ladder would hide every
  wrong typed answer; it was the one client value ever read, and is gone. That
  the answer came from a speak card is not recorded.)
- **`record_answer` stays the authority.** `listen` is accepted only when the
  word's own level is `listen`; its fallback is `recall` (`LISTEN_FALLBACK_
  EXERCISE`; the plan stays `listen`, an Again demotes). Spoken `speak` is
  accepted only for a passive word at `recall` or `listen` (`SPEAK_LEVELS`).
  Anything else is the same 422 as any unknown claim. No client-claimed plan
  is read.
- **"Can't listen now" costs nothing to press, not nothing to answer.** The
  link itself writes nothing; the item is then answered as the `recall`
  fallback, graded as recall, and a wrong one is an FSRS Again that demotes
  `listen` -> `recall` like any fallback answer (the same pattern as the
  distractor fallback). A correct one is a Good and moves nothing.
- **Requeue of `listen`/`speak`.** The client turns a requeued `listen`/`speak`
  card into its recall fallback and still sends `requeued`, so the check is
  `_requeue_exercise_matches`: the same exercise as the last logged Again, or
  `recall` after a logged `listen`/`speak`. The level gates run again on the
  requeue: `speak` (either form) needs `SPEAK_LEVELS`; `listen` (either form)
  needs `LISTEN_REQUEUE_LEVELS` -- `recall` too, because the Again being
  requeued has already demoted the word off `listen`.
- **`listen` is graded against the LEMMA**, not the sentence's surface (the
  recall fallback is graded against the surface, as it always was): the audio
  is the exact lemma, and "type what you hear" must not mark the lemma wrong
  because the sentence said `undertaken`. Same rating table as recall.
- **A `listen` item exists only with its audio READY**; otherwise it is an
  ordinary recall item with `planned_exercise="listen"` (the render is queued
  by `word_audio`). Audio for a whole session is ONE `word_audio_many` call
  (and `definition_audio_urls` for `speak`) -- never per item.
- **`speak` is manual only** (`mode="speak"` or settings `["speak"]`); candidates
  are passive words at `recall`/`listen`; an automatic session never builds
  one. Its prompt carries the definition masked exactly as recall masks it. The
  answer is verified server-side by re-running the matcher on `given`
  (`speech_match.matches`, 422 on no match); `gave_up` (only valid with
  `exercise_type="speak"`) rates Again.
- **The matcher is spelling rules, not similarity** (`speech_match.py`):
  th -> t/s/d/z, w -> v, a<->e on the target's letters, ANY vowel before an
  initial consonant cluster (glued, `istop`, or split off as a one-letter
  token, `i stop` -- a recogniser returns words), phrases whole. No inflection, no edit distance.
  `cat`/`ket`, `play`/`pray`, `school`/`iskool` are misses on purpose; a false
  accept teaches the wrong word and a miss costs nothing (decision 18). The
  target becomes ONE regex, never a list of variants.
- **`speak-check` writes nothing to the schedule or review log**, only a
  `speak_misses` row per miss (with `lemma`, always). The attempt is counted
  SERVER-side from the learner's misses on the word in the last
  `SPEAK_ATTEMPT_WINDOW` (10 min), since the last reveal; the wire's `attempt`
  is accepted and never believed. `answer`/`audio` appear only when this miss
  is the server's third. At most `SPEAK_MISS_ROW_CAP` rows per (learner, word,
  window) are written. Three misses are OUR miss, never an Again.
- **On the go (`on_the_go.py`)**: words in rotation (not `EXCLUDED_STATUSES`,
  practisable), `created_at` desc, independent of the daily queue. An item is
  `(word_url, definition_masked_url, definition_full_url)` -- the word's TTS
  render in the learner's accent and the sense's definition in both renders
  (masked, for `meaning_first`; plain, for `word_first`: see "A definition is
  spoken exactly as recall shows it"). The one the learner's SAVED order needs
  (read from settings, as the accent is) must be ready for the item to be
  listed, and is never null; the other is queued in the same request and rides
  on the item when ready, else `null`, so the screen can change the order
  mid-session without a refetch (the client never plays the plain one before
  the word). `_failed_words` looks only at the needed one: a failed plain render
  hides no `meaning_first` item. Listed only when BOTH parts are ready;
  `preparing` = the rest that is still being made (queued or in progress). A
  word with no speakable definition, or with a `failed` part, counts in neither
  (`_failed_words`: the keys are re-derived with the same public helpers
  `word_audio` uses). The words' text is never on the wire. **Order and pause
  are the learner's**: `vocabulary_settings.on_the_go_order`
  (`meaning_first` default | `word_first`) and `on_the_go_pause_s` (1..10,
  default 3), optional on `PUT /vocabulary/settings` (absent = unchanged) and
  returned on GET; the server applies neither -- the client sequences. The gap
  between words is a fixed 1.5 s on the client. Exposures insert one
  `on_the_go_exposures` row and touch no card.


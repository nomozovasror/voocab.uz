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
lemma, because what somebody is STUDYING is one word however many passages
they met it in. Each meeting is a `SavedWordContext` and **copies** the
gloss rather than pointing at it — a material can be re-glossed, and a saved
word changing meaning underneath somebody is worse than one that has aged.

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
- **`vocabulary.save` fills a new word's `pos`/`meaning_core_*` once, at
  creation, from the entry that caused it** — falling back to that entry's
  contextual meaning when it has no usual one yet, the same fallback the
  migration's backfill and every `MaterialVocabulary` reader use. A second
  save of the same lemma from another material never touches those columns
  again; only the context list grows.
- **`Mastered` and `Learning` are a partition, computed in Python over one
  query** (`_totals`), not three separate counts — `known` status OR
  `passive_stability ≥ 21` days (`MASTERED_STABILITY_DAYS`) is `mastered`;
  `suspended` is its own bucket; everything else is `learning`. The one
  case that needs the two columns looked at together is a suspended word
  stable enough to also qualify as mastered, which counts as mastered.

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

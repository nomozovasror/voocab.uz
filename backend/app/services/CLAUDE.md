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

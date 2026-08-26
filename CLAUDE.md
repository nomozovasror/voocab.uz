# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

This repo is mid-restructure. The previous layout (`bot/`, `frontend/`, and a `requirements.txt`-based backend) has been **deleted** but those deletions are not yet committed — they still show in `git status`. The active codebase is a single **uv-managed FastAPI backend** under `backend/`. When working here, treat `backend/` as the source of truth and ignore the deleted top-level `bot/` and `frontend/` trees unless explicitly asked to restore them.

## Architecture

- `backend/app/main.py` — the FastAPI application (`app`), currently exposing only `GET /health`. This is the ASGI entrypoint referenced as `app.main:app`.
- `backend/main.py` — an unrelated `uv`-generated console stub (`Hello from backend!`); **not** the server entrypoint. Don't confuse it with `app/main.py`.
- `docker-compose.yml` — orchestrates the `backend` service (port 8000) plus a `postgres:18` `db` service (port 5432, db `app`, user/pass `postgres`/`postgres`). The backend dir is bind-mounted into the container so `--reload` picks up edits.

## Commands

All commands run from `backend/` (uv project root).

```bash
# Install/sync dependencies into the local venv
uv sync

# Add a dependency (updates pyproject.toml + uv.lock)
uv add fastapi uvicorn

# Run the API server locally with autoreload
uv run uvicorn app.main:app --reload

# Full stack (API + Postgres) via Docker
docker compose up --build   # from repo root

# A catalogue to develop the learner's /listening page against — 15 public
# materials across all four parts, every question type, and the answers that
# give each one a difficulty band. Dev databases only (refuses to run unless
# DEV_LOGIN_ENABLED); --clean removes exactly what it wrote.
uv run python -m scripts.seed_practice
uv run python -m scripts.seed_practice --reset
```

No test, lint, or formatter setup exists yet.

## Versions

The project targets **Python 3.14** and **Postgres 18**. Keep these aligned across all four places when changing them:
- `backend/pyproject.toml` → `requires-python = ">=3.14"`
- `backend/.python-version` → `3.14`
- `backend/Dockerfile` → `FROM python:3.14-slim`
- `docker-compose.yml` → `image: postgres:18`

## The catalogue is a query, not a list

`GET /api/listening/practice` returns **one page**, filtered, ordered and
counted in SQL (`backend/app/services/listening.py`). Nothing about the list
is decided in the browser any more, and that is deliberate: at a thousand
materials, sending the library so the page can hide most of it is half a
megabyte of JSON and a thousand rows of DOM to show somebody thirty titles.

- **Add a filter in two places or not at all.** `catalogueParams` in
  `frontend/src/features/listening/practice.ts` turns the control state into
  query parameters; `_catalogue_where` in the service turns them into SQL. A
  filter that only exists in one of them narrows the page and not the count.
- **Facets are counted over the whole library**, never over the page and never
  over what the other filters left. An option that appears and vanishes as you
  filter is an option nobody can aim at.
- **`done` defaults to false** — materials the caller has sat are put away —
  and the endpoint says how many that hid (`done_hidden`). Never hide rows
  without saying so; a list quietly shorter than the reader knows the library
  to be is a list that looks broken.
- Anything a row prints that is a fact about the LIBRARY rather than about the
  material must come from the server. The author byline's "4 materials here"
  was counted in the browser and became a lie the day the browser stopped
  having the library.
- Paging is offset-based on purpose. Keyset is what survives six figures; at
  four, filters narrow before depth does, and one order per sort key is worth
  more than a cursor that has to encode which key it is on.

## A recommendation has to say why

`GET /api/listening/next` returns three materials and a `reason`
(`backend/app/services/recommend.py`). The reason is the contract, not
decoration: a recommendation that cannot justify itself is a shuffle with a
confident label on it, and the reader has no way to tell those apart except by
being told.

- **`weak_part` is guarded, and stays guarded.** The sidebar once named the
  lowest-scoring part outright and it did not survive being looked at — 62%
  against 66% over a few dozen answers is noise. A part is named only when it
  is scored at all, below `WEAK_CEILING`, and clear of the next-weakest by
  `DECISIVE_GAP`. Otherwise the reason falls through to `level`, which the
  same data does support. Loosening those constants means making a claim about
  somebody's ability on evidence that doesn't carry it.
- **The ladder never opens with `hard`**, at any level, and `new` is always
  last — "might be anything" is not a recommendation.
- Never recommend a material with no questions in it, or one already sat.
- The block is shown only over an **unnarrowed** list. A filter is the reader
  saying what they want; suggesting past it is the page talking over them.

## Loading states (frontend)

Three of the four pieces are structural and need no remembering:

- **Route progress** — `<RouteProgress/>` sits in both layouts, so every route
  present and future is covered. Route-level `lazy:` leaves the old page on
  screen while the next chunk downloads; this is the only thing that says so.
- **`HydrateFallback`** — comes from the `page()` helper in `src/app/router.tsx`.
  `lazy:` appears exactly once in the codebase, inside that helper. **Register
  new routes with `...page(() => import(...))`**; writing `lazy:` by hand loses
  the fallback and a cold load renders a blank page, header included.
- **Reduced motion** — one global rule in `globals.css` disables
  `animate-pulse`, so any new skeleton inherits it.

The fourth is a habit. When a page-level wait deserves a skeleton:

- **Build it from the real component's class strings, never from measured
  pixels.** That is the only way the two can't drift. It is also how the
  non-obvious mismatches get caught — the audio control's track is a 24px line
  box rather than the 4px bar it looks like, because the range input is
  `inline-block` on a text baseline.
- **Put a bar that stands in for TEXT inside the real element** (`<h1>`, `<p>`)
  as `inline-block h-[0.8em]`, so the element's own line-height sets the row.
  A block bar in an `items-baseline` row has no baseline and drags the row out.
- **No `loader-deferred`** on skeletons, unlike every other loader here. That
  delay exists because `LogoLoader` *replaces* the page and has a reflow to
  hide; a shape-matched skeleton has none, and over a 300ms wait a 250ms delay
  plus a 200ms fade is a blank page with extra steps.
- **Measure it in the browser** — skeleton and loaded, same `top` and same
  `height`. Reasoning about heights is how you end up 6px out per row.
- Reserve space for controls that don't depend on the data but live inside the
  loaded branch, or they shove everything sideways when they appear.

`PageLoader` (the brand mark) is still right where there is no shape to match:
`RequireAuth` guards *any* route, so it cannot know what it is waiting for, and
the two `<Suspense>` fallbacks are boundaries of last resort that never fire
for route-level `lazy:`.

Reference implementations: `src/features/listening/components/PaperSkeleton.tsx`
and `DashboardSkeleton` in `src/pages/studio/StudioDashboardPage.tsx`.

## Difficulty is measured, never stored

A listening material's `Easy` / `Medium` / `Hard` / `New` band is a function of
`QuestionAttempt` rows (`backend/app/services/difficulty.py`), never anything
an author declares. **Do not add a `difficulty` column to `materials`.** The
current answer is a classic proportion correct (stage 1); the next one is a
Rasch/1PL estimate that corrects for *who* sat the paper. As long as
difficulty stays a function, that swap touches one module — an authored column
would make it a migration, a backfill and a re-education of everyone who set
one.

**The projection is not that column.** The tally lives in a
`material_difficulty` table that `difficulty.recompute()` refills, because the
aggregate is a scan of every answer on the platform and running it per request
does not survive a catalogue of a thousand papers. The line: nothing authored
ever reaches that table, every column in it is derived, and dropping the whole
thing costs one `recompute()`. Stage 2 changes the computation and the table
refills — still no migration.

- The worker refreshes it every `DIFFICULTY_REFRESH_INTERVAL_S` (default 900),
  in its own loop beside transcription (`backend/app/worker.py`). A failed
  refresh is logged and swallowed: nobody waits on a band, and people wait on
  audio.
- **A band is only as fresh as the last refresh**, with one exception: the
  first crossing of `MIN_ANSWERS` happens on the submit that causes it
  (`refresh_if_unrated`, called from the attempts endpoint). A paper a class
  has just worked through, still saying nobody has answered it, is the
  catalogue contradicting itself. Everything after that first crossing waits
  for the timer. Anything writing attempts outside a request — the seed
  script — calls `recompute()` itself.
- **A skipped question is still an answer.** Grading writes a row for every
  question on the paper, so an untouched one counts toward the evidence and
  counts as wrong. That is what makes "missed entirely" classifiable at all,
  and it means a paper is four answers per attempt, not four minus the blanks.
- The read path derives the band from the stored *tally*, not from the stored
  `band` column. Move a threshold and the API is right immediately while the
  column catches up; the column exists so a paginated catalogue can filter and
  sort by difficulty in SQL.

Two constants guard against inventing numbers, and both are deliberate:

- `difficulty.MIN_ANSWERS` — below it, a material is `New` with no percentage.
- `learner_stats.MIN_ANSWERS` — below it, a distribution row on the practice
  page's statistics panel reports `accuracy_pct: null`, and the UI draws a dash
  with no bar. **Never substitute 0** — over four answers a zero is a false
  claim, and the panel exists to be trusted.

They are separate constants on purpose: "is this paper hard" and "is this
person weak here" are different questions, so one moving must not drag the
other.


## First attempts are the measurement

Every figure in the listening sidebar that describes *ability* — the average,
the mistake breakdown, the trend, the part split — counts each material's
**first** submitted attempt and nothing else
(`backend/app/services/learner_stats.py`). Somebody who sits a paper three
times and finishes on 95% has learned that paper, not listening.

- `first_try_avg_pct` is the headline; `best_avg_pct` sits under it and is
  **absent entirely** until something has actually been sat twice, because
  with no retries it is the same number under a second name.
- "Materials done" counts materials with at least one *submitted* attempt.
  Started-and-abandoned doesn't count.
- Percentages round half **up** (`_pct`), not Python's default half-to-even —
  two figures on one panel disagreeing by one is a bug nobody reports and
  everybody notices.

## Mistakes are classified, not counted

`backend/app/services/mistakes.py` turns a wrong answer into a *kind* —
spelling, missed entirely, singular/plural, over word limit, number/date
format, wrong answer — by comparing the raw `given_answer` against the
accepted ones. This is only possible because grading normalises for the
comparison and never writes the normalised form back: **keep storing
`given_answer` exactly as typed.**

The distinction the sidebar rests on is *spelling* against *missed entirely*:
one is a proof-reading problem and the other is a listening problem, and "you
got 62%" tells a candidate neither. The rules lean towards **not** claiming
spelling — see the threshold notes in that module.

Letter-answered groups (multiple choice, matching, boxed summaries) are
excluded: there is no spelling in "b". Distractor analysis is the equivalent
question there, and it belongs on the full statistics page.

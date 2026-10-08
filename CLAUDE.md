# CLAUDE.md

Guidance for Claude Code working in this repository.

## Where the rules live

This file stays short on purpose — it is loaded into every request. The
design rules that matter are kept beside the code they govern, and load when
you open those directories. **Read the relevant one before changing that
area:**

| File | Covers |
|---|---|
| `backend/app/services/CLAUDE.md` | Catalogue query, recommendations, collections, difficulty, learner stats, mistake classification, vocabulary, CALD definitions, `answers.py` layering |
| `frontend/CLAUDE.md` | Preferences, loading states and skeletons |
| `frontend/src/features/paper/CLAUDE.md` | What listening and reading SHARE: the skill descriptor, the take engine, question types, the review |
| `frontend/src/features/reading/CLAUDE.md` | The passage, and why the reading take screen is two panes |
| `frontend/src/features/vocabulary/CLAUDE.md` | The three lookups, the review's word list, what a saved word is |
| `frontend/src/features/listening/CLAUDE.md` | Take screen, audio engine, the travelling player, waveform, collection covers |
| `frontend/src/pages/listening/CLAUDE.md` | The results/review page |
| `frontend/src/pages/studio/CLAUDE.md` | Studio tabs, the author's collection shelf |
| `frontend/src/components/layout/CLAUDE.md` | The header, `HeaderGround`, docking |

## Architecture

- `backend/` — uv-managed **FastAPI** app. `app/main.py` is the ASGI
  entrypoint (`app.main:app`); routers for auth, materials, audio, listening,
  collections and studio, plus `GET /health`.
- `backend/main.py` — an unrelated `uv`-generated console stub (`Hello from
  backend!`); **not** the server entrypoint.
- `backend/app/worker.py` — four background loops: transcription, the
  difficulty projection refresh, lexicon enrichment, and TTS/On-the-go renders
  (a vocabulary word is a dictionary recording or Kokoro TTS, the learner's
  choice; definitions are always TTS; live clips were dropped).
- `frontend/` — **React 19 + Vite + Tailwind 4** SPA, React Router 7 and
  TanStack Query. Design notes in `frontend/docs/`.
- `docker-compose.yml` — `db` (postgres:18, port 5432, db/user/pass
  `app`/`postgres`/`postgres`), `backend` (port 8000) and `worker`. The
  backend dir is bind-mounted so `--reload` picks up edits.

## Commands

Backend, from `backend/` (uv project root):

```bash
uv sync                                   # install/sync the venv
uv add fastapi uvicorn                    # add a dep (updates pyproject + lock)
uv run uvicorn app.main:app --reload      # dev server
uv run pytest                             # tests (backend/tests/)

# 15 public materials across all four parts, every question type, with the
# answers that give each a difficulty band. Dev databases only (refuses
# unless DEV_LOGIN_ENABLED); --reset removes exactly what it wrote.
uv run python -m scripts.seed_practice
uv run python -m scripts.seed_practice --reset
```

Frontend, from `frontend/`:

```bash
npm run dev      # Vite dev server
npm run build    # typecheck + production build
npm run lint
```

Full stack: `docker compose up --build` from the repo root.

## Versions

The project targets **Python 3.14** and **Postgres 18**. Keep these aligned
across all four places when changing them:

- `backend/pyproject.toml` → `requires-python = ">=3.14"`
- `backend/.python-version` → `3.14`
- `backend/Dockerfile` → `FROM python:3.14-slim`
- `docker-compose.yml` → `image: postgres:18`

## One database

`backend/.env` and the dev app both point at the compose `db` service on
**5432**. There used to be a second Postgres on 5433 that `.env` aimed at, so
every schema change had to be migrated twice and anything run from the host
landed somewhere the site never looked.

The cost of collapsing them: tests write into whatever database they run
against, and some rewrite every lexeme sense. **Plain `uv run pytest` now
refuses to run** (`tests/conftest.py` aborts the session before anything
connects) unless the configured database has "test" in its name and is not
`app` -- it once destroyed the dev data. Always name a test database inline:

```bash
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/app_test uv run pytest
```

(or a named throwaway such as `voocab_restructure_test`; create it, run
`alembic upgrade head` against it, drop it when done). Never `export` the
variable: set it in the same command.

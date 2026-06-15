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
```

No test, lint, or formatter setup exists yet.

## Versions

The project targets **Python 3.14** and **Postgres 18**. Keep these aligned across all four places when changing them:
- `backend/pyproject.toml` → `requires-python = ">=3.14"`
- `backend/.python-version` → `3.14`
- `backend/Dockerfile` → `FROM python:3.14-slim`
- `docker-compose.yml` → `image: postgres:18`

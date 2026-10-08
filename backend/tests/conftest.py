"""Suite-wide guard: the worker's CALD hook (`app.services.lexicon_cald
.map_new_lexemes`, behind `settings.cald_map_new_lexemes`) is OFF for every
test. Several tests drive `app.worker._lexicon_enrich_once` on real lexemes;
with the hook on they would load the private CALD index on a developer's
machine, call the real Gemini API and append to the private decision log.
The hook's own tests turn it on for themselves, against a temporary
directory and a fake model.

Set before anything imports `app.core.config` (pytest imports this file
first), and as an environment variable because real env vars win over
`.env` in pydantic-settings.
"""

import os

import pytest

os.environ["CALD_MAP_NEW_LEXEMES"] = "false"


def pytest_configure(config) -> None:
    """Abort the WHOLE session, before any test or engine connects, unless the
    configured database is a test database: its name contains "test" and it is
    not `app`. Several tests truncate, rewrite or delete real rows (the CALD
    apply/restore tests alone touch every lexeme sense); run against the dev
    database they destroyed it once (2026-10-07). Resolved the way the app
    resolves it (environment, then `.env`), so a missing DATABASE_URL is caught
    too -- it falls back to `.env`, which names `app`."""
    from sqlalchemy.engine import make_url

    from app.core.config import settings

    name = make_url(settings.database_url).database or ""
    if name == "app" or "test" not in name:
        pytest.exit(
            f"REFUSING TO RUN: the configured database is {name!r}. Tests write to the "
            "database they run against; point DATABASE_URL at a test database (its name "
            "must contain 'test' and not be 'app'), e.g.\n"
            "  DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/app_test "
            "uv run pytest",
            returncode=4,
        )

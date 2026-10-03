"""The five curated lists' own rows: titles, one-sentence reasons, credit.

Data only, no entries -- ``word_list_entries`` is populated by the build job
(``scripts/build_word_lists.py``). :func:`seed_word_lists` is idempotent: it
inserts what is missing and refreshes the descriptive columns of what is
there, so wording can be corrected by editing this file and re-running it.
The alembic migration that creates the table inserts the same rows (a frozen
copy -- a migration must not change meaning when this file does).

Authors and titles are the ones in ``seed/wordlists/README.md``: all five
lists are by Browne, Culligan & Phillips, newgeneralservicelist.com, under
CC BY-SA 4.0 (attribution is a condition of use).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import select

from app.core.database import AsyncSession
from app.models.word_list import WordList

LICENCE_NAME = "CC BY-SA 4.0"
LICENCE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"
AUTHORS = "Browne, Culligan & Phillips"

WORD_LIST_SEEDS: tuple[dict[str, Any], ...] = (
    {
        "key": "core",
        "title": "Core English",
        "description": (
            "The most common words in English, which cover most of what you "
            "read and hear every day."
        ),
        "source_title": "New General Service List (NGSL) 1.2",
        "attribution_name": "New General Service List",
        "sort_order": 1,
    },
    {
        "key": "business",
        "title": "Business English",
        "description": (
            "The words that keep coming back in meetings, emails, contracts "
            "and reports."
        ),
        "source_title": "Business Service List (BSL) 1.20",
        "attribution_name": "Business Service List",
        "sort_order": 2,
    },
    {
        "key": "academic",
        "title": "Academic English",
        "description": (
            "The words that university texts and lectures lean on, whatever "
            "the subject."
        ),
        "source_title": "New Academic Word List (NAWL) 1.2",
        "attribution_name": "New Academic Word List",
        "sort_order": 3,
    },
    {
        "key": "medical",
        "title": "Medical English",
        "description": (
            "The words patients and health workers use with each other about "
            "the body, symptoms and treatment."
        ),
        "source_title": "Medical Oral English List (MOEL)",
        "attribution_name": "Medical Oral English List",
        "sort_order": 4,
    },
    {
        "key": "toeic",
        "title": "TOEIC",
        "description": (
            "The vocabulary the TOEIC test returns to, from offices and "
            "travel to shopping and meetings."
        ),
        "source_title": "TOEIC Service List (TSL) 1.2",
        "attribution_name": "TOEIC Service List",
        "sort_order": 5,
    },
)


def seed_rows() -> list[dict[str, Any]]:
    """The seeds as ``word_lists`` column dicts (no ``id``)."""
    rows = []
    for seed in WORD_LIST_SEEDS:
        rows.append(
            {
                "key": seed["key"],
                "title": seed["title"],
                "description": seed["description"],
                "source_title": seed["source_title"],
                "source_authors": AUTHORS,
                "licence_name": LICENCE_NAME,
                "licence_url": LICENCE_URL,
                "attribution": (
                    f"Based on the {seed['attribution_name']} by Browne, "
                    f"Culligan & Phillips. {LICENCE_NAME}."
                ),
                "sort_order": seed["sort_order"],
            }
        )
    return rows


async def seed_word_lists(session: AsyncSession) -> dict[str, WordList]:
    """Insert the five lists if missing, refresh their descriptive columns
    if present. Commits. Returns the rows by key."""
    for row in seed_rows():
        statement = insert(WordList).values(id=uuid.uuid4(), **row)
        update = {k: v for k, v in row.items() if k != "key"}
        await session.execute(
            statement.on_conflict_do_update(index_elements=["key"], set_=update)
        )
    await session.commit()
    rows = await session.exec(select(WordList))
    return {word_list.key: word_list for word_list in rows.all()}

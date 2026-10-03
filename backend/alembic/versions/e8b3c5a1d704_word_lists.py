"""word lists -- word_lists, word_list_entries, user_word_lists, saved_words.origin_list_id

Revision ID: e8b3c5a1d704
Revises: 5aa503d18266
Create Date: 2026-10-03 00:00:00.000000

Curated lists (Core, Business, Academic, Medical, TOEIC) a learner can draw
new words from. Subscribing is one `user_word_lists` row; a `saved_words`
row appears only when the learner first answers a list item (see
`backend/app/services/CLAUDE.md`, "Word lists"). `saved_words.origin_list_id`
records which list presented the word -- analytics only.

The data step inserts the five `word_lists` rows (a frozen copy of
`app.services.word_lists_seed`; the entries are filled by
`scripts/build_word_lists.py`, not here).

Reversible: `downgrade()` drops the column and the three tables.
"""
from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e8b3c5a1d704"
down_revision: Union[str, Sequence[str], None] = "5aa503d18266"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LICENCE = "CC BY-SA 4.0"
_URL = "https://creativecommons.org/licenses/by-sa/4.0/"
_AUTHORS = "Browne, Culligan & Phillips"

# key, title, description, source_title, name used in the credit, sort_order
_SEEDS = [
    (
        "core", "Core English",
        "The most common words in English, which cover most of what you read and hear every day.",
        "New General Service List (NGSL) 1.2", "New General Service List", 1,
    ),
    (
        "business", "Business English",
        "The words that keep coming back in meetings, emails, contracts and reports.",
        "Business Service List (BSL) 1.20", "Business Service List", 2,
    ),
    (
        "academic", "Academic English",
        "The words that university texts and lectures lean on, whatever the subject.",
        "New Academic Word List (NAWL) 1.2", "New Academic Word List", 3,
    ),
    (
        "medical", "Medical English",
        "The words patients and health workers use with each other about the body, symptoms and treatment.",
        "Medical Oral English List (MOEL)", "Medical Oral English List", 4,
    ),
    (
        "toeic", "TOEIC",
        "The vocabulary the TOEIC test returns to, from offices and travel to shopping and meetings.",
        "TOEIC Service List (TSL) 1.2", "TOEIC Service List", 5,
    ),
]


def upgrade() -> None:
    word_lists = op.create_table(
        "word_lists",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("key", sa.String(16), nullable=False),
        sa.Column("title", sa.String(80), nullable=False),
        sa.Column("description", sa.String(300), nullable=False, server_default=""),
        sa.Column("source_title", sa.String(160), nullable=False, server_default=""),
        sa.Column("source_authors", sa.String(160), nullable=False, server_default=""),
        sa.Column("licence_name", sa.String(60), nullable=False, server_default=""),
        sa.Column("licence_url", sa.String(200), nullable=False, server_default=""),
        sa.Column("attribution", sa.String(300), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_word_lists_key", "word_lists", ["key"], unique=True)

    op.create_table(
        "word_list_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "list_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("word_lists.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("lemma", sa.String(80), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("rank_source", sa.String(8), nullable=False, server_default="list"),
        sa.Column(
            "lexeme_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lexemes.id"), nullable=True,
        ),
        sa.Column(
            "sense_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lexeme_senses.id"), nullable=True,
        ),
        sa.UniqueConstraint("list_id", "lemma", name="uq_word_list_entry_lemma"),
    )
    op.create_index(
        "ix_word_list_entries_list_rank", "word_list_entries", ["list_id", "rank"]
    )
    op.create_index("ix_word_list_entries_lexeme_id", "word_list_entries", ["lexeme_id"])
    op.create_index("ix_word_list_entries_sense_id", "word_list_entries", ["sense_id"])

    op.create_table(
        "user_word_lists",
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column(
            "list_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("word_lists.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
    )

    op.add_column(
        "saved_words",
        sa.Column(
            "origin_list_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("word_lists.id", ondelete="SET NULL"), nullable=True,
        ),
    )

    op.bulk_insert(
        word_lists,
        [
            {
                "id": uuid.uuid4(),
                "key": key,
                "title": title,
                "description": description,
                "source_title": source_title,
                "source_authors": _AUTHORS,
                "licence_name": _LICENCE,
                "licence_url": _URL,
                "attribution": f"Based on the {credit} by {_AUTHORS}. {_LICENCE}.",
                "sort_order": sort_order,
            }
            for key, title, description, source_title, credit, sort_order in _SEEDS
        ],
    )


def downgrade() -> None:
    op.drop_column("saved_words", "origin_list_id")
    op.drop_table("user_word_lists")
    op.drop_index("ix_word_list_entries_sense_id", table_name="word_list_entries")
    op.drop_index("ix_word_list_entries_lexeme_id", table_name="word_list_entries")
    op.drop_index("ix_word_list_entries_list_rank", table_name="word_list_entries")
    op.drop_table("word_list_entries")
    op.drop_index("ix_word_lists_key", table_name="word_lists")
    op.drop_table("word_lists")

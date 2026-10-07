"""vocabulary stage 3 -- human word recordings and the learner's word voice

Revision ID: a8d5e2c1f730
Revises: f3a9c1d7e520
Create Date: 2026-10-07 21:00:00.000000

Phase 2b of the CALD integration: a word is spoken by the dictionary's human
recording where there is one for the learner's accent, by Kokoro otherwise.

* `vocabulary_settings.word_voice` -- `'recorded'` or `'synthetic'`, NOT NULL,
  server default `'recorded'` (every existing learner starts on the
  recording). Validated at the schema layer, so a third voice is not a
  migration.
* `word_recordings` -- one row per (sense, accent), UNIQUE, deleted with its
  sense. Schema only: `scripts/cald.py recordings --confirm-db <name>` writes
  the rows and the files, never a migration.

Reversible: `downgrade()` drops both.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a8d5e2c1f730"
down_revision: Union[str, Sequence[str], None] = "f3a9c1d7e520"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vocabulary_settings",
        sa.Column("word_voice", sa.String(16), nullable=False, server_default="recorded"),
    )
    op.create_table(
        "word_recordings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lexeme_sense_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("accent", sa.String(16), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("source_file", sa.String(120), nullable=False),
        sa.Column("basis", sa.String(8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lexeme_sense_id"], ["lexeme_senses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lexeme_sense_id", "accent", name="uq_word_recordings_sense_accent"),
    )


def downgrade() -> None:
    op.drop_table("word_recordings")
    op.drop_column("vocabulary_settings", "word_voice")

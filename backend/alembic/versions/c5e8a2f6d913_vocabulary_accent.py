"""vocabulary stage 3 -- the learner's accent choice

Revision ID: c5e8a2f6d913
Revises: a3c91e5d7f20
Create Date: 2026-10-07 00:00:00.000000

Decisions 22-26 of the stage 3 brief:

* `vocabulary_settings.accent` -- `'british'` or `'american'`, NOT NULL,
  server default `'british'`: every existing row becomes British, which is
  what they have been hearing. Validated at the schema layer, not here, so a
  third accent is not a migration.
* `lexeme_senses.pronunciation_us` -- the heteronym choice for the American
  voice, in misaki's American alphabet, beside the British
  `lexeme_senses.pronunciation`. Nullable, null for every sense that is not a
  heteronym or has no American decision yet; filled by
  `scripts/decide_heteronyms.py apply --accent american`.

Nothing is rewritten: American renders are new `audio_renders` rows (the voice
is part of every key), and the British ones keep their keys.

Reversible: `downgrade()` drops both columns.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5e8a2f6d913"
down_revision: Union[str, Sequence[str], None] = "a3c91e5d7f20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vocabulary_settings",
        sa.Column("accent", sa.String(16), nullable=False, server_default="british"),
    )
    op.add_column(
        "lexeme_senses", sa.Column("pronunciation_us", sa.String(120), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("lexeme_senses", "pronunciation_us")
    op.drop_column("vocabulary_settings", "accent")

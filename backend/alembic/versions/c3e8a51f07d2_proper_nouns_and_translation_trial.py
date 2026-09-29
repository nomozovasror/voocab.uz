"""lexemes.is_proper_noun; lexeme_senses.meaning_uz_prev / meaning_uz_alt_prev

Revision ID: c3e8a51f07d2
Revises: 88453c873f1f
Create Date: 2026-09-28 12:00:00.000000

## `lexemes.is_proper_noun`

Names (`alan`, `google`) are not vocabulary. The seed's candidate filter
always dropped them, but a name that only ever opens a sentence slipped
through it and the reading model glossed it anyway. Those with no material
row and no saved word are deleted by a data step (not this migration); the
few a learner has already met or saved are KEPT, marked here, carry no CEFR
(``cefr`` NULL -- the column was already nullable) and are left out of
practice. Defaults to ``false``.

## `lexeme_senses.meaning_uz_prev` / `meaning_uz_alt_prev`

The translation-prompt fix re-translates the senses the judge still calls
`different`. The old pair is stashed here BEFORE anything is overwritten, so
the decision (keep the new pair, or restore the old) is a data step over
rows that still hold both. Empty means "no trial".

## Reversibility

All three are additive, defaulted columns; `downgrade()` drops them.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3e8a51f07d2"
down_revision: Union[str, Sequence[str], None] = "88453c873f1f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lexemes",
        sa.Column("is_proper_noun", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index("ix_lexemes_is_proper_noun", "lexemes", ["is_proper_noun"])
    op.add_column(
        "lexeme_senses",
        sa.Column("meaning_uz_prev", sa.String(length=400), nullable=False, server_default=""),
    )
    op.add_column(
        "lexeme_senses",
        sa.Column("meaning_uz_alt_prev", sa.String(length=400), nullable=False,
                  server_default=""),
    )


def downgrade() -> None:
    op.drop_column("lexeme_senses", "meaning_uz_alt_prev")
    op.drop_column("lexeme_senses", "meaning_uz_prev")
    op.drop_index("ix_lexemes_is_proper_noun", table_name="lexemes")
    op.drop_column("lexemes", "is_proper_noun")

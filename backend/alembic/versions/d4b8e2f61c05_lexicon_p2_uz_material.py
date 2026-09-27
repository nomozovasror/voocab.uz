"""Lexicon P2: lexeme_senses.meaning_uz_material

Revision ID: d4b8e2f61c05
Revises: c7e2a9d40b18
Create Date: 2026-09-27 18:00:00.000000

* ``lexeme_senses.meaning_uz_material`` -- the material's own Uzbek a sense's
  ``meaning_uz`` was copied from, verbatim (empty when translated). P2
  rewrites sentence-style copies into dictionary style; this keeps the
  original for audit and lets a re-run recognise a copy it already rewrote.

Reversible: ``downgrade`` drops the column.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4b8e2f61c05'
down_revision: Union[str, Sequence[str], None] = 'c7e2a9d40b18'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lexeme_senses",
        sa.Column("meaning_uz_material", sa.String(length=400), nullable=False,
                  server_default=""),
    )
    op.alter_column("lexeme_senses", "meaning_uz_material", server_default=None)


def downgrade() -> None:
    op.drop_column("lexeme_senses", "meaning_uz_material")

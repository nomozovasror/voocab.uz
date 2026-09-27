"""Lexicon P2: lexemes.enriched_at, lexeme_senses.meaning_uz_alt

Revision ID: c7e2a9d40b18
Revises: b2d4f7e91a63
Create Date: 2026-09-27 15:00:00.000000

* ``lexemes.enriched_at`` -- P2's per-lexeme resume state. The enrichment
  (``app.services.lexicon_enrich``) writes one lexeme per transaction and
  sets this last, so a crash resumes at the first lexeme still null.
* ``lexeme_senses.meaning_uz_alt`` -- the second translator's Uzbek, kept so
  a reviewer sees both candidates when the judge disagreed.

Reversible: ``downgrade`` drops both columns and the index.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7e2a9d40b18'
down_revision: Union[str, Sequence[str], None] = 'b2d4f7e91a63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lexemes",
        sa.Column("enriched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f("ix_lexemes_enriched_at"), "lexemes", ["enriched_at"])
    op.add_column(
        "lexeme_senses",
        sa.Column("meaning_uz_alt", sa.String(length=400), nullable=False,
                  server_default=""),
    )
    op.alter_column("lexeme_senses", "meaning_uz_alt", server_default=None)


def downgrade() -> None:
    op.drop_column("lexeme_senses", "meaning_uz_alt")
    op.drop_index(op.f("ix_lexemes_enriched_at"), table_name="lexemes")
    op.drop_column("lexemes", "enriched_at")

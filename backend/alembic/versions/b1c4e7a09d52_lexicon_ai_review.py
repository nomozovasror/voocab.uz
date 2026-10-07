"""AI-assisted lexicon review -- a note for the human, and the undo log

Revision ID: b1c4e7a09d52
Revises: a8d5e2c1f730
Create Date: 2026-10-07 23:00:00.000000

* `lexeme_senses.review_note` -- text, NOT NULL, default `''`: why the AI
  review left a sense flagged "for a human". Studio shows it on the review row.
* `lexicon_ai_reviews` -- one row per decision `scripts/lexicon_ai_review.py
  apply` made, with the BEFORE and AFTER values of everything it changed, so
  `undo` can put a sense back exactly. Deleted with its sense.

Reversible: `downgrade()` drops both. (Dropping them forgets the way back for
decisions already applied; their approvals stay as the account's.)
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b1c4e7a09d52"
down_revision: Union[str, Sequence[str], None] = "a8d5e2c1f730"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lexeme_senses",
        sa.Column("review_note", sa.String(500), nullable=False, server_default=""),
    )
    op.create_table(
        "lexicon_ai_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sense_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=False),
        sa.Column("action", sa.String(8), nullable=False),
        sa.Column("confidence", sa.String(8), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("before", postgresql.JSONB(), nullable=False),
        sa.Column("after", postgresql.JSONB(), nullable=False),
        sa.Column("material_fixes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["sense_id"], ["lexeme_senses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lexicon_ai_reviews_sense_id", "lexicon_ai_reviews", ["sense_id"])
    op.create_index("ix_lexicon_ai_reviews_run_id", "lexicon_ai_reviews", ["run_id"])


def downgrade() -> None:
    op.drop_table("lexicon_ai_reviews")
    op.drop_column("lexeme_senses", "review_note")

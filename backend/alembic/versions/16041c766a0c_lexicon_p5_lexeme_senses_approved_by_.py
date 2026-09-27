"""Lexicon P5: lexeme_senses approved_by/approved_at

Revision ID: 16041c766a0c
Revises: d4b8e2f61c05
Create Date: 2026-09-27 16:46:41.209316

Studio's admin review tab (brief §6.2) needs to record who cleared a sense's
``needs_review`` flag and when -- "Approve" and "Fix" are both, in the end,
one reviewer's decision at one moment. Two columns rather than a separate
``lexeme_sense_reviews`` table: there is exactly one live reviewer per sense
(the one who most recently approved it), never a history of several, so a
row-per-review table would carry a cardinality this feature never needs. If
a later phase wants a full audit trail of every edit, that is a new table
added beside these, not a reason to model one now.

* ``approved_by`` -- nullable FK to ``users.id``, ``ON DELETE SET NULL`` (the
  same tolerance `translation_reports.material_vocabulary_id` already uses:
  losing the reviewer's account is not a reason to lose the fact that the
  sense was reviewed).
* ``approved_at`` -- nullable timestamp. Null means "never approved", which
  is what keeps a sense in the queue regardless of ``needs_review`` -- see
  the "core" bucket in `app.services.lexicon_review`, senses nobody has
  looked at yet but that were never flagged either.

Reversible: ``downgrade`` drops both columns.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '16041c766a0c'
down_revision: Union[str, Sequence[str], None] = 'd4b8e2f61c05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lexeme_senses",
        sa.Column("approved_by", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "lexeme_senses",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_lexeme_senses_approved_by", "lexeme_senses", "users",
        ["approved_by"], ["id"], ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_lexeme_senses_approved_at"), "lexeme_senses", ["approved_at"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_lexeme_senses_approved_at"), table_name="lexeme_senses")
    op.drop_constraint(
        "fk_lexeme_senses_approved_by", "lexeme_senses", type_="foreignkey",
    )
    op.drop_column("lexeme_senses", "approved_at")
    op.drop_column("lexeme_senses", "approved_by")

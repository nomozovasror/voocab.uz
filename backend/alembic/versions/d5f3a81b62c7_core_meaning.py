"""A word's usual meaning, beside the one this passage gives it

Revision ID: d5f3a81b62c7
Revises: c4e9b2f0a781
Create Date: 2026-09-22 00:00:00.000000

An entry used to carry one meaning, and that meaning was the passage's. The
reasoning is still in ``MaterialVocabulary``'s own docstring and still right:
``spring`` is a season in one passage and a coil in another, and a global
dictionary row has to pick one and is wrong for two thirds of the catalogue.

What it missed is that a learner does not stop at the passage. A text about
artificial intelligence gave ``learn`` the gloss "a computer process of
finding patterns in data", marked ``n`` — a correct reading of ``machine
learning`` and a false statement about the verb. Somebody who studies that
entry has learnt something wrong in every other sentence they will write.

So both are stored. ``meaning_core_*`` is what the word usually means and is
shown first; ``meaning_en``/``meaning_uz`` keep their meaning exactly and are
shown under "Here:" only where ``sense_differs`` says the two are genuinely
not the same.

Empty and false on every existing row, which is honest: nothing was asked
about the usual sense when they were written. The corpus is re-extracted to
fill them, and a saved word gets its copy topped up rather than rewritten —
see ``vocabulary.enrich_saved_contexts``.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5f3a81b62c7'
down_revision: Union[str, Sequence[str], None] = 'c4e9b2f0a781'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("material_vocabulary", "saved_word_contexts")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column(
            "meaning_core_en", sa.String(length=200),
            nullable=False, server_default=""))
        op.add_column(table, sa.Column(
            "meaning_core_uz", sa.String(length=200),
            nullable=False, server_default=""))
        op.add_column(table, sa.Column(
            "sense_differs", sa.Boolean(),
            nullable=False, server_default=sa.false()))


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, "sense_differs")
        op.drop_column(table, "meaning_core_uz")
        op.drop_column(table, "meaning_core_en")

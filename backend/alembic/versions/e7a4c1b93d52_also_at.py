"""Where else each glossed word stands in its passage

Revision ID: e7a4c1b93d52
Revises: d5f3a81b62c7
Create Date: 2026-09-22 00:00:00.000000

An entry carried one span, and the review drew exactly that one. ``AI
solutionism`` appears twice in Cambridge 21's third passage and only the
first of them was marked — which reads, to somebody using the page, as the
word list being incomplete rather than as the mark being economical.

Measured across the corpus: 17% of word entries appear more than once in
their own passage, and 8 864 occurrences had no mark on them at all.

One row per lemma per material stays exactly as it is — it is what makes a
tapped word have one answer — so the extra places are data on the row. They
cost nothing to produce: the deterministic scan in ``seed/vocabulary.py``
already walked every occurrence and was throwing all but the first away.

Empty on every existing row, and filled by ``read_vocabulary.py
--places-only``, which asks nobody anything.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e7a4c1b93d52'
down_revision: Union[str, Sequence[str], None] = 'd5f3a81b62c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("material_vocabulary", sa.Column(
        "also_at", postgresql.JSONB(astext_type=sa.Text()),
        nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("material_vocabulary", "also_at")

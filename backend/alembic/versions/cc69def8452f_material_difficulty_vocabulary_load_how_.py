"""material_difficulty.vocabulary_load: how much of the text is off the lists

Revision ID: cc69def8452f
Revises: b9026b88a3c3
Create Date: 2026-09-20 20:05:00.000000

The cold-start fix. A material nobody has sat carries ``New``, which is
honest and useless: the catalogue cannot sort it, a learner cannot choose by
it, and the recommender has nothing to reach for. But a material nobody has
sat still has its TEXT, and the text is measurable.

This column holds one number — the share of a passage's running words that
neither the NGSL nor the NAWL knows — measured once by ``seed/vocabulary.py``
while the passage is being read, and written here by the passage importer.
Below ``MIN_ANSWERS`` the band is estimated from it; at twenty answers the
measured proportion-correct takes over and this stops being consulted.

It lives in the projection rather than beside the passage because the
projection is what the catalogue filters and sorts by, and an estimate a
learner cannot find the material by is an estimate that only decorates a
row.

The one column here that is not a function of the attempts, which is why
``recompute`` reads it and never writes it: listing it in that upsert's
``set_`` would blank it on the worker's next pass.

Nullable, and null means unmeasured rather than easy — every listening paper,
and any reading one the extraction has not reached. Those keep saying ``New``,
which is what they are.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cc69def8452f'
down_revision: Union[str, Sequence[str], None] = 'b9026b88a3c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "material_difficulty",
        sa.Column("vocabulary_load", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("material_difficulty", "vocabulary_load")

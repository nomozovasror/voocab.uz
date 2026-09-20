"""material_vocabulary.unusual: a common word doing something unexpected

Revision ID: d41a70b5e8c2
Revises: cc69def8452f
Create Date: 2026-09-20 21:15:00.000000

``bank`` is NGSL rank 627 and ``spring`` is 1332, so the frequency filter
drops both — correctly by its own rule, and wrongly for a passage where one
is the side of a river and the other is a coil.

These are not rare words met for the first time. They are FAMILIAR words
doing something a reader does not expect, which is worse: nothing about them
looks difficult, so nothing signals that there is anything to check. They are
where an IELTS passage lays its traps.

No frequency list can find them — frequency is exactly what makes them
invisible — so they come from a third question asked of the whole passage,
beside the one about phrases.

A column rather than a derivation. ``frequency_band == "core" AND cefr_level
== "C1"`` would identify them today, purely because the candidate filter
drops everything under NGSL rank 2000 and so these are the only common words
in the table at all. That is a rule holding by accident of one constant, and
it would stop meaning anything, silently, the day the constant moved.

Defaults false, which is right for every row written before the question was
asked.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd41a70b5e8c2'
down_revision: Union[str, Sequence[str], None] = 'cc69def8452f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "material_vocabulary",
        sa.Column(
            "unusual", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.alter_column("material_vocabulary", "unusual", server_default=None)


def downgrade() -> None:
    op.drop_column("material_vocabulary", "unusual")

"""material difficulty projection, and the index the catalogue orders by

Revision ID: d2f8a3c15e47
Revises: a1c9f3d24b70
Create Date: 2026-08-26 12:00:00.000000

Difficulty is still a measurement and still nothing an author can set — this
table holds the tally, not an opinion, and every column in it is a function of
``question_attempts`` that ``app.services.difficulty.recompute`` refills from
scratch. Truncating it costs one pass of that job and nothing else; there is
no backfill in this migration for exactly that reason.

Why it exists: computed per request, the aggregate behind a difficulty band is
a scan of every answer on the platform, run again for every learner who opens
the practice page. That is affordable at fifteen materials and is not
affordable at a thousand. Here it is a primary-key lookup.

The second half of this migration is the index the catalogue's own query
wants. ``GET /api/listening/practice`` selects listening materials that are
public and orders them newest-first, and until now that was a sequential scan
plus a sort of the whole table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2f8a3c15e47'
down_revision: Union[str, Sequence[str], None] = 'a1c9f3d24b70'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "material_difficulty",
        # The material's own id is the key: there is nothing to say about a
        # material twice. CASCADE because a deleted material's tally is not a
        # fact about anything any more — and materials are deletable, taking
        # their attempts with them (app/services/materials.py).
        sa.Column("material_id", sa.Uuid(), nullable=False),
        sa.Column("answered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("band", sa.String(), nullable=False, server_default="new"),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["material_id"], ["materials.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("material_id"),
    )
    # What the band column is FOR: filtering and ordering the catalogue by
    # difficulty in SQL once the list is paginated. Derivable from the tally
    # beside it, indexed because a derived value you cannot filter on is a
    # value you have to fetch every row to use.
    op.create_index(
        "ix_material_difficulty_band", "material_difficulty", ["band"]
    )

    # The catalogue's own WHERE and ORDER BY, in one index. created_at
    # descending because newest-first is the order the endpoint returns and
    # the order the list header claims.
    op.create_index(
        "ix_materials_catalogue",
        "materials",
        ["type", "visibility", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_materials_catalogue", table_name="materials")
    op.drop_index("ix_material_difficulty_band", table_name="material_difficulty")
    op.drop_table("material_difficulty")

"""collection cover seed

A collection's cover is generated from a string (see
``frontend/src/features/listening/cover.ts``): stock, pattern and cut all
come out of one hash. Until now that string was the collection's id, which
made the cover stable forever and also made it the one thing about a
collection its author could not change.

``cover_seed`` is that string, when the author has asked for a different
book. Nullable, and null means "use the id" — so every collection that
already exists keeps the exact cover it has always had, and nothing has to
be backfilled.

Revision ID: c81d4f2a6b93
Revises: f9a2c47b83e1
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c81d4f2a6b93"
down_revision: Union[str, Sequence[str], None] = "f9a2c47b83e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "collections",
        sa.Column("cover_seed", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("collections", "cover_seed")

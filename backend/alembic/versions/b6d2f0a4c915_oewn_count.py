"""lexeme_senses.oewn_count

Revision ID: b6d2f0a4c915
Revises: e8b3c5a1d704
Create Date: 2026-10-03 12:00:00.000000

The SemCor tag COUNT behind `oewn_rank`, for the lookup's `most common` /
`common` / `less common` labels (a rank cannot say how far rank 2 is from
rank 1). Nullable: NULL = no OEWN data. Existing rows stay NULL until
`uv run python -m scripts.backfill_oewn_count` fills them from the OEWN
extract; nothing breaks before that (no count -> no label).

Reversible: `downgrade()` drops the column.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b6d2f0a4c915"
down_revision: Union[str, Sequence[str], None] = "e8b3c5a1d704"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("lexeme_senses", sa.Column("oewn_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("lexeme_senses", "oewn_count")

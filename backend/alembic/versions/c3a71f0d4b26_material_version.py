"""material version (optimistic concurrency)

Revision ID: c3a71f0d4b26
Revises: 8e971e17d8f8
Create Date: 2026-08-12 09:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3a71f0d4b26'
down_revision: Union[str, Sequence[str], None] = '8e971e17d8f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Existing rows start at 1, the same place a new material starts. The
    # server default is dropped afterwards: the model always supplies the
    # value, and leaving it would let a future INSERT silently skip it.
    op.add_column(
        'materials',
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
    )
    op.alter_column('materials', 'version', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('materials', 'version')

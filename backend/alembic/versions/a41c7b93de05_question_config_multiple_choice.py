"""question config (multiple choice)

Revision ID: a41c7b93de05
Revises: c3a71f0d4b26
Create Date: 2026-08-12 14:20:00.000000

Multiple choice needs a prompt and a list of options *per question*, where
form completion needed only a template *per group*. Both are presentation, so
they go where the group's presentation already goes — a JSONB ``config`` —
one level down, on the question.

Nullable rather than defaulted to ``{}``: NULL is what says "this question has
no presentation of its own", which is exactly true of a gap in a form, and is
what grading reads to tell an accepted-variants list from an answer key. Every
existing row is a form-completion gap, so they all stay NULL and no backfill
is needed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a41c7b93de05'
down_revision: Union[str, Sequence[str], None] = 'c3a71f0d4b26'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'questions',
        sa.Column(
            'config', postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Choice questions do not survive this: their prompt and options are only
    # in here. Their rows remain, and would come back as gaps with an answer
    # key of letters — so the downgrade drops them along with the column,
    # rather than leaving nonsense behind that grades.
    op.execute(
        "DELETE FROM question_attempts WHERE question_id IN "
        "(SELECT id FROM questions WHERE config IS NOT NULL)"
    )
    op.execute("DELETE FROM questions WHERE config IS NOT NULL")
    op.execute(
        "DELETE FROM question_groups WHERE type = 'multiple_choice'"
    )
    op.drop_column('questions', 'config')

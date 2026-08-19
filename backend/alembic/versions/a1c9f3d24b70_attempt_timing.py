"""attempt timing: how the answers were arrived at, and how the audio was used

Revision ID: a1c9f3d24b70
Revises: e5b34a0c71d9
Create Date: 2026-08-19 10:00:00.000000

Every column here is nullable and none of them defaults to 0, which is the
whole design. NULL means "this attempt predates the measurement", 0 means "we
measured, and it was zero". Backfilling a DEFAULT 0 would make every attempt
taken before today claim the learner never pressed play and never changed an
answer — a fabricated fact, indistinguishable afterwards from a real one, in
exactly the table difficulty scoring will be built on.

Nothing here is ever an input to grading. The values are reported by the page
the learner sat in front of, and a client that lies about them costs the
statistics and not the mark, which is why none of it is verified.

``question_attempts.hearings`` is the exception to "reported by the client":
the client is deliberately never told where in the recording the answers are
said, so it cannot count how often the learner played that stretch. It sends
the spans it played; the server crosses them with the ranges the AUTHOR marked
and writes the count here (see app/services/grading.py).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c9f3d24b70'
down_revision: Union[str, Sequence[str], None] = 'e5b34a0c71d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("attempts", sa.Column("listened_ms", sa.Integer(), nullable=True))
    op.add_column("attempts", sa.Column("seeks_back", sa.Integer(), nullable=True))

    op.add_column(
        "question_attempts",
        sa.Column("first_answered_ms", sa.Integer(), nullable=True),
    )
    op.add_column(
        "question_attempts", sa.Column("last_changed_ms", sa.Integer(), nullable=True)
    )
    op.add_column("question_attempts", sa.Column("changes", sa.Integer(), nullable=True))
    op.add_column("question_attempts", sa.Column("focus_ms", sa.Integer(), nullable=True))
    op.add_column(
        "question_attempts", sa.Column("hearings", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("question_attempts", "hearings")
    op.drop_column("question_attempts", "focus_ms")
    op.drop_column("question_attempts", "changes")
    op.drop_column("question_attempts", "last_changed_ms")
    op.drop_column("question_attempts", "first_answered_ms")

    op.drop_column("attempts", "seeks_back")
    op.drop_column("attempts", "listened_ms")

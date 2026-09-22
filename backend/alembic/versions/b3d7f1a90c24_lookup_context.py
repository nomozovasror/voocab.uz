"""lookup_events.context: asked during the paper, or after it

Revision ID: b3d7f1a90c24
Revises: a1c8e5d20f74
Create Date: 2026-09-22 00:00:00.000000

Looking a word up used to happen in one place — mid-paper, out of a budget of
three — so every row in this table meant the same thing and needed no label.
The review page now lets a reader tap any word in the passage, with no budget,
because the exam is over and what is left is studying.

Those two are not the same event and must not be counted as one. A ``take``
lookup says *this word stopped me badly enough to spend one of three.* A
``review`` lookup says something the platform has no other way to learn: *I
did not know this word, and I did not know that I did not know it* — the
reader went past it, answered the questions, and only found out afterwards.

That second population is the one worth acting on. A word many readers look
up in REVIEW which the extraction never offered is a word the frequency lists
and the learners disagree about, and the filter is what has to change.

``take`` for every existing row, which is what they all were: the review
lookup did not exist when they were written.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3d7f1a90c24'
down_revision: Union[str, Sequence[str], None] = 'a1c8e5d20f74'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lookup_events",
        sa.Column(
            "context",
            sa.String(length=8),
            nullable=False,
            server_default="take",
        ),
    )
    op.create_index(
        "ix_lookup_events_context", "lookup_events", ["context"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_lookup_events_context", table_name="lookup_events")
    op.drop_column("lookup_events", "context")

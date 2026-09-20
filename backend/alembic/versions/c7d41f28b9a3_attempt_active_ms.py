"""attempts.active_ms: the part of the sitting somebody was actually there for

Revision ID: c7d41f28b9a3
Revises: b3e91a7c40d2
Create Date: 2026-09-20 01:10:00.000000

``time_spent_ms`` is how long the page was open. It was also, until now, the
number every figure that measures a learner was built on: "time spent" on the
statistics page, pace, and the per-question timings behind "where you lose
marks".

Those are two different facts and only one of them is about the learner. A
candidate who opens a passage, switches tabs for twenty minutes and comes back
did not spend twenty-three minutes reading it. Listening hid the problem —
the recording is the clock there, and a paper cannot outlast it by much — and
reading has nothing of the kind, which is what makes the second column worth a
migration.

Nullable, and null means the attempt predates the measurement rather than that
nobody was present. Every reader falls back to ``time_spent_ms``, so no
existing attempt changes what it reports.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7d41f28b9a3'
down_revision: Union[str, Sequence[str], None] = 'b3e91a7c40d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("attempts", sa.Column("active_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("attempts", "active_ms")

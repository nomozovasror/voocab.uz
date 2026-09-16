"""attempts.group_id: the one question group a drill worked

A drill is one question group practised on its own — the map cut out of Part 2,
without the four multiple-choice questions printed beside it. The attempt still
belongs to the material the group came from, so nothing here loosens
``material_id``; this column says WHICH group was worked.

What makes an attempt a drill is its STATUS (``AttemptStatus.DRILLED``), not
this column. That distinction is deliberate: twenty queries across five
services ask "has this learner sat this material" by comparing
``status == 'submitted'``, and a third status excludes drills from all of them
at once. This column exists so the drill list can mark one done and the review
can find the next.

NULL means a sitting of the whole material, which is every row that exists
today, so nothing is backfilled.

Revision ID: a7e29c14b8d5
"""

import sqlalchemy as sa
from alembic import op

revision = "a7e29c14b8d5"
down_revision = "d3f7a1c95e02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("attempts", sa.Column("group_id", sa.Uuid(), nullable=True))
    op.create_index("ix_attempts_group_id", "attempts", ["group_id"])
    op.create_foreign_key(
        "fk_attempts_group_id_question_groups",
        "attempts",
        "question_groups",
        ["group_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_attempts_group_id_question_groups", "attempts", type_="foreignkey"
    )
    op.drop_index("ix_attempts_group_id", table_name="attempts")
    op.drop_column("attempts", "group_id")

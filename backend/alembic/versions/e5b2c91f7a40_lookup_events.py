"""lookup_events: one row every time a reader asked what a word meant

Revision ID: e5b2c91f7a40
Revises: d41a70b5e8c2
Create Date: 2026-09-21 09:30:00.000000

Written from the first day the feature ships, because every question this
table will be asked is a question about the past. Added in three months it
starts empty, and the three months worth knowing about are gone.

The column that cannot be reconstructed later is ``source``. A live lookup
saves its answer into ``material_vocabulary``, where it is indistinguishable
from one the seed pipeline wrote — so by the time anybody asks "what share
did we serve from the extraction", the evidence has erased itself. That
number decides whether pushing a five-thousand-word dictionary through the
pipeline in advance is worth anything.

``attempt_id`` is nullable and filled at SUBMIT, not here: no attempt row
exists while a paper is open. Null afterwards means the passage was never
finished, which is its own fact — three lookups and then abandoned is a
different story from three lookups and a score.

No unique constraint. The same reader asking the same word twice is two
events; the budget charges once, but that is a rule about fairness rather
than a claim about what happened, and somebody who checked a word three
times has told us something about the word.

Cheap: at most three rows per sitting.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'e5b2c91f7a40'
down_revision: Union[str, Sequence[str], None] = 'd41a70b5e8c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lookup_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("material_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=True),
        sa.Column("asked", sqlmodel.sql.sqltypes.AutoString(length=120), nullable=False),
        sa.Column("lemma", sqlmodel.sql.sqltypes.AutoString(length=80), nullable=False),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(length=8), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("found", sa.Boolean(), nullable=False),
        sa.Column("paragraph_index", sa.Integer(), nullable=True),
        sa.Column("offset", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["material_id"], ["materials.id"]),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_lookup_events_user_id"), "lookup_events", ["user_id"])
    op.create_index(op.f("ix_lookup_events_material_id"), "lookup_events", ["material_id"])
    op.create_index(op.f("ix_lookup_events_attempt_id"), "lookup_events", ["attempt_id"])
    op.create_index(op.f("ix_lookup_events_lemma"), "lookup_events", ["lemma"])
    op.create_index(op.f("ix_lookup_events_source"), "lookup_events", ["source"])


def downgrade() -> None:
    op.drop_table("lookup_events")

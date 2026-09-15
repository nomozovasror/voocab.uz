"""parts.first_number: where a part's numbering starts on its own paper

A real IELTS Listening paper numbers its questions 1 to 40 straight through,
so Part 4 is Questions 31-40 and the recording says so aloud. A seeded
material is ONE part of such a paper, and numbering it from 1 put "Question 1"
on screen while the audio said thirty-one.

NULL means "number from 1", which is what every part written by an author
means and what every existing row means, so nothing is backfilled.

Revision ID: d3f7a1c95e02
"""

import sqlalchemy as sa
from alembic import op

revision = "d3f7a1c95e02"
down_revision = "c81d4f2a6b93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("parts", sa.Column("first_number", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("parts", "first_number")

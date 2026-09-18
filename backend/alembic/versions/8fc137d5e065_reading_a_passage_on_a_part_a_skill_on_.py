"""reading: a passage on a part, a skill on a collection

Revision ID: 8fc137d5e065
Revises: a7e29c14b8d5
Create Date: 2026-09-18 15:31:01.087129

Two additive columns and nothing else. Reading needs no table of its own:
a reading paper is a Material of type ``reading`` holding Parts holding
question groups, exactly as a listening one does, and ``materials.type`` and
``question_groups.type`` are plain varchar, so the new type names and the six
new question-group types cost no DDL at all.

Hand-written rather than left as autogenerate wrote it. Autogenerate does not
know about the indexes and constraints earlier revisions created in raw SQL,
so it proposed dropping ``ix_materials_catalogue``, both trigram indexes, and
rewriting every ``ON DELETE CASCADE`` foreign key as a plain one -- a
migration that would have quietly cost the catalogue its search and its
cascades. Only the two ``add_column`` lines it found are real.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '8fc137d5e065'
down_revision: Union[str, Sequence[str], None] = 'a7e29c14b8d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # What a reading part's questions are answered from. NULL on every
    # listening part, which is answered from the recording instead.
    op.add_column(
        "parts",
        sa.Column("passage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    # Which paper a course is in. The server default backfills every existing
    # collection correctly -- all of them are listening courses -- and is then
    # dropped, so a row written from here on has to say what it is rather than
    # inheriting an answer from history.
    op.add_column(
        "collections",
        sa.Column(
            "skill", sa.String(), nullable=False, server_default="listening"
        ),
    )
    op.alter_column("collections", "skill", server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("collections", "skill")
    op.drop_column("parts", "passage")

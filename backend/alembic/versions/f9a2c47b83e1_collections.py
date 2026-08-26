"""collections: an ordered set of materials somebody put together on purpose

Revision ID: f9a2c47b83e1
Revises: e7b41c8d20a3
Create Date: 2026-08-26 16:00:00.000000

The catalogue answers what exists. A library of a thousand papers still cannot
say what to do in what order, and that is what these are for — a course, a
mock-test set, "the ten Part 3s worth doing first".

Two tables and nothing else. There is deliberately no enrolment table: a
learner's progress through a collection is derived from the attempts they have
already made, so opening one commits them to nothing and there is no state to
go stale when they wander off. Enrolment is a row that exists to be forgotten
about; an attempt is a row that had to exist anyway.

The unique constraint on (collection_id, order_index) is what makes the order
a real order rather than a hint, and it is why the item list is rewritten as a
unit rather than patched a row at a time — see
app/services/collections.set_items.

Both foreign keys cascade. A deleted collection's items are not facts about
anything; a deleted material's place in somebody's course is a hole, and a
hole that removes itself is better than one that 404s halfway down a page.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f9a2c47b83e1'
down_revision: Union[str, Sequence[str], None] = 'e7b41c8d20a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "collections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=False, server_default=""),
        sa.Column(
            "visibility", sa.String(), nullable=False, server_default="private"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_collections_author_id", "collections", ["author_id"])
    # What the learner-facing list selects and orders by, in one index.
    op.create_index(
        "ix_collections_public",
        "collections",
        ["visibility", sa.text("created_at DESC")],
    )

    op.create_table(
        "collection_items",
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("material_id", sa.Uuid(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["collections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["material_id"], ["materials.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("collection_id", "material_id"),
        sa.UniqueConstraint(
            "collection_id", "order_index", name="uq_collection_items_order"
        ),
    )
    # The reverse direction: "which collections is this material in", which is
    # what a material's own page will want and what the delete path walks.
    op.create_index(
        "ix_collection_items_material_id", "collection_items", ["material_id"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_collection_items_material_id", table_name="collection_items")
    op.drop_table("collection_items")
    op.drop_index("ix_collections_public", table_name="collections")
    op.drop_index("ix_collections_author_id", table_name="collections")
    op.drop_table("collections")

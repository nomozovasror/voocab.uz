"""materials.reference: where a seeded material came from in its book

Revision ID: b3e91a7c40d2
Revises: 8fc137d5e065
Create Date: 2026-09-19 22:30:00.000000

"C21 T1 P3" — Cambridge 21, test 1, passage 3. It was a suffix on the title
("Book review: The World of Sugar by Ulbe Bosma — C21 T1 P3") and three
different readers wanted it out of there, for what turned out to be one
reason.

The catalogue card wants to PRINT it separately. The name of the passage is
what a learner reads and recognises; which test it came from is a fact about
its provenance, and belongs on the meta line beside the part and the question
count, where the row already says the small factual things.

The seed importers want it as their dedup key. They had to use the title,
because the title was the only thing carrying the reference — which meant the
key was a display string, and a key inside a display string moves the moment
anybody edits the display. Renaming the corpus, which has now happened twice,
each time had to be done as a migration rather than a re-import for exactly
that reason.

And ``seed_status`` and ``publish_seeded`` want to ask "is this one of the
seeded ones". They were asking it with a regular expression over the title,
which had already been wrong once — it missed every listening material for a
month because "· Part 1" has a space in it where "P1" does not.

Nullable, and null is the normal case: everything an author writes here has
no book to point at. Indexed twice on purpose — a b-tree for the importers,
which look one up by its exact reference, and a trigram index for the
catalogue's search field, which looks for it with a leading wildcard and
cannot use a b-tree at all. The trigram argument is the one
``e7b41c8d20a3`` makes at length; ``collections.title`` gets one here too,
because the same search now reaches it and it arrived without one.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3e91a7c40d2'
down_revision: Union[str, Sequence[str], None] = '8fc137d5e065'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "materials",
        sa.Column("reference", sa.String(length=40), nullable=True),
    )
    op.create_index(
        "ix_materials_reference", "materials", ["reference"], unique=False
    )
    # pg_trgm is already installed by e7b41c8d20a3; IF NOT EXISTS so this
    # revision also stands on a database built from a later baseline.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX ix_materials_reference_trgm "
        "ON materials USING gin (lower(reference) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_collections_title_trgm "
        "ON collections USING gin (lower(title) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_collections_title_trgm")
    op.execute("DROP INDEX IF EXISTS ix_materials_reference_trgm")
    op.drop_index("ix_materials_reference", table_name="materials")
    op.drop_column("materials", "reference")

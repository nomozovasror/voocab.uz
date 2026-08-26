"""trigram indexes for the catalogue's search field

Revision ID: e7b41c8d20a3
Revises: d2f8a3c15e47
Create Date: 2026-08-26 15:00:00.000000

The catalogue searches titles and author names with ``lower(col) LIKE
'%term%'``, and a leading wildcard is exactly the shape a b-tree cannot help
with — every row, every term, every keystroke. At a few hundred materials that
is invisible; it is the query that gets slower fastest as the library grows,
because the field is used far more often than any chip.

``pg_trgm`` is what makes a leading wildcard indexable: it decomposes the text
into three-character sequences and indexes those, so ``%ridge%`` becomes a
lookup for the trigrams in "ridge" rather than a scan. GIN rather than GiST —
this is a read-mostly catalogue, and GIN is the faster of the two to search at
the cost of being slower to update, which is the right way round here.

Two things worth knowing before relying on it:

* A term shorter than three characters has no complete trigram, so Postgres
  falls back to a scan for it. That is correct rather than broken — "a" as a
  search term matches most of the library anyway — and it is why the query
  keeps working with no special case for short terms.
* ``CREATE EXTENSION`` needs elevated rights. It is ``IF NOT EXISTS`` so a
  database where a superuser has already enabled it upgrades cleanly, but a
  managed instance may need the extension turned on out of band first.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e7b41c8d20a3'
down_revision: Union[str, Sequence[str], None] = 'd2f8a3c15e47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Indexed on the same expression the query uses, lower() included. An
    # index on `title` would not be consulted for a search on `lower(title)`:
    # to Postgres those are two different expressions.
    op.execute(
        "CREATE INDEX ix_materials_title_trgm "
        "ON materials USING gin (lower(title) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_users_display_name_trgm "
        "ON users USING gin (lower(display_name) gin_trgm_ops)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_users_display_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_materials_title_trgm")
    # The extension is left in place. Something else may have come to depend
    # on it, and dropping an extension is not the business of the migration
    # that happened to enable it.

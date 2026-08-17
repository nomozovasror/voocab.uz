"""image_blob: the pictures a map or diagram task is labelled on

Revision ID: e5b34a0c71d9
Revises: b7e2c419af05
Create Date: 2026-08-17 10:00:00.000000

Content-addressed like ``audio_blob``, and for the same reason: two authors who
upload the same map are pointing at the same map, so the SHA-256 is the
identity and the unique index on it is what makes the upload endpoint's dedup
real rather than best-effort.

``width``/``height`` are NOT NULL because they are read from the file's own
header before the row is written — a picture whose size we couldn't read is one
the upload refuses, so there is no state where a row exists without them. That
is what lets the take page reserve the picture's box before its bytes arrive.

No per-owner table beside it. ``audio_blob`` has ``audio_asset`` because an
owner has something of their own to say about a shared recording (their
transcript corrections); a picture has no equivalent, and ownership here would
be bookkeeping that protects nothing, since the bytes are served from a public
URL either way.

Nothing references this yet: the groups that will name a picture do so from
their JSONB ``config``, which needs no migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'e5b34a0c71d9'
down_revision: Union[str, Sequence[str], None] = 'b7e2c419af05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "image_blob",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("storage_key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("mime_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_image_blob_sha256"), "image_blob", ["sha256"], unique=True
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_image_blob_sha256"), table_name="image_blob")
    op.drop_table("image_blob")

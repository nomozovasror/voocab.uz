"""vocabulary stage 3 -- live clips dropped: no `word_clips`, no clip items

Revision ID: d6a1f3b8e204
Revises: c5e8a2f6d913
Create Date: 2026-10-07 00:00:00.000000

The owner listened to the cut clips (fragments of neighbouring words, the
emotion and pitch of the sentence) and dropped them: every word is Kokoro TTS.

* `word_clips` goes. It only ever held candidates, cuts and verdicts about
  recordings; the recordings themselves are untouched.
* `audio_renders` rows of kind `item` that embedded a clip go too. Their key
  named the clip (the input holds `"source":"clip"` and the clip's storage
  key), so with the clip concept gone nothing can ever ask for that key again;
  leaving them would be rows pointing at something removed. An item is
  re-rendered on demand with the TTS word (a different input, hence a new key
  -- the TTS-worded items' keys are unchanged). Their FILES are not deleted
  here: a migration does not reach storage, and `check-files` / a manual
  sweep owns orphans.

Reversible in shape, not in data: `downgrade()` recreates `word_clips` EMPTY
(the candidates are re-indexed by code that no longer exists, so there is
nothing to restore) and the deleted item renders are not brought back -- they
are re-made on demand like any other.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d6a1f3b8e204"
down_revision: Union[str, Sequence[str], None] = "c5e8a2f6d913"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `item_spec` wrote the input with compact separators and sorted keys, so
    # the clip word part is exactly `"source":"clip"`.
    op.execute(
        "DELETE FROM audio_renders "
        "WHERE kind = 'item' AND input LIKE '%\"source\":\"clip\"%'"
    )
    op.drop_index("ix_word_clips_form_status", table_name="word_clips")
    op.drop_index("ix_word_clips_blob_id", table_name="word_clips")
    op.drop_table("word_clips")


def downgrade() -> None:
    # The table as a3c91e5d7f20 created it, empty.
    op.create_table(
        "word_clips",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("form", sa.String(160), nullable=False),
        sa.Column(
            "blob_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("audio_blob.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("segment_order_index", sa.Integer(), nullable=False),
        sa.Column("word_start_index", sa.Integer(), nullable=False),
        sa.Column("word_end_index", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("context_start_index", sa.Integer(), nullable=False),
        sa.Column("context_end_index", sa.Integer(), nullable=False),
        sa.Column("context_start_ms", sa.Integer(), nullable=False),
        sa.Column("context_end_ms", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=True),
        sa.Column("context_storage_key", sa.String(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="candidate"),
        sa.Column("heard", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cut_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "blob_id", "segment_order_index", "word_start_index", "word_end_index",
            name="uq_word_clip_place",
        ),
    )
    op.create_index("ix_word_clips_blob_id", "word_clips", ["blob_id"])
    op.create_index("ix_word_clips_form_status", "word_clips", ["form", "status"])

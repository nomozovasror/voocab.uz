"""vocabulary stage 3 -- the audio layer's whole schema

Revision ID: a3c91e5d7f20
Revises: b6d2f0a4c915
Create Date: 2026-10-04 00:00:00.000000

Everything stage 3 needs from the database, in one revision, so the engineers
who build `listen`, On the go and `speak` on top of the audio layer need no
migration of their own:

* `word_clips` -- a place in a recording where a lexicon form is spoken, and
  the small files cut from it (decisions 1, 3, 4).
* `audio_renders` -- the TTS / On-the-go render QUEUE and its output, keyed by
  the content address of the input (decisions 5, 7, 13).
* `lexeme_senses.pronunciation` -- misaki phonemes, heteronym senses only
  (decision 6).
* `vocabulary_settings.pronunciation` -- default TRUE, every existing row set
  to true (decision 20: nobody ever chose false, the control did not exist).
* `on_the_go_exposures` -- the exposure log (decision 14).
* `speak_misses` -- the speak-miss log (decision 18). Both keep their rows
  when a saved word is forgotten (`saved_word_id` is ON DELETE SET NULL, the
  `lemma` is copied), like `vocabulary_review_logs`.

Reversible: `downgrade()` drops them in the opposite order and puts the
settings default back.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3c91e5d7f20"
down_revision: Union[str, Sequence[str], None] = "b6d2f0a4c915"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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

    op.create_table(
        "audio_renders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("voice", sa.String(32), nullable=False),
        sa.Column("model", sa.String(48), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("storage_key", sa.String(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("word_offset_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        # A row is not claimable before this (a failure's back-off).
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_audio_renders_key", "audio_renders", ["key"], unique=True)
    op.create_index("ix_audio_renders_claim", "audio_renders", ["status", "created_at"])

    op.add_column("lexeme_senses", sa.Column("pronunciation", sa.String(120), nullable=True))

    # Decision 20. The server default covers rows written by code that never
    # heard of the column; the UPDATE is the backfill of the rows that exist.
    op.alter_column(
        "vocabulary_settings", "pronunciation",
        existing_type=sa.Boolean(), server_default=sa.true(), existing_nullable=False,
    )
    op.execute("UPDATE vocabulary_settings SET pronunciation = true")

    op.create_table(
        "on_the_go_exposures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "saved_word_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("saved_words.id", ondelete="SET NULL"), nullable=True,
        ),
        # Copied, like vocabulary_review_logs.lemma: forgetting a word keeps
        # its history, and the row must still say which word it was about.
        sa.Column("lemma", sa.String(80), nullable=False, server_default=""),
        sa.Column("played_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False, server_default="on_the_go"),
    )
    op.create_index(
        "ix_on_the_go_exposures_saved_word_id", "on_the_go_exposures", ["saved_word_id"]
    )
    op.create_index(
        "ix_on_the_go_exposures_user_played", "on_the_go_exposures", ["user_id", "played_at"]
    )

    op.create_table(
        "speak_misses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "saved_word_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("saved_words.id", ondelete="SET NULL"), nullable=True,
        ),
        # Copied, like vocabulary_review_logs.lemma: forgetting a word keeps
        # its history, and the row must still say which word it was about.
        sa.Column("lemma", sa.String(80), nullable=False, server_default=""),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column(
            "alternatives", postgresql.JSONB(), nullable=False, server_default="[]"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_speak_misses_saved_word_id", "speak_misses", ["saved_word_id"])
    op.create_index("ix_speak_misses_user_created", "speak_misses", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("speak_misses")
    op.drop_table("on_the_go_exposures")
    op.alter_column(
        "vocabulary_settings", "pronunciation",
        existing_type=sa.Boolean(), server_default=None, existing_nullable=False,
    )
    op.drop_column("lexeme_senses", "pronunciation")
    op.drop_table("audio_renders")
    op.drop_table("word_clips")

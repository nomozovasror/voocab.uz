"""vocabulary stage 3 -- On the go is client-sequenced: order and pause are the learner's

Revision ID: e7b2c4d9a315
Revises: d6a1f3b8e204
Create Date: 2026-10-07 00:00:00.000000

The owner rejected the composed item file (definition + 3 s + word): with the
order and the pause baked in, the learner could neither hear the word first nor
change the pause. The client now plays the word's own render and the sense's
definition render one after the other, so:

* `vocabulary_settings.on_the_go_order` -- `'meaning_first'` (default) or
  `'word_first'`, NOT NULL. Validated at the schema layer, like `accent`.
* `vocabulary_settings.on_the_go_pause_s` -- whole seconds between the two
  parts, NOT NULL, default 3 (1..10 at the schema layer).
* `audio_renders` rows of kind `item` are deleted, and `word_offset_ms` (set
  for items only) goes with them. Their FILES (`renders/...`) are not deleted
  here: a migration does not reach storage, so they are removed by hand.

`downgrade()` drops the two settings columns and re-adds `word_offset_ms`
EMPTY; the deleted item renders are not brought back (nothing in the code that
would ask for them survives either).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7b2c4d9a315"
down_revision: Union[str, Sequence[str], None] = "d6a1f3b8e204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vocabulary_settings",
        sa.Column(
            "on_the_go_order",
            sa.String(16),
            nullable=False,
            server_default="meaning_first",
        ),
    )
    op.add_column(
        "vocabulary_settings",
        sa.Column(
            "on_the_go_pause_s", sa.Integer(), nullable=False, server_default="3"
        ),
    )
    op.execute("DELETE FROM audio_renders WHERE kind = 'item'")
    op.drop_column("audio_renders", "word_offset_ms")


def downgrade() -> None:
    op.add_column(
        "audio_renders", sa.Column("word_offset_ms", sa.Integer(), nullable=True)
    )
    op.drop_column("vocabulary_settings", "on_the_go_pause_s")
    op.drop_column("vocabulary_settings", "on_the_go_order")

"""lexemes.is_function_word; lexeme_senses.oewn_rank

Revision ID: 5aa503d18266
Revises: c3e8a51f07d2
Create Date: 2026-09-29 12:00:00.000000

## `lexemes.is_function_word`

A grammatical function word (`the`, `of`, `have`, `not`, ...) or a
single-letter token (`a`, `i`) is not vocabulary, the same judgement
`is_proper_noun` makes about a name. Those with no material row and no
saved word are deleted by a data step (not this migration,
`scripts/lexicon_cleanup.py function-words`); the few a learner has already
met or saved are KEPT, marked here, and left out of practice. Defaults to
``false``.

## `lexeme_senses.oewn_rank`

An `oewn` sense's Princeton WordNet 3.1 SemCor tag-count rank among its
lemma's synsets -- previously only ever held in memory for the length of one
enrichment run (`lexicon_enrich.Sense.oewn_rank`), never written back to the
row it ranked. Persisted from this migration on so
`app.services.lexicon_licences` can show Princeton WordNet 3.1 on the public
licences page because the data actually used it, not as a permanent
hand-written claim. Null for a `model` sense, or one no backfill has reached
yet.

## Reversibility

Both are additive, defaulted/nullable columns; `downgrade()` drops them.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "5aa503d18266"
down_revision: Union[str, Sequence[str], None] = "c3e8a51f07d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lexemes",
        sa.Column("is_function_word", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index("ix_lexemes_is_function_word", "lexemes", ["is_function_word"])
    op.add_column(
        "lexeme_senses",
        sa.Column("oewn_rank", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("lexeme_senses", "oewn_rank")
    op.drop_index("ix_lexemes_is_function_word", table_name="lexemes")
    op.drop_column("lexemes", "is_function_word")

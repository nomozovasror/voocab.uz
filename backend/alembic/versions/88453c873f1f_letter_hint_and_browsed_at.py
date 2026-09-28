"""needs_letter_hint, browsed_at -- the recall cue and Browse mode

Revision ID: 88453c873f1f
Revises: a4fb4d79f1ac
Create Date: 2026-09-28 00:00:00.000000

Two independent, unrelated columns, bundled into one migration because
neither is worth a migration of its own and both come from the same brief
(`brief-vocabulary-tuzatish-browse.md`, parts B and C).

## `lexeme_senses.needs_letter_hint`

The recall prompt's first-letter cue used to be unconditional. It is now
shown only when ANOTHER lexeme's sense could plausibly be confused for this
one -- sharing an OEWN synset, or carrying a (near-)identical definition
after normalisation -- which is exactly the case a bare "starts with s"
narrows nothing for. Computed by `app.services.lexicon_hints.recompute_all`
(a data step run once by `scripts/backfill_letter_hint.py`, NOT inline in
this migration -- the comparison is O(senses) in Python, not a SQL
expression, and belongs beside the worker hook that keeps it fresh, not
duplicated into a one-off migration script). Defaults to ``false``, so a
database that has not yet run the backfill shows no cue anywhere rather than
guessing.

## `saved_words.browsed_at`

Browse (§C) is explicitly not practice: no `VocabularyReviewLog` row, no
FSRS card touched, no `due` change, nothing counted in daily minutes. The
one fact worth keeping is when a card was last shown while flipping through
the deck -- nullable, since most saved words have never been browsed.

## Reversibility

Both are additive, nullable-or-defaulted columns nothing yet depends on;
`downgrade()` simply drops them.

## The exposure aggregate's own indexes (A1)

The admin review queue's new ordering (`app.services.lexicon_review`) sums,
per sense, how many distinct learners submitted an attempt on a material
that glosses it. That query joins `attempts` to `material_vocabulary` on
`material_id` and filters on `status = 'submitted'` -- `attempts.material_id`
already has its own index, but the pair is worth its own composite one
rather than asking Postgres to intersect two indexes on every admin page
load.

The same query's other join -- `lookup_events` to `material_vocabulary` on
`(material_id, lemma)`, counting how many lookups resolved to each sense --
gets the identical treatment: `lookup_events` already has single-column
indexes on `material_id` and on `lemma` alone (from the table's own first
migration), which is exactly the "intersect two indexes" case the paragraph
above already calls out for `attempts`, and the fix is the same fix.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "88453c873f1f"
down_revision: Union[str, Sequence[str], None] = "a4fb4d79f1ac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lexeme_senses",
        sa.Column(
            "needs_letter_hint", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    op.add_column(
        "saved_words",
        sa.Column("browsed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_attempts_material_id_status", "attempts", ["material_id", "status"],
    )
    op.create_index(
        "ix_lookup_events_material_id_lemma", "lookup_events", ["material_id", "lemma"],
    )


def downgrade() -> None:
    op.drop_index("ix_lookup_events_material_id_lemma", table_name="lookup_events")
    op.drop_index("ix_attempts_material_id_status", table_name="attempts")
    op.drop_column("saved_words", "browsed_at")
    op.drop_column("lexeme_senses", "needs_letter_hint")

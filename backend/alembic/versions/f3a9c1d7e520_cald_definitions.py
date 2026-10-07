"""lexicon -- CALD definitions: where a definition came from, and the way back

Revision ID: f3a9c1d7e520
Revises: e7b2c4d9a315
Create Date: 2026-10-07 18:00:00.000000

Phase 2a of moving the lexicon's English definitions to the Cambridge
Advanced Learner's Dictionary (`app.services.lexicon_cald`). Schema only:
the data is written by `scripts/cald.py apply`, never by a migration.

## `lexeme_senses`

* `definition_source` -- whose TEXT `definition_en` is: `oewn` (an Open
  English WordNet synset's gloss), `model` (this project's own), `cald`, or
  `human` (a CALD sense a Studio reviewer rewrote).
  NOT NULL, backfilled from what each sense is today: `source_id = 'oewn'`
  -> `oewn`, anything else -> `model` (the two columns agree on every row
  this migration meets; `source_id` keeps saying where the SENSE came from).
* `cald_ref` -- the CALD sense (`entry#block#sense`) the definition was
  taken from; NULL unless `definition_source = 'cald'`.
* `cefr_source` -- `ours` (graded by this project: the model, or the
  material majority before that) or `cald` (CALD's per-sense level). NOT
  NULL, default `ours`.
* `cald_cefr` -- CALD's own level for `cald_ref`, applied or not: CALD's
  level is taken only within one band of ours, so where it is further away
  ours stays in `cefr` and both are on the row for the review queue
  (reason `cald_cefr_far`).
* `*_pre_cald` -- DURABLE copies of `definition_en`, `cefr`, `meaning_uz`,
  `meaning_uz_alt`, `licence`, `review_reasons` and `needs_review` as they
  were before the
  first CALD apply, with `cald_applied_at`. NULL = never applied.
  `scripts/cald.py restore` reads them back. (Unlike the retranslation
  trial's `meaning_uz_prev`, these are not cleared by a decision: the way
  back stays for as long as the CALD text does.)

## `material_vocabulary`

* `cefr_level_pre_cald` -- the row's `cefr_level` before a CALD level
  replaced it; NULL = not re-levelled.

## Reversibility

All additive; `downgrade()` drops them. Run `scripts/cald.py restore --all`
BEFORE a downgrade, or the CALD text stays in `definition_en` with nothing
left saying so.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f3a9c1d7e520"
down_revision: Union[str, Sequence[str], None] = "e7b2c4d9a315"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lexeme_senses",
        sa.Column("definition_source", sa.String(length=16), nullable=False,
                  server_default="model"),
    )
    op.execute("UPDATE lexeme_senses SET definition_source = 'oewn' WHERE source_id = 'oewn'")
    op.add_column("lexeme_senses", sa.Column("cald_ref", sa.String(length=200), nullable=True))
    op.add_column(
        "lexeme_senses",
        sa.Column("cefr_source", sa.String(length=8), nullable=False, server_default="ours"),
    )
    op.add_column("lexeme_senses", sa.Column("cald_cefr", sa.String(length=4), nullable=True))
    op.add_column("lexeme_senses",
                  sa.Column("definition_en_pre_cald", sa.String(length=400), nullable=True))
    op.add_column("lexeme_senses", sa.Column("cefr_pre_cald", sa.String(length=4), nullable=True))
    op.add_column("lexeme_senses",
                  sa.Column("meaning_uz_pre_cald", sa.String(length=400), nullable=True))
    op.add_column("lexeme_senses",
                  sa.Column("meaning_uz_alt_pre_cald", sa.String(length=400), nullable=True))
    op.add_column("lexeme_senses",
                  sa.Column("licence_pre_cald", sa.String(length=16), nullable=True))
    op.add_column("lexeme_senses",
                  sa.Column("review_reasons_pre_cald", postgresql.ARRAY(sa.TEXT()), nullable=True))
    op.add_column("lexeme_senses",
                  sa.Column("needs_review_pre_cald", sa.Boolean(), nullable=True))
    op.add_column("lexeme_senses",
                  sa.Column("cald_applied_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("material_vocabulary",
                  sa.Column("cefr_level_pre_cald", sa.String(length=4), nullable=True))


def downgrade() -> None:
    op.drop_column("material_vocabulary", "cefr_level_pre_cald")
    for column in ("cald_applied_at", "needs_review_pre_cald", "review_reasons_pre_cald",
                   "licence_pre_cald", "meaning_uz_alt_pre_cald", "meaning_uz_pre_cald",
                   "cefr_pre_cald", "definition_en_pre_cald", "cald_cefr", "cefr_source", "cald_ref",
                   "definition_source"):
        op.drop_column("lexeme_senses", column)

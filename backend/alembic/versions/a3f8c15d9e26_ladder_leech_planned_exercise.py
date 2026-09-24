"""Vocabulary stage 2: the ladder, leech, set-aside

Revision ID: a3f8c15d9e26
Revises: 1fc16780c6ce
Create Date: 2026-09-24 23:40:00.000000

Three additions, all read and written by ``app.services.practice`` alone:

* ``saved_words.passive_level`` (``recognise``/``recall``, never null) and
  ``active_level`` (``recognise``/``produce``, null = active not started) --
  the exercise actually SERVED, decided by the ladder in
  ``app.services.practice`` and stored rather than derived from the FSRS
  state, because promotion/demotion is a task-matching rule with its own
  streak logic and "has this word ever been higher" question, not a fact
  that falls out of stability or difficulty.
* ``saved_words.leech_reset_at`` / ``suspended_until`` -- the leech brief's
  three choices ("set aside 30 days" / "see it where you met it" / "keep
  practising") all either start a fresh lapse-counting window or set an
  expiry, and both are resolved lazily by the queries that read them (see
  ``practice._reap_suspensions``), never by a worker.
* ``vocabulary_review_logs.planned_exercise`` -- what the ladder ASKED for,
  independent of ``exercise_type`` (what was actually served). The two
  differ exactly when the distractor pipeline falls back to a harder
  exercise (too few good distractors, or a definition too short to quiz on)
  -- see ``app.services.distractors``. Nullable because every stage-1 row
  predates the column and never had a "plan" distinct from what it served.

Backfill: a word whose passive card was practised in stage 1
(``passive_state`` not null) starts stage 2 at ``recall`` -- it already
demonstrated recognition, repeatedly, and starting it back at the bottom of
its own ladder would be a demotion nobody's answer earned. A never-practised
word starts at ``recognise``, the ladder's own floor.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # SQLModel column types (e.g. AutoString) appear in autogen output


# revision identifiers, used by Alembic.
revision: str = 'a3f8c15d9e26'
down_revision: Union[str, Sequence[str], None] = '1fc16780c6ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('saved_words', sa.Column(
        'passive_level', sqlmodel.sql.sqltypes.AutoString(length=16),
        nullable=False, server_default='recognise'))
    op.add_column('saved_words', sa.Column(
        'active_level', sqlmodel.sql.sqltypes.AutoString(length=16),
        nullable=True))
    op.add_column('saved_words', sa.Column(
        'leech_reset_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('saved_words', sa.Column(
        'suspended_until', sa.DateTime(timezone=True), nullable=True))

    op.add_column('vocabulary_review_logs', sa.Column(
        'planned_exercise', sqlmodel.sql.sqltypes.AutoString(length=16),
        nullable=True))

    # A word already drilled in stage 1 has proven recognition, over and
    # over -- it starts stage 2 at `recall`, not back at the ladder's floor.
    op.execute("""
        UPDATE saved_words
        SET passive_level = 'recall'
        WHERE passive_state IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_column('vocabulary_review_logs', 'planned_exercise')
    op.drop_column('saved_words', 'suspended_until')
    op.drop_column('saved_words', 'leech_reset_at')
    op.drop_column('saved_words', 'active_level')
    op.drop_column('saved_words', 'passive_level')

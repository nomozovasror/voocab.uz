"""Vocabulary practice: FSRS cards, review logs, decks, settings

Revision ID: 1fc16780c6ce
Revises: e7a4c1b93d52
Create Date: 2026-09-24 22:19:51.747389

The vocabulary module's stage 1 brief (see ``docs`` handed to the agent, not
checked into this repo) settles the whole data model at once, on purpose:
every table a later stage needs is created here so none of them ever need a
second migration.

* ``saved_words`` gains a part of speech, a usual meaning and two independent
  FSRS cards -- ``passive`` (recognising the word) and ``active`` (producing
  it), because a learner can hold one skill without the other. Each card
  mirrors ``fsrs.Card`` exactly (``state``, ``step``, ``stability``,
  ``difficulty``, ``due``, ``last_review``); null ``{direction}_state`` means
  "never practised", which is a different fact from ``fsrs.State.Learning``
  and is why the column is nullable rather than defaulted to 1.
* ``saved_word_contexts`` gains the audio span a listening word was met in
  (null until stage 3 cuts anything) and ``seen_at`` (null until a later
  stage's "met again" signal writes it).
* ``vocabulary_review_logs`` is new: every answer, with the RAW typed text
  and the card's parameters after the answer, so FSRS's own parameters --
  fit on ~727 million reviews of somebody else's population -- can one day
  be re-fit on ours. See the model's own docstring for why each column is
  there.
* ``decks``/``deck_words`` exist so a later assignment system has somewhere
  to point; stage 1 resolves ``all`` and ``material`` decks virtually and
  creates no ``custom`` ones.
* ``vocabulary_settings`` holds all four preferences the brief's settings
  screen shows, though stage 1 only reads/writes ``daily_minutes`` -- adding
  the other three in a second migration would mean changing the row's shape
  under people who had already saved a preference.

The backfill at the end fills ``pos``/``meaning_core_en``/``meaning_core_uz``
on every EXISTING saved word from its newest context (``created_at`` desc),
falling back to that context's contextual meaning where it has no usual one
yet -- the same fallback ``MaterialVocabulary`` and the API already use for
a context enriched before this field existed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # SQLModel column types (e.g. AutoString) appear in autogen output
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '1fc16780c6ce'
down_revision: Union[str, Sequence[str], None] = 'e7a4c1b93d52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('saved_words', sa.Column(
        'pos', sqlmodel.sql.sqltypes.AutoString(length=8),
        nullable=False, server_default=''))
    op.add_column('saved_words', sa.Column(
        'meaning_core_en', sqlmodel.sql.sqltypes.AutoString(length=200),
        nullable=False, server_default=''))
    op.add_column('saved_words', sa.Column(
        'meaning_core_uz', sqlmodel.sql.sqltypes.AutoString(length=200),
        nullable=False, server_default=''))
    op.add_column('saved_words', sa.Column(
        'status', sqlmodel.sql.sqltypes.AutoString(length=16),
        nullable=False, server_default='learning'))
    op.create_index(op.f('ix_saved_words_status'), 'saved_words', ['status'])

    for direction in ('passive', 'active'):
        op.add_column('saved_words', sa.Column(
            f'{direction}_state', sa.SmallInteger(), nullable=True))
        op.add_column('saved_words', sa.Column(
            f'{direction}_step', sa.Integer(), nullable=True))
        op.add_column('saved_words', sa.Column(
            f'{direction}_stability', sa.Float(), nullable=True))
        op.add_column('saved_words', sa.Column(
            f'{direction}_difficulty', sa.Float(), nullable=True))
        op.add_column('saved_words', sa.Column(
            f'{direction}_due', sa.DateTime(timezone=True), nullable=True))
        op.add_column('saved_words', sa.Column(
            f'{direction}_last_review', sa.DateTime(timezone=True),
            nullable=True))

    op.add_column('saved_words', sa.Column(
        'lapses', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('saved_words', sa.Column(
        'reps', sa.Integer(), nullable=False, server_default='0'))

    op.add_column('saved_word_contexts', sa.Column(
        'audio_start_ms', sa.Integer(), nullable=True))
    op.add_column('saved_word_contexts', sa.Column(
        'audio_end_ms', sa.Integer(), nullable=True))
    op.add_column('saved_word_contexts', sa.Column(
        'seen_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        'vocabulary_settings',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('daily_minutes', sa.Integer(), nullable=False),
        sa.Column('direction', sqlmodel.sql.sqltypes.AutoString(length=8),
                  nullable=False),
        sa.Column('exercise_types', postgresql.ARRAY(sa.String(length=16)),
                  nullable=True),
        sa.Column('pronunciation', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('user_id'),
    )

    op.create_table(
        'decks',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(length=16),
                  nullable=False),
        sa.Column('material_id', sa.Uuid(), nullable=True),
        sa.Column('title', sqlmodel.sql.sqltypes.AutoString(length=200),
                  nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['material_id'], ['materials.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_decks_user_id'), 'decks', ['user_id'])

    op.create_table(
        'deck_words',
        sa.Column('deck_id', sa.Uuid(), nullable=False),
        sa.Column('saved_word_id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['deck_id'], ['decks.id']),
        sa.ForeignKeyConstraint(['saved_word_id'], ['saved_words.id']),
        sa.PrimaryKeyConstraint('deck_id', 'saved_word_id'),
    )

    op.create_table(
        'vocabulary_review_logs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('saved_word_id', sa.Uuid(), nullable=True),
        sa.Column('lemma', sqlmodel.sql.sqltypes.AutoString(length=80),
                  nullable=False),
        sa.Column('context_id', sa.Uuid(), nullable=True),
        sa.Column('direction', sqlmodel.sql.sqltypes.AutoString(length=8),
                  nullable=False),
        sa.Column('exercise_type', sqlmodel.sql.sqltypes.AutoString(length=16),
                  nullable=False),
        sa.Column('rating', sa.SmallInteger(), nullable=False),
        sa.Column('given', sqlmodel.sql.sqltypes.AutoString(length=200),
                  nullable=False, server_default=''),
        sa.Column('elapsed_ms', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('state', sa.SmallInteger(), nullable=False),
        sa.Column('stability', sa.Float(), nullable=True),
        sa.Column('difficulty', sa.Float(), nullable=True),
        # SET NULL, not CASCADE: "forget" removes a word from somebody's
        # list, and the answers it produced are real training data that
        # outlives the decision to stop studying one lemma. See the model.
        sa.ForeignKeyConstraint(['context_id'], ['saved_word_contexts.id'],
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['saved_word_id'], ['saved_words.id'],
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_vocabulary_review_logs_lemma'),
                    'vocabulary_review_logs', ['lemma'])
    op.create_index(op.f('ix_vocabulary_review_logs_saved_word_id'),
                    'vocabulary_review_logs', ['saved_word_id'])
    op.create_index(op.f('ix_vocabulary_review_logs_user_id'),
                    'vocabulary_review_logs', ['user_id'])

    # Backfill: every saved word's newest context supplies the part of
    # speech and usual meaning it never had a column for. `DISTINCT ON`
    # picks that one context per word directly in SQL rather than looping
    # in Python, which would be one round trip per saved word on a table
    # this pass may have to cross for every learner at once.
    #
    # `NULLIF(..., '') ` falls back to the contextual meaning when a
    # context predates `meaning_core_en` itself and was never enriched --
    # the same fallback `enrich_saved_contexts` and every reader of
    # `MaterialVocabulary` already use, so a word backfilled here shows
    # exactly what it would show if asked live.
    op.execute("""
        UPDATE saved_words AS sw
        SET pos = COALESCE(newest.pos, ''),
            meaning_core_en = COALESCE(
                NULLIF(newest.meaning_core_en, ''), newest.meaning_en, ''),
            meaning_core_uz = COALESCE(
                NULLIF(newest.meaning_core_uz, ''), newest.meaning_uz, '')
        FROM (
            SELECT DISTINCT ON (saved_word_id)
                saved_word_id, pos, meaning_core_en, meaning_core_uz,
                meaning_en, meaning_uz
            FROM saved_word_contexts
            ORDER BY saved_word_id, created_at DESC, id DESC
        ) AS newest
        WHERE sw.id = newest.saved_word_id
    """)


def downgrade() -> None:
    op.drop_index(op.f('ix_vocabulary_review_logs_user_id'),
                  table_name='vocabulary_review_logs')
    op.drop_index(op.f('ix_vocabulary_review_logs_saved_word_id'),
                  table_name='vocabulary_review_logs')
    op.drop_index(op.f('ix_vocabulary_review_logs_lemma'),
                  table_name='vocabulary_review_logs')
    op.drop_table('vocabulary_review_logs')

    op.drop_table('deck_words')

    op.drop_index(op.f('ix_decks_user_id'), table_name='decks')
    op.drop_table('decks')

    op.drop_table('vocabulary_settings')

    op.drop_column('saved_word_contexts', 'seen_at')
    op.drop_column('saved_word_contexts', 'audio_end_ms')
    op.drop_column('saved_word_contexts', 'audio_start_ms')

    op.drop_column('saved_words', 'reps')
    op.drop_column('saved_words', 'lapses')
    for direction in ('active', 'passive'):
        op.drop_column('saved_words', f'{direction}_last_review')
        op.drop_column('saved_words', f'{direction}_due')
        op.drop_column('saved_words', f'{direction}_difficulty')
        op.drop_column('saved_words', f'{direction}_stability')
        op.drop_column('saved_words', f'{direction}_step')
        op.drop_column('saved_words', f'{direction}_state')
    op.drop_index(op.f('ix_saved_words_status'), table_name='saved_words')
    op.drop_column('saved_words', 'status')
    op.drop_column('saved_words', 'meaning_core_uz')
    op.drop_column('saved_words', 'meaning_core_en')
    op.drop_column('saved_words', 'pos')

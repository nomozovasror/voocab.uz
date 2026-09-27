"""Lexicon P1: lexemes, lexeme_senses, translation_reports, users.is_admin

Revision ID: b2d4f7e91a63
Revises: a3f8c15d9e26
Create Date: 2026-09-27 09:00:00.000000

`brief-lexicon.md` builds a global vocabulary independent of any material:
`material_vocabulary` answers "what does this word mean IN THIS PASSAGE" (24
000+ rows, one per word per material) and cannot answer "how many words does
this platform teach" -- `appropriate` is one word to a learner and up to
seventeen rows to that table. See `app.models.lexicon` for the full
reasoning behind the shape below; this migration is schema only.

* ``lexemes`` -- one row per ``(lemma, pos)``, global. ``cefr`` is a
  denormalisation of its rank-1 sense, recomputed by the build script, never
  hand-set; null until the lexeme has a sense at all.
* ``lexeme_senses`` -- one row per MEANING. CEFR lives here, not on the
  lexeme, because level is a fact about a sense (`spring` the season is not
  `spring` the coil). ``review_reasons`` is a text array kept separate from
  the plain ``needs_review`` boolean so each failure mode can be counted on
  its own (`lexicon-spec.md` D5).
* ``material_vocabulary.lexeme_id``/``sense_id`` -- nullable in the DDL
  because a migration cannot backfill 24 000+ rows inside the transaction
  that adds the column without holding a lock on it for the length of the
  backfill. ``backend/scripts/build_lexicon.py`` fills every row immediately
  after this migration runs; that script's own verification is "is any row
  still null".
* ``translation_reports`` -- "this translation is wrong", filed from the
  word page or a practice reveal (brief §6.3). Schema only: nothing writes
  to it until a later phase wires up the link.
* ``users.is_admin`` -- the whole of this project's admin story (brief §6.2,
  D7): one flag, no role table, because the only screen it gates is a single
  Studio review tab (P5).

Reversible: ``downgrade`` drops everything in reverse dependency order.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b2d4f7e91a63'
down_revision: Union[str, Sequence[str], None] = 'a3f8c15d9e26'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lexemes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("lemma", sqlmodel.sql.sqltypes.AutoString(length=80), nullable=False),
        sa.Column("pos", sqlmodel.sql.sqltypes.AutoString(length=8), nullable=False),
        sa.Column("is_phrase", sa.Boolean(), nullable=False),
        sa.Column("cefr", sqlmodel.sql.sqltypes.AutoString(length=4), nullable=True),
        sa.Column("frequency_band", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=True),
        sa.Column("frequency_source", sqlmodel.sql.sqltypes.AutoString(length=8), nullable=True),
        sa.Column(
            "domain_tags", postgresql.ARRAY(sa.TEXT()),
            nullable=False, server_default="{}",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lemma", "pos", name="uq_lexeme_lemma_pos"),
    )
    op.create_index(op.f("ix_lexemes_lemma"), "lexemes", ["lemma"])
    op.create_index(op.f("ix_lexemes_cefr"), "lexemes", ["cefr"])
    op.create_index(op.f("ix_lexemes_frequency_band"), "lexemes", ["frequency_band"])

    op.create_table(
        "lexeme_senses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("lexeme_id", sa.Uuid(), nullable=False),
        sa.Column("sense_rank", sa.Integer(), nullable=False),
        sa.Column("definition_en", sqlmodel.sql.sqltypes.AutoString(length=400), nullable=False),
        sa.Column("meaning_uz", sqlmodel.sql.sqltypes.AutoString(length=400), nullable=False),
        sa.Column("cefr", sqlmodel.sql.sqltypes.AutoString(length=4), nullable=True),
        sa.Column("oewn_synset_id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True),
        sa.Column("source_id", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("licence", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column(
            "review_reasons", postgresql.ARRAY(sa.TEXT()),
            nullable=False, server_default="{}",
        ),
        sa.Column("provisional", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["lexeme_id"], ["lexemes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_lexeme_senses_lexeme_id"), "lexeme_senses", ["lexeme_id"])
    op.create_index(op.f("ix_lexeme_senses_cefr"), "lexeme_senses", ["cefr"])
    op.create_index(op.f("ix_lexeme_senses_oewn_synset_id"), "lexeme_senses", ["oewn_synset_id"])
    op.create_index(op.f("ix_lexeme_senses_needs_review"), "lexeme_senses", ["needs_review"])
    op.create_index(op.f("ix_lexeme_senses_provisional"), "lexeme_senses", ["provisional"])

    op.add_column(
        "material_vocabulary",
        sa.Column("lexeme_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "material_vocabulary",
        sa.Column("sense_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_material_vocabulary_lexeme_id", "material_vocabulary", "lexemes",
        ["lexeme_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_material_vocabulary_sense_id", "material_vocabulary", "lexeme_senses",
        ["sense_id"], ["id"],
    )
    op.create_index(
        op.f("ix_material_vocabulary_lexeme_id"), "material_vocabulary", ["lexeme_id"],
    )
    op.create_index(
        op.f("ix_material_vocabulary_sense_id"), "material_vocabulary", ["sense_id"],
    )

    op.create_table(
        "translation_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("lexeme_sense_id", sa.Uuid(), nullable=False),
        sa.Column("material_vocabulary_id", sa.Uuid(), nullable=True),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("note", sqlmodel.sql.sqltypes.AutoString(length=500), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["lexeme_sense_id"], ["lexeme_senses.id"]),
        sa.ForeignKeyConstraint(
            ["material_vocabulary_id"], ["material_vocabulary.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_translation_reports_user_id"), "translation_reports", ["user_id"],
    )
    op.create_index(
        op.f("ix_translation_reports_lexeme_sense_id"), "translation_reports",
        ["lexeme_sense_id"],
    )
    op.create_index(
        op.f("ix_translation_reports_status"), "translation_reports", ["status"],
    )

    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("users", "is_admin", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "is_admin")

    op.drop_index(op.f("ix_translation_reports_status"), table_name="translation_reports")
    op.drop_index(
        op.f("ix_translation_reports_lexeme_sense_id"), table_name="translation_reports",
    )
    op.drop_index(op.f("ix_translation_reports_user_id"), table_name="translation_reports")
    op.drop_table("translation_reports")

    op.drop_index(op.f("ix_material_vocabulary_sense_id"), table_name="material_vocabulary")
    op.drop_index(op.f("ix_material_vocabulary_lexeme_id"), table_name="material_vocabulary")
    op.drop_constraint(
        "fk_material_vocabulary_sense_id", "material_vocabulary", type_="foreignkey",
    )
    op.drop_constraint(
        "fk_material_vocabulary_lexeme_id", "material_vocabulary", type_="foreignkey",
    )
    op.drop_column("material_vocabulary", "sense_id")
    op.drop_column("material_vocabulary", "lexeme_id")

    op.drop_index(op.f("ix_lexeme_senses_provisional"), table_name="lexeme_senses")
    op.drop_index(op.f("ix_lexeme_senses_needs_review"), table_name="lexeme_senses")
    op.drop_index(op.f("ix_lexeme_senses_oewn_synset_id"), table_name="lexeme_senses")
    op.drop_index(op.f("ix_lexeme_senses_cefr"), table_name="lexeme_senses")
    op.drop_index(op.f("ix_lexeme_senses_lexeme_id"), table_name="lexeme_senses")
    op.drop_table("lexeme_senses")

    op.drop_index(op.f("ix_lexemes_frequency_band"), table_name="lexemes")
    op.drop_index(op.f("ix_lexemes_cefr"), table_name="lexemes")
    op.drop_index(op.f("ix_lexemes_lemma"), table_name="lexemes")
    op.drop_table("lexemes")

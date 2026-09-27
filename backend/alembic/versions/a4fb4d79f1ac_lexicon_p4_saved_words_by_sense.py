"""Lexicon P4: saved_words keyed by sense, translation_reports made real

Revision ID: a4fb4d79f1ac
Revises: 16041c766a0c
Create Date: 2026-09-27 18:00:00.000000

`brief-lexicon.md` §3 / decision D4: a saved word is one `LexemeSense` per
learner, not one lemma. `bank` (finance) and `bank` (river) are two words to
study and two FSRS cards -- the dedup-by-lemma design saved from stage 1
could not tell them apart, and a card that tried to be both taught neither.

## The column, and what stays

``saved_words.lexeme_sense_id`` is the new key: NOT NULL, FK to
``lexeme_senses.id``, no ``ondelete`` -- a sense a saved word points at must
be REPOINTED before it is ever deleted (see `app.services.lexicon_enrich
._absorb`, updated alongside this migration to repoint saved words the same
way it already repoints `material_vocabulary.sense_id` and
`translation_reports.lexeme_sense_id` when two provisional senses merge).
``lemma`` stays as a denormalised display/search column -- two rows may now
legitimately share it -- and ``meaning_core_en``/``meaning_core_uz`` stay on
the table but dead: nothing writes them from this point on and nothing
reads them either, because a saved word's usual meaning/definition/CEFR are
now read LIVE from its `LexemeSense` (`app.services.vocabulary`), which is
what lets an admin's fix in Studio reach every learner already studying the
word instead of only the next one who saves it.

## The backfill

Every saved word's contexts point (via `vocabulary_id`, or failing that
`(material_id, lemma)`) at whatever `MaterialVocabulary` row they were saved
from, and that row already carries a `sense_id` -- P1's corpus-wide backfill
and P3's `link_row` between them mean essentially every row has one, but the
migration does not assume it: a context that resolves to nothing usable
falls back to its lexeme's rank-1 sense, and a saved word with no contexts
at all (should not happen, kept defensive) does the same by its own
lemma/pos.

A word's contexts do not have to agree. Two contexts of one saved word that
resolve to the SAME sense are one word, unchanged. Two that resolve to
DIFFERENT senses are two words that happened to share a spelling: the
NEWEST context's sense keeps this row's id (and therefore its FSRS cards and
review log history -- the learner's most recent encounter is the one still
worth the card that already exists), and every other resolved sense buys a
brand-new saved word, with fresh FSRS state (`status='learning'`,
`passive_level='recognise'`, no stability/difficulty/due, zero lapses/reps)
-- a meaning the learner has not actually been drilled on yet must not
inherit a card's schedule from an unrelated meaning.

A LAST pass (`_merge_cross_word_collisions`), after every word above has
been resolved, catches the collision the per-word pass above cannot see:
two words that started life as DIFFERENT raw lemmas -- `saved_words` has
never merged by inflection the way the lexicon tables do -- can still land
on the identical sense, because the corpus's own inflectional merge
(`app.services.lexicon.merge_candidate`) folded that lemma pair into one
`Lexeme` sometime after both were saved. Found on a real dev copy, not
hypothesised: this is the dry run's whole reason for existing. The OLDER
word survives (real FSRS history outranks a split artifact created moments
earlier purely to hold a context) and the other's contexts move onto it.

`upgrade()` logs, at INFO, how many saved words were mapped without a split,
how many extra words a split produced, how many context resolutions fell
all the way back to a lexeme's rank-1 sense for want of anything better, and
how many were merged back together as a cross-word collision -- the numbers
this phase's dry run against a copy of the dev database is asked to report.

## Reversibility

`downgrade()` drops the column and its constraints and restores
`uq_saved_user_lemma`. That restore only succeeds if the two features this
migration turns on were never used: no split has ever produced a second
saved word sharing a lemma with the first, and no later save has legitimately
created two senses of one lemma for one learner (which, after this
migration, is no longer a bug -- it is the whole point). A downgrade run
against a database that has actually lived with this schema for a while is
expected to fail loudly on that constraint rather than silently merging two
different meanings back into one row; that failure is correct, not a defect
in this migration.

`translation_reports` also gains a partial unique index -- `(user_id,
lexeme_sense_id)` where `status = 'open'` -- which is the whole of "one open
report per (user, sense); repeat = no-op" enforced at the one layer that
cannot race.
"""
from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4fb4d79f1ac"
down_revision: Union[str, Sequence[str], None] = "16041c766a0c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")


def _rank1_sense_for(bind, lemma: str, pos: str) -> uuid.UUID:
    """The lexeme's commonest sense, by ``(lemma, pos)`` first and by
    ``lemma`` alone if that fails -- the migration's own last-resort
    fallback for a context (or a whole saved word) that cannot be traced
    back to any `MaterialVocabulary` row at all.

    Every material row this project has should already carry a
    `lexeme_id`/`sense_id` (P1's corpus backfill, P3's `link_row` on every
    write since) -- so the deepest branch here, which invents a brand-new
    provisional `Lexeme`/`LexemeSense` from nothing but the saved word's own
    lemma, is not expected to fire against real data. It exists so the
    `NOT NULL` this migration adds can never fail the run over a row this
    defensive rather than leaving one saved word permanently unmigratable.
    """
    row = None
    if pos:
        row = bind.execute(
            sa.text(
                "SELECT ls.id FROM lexeme_senses ls "
                "JOIN lexemes lx ON lx.id = ls.lexeme_id "
                "WHERE lx.lemma = :lemma AND lx.pos = :pos "
                "ORDER BY ls.sense_rank ASC LIMIT 1"
            ),
            {"lemma": lemma, "pos": pos},
        ).first()
    if row is None:
        row = bind.execute(
            sa.text(
                "SELECT ls.id FROM lexeme_senses ls "
                "JOIN lexemes lx ON lx.id = ls.lexeme_id "
                "WHERE lx.lemma = :lemma "
                "ORDER BY ls.sense_rank ASC LIMIT 1"
            ),
            {"lemma": lemma},
        ).first()
    if row is not None:
        return row[0]

    lexeme_id = uuid.uuid4()
    bind.execute(
        sa.text(
            "INSERT INTO lexemes "
            "(id, lemma, pos, is_phrase, domain_tags, created_at, updated_at) "
            "VALUES (:id, :lemma, :pos, false, '{}', now(), now())"
        ),
        {"id": lexeme_id, "lemma": lemma, "pos": pos or ""},
    )
    sense_id = uuid.uuid4()
    bind.execute(
        sa.text(
            "INSERT INTO lexeme_senses "
            "(id, lexeme_id, sense_rank, definition_en, meaning_uz, "
            "meaning_uz_alt, meaning_uz_material, source_id, licence, "
            "needs_review, review_reasons, provisional, created_at, updated_at) "
            "VALUES (:id, :lexeme_id, 1, '', '', '', '', 'model', 'proprietary', "
            "false, '{}', true, now(), now())"
        ),
        {"id": sense_id, "lexeme_id": lexeme_id},
    )
    return sense_id


def _resolve_context_sense(bind, context: dict, lemma: str) -> tuple[uuid.UUID, bool]:
    """The sense a context maps to, and whether that was a fallback."""
    if context["vocabulary_id"] is not None:
        row = bind.execute(
            sa.text("SELECT sense_id FROM material_vocabulary WHERE id = :id"),
            {"id": context["vocabulary_id"]},
        ).first()
        if row is not None and row[0] is not None:
            return row[0], False

    row = bind.execute(
        sa.text(
            "SELECT sense_id FROM material_vocabulary "
            "WHERE material_id = :mid AND lemma = :lemma AND sense_id IS NOT NULL "
            "LIMIT 1"
        ),
        {"mid": context["material_id"], "lemma": lemma},
    ).first()
    if row is not None:
        return row[0], False

    return None, True  # resolved below, once the caller has `pos`


def _backfill_saved_words(bind) -> dict[str, int]:
    stats = {"words": 0, "mapped": 0, "split": 0, "fallback": 0}

    words = bind.execute(
        sa.text("SELECT id, lemma, pos FROM saved_words")
    ).mappings().all()
    stats["words"] = len(words)

    contexts_by_word: dict[uuid.UUID, list[dict]] = defaultdict(list)
    for row in bind.execute(
        sa.text(
            "SELECT id, saved_word_id, material_id, vocabulary_id "
            "FROM saved_word_contexts ORDER BY saved_word_id, created_at, id"
        )
    ).mappings():
        contexts_by_word[row["saved_word_id"]].append(dict(row))

    for word in words:
        word_id, lemma, pos = word["id"], word["lemma"], word["pos"] or ""
        contexts = contexts_by_word.get(word_id, [])

        if not contexts:
            sense_id = _rank1_sense_for(bind, lemma, pos)
            bind.execute(
                sa.text(
                    "UPDATE saved_words SET lexeme_sense_id = :sense_id WHERE id = :id"
                ),
                {"sense_id": sense_id, "id": word_id},
            )
            stats["mapped"] += 1
            stats["fallback"] += 1
            continue

        resolved: list[tuple[dict, uuid.UUID]] = []
        for context in contexts:
            sense_id, fell_back = _resolve_context_sense(bind, context, lemma)
            if fell_back:
                sense_id = _rank1_sense_for(bind, lemma, pos)
                stats["fallback"] += 1
            resolved.append((context, sense_id))

        by_sense: dict[uuid.UUID, list[dict]] = defaultdict(list)
        for context, sense_id in resolved:
            by_sense[sense_id].append(context)

        # The newest context is the last in `resolved` -- contexts were
        # loaded ordered by (created_at, id) per word above.
        newest_sense_id = resolved[-1][1]
        bind.execute(
            sa.text(
                "UPDATE saved_words SET lexeme_sense_id = :sense_id WHERE id = :id"
            ),
            {"sense_id": newest_sense_id, "id": word_id},
        )
        stats["mapped"] += 1

        for sense_id, group in by_sense.items():
            if sense_id == newest_sense_id:
                continue
            new_word_id = uuid.uuid4()
            bind.execute(
                sa.text(
                    "INSERT INTO saved_words "
                    "(id, user_id, lemma, lexeme_sense_id, pos, status, "
                    "passive_level, lapses, reps, created_at) "
                    "SELECT :new_id, user_id, lemma, :sense_id, pos, "
                    "'learning', 'recognise', 0, 0, now() "
                    "FROM saved_words WHERE id = :old_id"
                ),
                {"new_id": new_word_id, "sense_id": sense_id, "old_id": word_id},
            )
            for context in group:
                bind.execute(
                    sa.text(
                        "UPDATE saved_word_contexts SET saved_word_id = :new_id "
                        "WHERE id = :id"
                    ),
                    {"new_id": new_word_id, "id": context["id"]},
                )
            stats["split"] += 1

    stats["merged"] = _merge_cross_word_collisions(bind)
    return stats


def _merge_cross_word_collisions(bind) -> int:
    """After every original word above has been resolved (and possibly
    split), two words that started out as DIFFERENT raw lemmas can still
    land on the SAME sense -- `saved_words` has never merged by lemma
    inflection the way the lexicon tables do (`app.services.lexicon
    .merge_candidate`), so a learner who saved both `leverage` and
    `leveraging` before the corpus's own inflectional rule folded that
    lemma pair into one `Lexeme` now has two saved words for one sense, a
    real collision the resolution pass above has no way to see one word at
    a time. Found here, once, over the whole table.

    The OLDEST word (by `created_at`) survives -- real accumulated FSRS
    history outranks a same-day split artifact created moments ago by the
    pass above purely to hold a context -- and every other's contexts move
    onto it (a context for a material the survivor already has is dropped,
    per `uq_saved_context_material`; the survivor's own meeting of the word
    stands). The losing word's review logs keep pointing at nothing
    (`ON DELETE SET NULL`) rather than being merged into the survivor's
    history, the same tolerance `app.services.lexicon_enrich._repoint_saved_
    words` accepts for the identical shape of collision at enrichment time:
    there is no honest way to combine two schedules into one.
    """
    merged = 0
    groups = bind.execute(
        sa.text(
            "SELECT user_id, lexeme_sense_id, array_agg(id ORDER BY created_at) AS ids "
            "FROM saved_words GROUP BY user_id, lexeme_sense_id HAVING count(*) > 1"
        )
    ).all()
    for _user_id, _sense_id, ids in groups:
        survivor_id, *losers = ids
        for loser_id in losers:
            existing_materials = {
                row[0]
                for row in bind.execute(
                    sa.text(
                        "SELECT material_id FROM saved_word_contexts "
                        "WHERE saved_word_id = :id"
                    ),
                    {"id": survivor_id},
                )
            }
            contexts = bind.execute(
                sa.text(
                    "SELECT id, material_id FROM saved_word_contexts "
                    "WHERE saved_word_id = :id"
                ),
                {"id": loser_id},
            ).all()
            for context_id, material_id in contexts:
                if material_id in existing_materials:
                    bind.execute(
                        sa.text("DELETE FROM saved_word_contexts WHERE id = :id"),
                        {"id": context_id},
                    )
                else:
                    bind.execute(
                        sa.text(
                            "UPDATE saved_word_contexts SET saved_word_id = :survivor "
                            "WHERE id = :id"
                        ),
                        {"survivor": survivor_id, "id": context_id},
                    )
                    existing_materials.add(material_id)
            bind.execute(
                sa.text("DELETE FROM saved_words WHERE id = :id"), {"id": loser_id}
            )
            merged += 1
    return merged


def upgrade() -> None:
    op.add_column(
        "saved_words",
        sa.Column("lexeme_sense_id", sa.Uuid(), nullable=True),
    )
    # Dropped BEFORE the backfill runs, not after: a split writes a second
    # saved word that shares its lemma with the first on purpose (two
    # senses, one spelling), and the old lemma-keyed constraint would reject
    # that insert the moment the first split happens.
    op.drop_constraint("uq_saved_user_lemma", "saved_words", type_="unique")

    bind = op.get_bind()
    stats = _backfill_saved_words(bind)
    logger.info(
        "Lexicon P4 backfill: %d saved words, %d mapped (%d via a rank-1 "
        "fallback), %d split into extra words for a second sense, %d merged "
        "back together as cross-word sense collisions",
        stats["words"], stats["mapped"], stats["fallback"], stats["split"],
        stats["merged"],
    )

    op.alter_column("saved_words", "lexeme_sense_id", nullable=False)
    op.create_foreign_key(
        "fk_saved_words_lexeme_sense_id", "saved_words", "lexeme_senses",
        ["lexeme_sense_id"], ["id"],
    )
    op.create_index(
        op.f("ix_saved_words_lexeme_sense_id"), "saved_words", ["lexeme_sense_id"],
    )
    op.create_unique_constraint(
        "uq_saved_user_lexeme_sense", "saved_words", ["user_id", "lexeme_sense_id"],
    )

    # "One open report per (user, sense); repeat = no-op" -- enforced here,
    # not only in the service, because this is the layer that cannot race.
    op.create_index(
        "uq_translation_reports_open_user_sense",
        "translation_reports",
        ["user_id", "lexeme_sense_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_translation_reports_open_user_sense", table_name="translation_reports",
    )
    op.drop_constraint("uq_saved_user_lexeme_sense", "saved_words", type_="unique")
    # Fails loudly, by design, if this database has ever actually split a
    # word or saved two senses of one lemma for one learner -- see the
    # module docstring's "Reversibility" section.
    op.create_unique_constraint(
        "uq_saved_user_lemma", "saved_words", ["user_id", "lemma"],
    )
    op.drop_constraint("fk_saved_words_lexeme_sense_id", "saved_words", type_="foreignkey")
    op.drop_index(op.f("ix_saved_words_lexeme_sense_id"), table_name="saved_words")
    op.drop_column("saved_words", "lexeme_sense_id")

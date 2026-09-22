"""saved_word_contexts.vocabulary_id: let the entry it points at be deleted

Revision ID: c4e9b2f0a781
Revises: b3d7f1a90c24
Create Date: 2026-09-22 00:00:00.000000

A saved word COPIES its gloss rather than reading it back through
``vocabulary_id``: a material can be re-glossed, and a learner's saved word
quietly changing meaning underneath them — or losing it when a row is
replaced — is worse than a copy that has aged. ``vocabulary_id`` is kept only
as provenance, nullable, for anybody later asking where a translation came
from.

The foreign key did not know that. It was a plain reference with no delete
behaviour, so the moment one learner had saved a word from a passage, a
re-extraction could not delete that passage's entries at all — and
``replace_extracted`` deletes every machine-made row by design. The whole
import of the passage failed on it.

Found by running a vocabulary re-import across the corpus for the first time
on a database that had saved words in it: 202 passages went through and
`cam11-t1-p1` raised, over a single saved word.

SET NULL rather than CASCADE, and the difference is the learner's list. The
row here is their saved word's context — its meaning, its Uzbek, its sentence
from the passage — and none of that came from the row being deleted; it was
copied at the moment of saving. What goes null is the pointer, which is
exactly what "this came from an entry that no longer exists" should look
like. CASCADE would delete somebody's vocabulary because a pipeline ran.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c4e9b2f0a781'
down_revision: Union[str, Sequence[str], None] = 'b3d7f1a90c24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NAME = "saved_word_contexts_vocabulary_id_fkey"


def upgrade() -> None:
    op.drop_constraint(NAME, "saved_word_contexts", type_="foreignkey")
    op.create_foreign_key(
        NAME,
        "saved_word_contexts",
        "material_vocabulary",
        ["vocabulary_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(NAME, "saved_word_contexts", type_="foreignkey")
    op.create_foreign_key(
        NAME,
        "saved_word_contexts",
        "material_vocabulary",
        ["vocabulary_id"],
        ["id"],
    )

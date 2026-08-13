"""where a choice answer is given moves onto the option

Revision ID: b7e2c419af05
Revises: f4c1d0a97b3e
Create Date: 2026-08-13 20:10:00.000000

A choice question carried one replay range, on the question, the way a form
gap does. A gap can: one gap is one answer. A "Choose TWO letters" is two
answers, said at two different moments, and one range could only ever point
at the first of them — so the mark moves to where the answer is, the right
option.

Stored in ``questions.config.option_replay``, keyed by option letter, which
is what already identifies an option once it is stored (``correct_answers``
is written the same way).

Data: a question with a range and a right option keeps it, attached to the
FIRST right option — for a single-answer question that is exactly what was
meant, and for a "choose two" it is the only one of the two moments anyone
ever recorded. The question's own ``replay_*`` columns are then cleared for
choice questions; they stay as they are for gaps, whose answer really is the
question's.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e2c419af05'
down_revision: Union[str, Sequence[str], None] = 'f4c1d0a97b3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: A choice question is one with a config; a gap's is NULL. Same discriminator
#: the model and the grader use.
_IS_CHOICE = "q.config IS NOT NULL"


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        sa.text(
            f"""
            UPDATE questions AS q
               SET config = q.config || jsonb_build_object(
                       'option_replay',
                       jsonb_build_object(
                           q.correct_answers->>0,
                           jsonb_build_array(q.replay_start_ms, q.replay_end_ms)
                       )
                   )
             WHERE {_IS_CHOICE}
               AND q.replay_start_ms IS NOT NULL
               AND q.replay_end_ms IS NOT NULL
               AND jsonb_array_length(q.correct_answers) > 0
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            UPDATE questions AS q
               SET replay_start_ms = NULL, replay_end_ms = NULL
             WHERE {_IS_CHOICE}
            """
        )
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Back onto the question, taking whichever marked option comes first.
    # A question marked in two places loses the second: there was nowhere on
    # the question to put it, which is the whole reason for this migration.
    op.execute(
        sa.text(
            f"""
            UPDATE questions AS q
               SET replay_start_ms = (first.span->>0)::int,
                   replay_end_ms = (first.span->>1)::int
              FROM (
                SELECT id,
                       (SELECT value
                          FROM jsonb_each(config->'option_replay')
                         ORDER BY key
                         LIMIT 1) AS span
                  FROM questions
                 WHERE config ? 'option_replay'
              ) AS first
             WHERE q.id = first.id
               AND first.span IS NOT NULL
               AND {_IS_CHOICE}
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE questions
               SET config = config - 'option_replay'
             WHERE config ? 'option_replay'
            """
        )
    )

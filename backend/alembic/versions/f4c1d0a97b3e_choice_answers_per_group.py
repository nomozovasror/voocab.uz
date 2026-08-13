"""how many answers a choice question wants moves to its group

Revision ID: f4c1d0a97b3e
Revises: a41c7b93de05
Create Date: 2026-08-13 09:40:00.000000

"One answer or several" was stored per question, in ``questions.config.mode``.
It belongs to the group: the instruction line printed above the set is what
states it ("Choose the correct letter, A, B or C" against "Choose TWO letters,
A-E"), and the instruction line is the group's. Held per question, a group
could be built whose instructions said one thing and whose questions said
another, and nothing objected.

And it becomes a count rather than a flag. "Several" never said how many, so
the number the candidate was actually asked for was read off the length of the
author's answer key — meaning a group whose instructions said "choose two"
asked for three wherever the author had marked three.

Data: for each multiple-choice group, the count is the largest key any of its
questions carries (at least 1). That is what the take page was already
computing per question, so nothing a candidate sees changes for a group that
was internally consistent, and a group that wasn't is resolved towards the
question that asked for most — the safe direction, since a key longer than the
group's count is refused from here on and would otherwise become ungradeable.
Then ``mode`` is dropped from every question.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4c1d0a97b3e'
down_revision: Union[str, Sequence[str], None] = 'a41c7b93de05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # jsonb_array_length over the answer key, biggest per group, floored at 1.
    op.execute(
        sa.text(
            """
            UPDATE question_groups AS g
            SET config = COALESCE(g.config, '{}'::jsonb)
                         || jsonb_build_object('answers_per_question', w.wanted)
            FROM (
                SELECT q.group_id,
                       GREATEST(
                           1,
                           MAX(jsonb_array_length(q.correct_answers))
                       ) AS wanted
                  FROM questions AS q
                 GROUP BY q.group_id
            ) AS w
            WHERE g.id = w.group_id
              AND g.type = 'multiple_choice'
            """
        )
    )
    # A group with no questions yet has nothing to derive from and takes the
    # ordinary single-answer default, same as one written from now on.
    op.execute(
        sa.text(
            """
            UPDATE question_groups
               SET config = COALESCE(config, '{}'::jsonb)
                            || '{"answers_per_question": 1}'::jsonb
             WHERE type = 'multiple_choice'
               AND NOT (COALESCE(config, '{}'::jsonb) ? 'answers_per_question')
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE questions
               SET config = config - 'mode'
             WHERE config ? 'mode'
            """
        )
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Back to a per-question flag, rebuilt from each question's own key. A
    # question the author had set to "choose two" but only half answered comes
    # back as single-answer, because the flag has nowhere else to come from —
    # which is the ambiguity this migration existed to remove.
    op.execute(
        sa.text(
            """
            UPDATE questions AS q
               SET config = jsonb_set(
                       q.config,
                       '{mode}',
                       CASE
                           WHEN jsonb_array_length(q.correct_answers) > 1
                           THEN '"multiple"'::jsonb
                           ELSE '"one"'::jsonb
                       END
                   )
             WHERE q.config IS NOT NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE question_groups
               SET config = config - 'answers_per_question'
             WHERE config ? 'answers_per_question'
            """
        )
    )

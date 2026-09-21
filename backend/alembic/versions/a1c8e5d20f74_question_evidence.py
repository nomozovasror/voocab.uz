"""questions.evidence: where in the passage the answer was

Revision ID: a1c8e5d20f74
Revises: e5b2c91f7a40
Create Date: 2026-09-20 00:00:00.000000

A listening question has always carried ``replay_start_ms``/``replay_end_ms``
— where in the recording the answer is said — and on the review screen that
turned out to be worth more than the score beside it. Knowing you were wrong
teaches nobody anything; being put back in front of the sentence you misread
is the whole of what a review is.

Reading had no such column. Its review found a line by searching the passage
for the answer string, which works for a gap-fill and says nothing at all
about a TRUE / FALSE / NOT GIVEN item or a multiple choice — the answer to
those is not a string that appears anywhere in the text. So the questions a
candidate most needs explained were the ones the page had least to say about.

JSONB and a LIST rather than two integer columns, for two reasons. The
evidence for one question is often in two places (a NOT GIVEN decided by a
clause here and a clause there), and pointing at one of them points at half
of why they were wrong. And the offsets are offsets into a PARAGRAPH — the
coordinates ``material_vocabulary`` and the reader's own highlights already
use — so each span has to carry which paragraph it is in.

    [{"index": 3, "start": 120, "end": 198}, ...]

Nullable, with no default. NULL means nothing is known — every question
written before the extraction ran, and every listening question for ever.
``[]`` would mean the extraction ran and found nothing, which is a different
thing worth being able to tell apart.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a1c8e5d20f74'
down_revision: Union[str, Sequence[str], None] = 'e5b2c91f7a40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "questions",
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=True),
    )


def downgrade() -> None:
    op.drop_column("questions", "evidence")

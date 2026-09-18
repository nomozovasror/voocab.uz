import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class Part(SQLModel, table=True):
    """A section of a paper — "Part 1" of a listening test, "Reading Passage
    2" of a reading one — and the thing its questions are answered from.

    What that thing is, is the whole difference between the two skills. A
    listening part points at a sub-range of the material's single audio file
    (``audio_start_ms``/``audio_end_ms``, nullable — NULL means this part
    spans the whole audio, which is right for a single-part material). A
    reading part carries its text in ``passage``. Neither fills the other's
    columns, and a part has exactly one of them by construction: a paper is
    heard or it is read.

    Everything above and below this row is the same for both — a material
    holds ordered parts, a part holds ordered question groups, numbering runs
    across the whole paper — which is why reading is a column here rather
    than a second tree beside this one."""

    __tablename__ = "parts"
    __table_args__ = (
        UniqueConstraint("material_id", "order_index", name="uq_parts_material_order"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    material_id: uuid.UUID = Field(foreign_key="materials.id", index=True)
    order_index: int
    title: str
    audio_start_ms: int | None = Field(default=None)
    audio_end_ms: int | None = Field(default=None)
    #: The number this part's first question carries on the paper it came
    #: from. NULL means "number from 1", which is right for anything an
    #: author writes here and was the only behaviour before.
    #:
    #: A real Listening paper numbers 1 to 40 straight through, so its Part 4
    #: is Questions 31-40 and the recording says so out loud -- "now turn to
    #: questions thirty-one to forty". A seeded material is ONE part of such a
    #: paper, so numbering it from 1 put "Question 1" on screen while the
    #: audio said thirty-one.
    first_number: int | None = Field(default=None)
    #: The text a reading part's questions are answered from, or NULL for a
    #: listening part, which is answered from the recording instead.
    #:
    #: ``{"paragraphs": [{"label": "A", "text": "..."}, ...],
    #:   "subtitle": str | None, "source": str | None}``
    #:
    #: Paragraphs rather than one block of prose, and each with its own
    #: label, because the paper letters them and two of Reading's own tasks
    #: are answered BY that letter — "which paragraph contains the following
    #: information" is a question whose options are A to G. A passage stored
    #: as one string would have to be re-split to ask it, and a re-split that
    #: disagreed with the printed lettering by one would mark every one of
    #: those answers wrong. ``label`` is nullable for a passage the book
    #: prints without letters, which is most of them.
    passage: dict | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel


class MaterialDifficulty(SQLModel, table=True):
    """How hard each material turned out to be — the tally, kept ready.

    **This is a projection, not a property.** Nothing here is authored, and
    nothing here is the source of anything: every column is a function of the
    :class:`QuestionAttempt` rows that existed when it was last computed, and
    throwing the whole table away costs one pass of
    :func:`app.services.difficulty.recompute`. That is the distinction
    CLAUDE.md's "difficulty is measured, never stored" is protecting — a
    ``difficulty`` column on ``materials`` that an author sets is a different
    thing entirely, and is still forbidden. When stage 2 replaces proportion
    correct with a Rasch/1PL estimate, the recompute changes and this table
    refills; no migration, no backfill, nothing upstream notices.

    It exists because the alternative does not survive a catalogue. Computed
    per request, the aggregate is a scan of every question attempt on the
    platform, on every load of the practice page, for every learner — at a
    thousand materials that is seconds of database time to draw a four-letter
    chip. Here it is a primary-key lookup.

    ``answered``/``correct`` are the tally; ``band`` is what the thresholds
    made of it. The band is stored as well as derivable because the catalogue
    has to be able to FILTER and ORDER BY it in SQL once the list is paginated
    — that is the whole reason a column exists rather than a cache in memory.
    Move a threshold and the stored bands are stale until the next refresh,
    while the API's own reading of them is not: see
    :func:`app.services.difficulty.material_difficulty`.
    """

    __tablename__ = "material_difficulty"

    #: One row per material, and the material's own id is the key: there is
    #: nothing to say about a material twice.
    material_id: uuid.UUID = Field(foreign_key="materials.id", primary_key=True)

    #: Answers counted, and how many came back right. Both raw, so a change of
    #: thresholds is a re-band rather than a re-count.
    answered: int = Field(default=0)
    correct: int = Field(default=0)

    #: ``new`` / ``easy`` / ``medium`` / ``hard`` — indexed because a filter
    #: chip and a sort order are what it is for.
    band: str = Field(default="new", index=True)

    #: When this row was last worked out. Not decoration: it is how anybody
    #: asking "why does this say New" can tell a material nobody has answered
    #: from a refresher that has stopped running.
    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

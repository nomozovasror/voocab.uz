import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, func
from sqlmodel import Field, SQLModel


#: The material types that are a PAPER — a tree of parts, question groups and
#: questions, sat as an attempt and marked out of its numbers. Dictation is not
#: one of them: it is segments of audio typed back, graded word by word.
#:
#: Named once because three different readers ask the question and they must
#: agree: the difficulty projection scans "every paper on the platform", the
#: studio dashboard counts them, and the catalogue filters to one of them.
PAPER_TYPES: tuple[str, ...] = ("listening", "reading")


class Material(SQLModel, table=True):
    """A piece of practice content authored by a user.

    ``type`` is what kind: ``dictation``, ``listening`` or ``reading``. The
    two in :data:`PAPER_TYPES` share this whole tree — parts, question
    groups, questions, attempts — and differ only in what a part is answered
    from (see :class:`app.models.part.Part`)."""

    __tablename__ = "materials"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    author_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    type: str = Field(default="dictation")
    title: str
    #: Where this material came from in a printed book -- "C21 T1 P3" for
    #: Cambridge 21's first test, third passage. Null for anything an author
    #: wrote themselves, which is most of what this table will eventually
    #: hold.
    #:
    #: Its own column rather than a suffix on the title, for three reasons
    #: that turned out to be the same reason. The card wants to PRINT it
    #: separately -- the name of the passage is what a learner reads, and
    #: which test it is is a fact about where it came from, which belongs on
    #: the meta line with the part and the question count. The seed importers
    #: want it as their dedup key, and a key that lives inside a display
    #: string is a key that moves whenever somebody edits the display. And
    #: `seed_status` and `publish_seeded` want to ask "is this one of the
    #: seeded ones", which they were doing with a regular expression over the
    #: title. All three want the same thing: the reference as data.
    reference: str | None = Field(default=None, max_length=40, index=True)
    # Optional because non-audio material types (grammar/vocab/reading) won't
    # have a clip. Readiness (pending/processing/ready) is NOT stored here —
    # it's derived from audio_asset -> audio_blob.transcript_status at read
    # time, to avoid a duplicated column drifting out of sync.
    audio_asset_id: uuid.UUID | None = Field(
        default=None, foreign_key="audio_asset.id", index=True
    )
    case_sensitive: bool = Field(default=False)
    punctuation_sensitive: bool = Field(default=False)
    visibility: str = Field(default="private")  # "private" | "public"
    # Bumped by every authoring write to the material OR to anything under it
    # — a part, a question group, a question. The material is what an author
    # edits; parts and groups are pieces of it, so one counter over the whole
    # tree is what an editor can meaningfully check against.
    #
    # A client that sends the version it loaded gets a 409 when the material
    # has moved on since (see app/api/materials.py), which is how two windows
    # open on the same material stop silently overwriting each other. Sending
    # it is optional: a caller that doesn't simply keeps the old last-write-
    # wins behaviour.
    version: int = Field(default=1, nullable=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    # Auto-bumped by the DB driver on every UPDATE of this row (SQLAlchemy's
    # client-side `onupdate`, not just a DDL trigger) -- callers never need
    # to set it themselves. Powers "Edited X" vs "Created X" in the Studio
    # activity feed and `recent` ordering.
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        ),
    )

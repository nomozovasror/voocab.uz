import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, Text, func
from sqlmodel import Field, SQLModel


class RenderKind(enum.StrEnum):
    """What a render is.

    ``word`` -- the word spoken by the TTS voice. ``definition`` -- a sense's
    definition, as recall would show it (the headword masked), the masks
    spoken as silence. ``item`` -- one On the go file: definition, a pause,
    the word, a pause."""

    WORD = "word"
    DEFINITION = "definition"
    ITEM = "item"


class RenderStatus(enum.StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class AudioRender(SQLModel, table=True):
    """One piece of audio the server makes itself, and the QUEUE of making it.

    The same shape as ``audio_blob.transcript_status``: the table is the
    queue, the worker claims a ``pending`` row with ``FOR UPDATE SKIP
    LOCKED``, and a request that wants audio that does not exist yet only
    inserts the row (``INSERT ... ON CONFLICT DO NOTHING`` on ``key``) and
    answers "not ready". Nothing is ever synthesised inside a request.

    ``key`` is the content address of the INPUT, not of the output (the output
    does not exist when the row is first written): a SHA-256 over the exact
    synthesis input, voice and model for ``word``/``definition``, and over the
    parts for ``item`` (see :mod:`app.services.tts`). One word is therefore
    synthesised once in the whole system, a changed definition is a new row
    and never an edit of an old one, and the seed script on the GPU machine and
    the production worker write to the same keys. ``input`` is that exact
    text -- what was hashed -- so a row can be read and re-derived by hand.

    ``storage_key`` (``tts/...`` for words and definitions, ``renders/...`` for
    items) is the output once ``ready``. ``word_offset_ms`` is set for items
    only: where, inside the file, the word begins -- the moment the client
    counts as "the word was played" for the exposure log, and the one thing it
    must not read off the lock screen.

    ``updated_at`` is the heartbeat the queue's recovery reads: a
    ``processing`` row not touched for ``tts_stale_after_s`` was left by a
    worker that died, and goes back to ``pending`` (a live worker's row is
    never that old, so recovery cannot steal one)."""

    __tablename__ = "audio_renders"
    __table_args__ = (Index("ix_audio_renders_claim", "status", "created_at"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    key: str = Field(max_length=64, unique=True, index=True)
    kind: str = Field(max_length=16)
    input: str = Field(sa_column=Column(Text, nullable=False))
    voice: str = Field(max_length=32)
    model: str = Field(max_length=48)
    status: str = Field(default=RenderStatus.PENDING, max_length=16)
    attempts: int = Field(default=0)
    error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    storage_key: str | None = Field(default=None)
    duration_ms: int | None = Field(default=None)
    word_offset_ms: int | None = Field(default=None)
    #: A ``pending`` row is not claimable before this: a failure's back-off, so
    #: a systemic fault (storage down, a model that will not load) walks the
    #: queue once per back-off instead of burning every row's attempts in
    #: seconds. ``None`` = claimable now.
    next_attempt_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        ),
    )

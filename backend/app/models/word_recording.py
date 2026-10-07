import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as SA_UUID
from sqlmodel import Field, SQLModel


class WordRecording(SQLModel, table=True):
    """The human recording a sense's word is spoken with, per accent.

    One row per ``(sense, accent)``: a request for the learner's words asks
    ``WHERE lexeme_sense_id IN (...) AND accent = :accent`` once and has every
    answer (:func:`app.services.word_audio.word_audio_many`). The row says
    nothing about WHICH dictionary block it came from -- that is decided once,
    at import, from the sense's own ``cald_ref`` (``basis = 'ref'``: the block
    that sense was defined in, so a heteronym's noun and verb are spoken
    differently) or, for a sense CALD never defined, from the lemma's part of
    speech (``basis = 'pos'``; never for a heteronym). Two senses that
    resolved to the same block share one file: the key is the hash of the
    normalised bytes.

    ``accent`` is OUR word (``british`` / ``american``), not the dictionary's
    ``uk`` / ``us``: the reader of this table is the learner's accent setting.
    A sense with no row for an accent is spoken by Kokoro, exactly as before.

    ``storage_key`` (``rec/<sha256>.m4a``) is the file after
    :func:`app.services.word_recordings.normalise`: 24 kHz mono AAC, edges
    trimmed and RMS-levelled like a TTS render, so the word and the (always
    synthetic) definition of an On the go item sit at the same loudness.
    ``source_file`` is the file name in the source directory
    (a name like ``abc123.mp3``); it is what makes the import resumable and lets a
    changed ``cald_ref`` replace the row. The transcription of the word is
    NOT stored: it belongs to the private index, not to this database."""

    __tablename__ = "word_recordings"
    __table_args__ = (
        UniqueConstraint("lexeme_sense_id", "accent", name="uq_word_recordings_sense_accent"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    lexeme_sense_id: uuid.UUID = Field(
        sa_column=Column(
            SA_UUID(as_uuid=True),
            ForeignKey("lexeme_senses.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    accent: str = Field(max_length=16)
    storage_key: str
    duration_ms: int
    source_file: str = Field(max_length=120)
    basis: str = Field(max_length=8)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

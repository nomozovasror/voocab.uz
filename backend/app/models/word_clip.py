import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as SA_UUID
from sqlmodel import Field, SQLModel


class ClipStatus(enum.StrEnum):
    """Where a clip is on its way to being served.

    ``candidate`` is a row the index wrote: a place in a transcript where a
    lexicon form is spoken, nothing more. ``cut`` has bytes in storage.
    ``verified`` is the only state anything is ever served from. ``rejected``
    means the verifier did not hear the word in the cut (the ASR timing was
    off, or the speaker swallowed it); ``failed`` means the cut itself broke
    (undecodable audio, a missing file) and is worth a retry.

    A plain string column, like :class:`app.models.audio_blob.TranscriptStatus`:
    a new state later is a data change, not a migration on a type."""

    CANDIDATE = "candidate"
    CUT = "cut"
    VERIFIED = "verified"
    REJECTED = "rejected"
    FAILED = "failed"


class WordClip(SQLModel, table=True):
    """One place in one recording where a lexicon form is spoken, and (once
    cut) the small file that holds just that word.

    Decision 4 of the vocabulary stage-3 brief: the server cuts, once, into a
    file of its own, so the browser never seeks inside a thirty-minute
    recording to play one word. The padding is already baked into
    ``start_ms``/``end_ms`` (150 ms either side of the word's first and last
    ASR timestamp, clamped to the recording) -- the columns say what was cut,
    not what the ASR said, and a re-cut with different padding is a new
    decision, not a recalculation.

    ``form`` is the NORMALISED surface -- lowercase, punctuation stripped
    except inside a word, a phrase space-joined -- because decision 1 is
    "exact form only": ``played`` is not a clip of ``play``. It is matched
    against a lexeme's lemma, so the learner types what they hear.

    The word range is ``word_start_index``..``word_end_index`` INCLUSIVE, into
    ``audio_segment.words`` of the segment with ``segment_order_index``; the
    context range is the same segment's two words either side (fewer if the
    segment ends sooner -- though the index never takes a word that is first
    or last in its segment, so there is always at least one neighbour a
    side). Unique on blob + segment + word range: re-indexing is idempotent.

    ``heard`` is what the verifier transcribed from the word clip -- kept so a
    rejection can be reviewed rather than trusted, and so a better verifier
    can be run over exactly the clips the last one refused."""

    __tablename__ = "word_clips"
    __table_args__ = (
        UniqueConstraint(
            "blob_id",
            "segment_order_index",
            "word_start_index",
            "word_end_index",
            name="uq_word_clip_place",
        ),
        Index("ix_word_clips_form_status", "form", "status"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    form: str = Field(max_length=160)
    blob_id: uuid.UUID = Field(
        sa_column=Column(
            SA_UUID(as_uuid=True),
            ForeignKey("audio_blob.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    segment_order_index: int
    word_start_index: int
    word_end_index: int
    start_ms: int
    end_ms: int
    context_start_index: int
    context_end_index: int
    context_start_ms: int
    context_end_ms: int
    storage_key: str | None = Field(default=None)
    context_storage_key: str | None = Field(default=None)
    status: str = Field(default=ClipStatus.CANDIDATE, max_length=16)
    heard: str | None = Field(default=None)
    error: str | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    cut_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    verified_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

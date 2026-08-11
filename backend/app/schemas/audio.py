"""Read schemas for the audio-asset read endpoint (§10)."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class WordRead(BaseModel):
    word: str
    start_ms: int
    end_ms: int


class AudioSegmentRead(BaseModel):
    order_index: int
    start_ms: int
    end_ms: int
    text: str
    words: list[WordRead]
    #: True when the owner has corrected this line. The word timings below are
    #: still the ASR's and no longer line up with the text, so a caller that
    #: renders word by word should stop doing so for an edited line.
    edited: bool = False


class SegmentTextUpdate(BaseModel):
    text: str


class AudioAssetRead(BaseModel):
    """The caller's view of one owned audio asset + its blob's transcript
    state. ``segments`` is populated only once ``transcript_status`` is
    ``ready``; ``transcript_error`` only once it's ``failed`` — the frontend
    is expected to poll while ``pending``/``processing``."""

    asset_id: uuid.UUID
    blob_id: uuid.UUID
    title: str | None
    sha256: str
    transcript_status: str
    duration_ms: int | None
    created_at: datetime
    transcript_error: str | None = None
    segments: list[AudioSegmentRead] = []

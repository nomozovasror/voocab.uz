"""Request/response schemas for material authoring.

Kept separate from the ORM models so the API contract is explicit: clients never
set ``author_id`` (taken from the session) and segment ``order_index`` is derived
from array position rather than trusted from input.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Visibility = Literal["private", "public"]
MaterialType = Literal["dictation", "listening"]


class SegmentIn(BaseModel):
    """One audio slice to type. ``order_index`` is assigned server-side."""

    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    reference_text: str = Field(min_length=1)

    @field_validator("reference_text")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("reference_text must not be blank")
        return v

    @model_validator(mode="after")
    def _ordered(self) -> "SegmentIn":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class SegmentRead(BaseModel):
    id: uuid.UUID
    order_index: int
    start_ms: int
    end_ms: int
    reference_text: str


class MaterialCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    type: MaterialType = "dictation"
    # The uploaded clip to attach, from a prior POST /api/uploads/audio
    # (asset_id in that response). Ownership is checked server-side in
    # app/services/materials.py — a caller can only attach an asset they
    # themselves own.
    audio_asset_id: uuid.UUID | None = None
    case_sensitive: bool = False
    punctuation_sensitive: bool = False
    visibility: Visibility = "private"
    segments: list[SegmentIn] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def _strip_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title must not be blank")
        return v


class MaterialUpdate(BaseModel):
    """All fields optional. If ``segments`` is provided it replaces the set."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    audio_asset_id: uuid.UUID | None = None
    case_sensitive: bool | None = None
    punctuation_sensitive: bool | None = None
    visibility: Visibility | None = None
    segments: list[SegmentIn] | None = None

    @field_validator("title")
    @classmethod
    def _strip_title(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("title must not be blank")
        return v


class MaterialRead(BaseModel):
    """List-row view (no segments, but a count)."""

    id: uuid.UUID
    author_id: uuid.UUID
    type: str
    title: str
    audio_asset_id: uuid.UUID | None
    case_sensitive: bool
    punctuation_sensitive: bool
    visibility: str
    created_at: datetime
    #: Bumped by every authoring write to this material or anything under it.
    #: Send it back in ``X-Material-Version`` on a write to be told (409) when
    #: someone else has changed the material in the meantime.
    version: int
    segment_count: int


class MaterialDetail(MaterialRead):
    segments: list[SegmentRead]
    # Listening authoring tree (parts -> question_groups -> questions). Left
    # untyped (plain dicts, built by app.services.listening.get_author_tree)
    # so the caller controls exactly which keys are present per-request --
    # notably whether each question dict carries "correct_answers" at all,
    # gated on ownership (§3.4: never leak answers to a non-owner, even here).
    parts: list[dict] = Field(default_factory=list)
    # Resolved from audio_asset_id -> AudioAsset -> AudioBlob at read time
    # (app/api/materials.py) so the Studio player has a real, fetchable URL
    # rather than just an opaque asset id. Null when no audio is attached.
    audio_url: str | None = None
    transcript_status: str | None = None
    duration_ms: int | None = None


class AudioUploadRead(BaseModel):
    asset_id: uuid.UUID
    blob_id: uuid.UUID
    sha256: str
    transcript_status: str

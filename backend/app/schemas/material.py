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
MaterialType = Literal["dictation"]


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
    # NOTE: audio wiring (audio_asset_id) is deferred to a later phase; this
    # schema doesn't accept audio input yet.
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
    segment_count: int


class MaterialDetail(MaterialRead):
    segments: list[SegmentRead]


class AudioUploadRead(BaseModel):
    asset_id: uuid.UUID
    blob_id: uuid.UUID
    sha256: str
    transcript_status: str

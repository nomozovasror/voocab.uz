"""Response schema for the Studio dashboard stats endpoint
(GET /api/studio/stats). All fields are real, aggregate-computed numbers --
no placeholders; anything not yet implemented (subscribers, saves, ...) is
simply absent here and rendered as "-" by the frontend itself.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel


class ByTypeStat(BaseModel):
    type: str
    total: int
    public: int
    private: int
    completions: int


class RecentMaterial(BaseModel):
    id: uuid.UUID
    title: str
    type: str
    visibility: str
    item_count: int
    created_at: datetime
    updated_at: datetime


class StudioStats(BaseModel):
    materials_total: int
    content_ms: int
    learners: int
    completions: int
    by_type: list[ByTypeStat]
    recent: list[RecentMaterial]


class ListeningListItem(BaseModel):
    id: uuid.UUID
    title: str
    visibility: str
    duration_ms: int | None
    transcript_status: str | None
    #: Every kind of question group the material holds, in the order they are
    #: asked. A list rather than "the first one": a part can mix form
    #: completion and multiple choice, and naming only the first would label
    #: half the material after the other half.
    question_types: list[str]
    question_count: int
    attempts: int
    avg_score_pct: float | None
    updated_at: datetime


class ListeningList(BaseModel):
    total: int
    duration_ms: int
    items: list[ListeningListItem]

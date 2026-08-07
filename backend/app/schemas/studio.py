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

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel


class Attempt(SQLModel, table=True):
    """An activity EVENT: one time a user worked through a material. Statistics,
    XP and achievements are derived from these events rather than stored as
    standalone counters."""

    __tablename__ = "attempts"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    material_id: uuid.UUID = Field(foreign_key="materials.id", index=True)
    score: float
    time_spent_ms: int
    completed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

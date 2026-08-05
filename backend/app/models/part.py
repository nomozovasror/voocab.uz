import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel


class Part(SQLModel, table=True):
    """A section of a listening material (e.g. "Part 1"), pointing at a
    sub-range of the material's single audio file. ``audio_start_ms``/
    ``audio_end_ms`` are nullable — NULL means this part spans the whole
    audio (relevant for single-part materials)."""

    __tablename__ = "parts"
    __table_args__ = (
        UniqueConstraint("material_id", "order_index", name="uq_parts_material_order"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    material_id: uuid.UUID = Field(foreign_key="materials.id", index=True)
    order_index: int
    title: str
    audio_start_ms: int | None = Field(default=None)
    audio_end_ms: int | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

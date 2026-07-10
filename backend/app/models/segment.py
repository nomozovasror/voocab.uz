import uuid

from sqlmodel import Field, SQLModel


class Segment(SQLModel, table=True):
    """One orderable chunk of a material — for dictation, a slice of audio with
    the reference text the learner should type."""

    __tablename__ = "segments"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    material_id: uuid.UUID = Field(foreign_key="materials.id", index=True)
    order_index: int
    start_ms: int
    end_ms: int
    reference_text: str

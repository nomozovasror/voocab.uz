import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel


class ImageBlob(SQLModel, table=True):
    """Shared, content-addressed image bytes: the map, plan or diagram a
    labelling task is answered on. One row per unique file (by SHA-256),
    however many groups end up pointing at it.

    There is no per-owner ``ImageAsset`` beside this, the way
    :class:`app.models.audio_asset.AudioAsset` sits beside an audio blob. That
    exists because an owner has something of their own to say about a shared
    recording — their transcript corrections — and a picture has no equivalent:
    two authors who upload the same map want the same map. Ownership would only
    be bookkeeping, and it would not be protecting anything, since these bytes
    are served from a public URL either way.

    ``width``/``height`` are read from the file's own header at upload
    (:mod:`app.services.image_codec`) and stored rather than recomputed or
    accepted from the client. They are what lets the take page reserve the
    picture's box before the bytes arrive, so the questions under it don't jump
    down the screen mid-render.
    """

    __tablename__ = "image_blob"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    sha256: str = Field(unique=True, index=True)
    storage_key: str
    size_bytes: int
    mime_type: str
    width: int
    height: int
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

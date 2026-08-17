"""Image ingestion data layer: get-or-create for content-addressed blobs.

Pure data layer — no HTTP, no storage I/O. The router (app/api/materials.py)
orchestrates this together with app.services.storage, exactly as it does for
audio.

Simpler than its audio counterpart by one whole table: an image has no
transcript to own and so no per-owner asset row (see
:class:`app.models.image_blob.ImageBlob`). What it shares is the
concurrent-insert race on ``sha256``: two authors uploading the same map at the
same moment must end up on one row, with one of them re-reading the row the
other won rather than either erroring.
"""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.core.database import AsyncSession
from app.models.image_blob import ImageBlob


async def get_or_create_blob(
    session: AsyncSession,
    sha256: str,
    storage_key: str,
    size_bytes: int,
    mime_type: str,
    width: int,
    height: int,
) -> tuple[ImageBlob, bool]:
    """Look up an :class:`ImageBlob` by content hash; create it if absent.

    Returns ``(blob, created)`` where ``created`` is True only when this call
    actually inserted a new row — the caller uses that to decide whether to
    write bytes to storage, since a dedup hit must never rewrite them.
    """
    existing = (
        await session.exec(select(ImageBlob).where(ImageBlob.sha256 == sha256))
    ).first()
    if existing is not None:
        return existing, False

    blob = ImageBlob(
        sha256=sha256,
        storage_key=storage_key,
        size_bytes=size_bytes,
        mime_type=mime_type,
        width=width,
        height=height,
    )
    try:
        # A SAVEPOINT, not a full rollback: losing this race must unwind only
        # this insert, not anything else already flushed on the caller's
        # transaction.
        async with session.begin_nested():
            session.add(blob)
            await session.flush()  # assign blob.id, surface the race now
    except IntegrityError:
        existing = (
            await session.exec(select(ImageBlob).where(ImageBlob.sha256 == sha256))
        ).first()
        assert existing is not None  # the row that won the race must exist now
        return existing, False
    return blob, True


async def get_blob(session: AsyncSession, blob_id: uuid.UUID) -> ImageBlob | None:
    """One image by id. Used when a group's config names a picture, to turn
    that id into a URL and a size the editor and the take page can lay out
    with — and to refuse a group naming a picture that doesn't exist."""
    return await session.get(ImageBlob, blob_id)

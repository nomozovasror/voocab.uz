"""Audio ingestion data layer: hashing + get-or-create for blobs/assets.

Pure data layer — no HTTP, no storage I/O. The router (app/api/materials.py)
orchestrates this together with app.services.storage.

``AudioBlob`` is content-addressed and shared (no owner); ``AudioAsset`` is
the per-owner claim on a blob. Both get-or-create helpers handle the
concurrent-insert race on their respective unique constraints: two requests
racing to create the same row will have one "win" the insert and the other
fall back to re-reading the now-existing row, rather than erroring or
double-inserting.
"""

import hashlib
import uuid

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.core.database import AsyncSession
from app.models.audio_asset import AudioAsset
from app.models.audio_blob import AudioBlob, TranscriptStatus
from app.models.audio_segment import AudioSegment
from app.services.asr import TranscriptResult


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def get_or_create_blob(
    session: AsyncSession,
    sha256: str,
    storage_key: str,
    size_bytes: int,
    mime_type: str,
) -> tuple[AudioBlob, bool]:
    """Look up an ``AudioBlob`` by content hash; create it if absent.

    Returns ``(blob, created)`` where ``created`` is True only when this call
    actually inserted a new row — the caller uses that to decide whether to
    write bytes to storage (dedup hits must never rewrite storage).
    """
    existing = (
        await session.exec(select(AudioBlob).where(AudioBlob.sha256 == sha256))
    ).first()
    if existing is not None:
        return existing, False

    blob = AudioBlob(
        sha256=sha256,
        storage_key=storage_key,
        size_bytes=size_bytes,
        mime_type=mime_type,
        transcript_status=TranscriptStatus.PENDING,
    )
    try:
        # A SAVEPOINT, not a full rollback: if the insert races and loses, we
        # only unwind this insert, not anything else already flushed/added on
        # the caller's session/transaction (e.g. an asset created earlier in
        # the same request).
        async with session.begin_nested():
            session.add(blob)
            await session.flush()  # assign blob.id, surface a unique-violation race now
    except IntegrityError:
        # Another request inserted the same sha256 between our lookup and our
        # insert. Back off and use theirs.
        existing = (
            await session.exec(select(AudioBlob).where(AudioBlob.sha256 == sha256))
        ).first()
        assert existing is not None  # the row that won the race must exist now
        return existing, False
    return blob, True


async def get_or_create_asset(
    session: AsyncSession,
    owner_id: uuid.UUID,
    blob_id: uuid.UUID,
    title: str | None = None,
) -> AudioAsset:
    """Look up an ``AudioAsset`` by ``(owner_id, blob_id)``; create it if
    absent. One owner always gets exactly one asset per blob, even if several
    materials end up referencing it."""
    existing = (
        await session.exec(
            select(AudioAsset).where(
                AudioAsset.owner_id == owner_id, AudioAsset.blob_id == blob_id
            )
        )
    ).first()
    if existing is not None:
        return existing

    asset = AudioAsset(owner_id=owner_id, blob_id=blob_id, title=title)
    try:
        async with session.begin_nested():
            session.add(asset)
            await session.flush()  # assign asset.id, surface a unique-violation race now
    except IntegrityError:
        existing = (
            await session.exec(
                select(AudioAsset).where(
                    AudioAsset.owner_id == owner_id, AudioAsset.blob_id == blob_id
                )
            )
        ).first()
        assert existing is not None
        return existing
    return asset


async def persist_transcript_result(
    session: AsyncSession, blob: AudioBlob, result: TranscriptResult
) -> None:
    """Write a normalized :class:`TranscriptResult` as the final, successful
    state of a blob's transcription: one ``AudioSegment`` row per segment (in
    ``order_index`` order, ``words`` as JSON), ``duration_ms`` filled in, and
    ``transcript_status`` flipped to ``ready``.

    Shared by both the production path (the Faza 4 worker, after a
    ``GroqASR`` call) and the offline seed script (after a ``faster-whisper``
    call) — same function, same rows, regardless of which ASR produced the
    result. Does not commit; the caller controls the transaction boundary.
    """
    for seg in result.segments:
        session.add(
            AudioSegment(
                blob_id=blob.id,
                order_index=seg.order_index,
                start_ms=seg.start_ms,
                end_ms=seg.end_ms,
                text=seg.text,
                words=[
                    {"word": w.word, "start_ms": w.start_ms, "end_ms": w.end_ms}
                    for w in seg.words
                ],
            )
        )
    blob.duration_ms = result.duration_ms
    blob.transcript_status = TranscriptStatus.READY
    blob.transcript_error = None
    session.add(blob)


async def get_asset(session: AsyncSession, asset_id: uuid.UUID) -> AudioAsset | None:
    """Look up an ``AudioAsset`` by id. Ownership/authz is the router's job
    (see app/api/audio.py) — this is a plain data lookup."""
    return await session.get(AudioAsset, asset_id)


async def get_asset_segments(
    session: AsyncSession, blob_id: uuid.UUID
) -> list[AudioSegment]:
    """The blob's ASR segments, in playback order."""
    return list(
        (
            await session.exec(
                select(AudioSegment)
                .where(AudioSegment.blob_id == blob_id)
                .order_by(AudioSegment.order_index)
            )
        ).all()
    )

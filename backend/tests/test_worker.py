"""Integration tests for app.worker (§9 acceptance criteria) — real DB, fake
ASR provider (no network). Every test creates its own throwaway AudioBlob
row(s) (and, where needed, bytes in local storage under a throwaway key) and
tears them down again with targeted deletes at the end.
"""

import uuid

import httpx
import pytest
from sqlmodel import select

from app.core.config import settings
from app.core.database import async_session_factory
from app.models.audio_blob import AudioBlob, TranscriptStatus
from app.models.audio_segment import AudioSegment
from app.services.asr import TranscriptResult, TranscriptSegment, WordTiming
from app.services.storage import get_storage
from app.worker import claim_one, classify_error, process_blob, recover_stale


def _sha() -> str:
    return f"test-{uuid.uuid4().hex}"


async def _make_blob(status: str = TranscriptStatus.PENDING, **overrides) -> AudioBlob:
    async with async_session_factory() as session:
        blob = AudioBlob(
            sha256=_sha(),
            storage_key=f"audio/test-{uuid.uuid4().hex}.mp3",
            size_bytes=10,
            mime_type="audio/mpeg",
            transcript_status=status,
            **overrides,
        )
        session.add(blob)
        await session.commit()
        await session.refresh(blob)
        return blob


async def _put_fake_bytes(blob: AudioBlob) -> None:
    """process_blob always reads the audio from storage before calling the
    provider, so every test that exercises the provider's error/result
    handling needs real bytes behind the blob's storage_key first."""
    await get_storage().put(blob.storage_key, b"fake audio bytes", blob.mime_type)


def _remove_fake_bytes(blob: AudioBlob) -> None:
    import os

    disk_path = os.path.join(settings.media_root, blob.storage_key)
    if os.path.exists(disk_path):
        os.remove(disk_path)


async def _cleanup_blob(blob_id: uuid.UUID) -> None:
    async with async_session_factory() as session:
        segments = (
            await session.exec(
                select(AudioSegment).where(AudioSegment.blob_id == blob_id)
            )
        ).all()
        for seg in segments:
            await session.delete(seg)
        await session.flush()
        blob = await session.get(AudioBlob, blob_id)
        if blob is not None:
            await session.delete(blob)
        await session.commit()


class FakeProviderSuccess:
    def __init__(self, result: TranscriptResult) -> None:
        self._result = result

    async def transcribe(self, audio: bytes, mime_type: str, language: str = "en"):
        return self._result


class FakeProviderRaises:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def transcribe(self, audio: bytes, mime_type: str, language: str = "en"):
        raise self._exc


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/audio/transcriptions")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(f"status {status_code}", request=request, response=response)


FIXTURE_RESULT = TranscriptResult(
    duration_ms=3500,
    segments=[
        TranscriptSegment(
            order_index=0,
            start_ms=0,
            end_ms=1800,
            text="Hello world.",
            words=[
                WordTiming(word="Hello", start_ms=0, end_ms=500),
                WordTiming(word="world", start_ms=600, end_ms=1000),
            ],
        ),
        TranscriptSegment(
            order_index=1,
            start_ms=1800,
            end_ms=3500,
            text="This is a test.",
            words=[
                WordTiming(word="This", start_ms=1800, end_ms=2000),
                WordTiming(word="is", start_ms=2000, end_ms=2200),
                WordTiming(word="a", start_ms=2200, end_ms=2300),
                WordTiming(word="test", start_ms=2300, end_ms=2600),
            ],
        ),
    ],
)


@pytest.mark.asyncio
async def test_process_blob_success_writes_segments_and_ready() -> None:
    blob = await _make_blob(status=TranscriptStatus.PROCESSING)
    await _put_fake_bytes(blob)
    try:
        async with async_session_factory() as session:
            fresh = await session.get(AudioBlob, blob.id)
            await process_blob(session, fresh, FakeProviderSuccess(FIXTURE_RESULT))

        async with async_session_factory() as session:
            refreshed = await session.get(AudioBlob, blob.id)
            assert refreshed.transcript_status == TranscriptStatus.READY
            assert refreshed.duration_ms == 3500
            assert refreshed.transcript_error is None

            segments = (
                await session.exec(
                    select(AudioSegment)
                    .where(AudioSegment.blob_id == blob.id)
                    .order_by(AudioSegment.order_index)
                )
            ).all()
            assert len(segments) == 2
            assert segments[0].order_index == 0
            assert segments[0].text == "Hello world."
            assert segments[0].start_ms == 0 and segments[0].end_ms == 1800
            assert segments[0].words == [
                {"word": "Hello", "start_ms": 0, "end_ms": 500},
                {"word": "world", "start_ms": 600, "end_ms": 1000},
            ]
            assert segments[1].order_index == 1
            assert segments[1].words[0] == {"word": "This", "start_ms": 1800, "end_ms": 2000}
    finally:
        _remove_fake_bytes(blob)
        await _cleanup_blob(blob.id)


@pytest.mark.asyncio
async def test_claim_one_skip_locked_never_double_claims() -> None:
    blob_a = await _make_blob()
    blob_b = await _make_blob()
    try:
        session1 = async_session_factory()
        session2 = async_session_factory()
        try:
            # Session 1 locks blob_a's row (as claim_one would) but does NOT
            # commit yet -- simulating "worker A is currently processing it".
            locked = (
                await session1.exec(
                    select(AudioBlob)
                    .where(AudioBlob.id == blob_a.id)
                    .with_for_update(skip_locked=True)
                )
            ).first()
            assert locked is not None

            # Session 2 claims: blob_a is locked (invisible to SKIP LOCKED),
            # so it must land on blob_b instead, never blob_a.
            claimed = await claim_one(session2)
            assert claimed is not None
            assert claimed.id == blob_b.id
            assert claimed.id != blob_a.id

            # A third claim attempt: blob_b is now `processing` (committed by
            # claim_one) and blob_a is still locked (uncommitted in session1)
            # -> nothing eligible is claimable.
            session3 = async_session_factory()
            try:
                claimed_again = await claim_one(session3)
                assert claimed_again is None
            finally:
                await session3.close()
        finally:
            await session1.rollback()  # release the lock on blob_a
            await session1.close()
            await session2.close()
    finally:
        await _cleanup_blob(blob_a.id)
        await _cleanup_blob(blob_b.id)


@pytest.mark.asyncio
async def test_retryable_error_returns_to_pending_then_fails_after_max_attempts() -> None:
    blob = await _make_blob(status=TranscriptStatus.PROCESSING)
    await _put_fake_bytes(blob)
    try:
        provider = FakeProviderRaises(_http_status_error(503))

        for expected_attempts in range(1, settings.asr_max_attempts):
            async with async_session_factory() as session:
                fresh = await session.get(AudioBlob, blob.id)
                await process_blob(session, fresh, provider)

            async with async_session_factory() as session:
                refreshed = await session.get(AudioBlob, blob.id)
                assert refreshed.transcript_attempts == expected_attempts
                assert refreshed.transcript_status == TranscriptStatus.PENDING
                # simulate the worker reclaiming it for the next attempt
                refreshed.transcript_status = TranscriptStatus.PROCESSING
                session.add(refreshed)
                await session.commit()

        # one more retryable failure crosses asr_max_attempts -> failed
        async with async_session_factory() as session:
            fresh = await session.get(AudioBlob, blob.id)
            await process_blob(session, fresh, provider)

        async with async_session_factory() as session:
            refreshed = await session.get(AudioBlob, blob.id)
            assert refreshed.transcript_attempts == settings.asr_max_attempts
            assert refreshed.transcript_status == TranscriptStatus.FAILED
            assert refreshed.transcript_error is not None
    finally:
        _remove_fake_bytes(blob)
        await _cleanup_blob(blob.id)


@pytest.mark.asyncio
async def test_classify_error_matches_status_code_table() -> None:
    for code in (408, 429, 500, 502, 503, 504):
        assert classify_error(_http_status_error(code)) == "retryable"
    for code in (400, 413, 415, 422):
        assert classify_error(_http_status_error(code)) == "non_retryable"
    assert classify_error(httpx.ConnectTimeout("timed out")) == "retryable"


@pytest.mark.asyncio
async def test_non_retryable_http_error_fails_immediately_no_retry() -> None:
    blob = await _make_blob(status=TranscriptStatus.PROCESSING)
    await _put_fake_bytes(blob)
    try:
        provider = FakeProviderRaises(_http_status_error(422))
        async with async_session_factory() as session:
            fresh = await session.get(AudioBlob, blob.id)
            await process_blob(session, fresh, provider)

        async with async_session_factory() as session:
            refreshed = await session.get(AudioBlob, blob.id)
            assert refreshed.transcript_status == TranscriptStatus.FAILED
            assert refreshed.transcript_error is not None
            # non-retryable path never increments attempts -- there's no retry
            assert refreshed.transcript_attempts == 0
    finally:
        _remove_fake_bytes(blob)
        await _cleanup_blob(blob.id)


@pytest.mark.asyncio
async def test_empty_transcript_fails_immediately_no_retry() -> None:
    blob = await _make_blob(status=TranscriptStatus.PROCESSING)
    await _put_fake_bytes(blob)
    try:
        empty_result = TranscriptResult(duration_ms=500, segments=[])
        provider = FakeProviderSuccess(empty_result)
        async with async_session_factory() as session:
            fresh = await session.get(AudioBlob, blob.id)
            await process_blob(session, fresh, provider)

        async with async_session_factory() as session:
            refreshed = await session.get(AudioBlob, blob.id)
            assert refreshed.transcript_status == TranscriptStatus.FAILED
            assert refreshed.transcript_error is not None
            assert refreshed.transcript_attempts == 0
    finally:
        _remove_fake_bytes(blob)
        await _cleanup_blob(blob.id)


@pytest.mark.asyncio
async def test_non_blank_segment_with_no_words_is_invalid_fails_no_retry() -> None:
    """A segment with real text but an empty words list would silently
    violate the §3.6 word-level guarantee if shipped -- must be treated as
    an invalid/empty transcript (non-retryable failed), not `ready`."""
    blob = await _make_blob(status=TranscriptStatus.PROCESSING)
    await _put_fake_bytes(blob)
    try:
        wordless_result = TranscriptResult(
            duration_ms=1000,
            segments=[
                TranscriptSegment(
                    order_index=0, start_ms=0, end_ms=1000, text="Hello.", words=[]
                )
            ],
        )
        provider = FakeProviderSuccess(wordless_result)
        async with async_session_factory() as session:
            fresh = await session.get(AudioBlob, blob.id)
            await process_blob(session, fresh, provider)

        async with async_session_factory() as session:
            refreshed = await session.get(AudioBlob, blob.id)
            assert refreshed.transcript_status == TranscriptStatus.FAILED
            assert refreshed.transcript_error is not None
            assert refreshed.transcript_attempts == 0

            segments = (
                await session.exec(
                    select(AudioSegment).where(AudioSegment.blob_id == blob.id)
                )
            ).all()
            assert segments == [], "no wordless segment should ever be persisted"
    finally:
        _remove_fake_bytes(blob)
        await _cleanup_blob(blob.id)


@pytest.mark.asyncio
async def test_classify_error_storage_errors() -> None:
    from botocore.exceptions import ClientError

    def _client_error(code: str) -> ClientError:
        return ClientError({"Error": {"Code": code}}, "GetObject")

    # Transient/infra R2 errors -> retryable.
    assert classify_error(_client_error("SlowDown")) == "retryable"
    assert classify_error(_client_error("InternalError")) == "retryable"
    assert classify_error(_client_error("ServiceUnavailable")) == "retryable"

    # Genuinely-permanent R2 errors -> non_retryable.
    assert classify_error(_client_error("NoSuchKey")) == "non_retryable"
    assert classify_error(_client_error("AccessDenied")) == "non_retryable"

    # Local disk: generic OSError is a transient infra hiccup (retryable),
    # but a missing file means storage_key points at nothing (non_retryable).
    assert classify_error(OSError("disk hiccup")) == "retryable"
    assert classify_error(FileNotFoundError("no such file")) == "non_retryable"


@pytest.mark.asyncio
async def test_process_blob_never_raises_when_storage_read_fails() -> None:
    """A missing/unreadable file behind storage_key must not propagate --
    process_blob's docstring promises it never raises."""
    blob = await _make_blob(status=TranscriptStatus.PROCESSING)
    # deliberately do NOT put bytes behind blob.storage_key -> get() raises
    # FileNotFoundError, which classify_error maps to non_retryable.
    try:
        async with async_session_factory() as session:
            fresh = await session.get(AudioBlob, blob.id)
            await process_blob(session, fresh, FakeProviderSuccess(FIXTURE_RESULT))

        async with async_session_factory() as session:
            refreshed = await session.get(AudioBlob, blob.id)
            assert refreshed.transcript_status == TranscriptStatus.FAILED
            assert refreshed.transcript_error is not None
    finally:
        await _cleanup_blob(blob.id)


@pytest.mark.asyncio
async def test_persist_failure_on_success_path_is_retryable_not_lost() -> None:
    """If persisting a successful transcript fails (e.g. a DB constraint
    violation / infra hiccup), process_blob must not raise or leave the blob
    stuck `processing` -- it should be treated as a retryable failure
    (Fix 1)."""
    blob = await _make_blob(status=TranscriptStatus.PROCESSING)
    await _put_fake_bytes(blob)
    try:
        # Pre-seed a segment at order_index=0 for this blob so
        # persist_transcript_result's insert of a *second* order_index=0
        # collides with the uq_audio_segment_blob_order unique constraint,
        # simulating an unexpected DB failure on the success path.
        async with async_session_factory() as session:
            session.add(
                AudioSegment(
                    blob_id=blob.id,
                    order_index=0,
                    start_ms=0,
                    end_ms=100,
                    text="pre-existing",
                    words=[],
                )
            )
            await session.commit()

        async with async_session_factory() as session:
            fresh = await session.get(AudioBlob, blob.id)
            await process_blob(session, fresh, FakeProviderSuccess(FIXTURE_RESULT))

        async with async_session_factory() as session:
            refreshed = await session.get(AudioBlob, blob.id)
            # retryable: back to pending (not stuck `processing`), attempts++
            assert refreshed.transcript_status == TranscriptStatus.PENDING
            assert refreshed.transcript_attempts == 1
    finally:
        _remove_fake_bytes(blob)
        await _cleanup_blob(blob.id)


@pytest.mark.asyncio
async def test_recover_stale_resets_processing_to_pending() -> None:
    blob = await _make_blob(status=TranscriptStatus.PROCESSING)
    try:
        async with async_session_factory() as session:
            recovered = await recover_stale(session)
            assert recovered >= 1

        async with async_session_factory() as session:
            refreshed = await session.get(AudioBlob, blob.id)
            assert refreshed.transcript_status == TranscriptStatus.PENDING
    finally:
        await _cleanup_blob(blob.id)

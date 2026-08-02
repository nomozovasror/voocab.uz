"""Postgres-backed async transcription worker (§9 of the audio-ingestion brief).

The queue is ``audio_blob.transcript_status`` itself — no Redis, no external
broker (volume is small: ~200-500/month). Multiple worker instances are safe
concurrently thanks to ``SELECT ... FOR UPDATE SKIP LOCKED`` in
:func:`claim_one`: a row locked by one worker is invisible to another's claim
query rather than blocking it, so nothing is ever double-processed in
steady state.

Entrypoint: ``python -m app.worker``.

Logic is split into small, independently testable functions (rather than one
big loop) precisely so §9's acceptance criteria can be driven directly
against the real DB with a fake/mock ``ASRProvider`` in tests — see
``tests/test_worker.py``.
"""

import asyncio
import logging
import signal

import httpx
from sqlmodel import select

from app.core.config import settings
from app.core.database import AsyncSession, async_session_factory
from app.models.audio_blob import AudioBlob, TranscriptStatus
from app.services.asr import ASRProvider, GroqASR, TranscriptResult
from app.services.audio import persist_transcript_result
from app.services.storage import get_storage

logger = logging.getLogger("app.worker")

# §9.3 error classification.
RETRYABLE_HTTP_STATUS_CODES = {408, 429, 500, 502, 503, 504}
NON_RETRYABLE_HTTP_STATUS_CODES = {400, 413, 415, 422}

# S3/R2 (botocore) error codes that mean "the object/bucket/credentials are
# genuinely wrong" -- retrying won't help, so these stay non-retryable.
# Everything else from botocore (throttling, 5xx, transient timeouts) is
# treated as a transient infra hiccup -- retryable.
NON_RETRYABLE_S3_ERROR_CODES = {
    "NoSuchKey",
    "NoSuchBucket",
    "404",
    "AccessDenied",
    "InvalidAccessKeyId",
    "SignatureDoesNotMatch",
}


def get_asr_provider() -> ASRProvider:
    """The ASR backend the worker uses. Only Groq is active today; swapping
    providers later is a one-line change here, nothing else in the worker."""
    return GroqASR()


async def recover_stale(session: AsyncSession) -> int:
    """Startup recovery: any blob left ``processing`` by a crashed/restarted
    worker goes back to ``pending`` so it's picked up again. Returns how many
    rows were recovered.

    Assumption: effectively a single worker at this volume (~200-500/month,
    per §9.1). Running this at startup with more than one worker instance
    has a theoretical startup-time race (two workers could both reset +
    reclaim overlapping rows before either progresses) — an accepted caveat
    at this scale. Steady-state double-processing is still impossible either
    way, because ``claim_one``'s SKIP LOCKED is what actually prevents it.
    """
    stale = (
        await session.exec(
            select(AudioBlob).where(
                AudioBlob.transcript_status == TranscriptStatus.PROCESSING
            )
        )
    ).all()
    for blob in stale:
        blob.transcript_status = TranscriptStatus.PENDING
        session.add(blob)
    if stale:
        await session.commit()
    return len(stale)


async def claim_one(session: AsyncSession) -> AudioBlob | None:
    """Atomically claim one ``pending`` blob for processing, or return
    ``None`` if the queue is empty (or every pending row is locked by
    another worker right now)."""
    stmt = (
        select(AudioBlob)
        .where(AudioBlob.transcript_status == TranscriptStatus.PENDING)
        .order_by(AudioBlob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    blob = (await session.exec(stmt)).first()
    if blob is None:
        return None
    blob.transcript_status = TranscriptStatus.PROCESSING
    session.add(blob)
    await session.commit()
    await session.refresh(blob)
    return blob


def classify_error(exc: Exception) -> str:
    """Map an exception raised while processing a blob to ``"retryable"`` or
    ``"non_retryable"`` per §9.3.

    Retryable: network timeouts/transport errors, HTTP
    408/429/500/502/503/504, and transient storage-layer errors (R2/S3
    throttling or 5xx via botocore, or a local-disk I/O hiccup) — these are
    infra problems, not a problem with the audio, so they're worth retrying.
    Non-retryable: HTTP 400/413/415/422, corrupt/unreadable audio, a storage
    error that means the object genuinely doesn't exist or credentials are
    wrong (retrying can't fix that), and any other unexpected error —
    retrying the same bytes against the same provider would just fail the
    same way, so these go straight to ``failed`` with no fallback provider
    (§9.3 note).
    """
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return "retryable" if code in RETRYABLE_HTTP_STATUS_CODES else "non_retryable"
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return "retryable"

    # boto3/botocore is only actually exercised by R2Storage, but importing
    # botocore.exceptions is cheap (boto3 is already a main dependency) and
    # lets us classify storage errors instead of lumping every non-httpx
    # exception into "non_retryable".
    from botocore.exceptions import ClientError

    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        return "non_retryable" if code in NON_RETRYABLE_S3_ERROR_CODES else "retryable"

    if isinstance(exc, OSError):
        # Local-disk hiccups (permission/IO blips) are infra -- retryable.
        # A genuinely missing file means the blob's storage_key points at
        # nothing, which retrying can't fix.
        return "non_retryable" if isinstance(exc, FileNotFoundError) else "retryable"

    return "non_retryable"


def _is_empty_transcript(result: TranscriptResult) -> bool:
    """True if the transcript is empty/unusable, per §3.6's word-level
    guarantee: no segments at all, every segment blank, OR any segment with
    non-blank text but zero words. That last case previously slipped through
    silently and would have shipped a `ready` blob with wordless segments,
    quietly violating the mandatory word-level timing guarantee -- treat it
    as invalid instead so it surfaces as a `failed` blob."""
    if not result.segments:
        return True
    if all(not seg.text.strip() for seg in result.segments):
        return True
    return any(seg.text.strip() and not seg.words for seg in result.segments)


async def _mark_ready(
    session: AsyncSession, blob: AudioBlob, result: TranscriptResult
) -> None:
    # Shared with the offline seed script (Faza 6) so both paths produce
    # identical AudioSegment/AudioBlob rows regardless of which ASR ran.
    await persist_transcript_result(session, blob, result)
    await session.commit()


async def _mark_failed(session: AsyncSession, blob: AudioBlob, error: str) -> None:
    """Immediate, non-retryable failure. No attempts increment — there's no
    retry to count."""
    blob.transcript_status = TranscriptStatus.FAILED
    blob.transcript_error = error[:2000]
    session.add(blob)
    await session.commit()


async def _mark_retry_or_failed(
    session: AsyncSession, blob: AudioBlob, error: str
) -> None:
    """Retryable failure: bump attempts and go back to ``pending``, unless
    that was the last allowed attempt — then ``failed``."""
    blob.transcript_attempts += 1
    if blob.transcript_attempts >= settings.asr_max_attempts:
        blob.transcript_status = TranscriptStatus.FAILED
        blob.transcript_error = error[:2000]
    else:
        blob.transcript_status = TranscriptStatus.PENDING
    session.add(blob)
    await session.commit()


async def process_blob(
    session: AsyncSession, blob: AudioBlob, provider: ASRProvider
) -> None:
    """Run ASR for one claimed (``processing``) blob and resolve its state
    in a single transaction. Never raises — every failure path, INCLUDING a
    failure while persisting a successful transcript, is recorded on the row
    itself (§9.2/§9.3), so a bad blob can't take down the worker loop or
    poison other blobs.
    """
    # Captured up front as a plain value: if the persist-on-success path
    # below fails and we roll back, `blob`'s attributes are expired and
    # re-reading them would need a sync DB round-trip outside of the async
    # greenlet context (MissingGreenlet). The id never changes, so grab it
    # before anything can invalidate the ORM instance.
    blob_id = blob.id

    try:
        data = await get_storage().get(blob.storage_key)
        result = await provider.transcribe(data, blob.mime_type, language="en")
    except Exception as exc:  # noqa: BLE001 - classified below, never propagated
        classification = classify_error(exc)
        message = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "blob %s transcription failed (%s): %s", blob_id, classification, message
        )
        if classification == "retryable":
            await _mark_retry_or_failed(session, blob, message)
        else:
            await _mark_failed(session, blob, message)
        return

    if _is_empty_transcript(result):
        logger.warning("blob %s produced an empty/invalid transcript", blob_id)
        await _mark_failed(session, blob, "ASR returned an empty transcript")
        return

    try:
        await _mark_ready(session, blob, result)
    except Exception as exc:  # noqa: BLE001 - never propagated; see below
        # A DB/commit failure here is an infra problem, not a problem with
        # the transcript we just got back -- treat it as retryable (bounded
        # by asr_max_attempts) rather than losing the ASR output outright by
        # letting the exception escape and leaving the blob stuck
        # `processing`. Roll back first: the failed flush/commit may have
        # left ORM state (incl. `blob`) stale/detached.
        await session.rollback()
        message = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "blob %s failed to persist a ready transcript (retryable): %s",
            blob_id,
            message,
        )
        fresh = await session.get(AudioBlob, blob_id)
        assert fresh is not None
        await _mark_retry_or_failed(session, fresh, message)
        return

    logger.info(
        "blob %s ready (%d segment(s), %dms)",
        blob_id,
        len(result.segments),
        result.duration_ms,
    )


_stop_event = asyncio.Event()


def _request_stop(*_args: object) -> None:
    _stop_event.set()


async def _sleep_or_stop(seconds: float) -> None:
    """Sleep up to ``seconds``, waking early if a stop signal arrives."""
    try:
        await asyncio.wait_for(_stop_event.wait(), timeout=seconds)
    except TimeoutError:
        pass


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:  # pragma: no cover - platforms without signals
            pass

    provider = get_asr_provider()

    async with async_session_factory() as session:
        recovered = await recover_stale(session)
        if recovered:
            logger.info("recovered %d stale processing blob(s) to pending", recovered)

    logger.info(
        "worker started; polling every %.1fs (max_attempts=%d)",
        settings.asr_poll_interval_s,
        settings.asr_max_attempts,
    )

    while not _stop_event.is_set():
        async with async_session_factory() as session:
            blob = await claim_one(session)

        if blob is None:
            await _sleep_or_stop(settings.asr_poll_interval_s)
            continue

        async with async_session_factory() as session:
            fresh = await session.get(AudioBlob, blob.id)
            assert fresh is not None
            try:
                await process_blob(session, fresh, provider)
            except Exception:  # noqa: BLE001 - last-resort safety net
                # process_blob already guards its own success/failure paths
                # (including the persist-on-success path), so reaching here
                # means something truly unexpected happened (e.g. a second
                # failure while recording the first). Never let one bad blob
                # kill the worker process: log and move on. The blob may be
                # left `processing`; recover_stale reclaims it on the next
                # worker restart.
                logger.exception(
                    "blob %s: unexpected error escaped process_blob; continuing",
                    blob.id,
                )
                continue
            await session.refresh(fresh)
            status_after = fresh.transcript_status
            attempts_after = fresh.transcript_attempts

        if status_after == TranscriptStatus.PENDING and attempts_after > 0:
            # Retryable failure: back off before the next claim so we don't
            # hammer a flaky/rate-limited provider immediately.
            # NOTE (reviewer finding #6, not fixed): this sleep blocks the
            # whole poll loop, not just this blob -- a per-blob backoff would
            # need a `next_attempt_at` column, which we deliberately kept out
            # of the frozen §4 schema. Acceptable at ~200-500 blobs/month.
            backoff = settings.asr_backoff_base_s * (2 ** (attempts_after - 1))
            logger.info(
                "blob %s backing off %.1fs before retry (attempt %d)",
                blob.id,
                backoff,
                attempts_after,
            )
            await _sleep_or_stop(backoff)

    logger.info("worker stopping")


if __name__ == "__main__":
    asyncio.run(main())

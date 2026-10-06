"""The background process: transcription, the difficulty refresh, the
lexicon's own enrichment, and the audio layer's text-to-speech and clips.

Five loops, run concurrently, and they have nothing to do with each other
beyond all five being work that must not happen inside a request.

**Transcription** (§9 of the audio-ingestion brief). The queue is
``audio_blob.transcript_status`` itself — no Redis, no external broker
(volume is small: ~200-500/month). Multiple worker instances are safe
concurrently thanks to ``SELECT ... FOR UPDATE SKIP LOCKED`` in
:func:`claim_one`: a row locked by one worker is invisible to another's claim
query rather than blocking it, so nothing is ever double-processed in
steady state.

**Difficulty** (:func:`app.services.difficulty.recompute`). Every material's
tally, refilled into ``material_difficulty`` on a timer. It lives here rather
than in a container of its own because "the process that does the work
nobody is waiting for" already exists, is already restart-managed, and this
is one query every fifteen minutes.

Its own loop rather than a step in the transcription one: that loop's pace is
set by the queue, and it sleeps out a doubling backoff after a failed ASR
call. A refresh queued behind that would run when the audio provider felt
like letting it.

**Lexicon enrichment** (`app.services.lexicon_enrich`, `lexicon-spec.md`
P3). `app.services.lexicon.link_row` runs synchronously on every
``material_vocabulary`` write (seed import and live lookup alike) and never
calls a model — it gives the row a ``Lexeme`` and a PROVISIONAL
``LexemeSense`` built from its own wording, and clears that lexeme's
``enriched_at``. This loop is what turns a provisional sense into a real
dictionary entry: the same per-lexeme, idempotent enrichment
``scripts/enrich_lexicon.py --all`` runs by hand, on a timer, picking up
whatever ``enriched_at IS NULL`` — a lexeme ``link_row`` just created, or one
an earlier pass of THIS loop failed on and left exactly as it found it
(:func:`app.services.lexicon_enrich.enrich` writes nothing until every
model step for a lexeme has answered). Its own loop for the same reason
difficulty is: a Gemini call has nothing to do with polling the
transcription queue, and gating either on the other's pace would be an
accident of implementation, not a decision.

**Text to speech** (`app.services.tts`, vocabulary stage 3). The queue is
``audio_renders`` -- the same shape as transcription: a request inserts a
``pending`` row (never synthesises), this loop claims one with ``FOR UPDATE
SKIP LOCKED``, Kokoro-82M makes it, the row goes ``ready`` or back to
``pending`` with ``attempts`` bumped (``failed`` at ``tts_max_attempts``). It
needs the ``tts`` extra -- installed in the worker image only -- and where
``kokoro`` is not importable (the API image, a Mac host) it says so ONCE and
does not run: the rest of the worker is unaffected. A failure sleeps out a
doubling back-off, because a broken model must not spin the loop.

**Clips** (`app.services.word_clips`). For recordings that became ready since
the loop last looked, index where each lexicon word is spoken and cut the
small word / context files. It never verifies (that needs a GPU model and is
the seed script's job) -- clips are only SERVED once verified -- but it keeps
the cuts primed, so a later verification run has bytes to listen to. Own loop,
own interval: cutting is CPU the transcription poll should not queue behind.

Entrypoint: ``python -m app.worker``.

Logic is split into small, independently testable functions (rather than one
big loop) precisely so §9's acceptance criteria can be driven directly
against the real DB with a fake/mock ``ASRProvider`` in tests — see
``tests/test_worker.py``.
"""

import asyncio
import logging
import signal
import time

from sqlmodel import select

from app.core.config import settings
from app.core.database import AsyncSession, async_session_factory
from app.models.audio_blob import AudioBlob, TranscriptStatus
from app.models.audio_render import AudioRender, RenderStatus
from app.models.lexicon import Lexeme
from app.services import accents
from app.services import difficulty as difficulty_service
from app.services import lexicon_enrich as lexicon_enrich_service
from app.services import lexicon_hints as lexicon_hints_service
from app.services import tts as tts_service
from app.services import word_clips as word_clips_service
from app.services.asr import ASRProvider, GroqASR, TranscriptResult
from app.services.audio import persist_transcript_result
from app.services.infra_errors import (  # noqa: F401 - re-exported: the worker's own names
    NON_RETRYABLE_HTTP_STATUS_CODES,
    NON_RETRYABLE_S3_ERROR_CODES,
    RETRYABLE_HTTP_STATUS_CODES,
    classify_error,
)
from app.services.storage import get_storage

logger = logging.getLogger("app.worker")

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


async def refresh_difficulty_once() -> int:
    """One pass of the difficulty projection. Never raises.

    Swallowing the error is the right call here and not laziness: a failed
    refresh means the catalogue's bands are one interval staler than they
    would have been, which is a state the page is already built to survive
    (a material with no row reads as ``New``). Letting it escape would take
    the transcription loop down with it — two unrelated jobs, one of which
    people are waiting on.
    """
    try:
        async with async_session_factory() as session:
            return await difficulty_service.recompute(session)
    except Exception:  # noqa: BLE001 - logged; the next pass tries again
        logger.exception("difficulty refresh failed; will retry next interval")
        return 0


async def _difficulty_loop() -> None:
    """Refill the difficulty projection every ``difficulty_refresh_interval_s``.

    Runs once at startup before waiting, so a fresh database — or one whose
    refresher has been down — is correct within a moment of the worker coming
    up rather than a quarter of an hour later.
    """
    interval = settings.difficulty_refresh_interval_s
    if interval <= 0:
        logger.info("difficulty refresh disabled (interval <= 0)")
        return

    logger.info("difficulty refresh every %.0fs", interval)
    while not _stop_event.is_set():
        written = await refresh_difficulty_once()
        logger.info("difficulty refreshed for %d material(s)", written)
        await _sleep_or_stop(interval)


#: lexeme id -> (consecutive failures, monotonic time before which it is not
#: retried). A lexeme that keeps failing is backed off so it cannot be the
#: oldest pending row of every batch forever.
_enrich_failures: dict = {}
ENRICH_BACKOFF_BASE_S = 3600.0
ENRICH_BACKOFF_MAX_S = 86400.0


def _enrich_blocked(now: float) -> list:
    return [lid for lid, (_n, until) in _enrich_failures.items() if until > now]


def _enrich_fail(lexeme_id: object, now: float) -> None:
    count = _enrich_failures.get(lexeme_id, (0, 0.0))[0] + 1
    delay = min(ENRICH_BACKOFF_BASE_S * 2 ** (count - 1), ENRICH_BACKOFF_MAX_S)
    _enrich_failures[lexeme_id] = (count, now + delay)
    logger.error(
        "lexicon enrichment of lexeme %s failed %d time(s); backing off %.0fs",
        lexeme_id, count, delay,
    )


async def _lexicon_enrich_once(
    gemini: lexicon_enrich_service.Gemini, oewn: dict[tuple[str, str], list[dict]]
) -> int:
    """One pass: enrich up to ``lexicon_enrich_batch_size`` lexemes still
    ``enriched_at IS NULL`` -- a brand-new find-or-create ``Lexeme``
    (:func:`app.services.lexicon.link_row`), or one an earlier pass left
    exactly as it found it. Returns how many were enriched; 0 means the queue
    is empty or everything failed (never raises).

    ``enrich`` writes nothing unless the whole batch succeeds, so a failed
    batch is retried lexeme by lexeme to find the one that fails; each
    failing lexeme is backed off (1h, 2h, ... capped at 24h) and skipped by
    the selection, so one poison lexeme cannot stall the queue.
    """
    now = time.monotonic()
    blocked = _enrich_blocked(now)
    async with async_session_factory() as session:
        query = select(Lexeme.id).where(Lexeme.enriched_at.is_(None))
        if blocked:
            query = query.where(Lexeme.id.not_in(blocked))
        ids = list((await session.exec(
            query.order_by(Lexeme.created_at).limit(settings.lexicon_enrich_batch_size)
        )).all())
    if not ids:
        return 0
    done_ids: list = []
    try:
        await lexicon_enrich_service.enrich(async_session_factory, gemini, ids, oewn)
        done_ids = ids
    except Exception:  # noqa: BLE001 - logged; isolated below
        logger.exception("lexicon enrichment failed for a batch of %d lexeme(s)", len(ids))
        if len(ids) == 1:
            _enrich_fail(ids[0], now)
        else:
            for lexeme_id in ids:
                try:
                    await lexicon_enrich_service.enrich(
                        async_session_factory, gemini, [lexeme_id], oewn
                    )
                    done_ids.append(lexeme_id)
                except Exception:  # noqa: BLE001
                    logger.exception("lexicon enrichment of lexeme %s failed", lexeme_id)
                    _enrich_fail(lexeme_id, now)
    for lexeme_id in done_ids:
        _enrich_failures.pop(lexeme_id, None)
    if not done_ids:
        return 0
    ids = done_ids
    # `enrich` just gave these lexemes' senses fresh `definition_en`/
    # `oewn_synset_id` values, which may change whether recall's
    # first-letter cue is worth showing on them (`app.services
    # .lexicon_hints`). Guarded and swallowed: a stale cue flag is a smaller
    # failure than taking the enrichment loop down over it.
    try:
        async with async_session_factory() as session:
            await lexicon_hints_service.recompute_for_lexemes(session, ids)
    except Exception:  # noqa: BLE001 - logged; the next enrichment pass retries
        logger.exception(
            "needs_letter_hint recompute failed for %d lexeme(s)", len(ids)
        )
    return len(ids)


async def _lexicon_loop() -> None:
    """Turn `link_row`'s provisional senses into a real dictionary entry --
    see the module docstring's "Lexicon enrichment" section.

    Disabled the same way the difficulty refresh is (``interval <= 0``), and
    additionally when no ``GEMINI_API_KEY`` is configured: there is nothing
    this loop could do without one, and logging a failed request every
    interval forever is worse than saying so once at startup.
    """
    interval = settings.lexicon_enrich_interval_s
    if interval <= 0:
        logger.info("lexicon enrichment disabled (interval <= 0)")
        return
    if not settings.gemini_api_key:
        logger.info("lexicon enrichment disabled (no GEMINI_API_KEY)")
        return

    oewn = lexicon_enrich_service.load_oewn()
    usage = lexicon_enrich_service.UsageLog()
    gemini = lexicon_enrich_service.Gemini(usage)
    logger.info(
        "lexicon enrichment every %.0fs, batch %d",
        interval, settings.lexicon_enrich_batch_size,
    )
    try:
        while not _stop_event.is_set():
            done = await _lexicon_enrich_once(gemini, oewn)
            if done:
                logger.info(
                    "lexicon: enriched %d lexeme(s), running cost $%.4f",
                    done, usage.total_cost(),
                )
            else:
                logger.info("lexicon: 0 pending")
            # A full batch means there is likely more behind it -- keep
            # draining rather than waiting out the whole interval. Anything
            # short of a full batch, including 0, waits the ordinary pace.
            await _sleep_or_stop(
                1.0 if done >= settings.lexicon_enrich_batch_size else interval
            )
    finally:
        await gemini.aclose()


#: Longest sleep after consecutive render failures.
TTS_BACKOFF_MAX_S = 60.0

#: How often the render loop runs its queue housekeeping (stale `processing`
#: rows, old `failed` ones). One cheap UPDATE each.
RENDER_MAINTENANCE_EVERY_S = 60.0


async def render_once(
    synth: tts_service.Synth, *, keys: list[str] | None = None
) -> str:
    """Claim and make ONE render. Returns ``"empty"`` (nothing pending),
    ``"ready"``, ``"retry"`` (failed, will be tried again) or ``"failed"``
    (out of attempts). Never raises: ``process_render`` records its own
    failures on the row, and anything it could not -- a database that went
    away mid-claim -- is logged here and reported as a retry. ``keys`` narrows
    the claim to those renders (tests; the loop passes nothing)."""
    try:
        async with async_session_factory() as session:
            row = await tts_service.claim_render(session, keys=keys)
        if row is None:
            return "empty"
        async with async_session_factory() as session:
            fresh = await session.get(AudioRender, row.id)
            assert fresh is not None
            await tts_service.process_render(session, fresh, synth)
            await session.refresh(fresh)
            return {
                RenderStatus.READY: "ready",
                RenderStatus.FAILED: "failed",
            }.get(fresh.status, "retry")
    except Exception:  # noqa: BLE001 - last-resort safety net
        logger.exception("render pass failed unexpectedly; continuing")
        return "retry"


async def maintain_renders() -> tuple[int, int]:
    """Queue housekeeping, run at the loop's start (the "startup recovery") and
    every :data:`RENDER_MAINTENANCE_EVERY_S`: stale ``processing`` rows back to
    ``pending``, old ``failed`` ones requeued. Never raises -- it runs inside
    ``asyncio.gather`` beside the transcription loop, and a database that is
    not up yet at startup must not take the worker down."""
    try:
        async with async_session_factory() as session:
            recovered, requeued = await tts_service.maintain_queue(session)
    except Exception:  # noqa: BLE001 - housekeeping only; the next pass retries
        logger.exception("render queue maintenance failed; will retry")
        return 0, 0
    if recovered:
        logger.info("recovered %d stale processing render(s) to pending", recovered)
    if requeued:
        logger.info("requeued %d old failed render(s)", requeued)
    return recovered, requeued


async def _render_loop() -> None:
    """Make the audio the app has asked for -- see the module docstring's
    "Text to speech" section."""
    interval = settings.tts_poll_interval_s
    if interval <= 0:
        logger.info("text to speech disabled (interval <= 0)")
        return
    if not tts_service.kokoro_available():
        logger.info("text to speech disabled (kokoro is not installed in this image)")
        return

    synth = tts_service.KokoroSynth()
    logger.info(
        "text to speech polling every %.1fs (voices %s, max_attempts=%d)",
        interval, ", ".join(a.voice for a in accents.ACCENTS.values()),
        settings.tts_max_attempts,
    )
    failures = 0
    last_maintenance = float("-inf")
    while not _stop_event.is_set():
        # Recovery by AGE, inside the loop: a worker that died mid-render
        # leaves a row `processing` for ever otherwise, and "everything
        # processing" at startup would take rows a second live worker is
        # making. `maintain_queue` never raises.
        if time.monotonic() - last_maintenance >= RENDER_MAINTENANCE_EVERY_S:
            last_maintenance = time.monotonic()
            await maintain_renders()
        outcome = await render_once(synth)
        if outcome == "empty":
            failures = 0
            await _sleep_or_stop(interval)
        elif outcome == "ready":
            failures = 0
        else:
            failures += 1
            backoff = min(settings.tts_backoff_base_s * 2 ** (failures - 1), TTS_BACKOFF_MAX_S)
            logger.info("render %s; backing off %.1fs", outcome, backoff)
            await _sleep_or_stop(backoff)


#: Blobs whose clips this process has indexed. In memory: a restart simply
#: indexes everything once more, which is idempotent.
_clip_indexed: set = set()


async def clips_once() -> tuple[int, int]:
    """One pass of the clip step: index recordings not yet indexed by this
    process, then cut up to ``clips_batch_size`` candidates. Returns
    ``(indexed blobs, cut clips)``. Never raises."""
    try:
        async with async_session_factory() as session:
            fresh_blobs = await word_clips_service.unindexed_blob_ids(session, _clip_indexed)
            if fresh_blobs:
                report = await word_clips_service.index_clips(session, blob_ids=fresh_blobs)
                _clip_indexed.update(fresh_blobs)
                logger.info(
                    "clips: indexed %d recording(s), %d new candidate(s)",
                    report.blobs, report.inserted,
                )
        async with async_session_factory() as session:
            cut = await word_clips_service.cut_clips(
                session, limit=settings.clips_batch_size
            )
        return len(fresh_blobs), cut.cut
    except Exception:  # noqa: BLE001 - logged; the next pass tries again
        logger.exception("clip pass failed; will retry next interval")
        return 0, 0


async def _clips_loop() -> None:
    interval = settings.clips_interval_s
    if interval <= 0:
        logger.info("clip indexing disabled (interval <= 0)")
        return
    logger.info("clip indexing and cutting every %.0fs", interval)
    while not _stop_event.is_set():
        _indexed, cut = await clips_once()
        # A full batch means more are waiting: keep draining.
        await _sleep_or_stop(1.0 if cut >= settings.clips_batch_size else interval)


async def _transcription_loop(provider: ASRProvider) -> None:
    async with async_session_factory() as session:
        recovered = await recover_stale(session)
        if recovered:
            logger.info("recovered %d stale processing blob(s) to pending", recovered)

    logger.info(
        "transcription polling every %.1fs (max_attempts=%d)",
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


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:  # pragma: no cover - platforms without signals
            pass

    logger.info("worker started")
    # All five loops watch the same stop event, so one SIGTERM ends them
    # all and `gather` returns when the slowest has finished its current
    # step. None is allowed to fail another: the transcription loop guards
    # every blob it touches, and the others swallow their own errors.
    await asyncio.gather(
        _transcription_loop(get_asr_provider()),
        _difficulty_loop(),
        _lexicon_loop(),
        _render_loop(),
        _clips_loop(),
    )

    logger.info("worker stopping")


if __name__ == "__main__":
    asyncio.run(main())

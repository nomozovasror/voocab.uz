"""Offline bulk audio for vocabulary: clips from the recordings, then TTS for
the rest (stage 3 of the vocabulary brief, decisions 3 and 7).

NOT part of the API or the worker -- a standalone script the owner runs by
hand on a machine with a GPU (the RTX 3060, Windows), the same contract as
``seed_audio.py``: it reads and writes through the configured database and
``MediaStorage`` (R2 in production, local disk in dev -- whatever
``app.core.config.settings`` points at on the machine this runs on), and it
writes the EXACT rows and keys the production worker would
(:mod:`app.services.tts`, :mod:`app.services.word_clips`), so the worker, which
generates only what is new or changed, finds the seed's output already there.

The step-by-step Windows run (tunnel to the dev database, local media folder,
copying files across) is ``scripts/SEED_TTS_WINDOWS.md``. Start with
``doctor``.

Prerequisite (GPU machine only). One environment holds one torch build, so
the GPU machine installs the ``tts-gpu`` extra (CUDA torch from the cu128
index) -- NOT ``tts``, which is the CPU build the worker image uses -- plus
``seed`` for faster-whisper::

    uv sync --extra seed --extra tts-gpu

For a different CUDA than 12.8, replace torch in that environment after the
sync with the matching wheel index, one line::

    uv pip install --reinstall torch --index-url https://download.pytorch.org/whl/cu126

(Kokoro and misaki's espeak loader do not run on macOS at all -- the
``espeakng-loader`` wheel kills the interpreter -- so on the Mac this script's
``words``/``definitions``/``items`` refuse to start; ``clips`` needs only PyAV
and works anywhere. Docker/Linux is where Kokoro runs on the dev machine.)

Usage (from the ``backend/`` directory), in this order::

    uv run python -m scripts.seed_tts doctor                 # preflight: PASS/FAIL list
    uv run python -m scripts.seed_tts clips                  # index + cut candidates
    uv run python -m scripts.seed_tts verify-clips           # faster-whisper, GPU
    uv run python -m scripts.seed_tts words                  # TTS for every word, both accents
    uv run python -m scripts.seed_tts definitions            # TTS for every definition, both accents
    uv run python -m scripts.seed_tts items                  # optional: On the go files
    uv run python -m scripts.seed_tts check-files            # which rows point at a missing file

* ``doctor`` -- see :mod:`scripts.seed_tts_doctor`. Exit status 1 on any FAIL.
* ``clips`` -- index where every lexicon form is spoken in the transcripts
  and cut the word and its context from the recordings
  (:func:`app.services.word_clips.index_clips` / ``cut_clips``). Idempotent.
  ``--concurrency`` recordings are fetched and cut at once (default 4: each is
  held in memory whole).
* ``verify-clips`` -- transcribe each cut word with faster-whisper and keep it
  only if the word is heard. ``--model`` (default ``large-v3``; a smaller one,
  e.g. ``small.en``, is fine on a CPU dev machine), ``--device`` (default
  ``cuda``; ``cpu`` runs int8). One model stream; storage reads and database
  writes of ``--concurrency`` forms overlap it. Stops with an error after ten
  clips in a row that could not be read or transcribed (a broken CUDA install
  would otherwise warn its way through the library). Only ``verified`` clips are
  ever served.
* ``words`` -- the word read by Kokoro, for EVERY lexicon sense, whether or not
  its word has a verified clip (decision 26: a verified clip is what a learner
  hears today, but a later "prefer the synthetic voice" option must need no
  generation). ``--skip-clipped`` restores the old behaviour (only words
  without a verified clip; run it AFTER ``verify-clips``). Heteronym senses
  are given their decided pronunciation in the voice's own alphabet
  (``lexeme_senses.pronunciation`` for British, ``pronunciation_us`` for
  American; see ``scripts/decide_heteronyms.py``).
* ``definitions`` -- the masked definition of every sense, the masks silences.
* ``items`` -- the single On the go file per word in rotation (needs the
  parts; makes them inline if not ready).
* ``check-files`` -- ``--what clips|renders|all``: every ``cut``/``verified``
  clip and every ``ready`` render whose file is not in the configured storage.
  ``--requeue`` puts such renders back to ``pending``. The check to run on
  the machine that serves the files, after they were copied there.

The two voices (decisions 22-26) -- British ``bf_emma`` and American
``af_heart``, one table in :mod:`app.services.accents`. ``--accent
british|american|both`` (default ``both``) on ``words``, ``definitions`` and
``items`` chooses which are made; each voice is its own set of renders (the
voice is in every key), so running one accent now and the other later is safe
and nothing is made twice. The synthesiser holds one pipeline per voice sharing
one model, so ``both`` costs one model load.

Flags: ``--limit N`` stops after N items (a pilot); ``--saved-only`` restricts
``words``/``definitions`` to senses somebody has saved (the dev run: a few
hundred renders instead of seventeen thousand); ``--device`` is the torch
device for Kokoro and the whisper device -- default ``cuda``, and the run
REFUSES to start if torch has no CUDA rather than quietly synthesising seventeen
thousand renders on the CPU (say ``--device cpu`` to mean it);
``--concurrency N`` (default 8, at most 12) is how many renders are in flight.

**Concurrency.** The GPU does one synthesis at a time (Kokoro is not safe
concurrently), on one dedicated thread; what overlaps with it is everything
else -- encoding, the storage write, the database commit -- so the GPU is not
idle while a round trip to a disk or a database completes. See
:func:`app.services.tts.drain`. The dev worker may drain the same queue
meanwhile: claims are ``SKIP LOCKED`` and committed before work starts, so no
render is made twice.

Every subcommand is safe to re-run: renders are keyed by the hash of their
input, so existing ones are never made twice, a render that failed is retried
by ``--retry-failed``, and rows a killed run left ``processing`` are put back
by age (``tts_stale_after_s``) at the start of the next one. Ctrl+C releases
what it had claimed at once.

On Windows the script reconfigures the console to UTF-8 (misaki phonemes are
not cp1252), runs on the selector event loop (no noisy Proactor shutdown
errors with asyncpg) and makes torch's bundled CUDA DLLs findable for
faster-whisper (:func:`_prepare_windows`).

NOTE: the real GPU run is for the project owner to verify -- the development
sandbox has no GPU. The logic is covered by ``tests/test_seed_tts.py`` and
``tests/test_audio_layer.py`` with fake synthesiser and transcriber; what is
proven only by running it is Kokoro/faster-whisper themselves, which is what
``doctor`` is for.
"""

import argparse
import asyncio
import io
import logging
import os
import sys
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select as sa_select
from sqlalchemy import update
from sqlmodel import select

from app.core.config import settings
from app.core.database import AsyncSession, async_session_factory, engine
from app.models.audio_render import AudioRender, RenderKind, RenderStatus
from app.models.lexicon import Lexeme, LexemeSense
from app.models.vocabulary import SavedWord
from app.models.word_clip import ClipStatus, WordClip
from app.services import tts, word_audio, word_clips
from app.services.accents import ACCENTS, Accent
from app.services.storage import MediaStorage, get_storage

logger = logging.getLogger("scripts.seed_tts")

#: Specs are enqueued this many at a time.
ENQUEUE_BATCH = 500
#: Seconds between progress lines.
PROGRESS_EVERY_S = 20.0
DEFAULT_CONCURRENCY = 8
DEFAULT_CUT_CONCURRENCY = 4


# --- Windows ---------------------------------------------------------------------


def _prepare_windows() -> None:
    """Things only Windows needs, done before anything heavy is imported.

    * The console: Windows consoles default to cp1252 and misaki phonemes
      (``ɹˈɛkɔːd``) are not in it -- one such log line raises
      ``UnicodeEncodeError`` out of ``logging``. Both streams are switched to
      UTF-8 with ``errors='replace'`` (any platform: a pipe is no better).
    * ``KMP_DUPLICATE_LIB_OK``: torch and ctranslate2 each ship their own
      ``libiomp5md.dll`` and loading both aborts with "OMP: Error #15".
      ``doctor`` loads both in one process, which is the proof it is safe here.
    * The CUDA DLLs: faster-whisper's ctranslate2 needs cuBLAS 12 and cuDNN 9.
      The torch cu128 wheel (installed with the ``tts-gpu`` extra) bundles
      exactly those in ``torch\\lib``; that directory is put on the DLL search
      path and ``PATH`` WITHOUT importing torch (importing it would load its
      OpenMP runtime into a process that only wants whisper)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    if sys.platform != "win32":
        return
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    import importlib.util

    spec = importlib.util.find_spec("torch")
    if spec is None or not spec.submodule_search_locations:
        return
    lib = Path(list(spec.submodule_search_locations)[0]) / "lib"
    if lib.is_dir():
        os.add_dll_directory(str(lib))
        os.environ["PATH"] = str(lib) + os.pathsep + os.environ.get("PATH", "")


def _run(coro: Awaitable[None]) -> None:
    """``asyncio.run`` on the SELECTOR loop under Windows: asyncpg works on the
    default Proactor loop too, but closing its connections there prints
    ``ConnectionResetError [WinError 10054]`` tracebacks at exit. (The loop
    policy API is deprecated in 3.14; ``loop_factory`` is the way.)"""
    factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(coro, loop_factory=factory)  # type: ignore[arg-type]


# --- Progress --------------------------------------------------------------------


def format_duration(seconds: float | None) -> str:
    if seconds is None or seconds != seconds or seconds == float("inf"):
        return "?"
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m{secs:02d}s" if minutes else f"{secs}s"


class Throughput:
    """Items per second over a sliding window (so a slow start or the dev
    worker taking a share does not skew the estimate for hours), and the time
    left at that rate."""

    def __init__(self, window_s: float = 300.0, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._window = window_s
        self._samples: deque[tuple[float, int]] = deque([(clock(), 0)])

    def record(self, done: int) -> None:
        now = self._clock()
        self._samples.append((now, done))
        while len(self._samples) > 2 and now - self._samples[0][0] > self._window:
            self._samples.popleft()

    def rate(self) -> float:
        (t0, d0), (t1, d1) = self._samples[0], self._samples[-1]
        return (d1 - d0) / (t1 - t0) if t1 > t0 else 0.0

    def eta_s(self, remaining: int) -> float | None:
        rate = self.rate()
        return remaining / rate if rate > 0 else None


async def _report_progress(
    label: str,
    done: Callable[[], int],
    remaining: Callable[[], Awaitable[int]],
    every_s: float = PROGRESS_EVERY_S,
) -> None:
    """Log ``done / left / rate / ETA`` until cancelled. ``remaining`` is asked
    of the database each time, so a share of the queue taken by another drainer
    shows up as a shorter queue, not as a stalled estimate."""
    meter = Throughput()
    while True:
        await asyncio.sleep(every_s)
        count = done()
        meter.record(count)
        try:
            left = await remaining()
        except Exception:  # noqa: BLE001 - progress must never take the run down
            logger.debug("progress query failed", exc_info=True)
            continue
        logger.info(
            "%s: %d done, %d left, %.1f/s, ETA %s",
            label, count, left, meter.rate(), format_duration(meter.eta_s(left)),
        )


# --- What to enqueue ---------------------------------------------------------------


async def _senses(
    session: AsyncSession, *, saved_only: bool, limit: int | None
) -> list[LexemeSense]:
    """Every sense of every non-proper-noun lexeme that has a definition (the
    words need only a lexeme, but a sense is what carries the pronunciation),
    most useful first: the commonest sense of each word."""
    query = (
        select(LexemeSense)
        .join(Lexeme, Lexeme.id == LexemeSense.lexeme_id)
        .where(Lexeme.is_proper_noun.is_(False))
        .order_by(LexemeSense.sense_rank, Lexeme.lemma)
    )
    if saved_only:
        saved = sa_select(SavedWord.lexeme_sense_id)
        query = query.where(LexemeSense.id.in_(saved))
    if limit is not None:
        query = query.limit(limit)
    return list((await session.exec(query)).all())


async def _lexemes(session: AsyncSession, senses: list[LexemeSense]) -> dict[uuid.UUID, Lexeme]:
    if not senses:
        return {}
    return {
        lexeme.id: lexeme
        for lexeme in (
            await session.exec(select(Lexeme).where(Lexeme.id.in_({s.lexeme_id for s in senses})))
        ).all()
    }


async def word_specs(
    session: AsyncSession,
    *,
    saved_only: bool,
    limit: int | None,
    accents_: list[Accent],
    skip_clipped: bool = False,
) -> list[tts.RenderSpec]:
    """The word render of each sense, in each accent's voice -- clip or no clip
    (decision 26). ``skip_clipped`` restores the old rule: a word that has a
    verified clip, and is not a heteronym, is left out."""
    senses = await _senses(session, saved_only=saved_only, limit=limit)
    lexemes = await _lexemes(session, senses)
    specs: dict[str, tts.RenderSpec] = {}
    for accent in accents_:
        sources = await word_audio.word_sources(session, senses, accent=accent)
        for sense in senses:
            source = sources.get(sense.id)
            if source is None:
                continue
            if source.clip is not None and skip_clipped:
                continue
            spec = word_audio.tts_word_spec(sense, lexemes[sense.lexeme_id], accent)
            specs[spec.key] = spec
    return list(specs.values())


async def definition_specs(
    session: AsyncSession, *, saved_only: bool, limit: int | None, accents_: list[Accent]
) -> list[tts.RenderSpec]:
    senses = await _senses(session, saved_only=saved_only, limit=limit)
    lexemes = await _lexemes(session, senses)
    specs: dict[str, tts.RenderSpec] = {}
    for accent in accents_:
        for sense in senses:
            spec = tts.definition_spec(sense.definition_en, lexemes[sense.lexeme_id].lemma, accent)
            if spec is not None:
                specs[spec.key] = spec
    return list(specs.values())


async def enqueue_words(
    session: AsyncSession,
    *,
    saved_only: bool,
    limit: int | None,
    accents_: list[Accent],
    skip_clipped: bool = False,
) -> int:
    """Queue the word renders (:func:`word_specs`). Returns how many specs were
    offered (new ones are ``pending``, the rest already existed)."""
    return await _enqueue(
        await word_specs(
            session, saved_only=saved_only, limit=limit, accents_=accents_,
            skip_clipped=skip_clipped,
        )
    )


async def enqueue_definitions(
    session: AsyncSession, *, saved_only: bool, limit: int | None, accents_: list[Accent]
) -> int:
    return await _enqueue(
        await definition_specs(session, saved_only=saved_only, limit=limit, accents_=accents_)
    )


async def _enqueue(specs: list[tts.RenderSpec]) -> int:
    new = 0
    for offset in range(0, len(specs), ENQUEUE_BATCH):
        new += await tts.enqueue(specs[offset : offset + ENQUEUE_BATCH])
    logger.info("%d render(s) offered, %d new", len(specs), new)
    return new


async def enqueue_items(
    session: AsyncSession, *, limit: int | None, accents_: list[Accent]
) -> int:
    """Queue the On the go file (and its parts) of every word in rotation, in
    each accent's voice."""
    query = (
        select(SavedWord)
        .where(SavedWord.status.in_(("learning", "review")))
        .order_by(SavedWord.created_at.desc())
    )
    if limit is not None:
        query = query.limit(limit)
    words = list((await session.exec(query)).all())
    for accent in accents_:
        await word_audio.item_renders(session, words, accent=accent)
    return len(words)


# --- Running ---------------------------------------------------------------------


async def run_renders(
    kinds: list[str],
    synth: tts.Synth,
    *,
    limit: int | None,
    storage: MediaStorage | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> int:
    """Drain the render queue for ``kinds`` in-process -- the 3060 has no
    worker. Same claim and process as the worker's loop, ``concurrency`` renders
    in flight over one synthesis stream (:func:`app.services.tts.drain`)."""
    async with async_session_factory() as session:
        # Rows a killed earlier run left `processing`: by AGE, like the
        # worker, so a row the dev worker is making right now is never taken.
        recovered = await tts.recover_stale_renders(session, older_than_s=settings.tts_stale_after_s)
    if recovered:
        logger.info("%d stale processing render(s) put back to pending", recovered)
    start = time.monotonic()
    handled = 0

    def on_progress(done: int) -> None:
        nonlocal handled
        handled = done

    label = "/".join(kinds)
    reporter = asyncio.create_task(
        _report_progress(label, lambda: handled, lambda: tts.queue_depth(kinds))
    )
    try:
        done = await tts.drain(
            synth, kinds=kinds, limit=limit, storage=storage,
            on_progress=on_progress, concurrency=concurrency,
        )
    finally:
        reporter.cancel()
    elapsed = time.monotonic() - start
    logger.info(
        "%s: %d render(s) handled in %s (%.1f/s)", label, done, format_duration(elapsed),
        done / elapsed if elapsed > 0 else 0.0,
    )
    async with async_session_factory() as session:
        failed = (
            await session.exec(
                select(AudioRender.error).where(
                    AudioRender.status == RenderStatus.FAILED, AudioRender.kind.in_(kinds)
                ).limit(5)
            )
        ).all()
    if failed:
        logger.warning("some renders are `failed` (e.g. %r); see audio_renders.error", failed[0])
    return done


def make_transcriber(model_name: str, device: str) -> Callable[[bytes], str]:
    """The real verifier: faster-whisper over a clip's bytes. Lazy import --
    ``faster_whisper`` is the optional ``seed`` extra, absent everywhere
    except the GPU machine."""
    from faster_whisper import WhisperModel  # lazy: optional, GPU-only

    model = WhisperModel(
        model_name,
        device=device,
        compute_type="float16" if device == "cuda" else "int8",
    )

    def transcribe(data: bytes) -> str:
        segments, _info = model.transcribe(
            io.BytesIO(data),
            language="en",  # locked, like seed_audio: no auto-detect
            beam_size=5,
            without_timestamps=True,
            condition_on_previous_text=False,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()

    return transcribe


def selected_accents(args: argparse.Namespace) -> list[Accent]:
    """``--accent`` as a list: ``both`` (the default) is every accent we have."""
    return list(ACCENTS) if args.accent == "both" else [args.accent]


def _require_kokoro() -> None:
    if not tts.kokoro_available():
        raise SystemExit(
            "Kokoro is not installed. On the GPU machine: "
            "`uv sync --extra seed --extra tts-gpu`. (It cannot run on macOS.)"
        )


def resolve_device(requested: str | None) -> str:
    """``--device`` or ``cuda``; and ``cuda`` is refused when torch cannot see
    one. The alternative -- Kokoro quietly on the CPU -- is a run that looks
    healthy and takes days."""
    device = requested or "cuda"
    if device.startswith("cuda"):
        try:
            import torch

            available = torch.cuda.is_available()
        except ImportError:
            available = False
        if not available:
            raise SystemExit(
                "CUDA is not available to torch here (run `doctor`). Fix the install, or "
                "pass --device cpu if a CPU run is what you want."
            )
    return device


async def cmd_clips(args: argparse.Namespace) -> None:
    async with async_session_factory() as session:
        report = await word_clips.index_clips(session)
        logger.info(
            "indexed %d recording(s): %d candidate(s) seen, %d new",
            report.blobs, report.candidates_seen, report.inserted,
        )
    # Cut in slabs so a long run reports progress and a crash loses little.
    total = 0
    meter = Throughput()
    while args.limit is None or total < args.limit:
        remaining = None if args.limit is None else args.limit - total
        async with async_session_factory() as session:
            cut = await word_clips.cut_clips(
                session,
                limit=min(200, remaining) if remaining is not None else 200,
                concurrency=args.concurrency,
            )
        total += cut.cut + cut.failed
        meter.record(total)
        left = await word_clips.count_candidates()
        logger.info(
            "cut %d (failed %d, deferred %d); %d handled, %d candidate(s) left, %.1f/s, ETA %s",
            cut.cut, cut.failed, cut.deferred, total, left, meter.rate(),
            format_duration(meter.eta_s(left)),
        )
        if cut.cut + cut.failed == 0:
            break


async def cmd_verify(args: argparse.Namespace) -> None:
    transcribe = make_transcriber(args.model, resolve_device(args.device))
    report = word_clips.VerifyReport()
    reporter = asyncio.create_task(
        _report_progress(
            "verify-clips (forms)",
            lambda: report.forms_done,
            _forms_left(report),
        )
    )
    try:
        async with async_session_factory() as session:
            await word_clips.verify_clips(
                session, transcribe, limit_forms=args.limit,
                stop_at_first=not args.all_candidates,
                concurrency=args.concurrency, report=report,
            )
    finally:
        reporter.cancel()
    logger.info(
        "verified %d, rejected %d, over %d form(s)",
        report.verified, report.rejected, report.forms_done,
    )


def _forms_left(report: word_clips.VerifyReport) -> Callable[[], Awaitable[int]]:
    async def left() -> int:
        return max(0, report.forms_total - report.forms_done)

    return left


async def cmd_words(args: argparse.Namespace) -> None:
    _require_kokoro()
    device = resolve_device(args.device)
    if args.retry_failed:
        async with async_session_factory() as session:
            await tts.requeue_failed(session, kinds=[RenderKind.WORD])
    async with async_session_factory() as session:
        await enqueue_words(
            session, saved_only=args.saved_only, limit=args.limit,
            accents_=selected_accents(args), skip_clipped=args.skip_clipped,
        )
    await run_renders(
        [RenderKind.WORD], tts.KokoroSynth(device=device), limit=None,
        concurrency=args.concurrency,
    )


async def cmd_definitions(args: argparse.Namespace) -> None:
    _require_kokoro()
    device = resolve_device(args.device)
    if args.retry_failed:
        async with async_session_factory() as session:
            await tts.requeue_failed(session, kinds=[RenderKind.DEFINITION])
    async with async_session_factory() as session:
        await enqueue_definitions(
            session, saved_only=args.saved_only, limit=args.limit,
            accents_=selected_accents(args),
        )
    await run_renders(
        [RenderKind.DEFINITION], tts.KokoroSynth(device=device), limit=None,
        concurrency=args.concurrency,
    )


async def cmd_items(args: argparse.Namespace) -> None:
    _require_kokoro()
    device = resolve_device(args.device)
    async with async_session_factory() as session:
        count = await enqueue_items(
            session, limit=args.limit, accents_=selected_accents(args)
        )
    logger.info("%d word(s) in rotation queued", count)
    await run_renders(
        [RenderKind.WORD, RenderKind.DEFINITION, RenderKind.ITEM],
        tts.KokoroSynth(device=device),
        limit=None,
        concurrency=args.concurrency,
    )


# --- check-files -----------------------------------------------------------------


@dataclass
class FileCheck:
    """Rows whose file is not in storage."""

    checked: int = 0
    missing_clips: list[str] = field(default_factory=list)
    missing_renders: list[tuple[uuid.UUID, str]] = field(default_factory=list)


async def check_files(
    storage: MediaStorage, *, clips: bool, renders: bool, concurrency: int = 32
) -> FileCheck:
    """Every ``cut``/``verified`` clip file and every ``ready`` render file
    that ``storage`` does not have. The seed writes files where it runs and the
    database says ``ready`` the moment a file is written -- if the files are
    then copied to the machine that SERVES them, this is how to know they all
    arrived (a missing file is served as no audio, never an error)."""
    out = FileCheck()
    gate = asyncio.Semaphore(concurrency)
    async with async_session_factory() as session:
        clip_rows = (
            list(
                (
                    await session.exec(
                        select(WordClip.storage_key, WordClip.context_storage_key).where(
                            WordClip.status.in_((ClipStatus.CUT, ClipStatus.VERIFIED))
                        )
                    )
                ).all()
            )
            if clips
            else []
        )
        render_rows = (
            list(
                (
                    await session.exec(
                        select(AudioRender.id, AudioRender.storage_key).where(
                            AudioRender.status == RenderStatus.READY,
                            AudioRender.storage_key.is_not(None),
                        )
                    )
                ).all()
            )
            if renders
            else []
        )

    async def has(key: str) -> bool:
        async with gate:
            return await storage.exists(key)

    clip_keys = sorted({k for pair in clip_rows for k in pair if k})
    found = await asyncio.gather(*(has(k) for k in clip_keys))
    out.missing_clips = [k for k, ok in zip(clip_keys, found) if not ok]
    found = await asyncio.gather(*(has(key) for _id, key in render_rows))
    out.missing_renders = [(i, k) for (i, k), ok in zip(render_rows, found) if not ok]
    out.checked = len(clip_keys) + len(render_rows)
    return out


async def cmd_check_files(args: argparse.Namespace) -> None:
    result = await check_files(
        get_storage(), clips=args.what in ("clips", "all"), renders=args.what in ("renders", "all")
    )
    logger.info(
        "%d file(s) checked: %d clip file(s) and %d render file(s) missing",
        result.checked, len(result.missing_clips), len(result.missing_renders),
    )
    for key in result.missing_clips[:10]:
        logger.info("  missing clip: %s", key)
    for _id, key in result.missing_renders[:10]:
        logger.info("  missing render: %s", key)
    if args.requeue and result.missing_renders:
        async with async_session_factory() as session:
            await session.execute(
                update(AudioRender)
                .where(AudioRender.id.in_([i for i, _k in result.missing_renders]))
                .values(status=RenderStatus.PENDING, attempts=0, error=None,
                        next_attempt_at=None, storage_key=None)
            )
            await session.commit()
        logger.info("%d render(s) put back to pending", len(result.missing_renders))
    if result.missing_clips or (result.missing_renders and not args.requeue):
        raise SystemExit(1)


async def cmd_doctor(args: argparse.Namespace) -> None:
    from scripts import seed_tts_doctor

    code = await seed_tts_doctor.run(args)
    if code:
        raise SystemExit(code)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.seed_tts",
        description=(
            "Offline bulk audio for vocabulary: word clips from the recordings "
            "and Kokoro TTS for everything else. Meant to be run by hand on a "
            "GPU machine; see the module docstring."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def concurrency(p: argparse.ArgumentParser, default: int) -> None:
        p.add_argument(
            "--concurrency", type=int, default=default, choices=range(1, tts.MAX_CONCURRENCY + 1),
            metavar=f"1-{tts.MAX_CONCURRENCY}", help=f"work in flight at once (default {default})",
        )

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--limit", type=int, help="stop after N (a pilot)")
        p.add_argument("--device", help="torch/whisper device (cuda, cpu)")

    p = sub.add_parser("doctor", help="preflight: PASS/FAIL list for this machine")
    p.add_argument("--device", help="torch/whisper device (default cuda)")
    p.add_argument("--model", default="large-v3", help="faster-whisper model (default large-v3)")
    p = sub.add_parser("clips", help="index and cut word clips")
    common(p)
    concurrency(p, DEFAULT_CUT_CONCURRENCY)
    p = sub.add_parser("verify-clips", help="verify cut clips with faster-whisper")
    common(p)
    concurrency(p, DEFAULT_CONCURRENCY)
    p.add_argument("--model", default="large-v3", help="faster-whisper model (default large-v3)")
    p.add_argument("--all-candidates", action="store_true",
                   help="verify every cut clip, not only until a form's first verified one")
    p = sub.add_parser("check-files", help="rows whose file is missing from the storage")
    p.add_argument("--what", choices=["clips", "renders", "all"], default="all")
    p.add_argument("--requeue", action="store_true",
                   help="put `ready` renders with no file back to pending")
    for name, helptext in (
        ("words", "TTS for every word (clip or not)"),
        ("definitions", "TTS for every masked definition"),
        ("items", "On the go files for words in rotation"),
    ):
        p = sub.add_parser(name, help=helptext)
        common(p)
        concurrency(p, DEFAULT_CONCURRENCY)
        p.add_argument("--saved-only", action="store_true",
                       help="only senses somebody has saved (dev)")
        p.add_argument("--retry-failed", action="store_true",
                       help="put failed renders back to pending first")
        p.add_argument("--accent", choices=[*ACCENTS, "both"], default="both",
                       help="which voice(s) to make (default both)")
        if name == "words":
            p.add_argument("--skip-clipped", action="store_true",
                           help="leave out words that have a verified clip (the pre-accent rule)")
    return parser.parse_args(argv)


async def _amain(handler: Callable[[argparse.Namespace], Awaitable[None]], args: argparse.Namespace) -> None:
    try:
        await handler(args)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    _prepare_windows()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    args = _parse_args(argv)
    handler = {
        "doctor": cmd_doctor,
        "clips": cmd_clips,
        "verify-clips": cmd_verify,
        "words": cmd_words,
        "definitions": cmd_definitions,
        "items": cmd_items,
        "check-files": cmd_check_files,
    }[args.command]
    try:
        _run(_amain(handler, args))
    except KeyboardInterrupt:
        raise SystemExit("interrupted; claimed renders were released, re-run to resume") from None


if __name__ == "__main__":
    main()

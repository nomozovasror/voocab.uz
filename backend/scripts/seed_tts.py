"""Offline bulk audio for vocabulary: Kokoro TTS for every word and definition
(stage 3 of the vocabulary brief).

NOT part of the API or the worker -- a standalone script the owner runs by
hand on a machine with a GPU (the RTX 3060, Windows), the same contract as
``seed_audio.py``: it reads and writes through the configured database and
``MediaStorage`` (R2 in production, local disk in dev -- whatever
``app.core.config.settings`` points at on the machine this runs on), and it
writes the EXACT rows and keys the production worker would
(:mod:`app.services.tts`), so the worker, which generates only what is new or changed, finds the seed's output already there.

The step-by-step Windows run (tunnel to the dev database, local media folder,
copying files across) is ``scripts/SEED_TTS_WINDOWS.md``. Start with
``doctor``.

Prerequisite (GPU machine only). One environment holds one torch build, so
the GPU machine installs the ``tts-gpu`` extra (CUDA torch from the cu128
index) -- NOT ``tts``, which is the CPU build the worker image uses::

    uv sync --extra tts-gpu

For a different CUDA than 12.8, replace torch in that environment after the
sync with the matching wheel index, one line::

    uv pip install --reinstall torch --index-url https://download.pytorch.org/whl/cu126

(Kokoro and misaki's espeak loader do not run on macOS at all -- the
``espeakng-loader`` wheel kills the interpreter -- so on the Mac this script's
``words``/``definitions`` refuse to start. Docker/Linux is where
Kokoro runs on the dev machine.)

Usage (from the ``backend/`` directory), in this order::

    uv run python -m scripts.seed_tts doctor                 # preflight: PASS/FAIL list
    uv run python -m scripts.seed_tts words                  # TTS for every word, both accents
    uv run python -m scripts.seed_tts definitions            # TTS for every definition, both accents
    uv run python -m scripts.seed_tts check-files            # which rows point at a missing file

* ``doctor`` -- see :mod:`scripts.seed_tts_doctor`. Exit status 1 on any FAIL.
* ``words`` -- the word read by Kokoro, for EVERY lexicon sense. (Live clips
  from the recordings were dropped on 2026-10-07: every word a learner hears is
  TTS.) Heteronym senses are given their decided pronunciation in the voice's
  own alphabet (``lexeme_senses.pronunciation`` for British,
  ``pronunciation_us`` for American; see ``scripts/decide_heteronyms.py``).
* ``definitions`` -- the masked definition of every sense, the masks silences.
  On the go plays exactly these two renders (the word, the definition) one
  after the other, so there is nothing else to make for it.
* ``check-files`` -- every ``ready`` render whose file is not in the
  configured storage. ``--requeue`` puts such renders back to ``pending``. The check to run on
  the machine that serves the files, after they were copied there.

The two voices (decisions 22-26) -- British ``bf_emma`` and American
``af_heart``, one table in :mod:`app.services.accents`. ``--accent
british|american|both`` (default ``both``) on ``words`` and ``definitions``
chooses which are made; each voice is its own set of renders (the
voice is in every key), so running one accent now and the other later is safe
and nothing is made twice. The synthesiser holds one pipeline per voice sharing
one model, so ``both`` costs one model load.

Flags: ``--limit N`` stops after N items (a pilot); ``--saved-only`` restricts
``words``/``definitions`` to senses somebody has saved (the dev run: a few
hundred renders instead of seventeen thousand); ``--device`` is the torch
device for Kokoro -- default ``cuda``, and the run
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
not cp1252) and runs on the selector event loop (no noisy Proactor shutdown
errors with asyncpg) (:func:`_prepare_windows`).

NOTE: the real GPU run is for the project owner to verify -- the development
sandbox has no GPU. The logic is covered by ``tests/test_seed_tts.py`` and
``tests/test_audio_layer.py`` with a fake synthesiser; what is proven only by
running it is Kokoro itself, which is what ``doctor`` is for.
"""

import argparse
import asyncio
import logging
import sys
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy import select as sa_select
from sqlalchemy import update
from sqlmodel import select

from app.core.config import settings
from app.core.database import AsyncSession, async_session_factory, engine
from app.models.audio_render import AudioRender, RenderKind, RenderStatus
from app.models.lexicon import Lexeme, LexemeSense
from app.models.vocabulary import SavedWord
from app.services import tts, word_audio
from app.services.accents import ACCENTS, Accent
from app.services.storage import MediaStorage, get_storage

logger = logging.getLogger("scripts.seed_tts")

#: Specs are enqueued this many at a time.
ENQUEUE_BATCH = 500
#: Seconds between progress lines.
PROGRESS_EVERY_S = 20.0
DEFAULT_CONCURRENCY = 8


# --- Windows ---------------------------------------------------------------------


def _prepare_windows() -> None:
    """Things only Windows needs, done before anything heavy is imported.

    * The console: Windows consoles default to cp1252 and misaki phonemes
      (``ɹˈɛkɔːd``) are not in it -- one such log line raises
      ``UnicodeEncodeError`` out of ``logging``. Both streams are switched to
      UTF-8 with ``errors='replace'`` (any platform: a pipe is no better)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


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
    session: AsyncSession, *, saved_only: bool, limit: int | None, accents_: list[Accent]
) -> list[tts.RenderSpec]:
    """The word render of each sense, in each accent's voice."""
    senses = await _senses(session, saved_only=saved_only, limit=limit)
    lexemes = await _lexemes(session, senses)
    specs: dict[str, tts.RenderSpec] = {}
    for accent in accents_:
        for sense in senses:
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
) -> int:
    """Queue the word renders (:func:`word_specs`). Returns how many specs were
    offered (new ones are ``pending``, the rest already existed)."""
    return await _enqueue(
        await word_specs(session, saved_only=saved_only, limit=limit, accents_=accents_)
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


def selected_accents(args: argparse.Namespace) -> list[Accent]:
    """``--accent`` as a list: ``both`` (the default) is every accent we have."""
    return list(ACCENTS) if args.accent == "both" else [args.accent]


def _require_kokoro() -> None:
    if not tts.kokoro_available():
        raise SystemExit(
            "Kokoro is not installed. On the GPU machine: "
            "`uv sync --extra tts-gpu`. (It cannot run on macOS.)"
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


async def cmd_words(args: argparse.Namespace) -> None:
    _require_kokoro()
    device = resolve_device(args.device)
    if args.retry_failed:
        async with async_session_factory() as session:
            await tts.requeue_failed(session, kinds=[RenderKind.WORD])
    async with async_session_factory() as session:
        await enqueue_words(
            session, saved_only=args.saved_only, limit=args.limit,
            accents_=selected_accents(args),
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


# --- check-files -----------------------------------------------------------------


@dataclass
class FileCheck:
    """Rows whose file is not in storage."""

    checked: int = 0
    missing_renders: list[tuple[uuid.UUID, str]] = field(default_factory=list)


async def check_files(storage: MediaStorage, *, concurrency: int = 32) -> FileCheck:
    """Every ``ready`` render file that ``storage`` does not have. The seed writes files where it runs and the
    database says ``ready`` the moment a file is written -- if the files are
    then copied to the machine that SERVES them, this is how to know they all
    arrived (a missing file is served as no audio, never an error)."""
    out = FileCheck()
    gate = asyncio.Semaphore(concurrency)
    async with async_session_factory() as session:
        render_rows = list(
            (
                await session.exec(
                    select(AudioRender.id, AudioRender.storage_key).where(
                        AudioRender.status == RenderStatus.READY,
                        AudioRender.storage_key.is_not(None),
                    )
                )
            ).all()
        )

    async def has(key: str) -> bool:
        async with gate:
            return await storage.exists(key)

    found = await asyncio.gather(*(has(key) for _id, key in render_rows))
    out.missing_renders = [(i, k) for (i, k), ok in zip(render_rows, found) if not ok]
    out.checked = len(render_rows)
    return out


async def cmd_check_files(args: argparse.Namespace) -> None:
    result = await check_files(get_storage())
    logger.info(
        "%d file(s) checked: %d render file(s) missing",
        result.checked, len(result.missing_renders),
    )
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
    if result.missing_renders and not args.requeue:
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
            "Offline bulk audio for vocabulary: Kokoro TTS for every word "
            "and definition. Meant to be run by hand on a "
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
        p.add_argument("--device", help="torch device (cuda, cpu)")

    p = sub.add_parser("doctor", help="preflight: PASS/FAIL list for this machine")
    p.add_argument("--device", help="torch device (default cuda)")
    p = sub.add_parser("check-files", help="rows whose file is missing from the storage")
    p.add_argument("--requeue", action="store_true",
                   help="put `ready` renders with no file back to pending")
    for name, helptext in (
        ("words", "TTS for every word"),
        ("definitions", "TTS for every masked definition"),
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
        "words": cmd_words,
        "definitions": cmd_definitions,
        "check-files": cmd_check_files,
    }[args.command]
    try:
        _run(_amain(handler, args))
    except KeyboardInterrupt:
        raise SystemExit("interrupted; claimed renders were released, re-run to resume") from None


if __name__ == "__main__":
    main()

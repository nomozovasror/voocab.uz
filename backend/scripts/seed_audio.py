"""Offline bulk audio ingestion (§11 of the audio-ingestion brief).

NOT part of the API or the worker — a standalone script the owner runs by
hand on a machine with a GPU (an RTX 3060) to bulk-ingest his own audio with
``faster-whisper`` (free, fast, accurate, no Groq quota spent). It writes the
EXACT same rows the production Groq path would (via the shared
``persist_transcript_result``), so a later user upload of one of these files
dedups straight to ``ready`` instead of re-transcribing.

Prerequisite (GPU machine only — never installed in the API/worker image):

    uv sync --extra seed

Usage (from the ``backend/`` directory):

    uv run python -m scripts.seed_audio --dir /path/to/audio --owner <user-uuid>

Each file in ``--dir`` is: hashed (SHA-256) -> deduped against existing
``AudioBlob`` rows (already-transcribed files are skipped, not re-stored or
re-transcribed) -> if new, stored via the configured ``AudioStorage`` backend
(R2 in prod, local disk in dev — whatever ``app.core.config.settings`` points
at on the machine this runs on) -> transcribed with faster-whisper
(``large-v3``, GPU, word-level timestamps, ``language="en"`` locked — no
auto-detect, per §3.5) -> persisted -> an ``AudioAsset`` is claimed for
``--owner``.

NOTE: the real GPU run (installing ``faster-whisper`` and pointing this at a
folder of audio on an RTX 3060) is for the project owner to verify locally —
this sandbox has no GPU and cannot install/run faster-whisper. The ingest
logic itself (dedup/store/persist/asset) is covered by
``tests/test_seed_audio.py`` using a fake transcriber, so everything except
the actual faster-whisper call is proven here.
"""

import argparse
import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.core.database import async_session_factory
from app.models.user import User
from app.services import audio as audio_service
from app.services.asr import TranscriptResult, TranscriptSegment, WordTiming
from app.services.storage import AUDIO_CONTENT_TYPES, audio_storage_key, get_storage

logger = logging.getLogger("scripts.seed_audio")

# A file -> its normalized TranscriptResult. Defaults to the real
# faster-whisper call; tests inject a fake so the ingest/dedup/persist logic
# is verifiable without a GPU or the faster-whisper package installed.
Transcriber = Callable[[Path], Awaitable[TranscriptResult]]


async def transcribe_file(path: Path) -> TranscriptResult:
    """Real transcription via faster-whisper (``large-v3``, GPU).

    Lazily imports ``faster_whisper`` so this module — and everything else in
    this script — imports fine even where the ``seed`` optional dependency
    group isn't installed (i.e. everywhere except the GPU machine this is
    meant to run on: never the API/worker container).
    """
    from faster_whisper import WhisperModel  # lazy: optional, GPU-only dependency

    def _run() -> TranscriptResult:
        # float16 on GPU, per faster-whisper's own recommended basic usage.
        model = WhisperModel("large-v3", device="cuda", compute_type="float16")
        segments_iter, info = model.transcribe(
            str(path),
            language="en",  # §3.5: locked, never auto-detect
            word_timestamps=True,  # §3.6: word-level timing is mandatory
        )

        segments: list[TranscriptSegment] = []
        for order_index, seg in enumerate(segments_iter):
            words = [
                WordTiming(
                    word=w.word.strip(),
                    start_ms=round(w.start * 1000),
                    end_ms=round(w.end * 1000),
                )
                for w in (seg.words or [])
            ]
            segments.append(
                TranscriptSegment(
                    order_index=order_index,
                    start_ms=round(seg.start * 1000),
                    end_ms=round(seg.end * 1000),
                    text=seg.text.strip(),
                    words=words,
                )
            )

        duration_ms = round((info.duration or 0.0) * 1000)
        return TranscriptResult(duration_ms=duration_ms, segments=segments)

    # model.transcribe() is synchronous/CPU-blocking (GPU work under the
    # hood, but the Python call itself blocks) — run it off the event loop.
    return await asyncio.to_thread(_run)


def _mime_type_for(path: Path) -> str | None:
    return AUDIO_CONTENT_TYPES.get(path.suffix.lower())


async def ingest_file(
    path: Path,
    owner_id: uuid.UUID,
    *,
    transcribe: Transcriber = transcribe_file,
    title: str | None = None,
) -> None:
    """Ingest one audio file: dedup -> store (if new) -> transcribe (if new)
    -> persist -> claim an asset for ``owner_id``.

    Safe to re-run: a dedup hit skips storage + transcription entirely and
    only (idempotently) ensures the owner has an asset over the existing
    blob.
    """
    mime_type = _mime_type_for(path)
    if mime_type is None:
        logger.warning("%s: skipping, unsupported extension", path.name)
        return

    data = path.read_bytes()
    if not data:
        logger.warning("%s: skipping, empty file", path.name)
        return

    sha256 = audio_service.sha256_hex(data)
    key = audio_storage_key(sha256, mime_type)

    async with async_session_factory() as session:
        blob, created = await audio_service.get_or_create_blob(
            session,
            sha256=sha256,
            storage_key=key,
            size_bytes=len(data),
            mime_type=mime_type,
        )
        if not created:
            logger.info(
                "%s: dedup, skipping (blob %s already %s)",
                path.name,
                blob.id,
                blob.transcript_status,
            )
        else:
            await get_storage().put(key, data, mime_type)
            logger.info("%s: new blob %s, transcribing...", path.name, blob.id)
            result = await transcribe(path)
            # Same function the production worker uses -- identical rows
            # regardless of which ASR (Groq vs. faster-whisper) produced them.
            await audio_service.persist_transcript_result(session, blob, result)
            logger.info(
                "%s: ready (%d segment(s), %dms)",
                path.name,
                len(result.segments),
                result.duration_ms,
            )

        asset = await audio_service.get_or_create_asset(
            session, owner_id, blob.id, title=title
        )
        await session.commit()
        logger.info("%s: asset %s (owner %s)", path.name, asset.id, owner_id)


async def run(
    directory: Path,
    owner_id: uuid.UUID,
    *,
    transcribe: Transcriber = transcribe_file,
    title_from_filename: bool = True,
) -> None:
    async with async_session_factory() as session:
        owner = await session.get(User, owner_id)
    if owner is None:
        raise SystemExit(f"no such user: {owner_id}")

    files = sorted(
        p
        for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in AUDIO_CONTENT_TYPES
    )
    if not files:
        logger.warning("no audio files found in %s", directory)
        return

    logger.info("ingesting %d file(s) from %s for owner %s", len(files), directory, owner_id)
    for path in files:
        await ingest_file(
            path,
            owner_id,
            transcribe=transcribe,
            title=path.stem if title_from_filename else None,
        )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.seed_audio",
        description=(
            "Offline bulk audio ingestion with faster-whisper (GPU). Requires "
            "the 'seed' optional dependency group: `uv sync --extra seed`. "
            "Meant to be run by hand on a machine with a GPU (e.g. an "
            "RTX 3060) -- not part of the API or the worker."
        ),
    )
    parser.add_argument(
        "--dir", required=True, type=Path, help="Folder of audio files to ingest"
    )
    parser.add_argument(
        "--owner",
        required=True,
        type=uuid.UUID,
        help="Owner user id (must already exist in the users table)",
    )
    parser.add_argument(
        "--no-title-from-filename",
        action="store_false",
        dest="title_from_filename",
        help="Don't set AudioAsset.title from each file's filename stem",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    args = _parse_args(argv)
    if not args.dir.is_dir():
        raise SystemExit(f"not a directory: {args.dir}")
    asyncio.run(
        run(
            args.dir,
            args.owner,
            title_from_filename=args.title_from_filename,
        )
    )


if __name__ == "__main__":
    main()

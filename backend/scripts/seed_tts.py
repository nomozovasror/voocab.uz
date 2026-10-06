"""Offline bulk audio for vocabulary: clips from the recordings, then TTS for
the rest (stage 3 of the vocabulary brief, decisions 3 and 7).

NOT part of the API or the worker -- a standalone script the owner runs by
hand on a machine with a GPU (the RTX 3060), the same contract as
``seed_audio.py``: it reads and writes through the configured database and
``MediaStorage`` (R2 in production, local disk in dev -- whatever
``app.core.config.settings`` points at on the machine this runs on), and it
writes the EXACT rows and keys the production worker would
(:mod:`app.services.tts`, :mod:`app.services.word_clips`), so the worker, which
generates only what is new or changed, finds the seed's output already there.

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

    uv run python -m scripts.seed_tts clips                  # index + cut candidates
    uv run python -m scripts.seed_tts verify-clips           # faster-whisper, GPU
    uv run python -m scripts.seed_tts words                  # TTS for every word, both accents
    uv run python -m scripts.seed_tts definitions            # TTS for every definition, both accents
    uv run python -m scripts.seed_tts items                  # optional: On the go files

* ``clips`` -- index where every lexicon form is spoken in the transcripts
  and cut the word and its context from the recordings
  (:func:`app.services.word_clips.index_clips` / ``cut_clips``). Idempotent.
* ``verify-clips`` -- transcribe each cut word with faster-whisper and keep it
  only if the word is heard. ``--model`` (default ``large-v3``; a smaller one,
  e.g. ``small.en``, is fine on a CPU dev machine), ``--device`` (default
  ``cuda``; ``cpu`` runs int8). Only ``verified`` clips are ever served.
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
device for Kokoro (default: cuda when torch sees one) and the whisper device.

Every subcommand is safe to re-run: renders are keyed by the hash of their
input, so existing ones are never made twice, and a render that failed is
retried by ``--retry-failed``.

NOTE: the real GPU run is for the project owner to verify locally -- this
sandbox has no GPU. The logic is covered by ``tests/test_seed_tts.py`` and
``tests/test_audio_layer.py`` with fake synthesiser and transcriber; what is
proven only by running it is Kokoro/faster-whisper themselves (Kokoro was
smoke-tested on CPU in the worker image).
"""

import argparse
import asyncio
import io
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select as sa_select
from sqlmodel import select

from app.core.database import AsyncSession, async_session_factory
from app.models.audio_render import RenderKind
from app.models.lexicon import Lexeme, LexemeSense
from app.models.vocabulary import SavedWord
from app.services import tts, word_audio, word_clips
from app.services.accents import ACCENTS, Accent
from app.services.storage import MediaStorage

logger = logging.getLogger("scripts.seed_tts")

#: Specs are enqueued this many at a time.
ENQUEUE_BATCH = 500


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


async def enqueue_words(
    session: AsyncSession,
    *,
    saved_only: bool,
    limit: int | None,
    accents_: list[Accent],
    skip_clipped: bool = False,
) -> int:
    """Queue the word render of each sense, in each accent's voice -- clip or no
    clip (decision 26). ``skip_clipped`` restores the old rule: a word that
    has a verified clip, and is not a heteronym, is left out. Returns how many
    specs were offered (new ones are ``pending``, the rest already existed)."""
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
    return await _enqueue(list(specs.values()))


async def enqueue_definitions(
    session: AsyncSession, *, saved_only: bool, limit: int | None, accents_: list[Accent]
) -> int:
    senses = await _senses(session, saved_only=saved_only, limit=limit)
    lexemes = await _lexemes(session, senses)
    specs: dict[str, tts.RenderSpec] = {}
    for accent in accents_:
        for sense in senses:
            spec = tts.definition_spec(sense.definition_en, lexemes[sense.lexeme_id].lemma, accent)
            if spec is not None:
                specs[spec.key] = spec
    return await _enqueue(list(specs.values()))


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


@dataclass
class Progress:
    """Logs every ``every`` finished renders."""

    every: int = 100

    def __call__(self, done: int) -> None:
        if done % self.every == 0:
            logger.info("%d render(s) done", done)


async def run_renders(
    kinds: list[str], synth: tts.Synth, *, limit: int | None, storage: MediaStorage | None = None
) -> int:
    """Drain the render queue for ``kinds`` in-process -- the 3060 has no
    worker. Same claim and process as the worker's loop."""
    done = await tts.drain(
        synth, kinds=kinds, limit=limit, storage=storage, on_progress=Progress()
    )
    logger.info("%s: %d render(s) handled", "/".join(kinds), done)
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


async def cmd_clips(args: argparse.Namespace) -> None:
    async with async_session_factory() as session:
        report = await word_clips.index_clips(session)
        logger.info(
            "indexed %d recording(s): %d candidate(s) seen, %d new",
            report.blobs, report.candidates_seen, report.inserted,
        )
    # Cut in slabs so a long run reports progress and a crash loses little.
    total = 0
    while args.limit is None or total < args.limit:
        remaining = None if args.limit is None else args.limit - total
        async with async_session_factory() as session:
            cut = await word_clips.cut_clips(
                session, limit=min(200, remaining) if remaining is not None else 200
            )
        total += cut.cut + cut.failed
        logger.info("cut %d (failed %d); %d handled", cut.cut, cut.failed, total)
        if cut.cut + cut.failed == 0:
            break


async def cmd_verify(args: argparse.Namespace) -> None:
    transcribe = make_transcriber(args.model, args.device or "cuda")
    async with async_session_factory() as session:
        report = await word_clips.verify_clips(
            session, transcribe, limit_forms=args.limit, stop_at_first=not args.all_candidates
        )
    logger.info(
        "verified %d, rejected %d, over %d form(s)",
        report.verified, report.rejected, report.forms_done,
    )


async def cmd_words(args: argparse.Namespace) -> None:
    _require_kokoro()
    if args.retry_failed:
        async with async_session_factory() as session:
            await tts.requeue_failed(session, kinds=[RenderKind.WORD])
    async with async_session_factory() as session:
        await enqueue_words(
            session, saved_only=args.saved_only, limit=args.limit,
            accents_=selected_accents(args), skip_clipped=args.skip_clipped,
        )
    await run_renders([RenderKind.WORD], tts.KokoroSynth(device=args.device), limit=None)


async def cmd_definitions(args: argparse.Namespace) -> None:
    _require_kokoro()
    if args.retry_failed:
        async with async_session_factory() as session:
            await tts.requeue_failed(session, kinds=[RenderKind.DEFINITION])
    async with async_session_factory() as session:
        await enqueue_definitions(
            session, saved_only=args.saved_only, limit=args.limit,
            accents_=selected_accents(args),
        )
    await run_renders([RenderKind.DEFINITION], tts.KokoroSynth(device=args.device), limit=None)


async def cmd_items(args: argparse.Namespace) -> None:
    _require_kokoro()
    async with async_session_factory() as session:
        count = await enqueue_items(
            session, limit=args.limit, accents_=selected_accents(args)
        )
    logger.info("%d word(s) in rotation queued", count)
    await run_renders(
        [RenderKind.WORD, RenderKind.DEFINITION, RenderKind.ITEM],
        tts.KokoroSynth(device=args.device),
        limit=None,
    )


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

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--limit", type=int, help="stop after N (a pilot)")
        p.add_argument("--device", help="torch/whisper device (cuda, cpu)")

    p = sub.add_parser("clips", help="index and cut word clips")
    common(p)
    p = sub.add_parser("verify-clips", help="verify cut clips with faster-whisper")
    common(p)
    p.add_argument("--model", default="large-v3", help="faster-whisper model (default large-v3)")
    p.add_argument("--all-candidates", action="store_true",
                   help="verify every cut clip, not only until a form's first verified one")
    for name, helptext in (
        ("words", "TTS for every word (clip or not)"),
        ("definitions", "TTS for every masked definition"),
        ("items", "On the go files for words in rotation"),
    ):
        p = sub.add_parser(name, help=helptext)
        common(p)
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


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    args = _parse_args(argv)
    handler = {
        "clips": cmd_clips,
        "verify-clips": cmd_verify,
        "words": cmd_words,
        "definitions": cmd_definitions,
        "items": cmd_items,
    }[args.command]
    asyncio.run(handler(args))


if __name__ == "__main__":
    main()

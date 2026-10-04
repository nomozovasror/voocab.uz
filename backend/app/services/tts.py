"""Text to speech, and the queue that makes it: words, definitions, and the
single On the go file per word.

Everything the learner hears that is NOT cut from a recording is made here, by
one voice -- Kokoro-82M, British English, ``bf_emma`` -- and always OUTSIDE a
request. A request that needs audio that does not exist only writes a row into
``audio_renders`` (:func:`enqueue`); the worker (``app.worker``) or the seed
script (``scripts/seed_tts.py``) claims it, synthesises, stores, marks it
``ready``. The two run the same functions, so the same input gives the same
key and the same file wherever it was made ("same model, same voice, in both
places: a mismatch would be heard at once", brief §2).

## What a render is, and what its key is

``audio_renders.key`` is the SHA-256 of the INPUT (:func:`render_key`): for a
word, the exact synthesis string + voice + model; for a definition, the masked
text + voice + model; for an item, the parts it is composed of. Content
addressing the input rather than the output is what lets a row exist, and be
looked up, before the audio does. Consequences worth stating:

* One word is synthesised once in the whole system, whoever asks.
* A changed definition (the lexicon corrects one) is a NEW key, hence a new
  render; the old file is simply no longer referenced.
* The synthesis string for a heteronym sense is ``[word](/phonemes/)``, so a
  heteronym's two senses are two keys, and a word that gains a decided
  pronunciation later gets a fresh render instead of keeping the guessed one.

## Definitions: the masks are silences

On the go plays a sense's definition, and recall's definition has the headword
blanked (``_____``, :data:`app.services.practice.MASK_TOKEN`) so it does not
give itself away. Audio would have to say something where the blank is, and
anything it said would be the answer or noise -- so the mask becomes a short
silence (decision 11, :data:`MASK_PAUSE_MS`). The text is the MASKED text
exactly as recall shows it (:func:`masked_definition` reuses
``practice._mask_definition``, one definition of masking for both); it is cut
at the masks, each piece is synthesised on its own, and the pieces are joined
with silence. Several masks in a row (a masked phrase is one blank per word)
are ONE silence: the learner hears one gap where one phrase was.

## An item is composed, not synthesised

definition + :data:`ITEM_PAUSE_MS` of silence + word + :data:`ITEM_TAIL_MS`,
in ONE file (decision 13: a locked phone cannot be trusted to chain files).
The word part is whatever :func:`app.services.word_audio` would serve for the
word -- a verified clip if there is one, TTS otherwise. Every part is levelled
to the same RMS before it is laid down (a lecture clip and Kokoro differ by
many dB), and the file records ``word_offset_ms``, where the word starts, which
the client uses as "the word was heard".

An item's ``input`` names its parts rather than holding audio, and the worker
resolves them itself -- a part whose own render is not ready yet is synthesised
inline and its row marked ready -- so an item never waits on, or fails because
of, the order the queue happened to be drained in.
"""

import asyncio
import hashlib
import importlib.util
import json
import logging
import re
import threading
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
from sqlalchemy import case, func, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select

from app.core.config import settings
from app.core.database import AsyncSession, async_session_factory
from app.models.audio_render import AudioRender, RenderKind, RenderStatus
from app.services import audio_pcm
from app.services.storage import MediaStorage, get_storage

logger = logging.getLogger(__name__)

VOICE = "bf_emma"
MODEL = "hexgrad/Kokoro-82M"
#: Kokoro's language code for British English.
LANG_CODE = "b"

#: Decision 12: definition, three seconds to recall, the word, then a beat.
ITEM_PAUSE_MS = 3000
ITEM_TAIL_MS = 1500
#: Decision 11: how long a masked word is silent.
MASK_PAUSE_MS = 400

#: Bump to re-render everything (a change to trimming, levelling or the
#: composition): it is part of every key.
KEY_VERSION = 1

AUDIO_MIME = "audio/mp4"

#: Silence at the edges of synthesised speech is trimmed to this much.
_EDGE_KEEP_MS = 60
_EDGE_THRESHOLD_DBFS = -45.0

#: text -> float32 mono samples at 24 kHz. Synchronous (it is the model); the
#: callers run it in a thread. Kokoro in production, a fake in tests.
Synth = Callable[[str], np.ndarray]

_MASK_RUN = re.compile(r"(?:\s*_{3,}\s*)+")


def kokoro_available() -> bool:
    """Whether the ``tts`` extra is installed here. False in the API image and
    on a Mac host -- where importing kokoro must never be attempted (its
    ``espeakng-loader`` wheel kills the interpreter), which is why this checks
    for the module without importing it."""
    return importlib.util.find_spec("kokoro") is not None


class KokoroSynth:
    """The production :data:`Synth`: ``KPipeline(lang_code='b')``, voice
    ``bf_emma``, loaded on first use and then kept (it is ~350 MB; the worker
    must not pay that per word). ``device`` is ``None`` for torch's own choice
    (CPU in the worker image), ``"cuda"`` on the seed machine."""

    def __init__(self, device: str | None = None) -> None:
        self._device = device
        self._pipeline: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        if self._pipeline is None:
            from kokoro import KPipeline  # lazy: the `tts` extra only

            self._pipeline = KPipeline(
                lang_code=LANG_CODE, repo_id=MODEL, device=self._device
            )
        return self._pipeline

    def __call__(self, text: str) -> np.ndarray:
        # One pipeline, one caller at a time: it holds torch state.
        with self._lock:
            pipeline = self._load()
            chunks: list[np.ndarray] = []
            for result in pipeline(text, voice=VOICE, speed=1.0):
                audio = result.audio
                if audio is not None:
                    chunks.append(audio.detach().cpu().numpy().reshape(-1))
        if not chunks:
            raise RuntimeError(f"Kokoro produced no audio for {text!r}")
        return np.concatenate(chunks).astype(np.float32, copy=False)


# --- Inputs and keys ------------------------------------------------------------


@dataclass(frozen=True)
class RenderSpec:
    """Everything that identifies one render: enough to enqueue it, and (for a
    word or definition) to make it."""

    kind: str
    input: str
    key: str
    voice: str = VOICE
    model: str = MODEL


def render_key(kind: str, input_text: str, voice: str = VOICE, model: str = MODEL) -> str:
    """The content address of a render's input. Canonical JSON (sorted keys,
    no spaces) so no formatting accident can change a key."""
    payload = json.dumps(
        {"v": KEY_VERSION, "kind": kind, "input": input_text, "voice": voice, "model": model},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def storage_key_for(kind: str, key: str) -> str:
    """``tts/{key}.m4a`` for words and definitions, ``renders/{key}.m4a`` for
    items. The key is the input's hash, so the object's name is stable before
    the object exists."""
    prefix = "renders" if kind == RenderKind.ITEM else "tts"
    return f"{prefix}/{key}.m4a"


def word_input(lemma: str, pronunciation: str | None) -> str:
    """What the voice is given for a word: the lemma as plain text, or -- for a
    heteronym sense -- ``[lemma](/phonemes/)``, misaki's own syntax for
    "say it like this" (brief §2)."""
    word = lemma.strip()
    return f"[{word}](/{pronunciation}/)" if pronunciation else word


def masked_definition(definition: str, lemma: str) -> str:
    """The definition as recall shows it: the headword (and its family) blanked
    with ``_____``. ``practice._mask_definition`` is the one implementation of
    masking; it is imported where it is used rather than at the top because
    ``practice`` will itself import the audio service, and a module-level
    import here would close the cycle."""
    from app.services.practice import _mask_definition

    masked, _count, _remaining = _mask_definition(definition or "", lemma, lemma)
    return masked.strip()


def word_spec(lemma: str, pronunciation: str | None) -> RenderSpec:
    text = word_input(lemma, pronunciation)
    return RenderSpec(RenderKind.WORD, text, render_key(RenderKind.WORD, text))


def definition_spec(definition: str, lemma: str) -> RenderSpec | None:
    """The render for a sense's masked definition, or ``None`` when there is
    no definition to speak."""
    text = masked_definition(definition, lemma)
    if not re.search(r"[A-Za-z0-9]", _MASK_RUN.sub(" ", text)):
        return None
    return RenderSpec(RenderKind.DEFINITION, text, render_key(RenderKind.DEFINITION, text))


def item_spec(
    definition: RenderSpec, *, word_spec_: RenderSpec | None, clip_storage_key: str | None
) -> RenderSpec:
    """The render for one On the go file. Exactly one of ``word_spec_`` (the
    word is TTS) and ``clip_storage_key`` (the word is a verified clip) is
    given. The input names the parts; see the module docstring."""
    if (word_spec_ is None) == (clip_storage_key is None):
        raise ValueError("an item's word is either TTS or a clip")
    word_part: dict[str, str]
    if clip_storage_key is not None:
        word_part = {"source": "clip", "storage_key": clip_storage_key}
    else:
        assert word_spec_ is not None
        word_part = {"source": "tts", "input": word_spec_.input}
    text = json.dumps(
        {
            "definition": {"input": definition.input},
            "word": word_part,
            "pause_ms": ITEM_PAUSE_MS,
            "tail_ms": ITEM_TAIL_MS,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return RenderSpec(RenderKind.ITEM, text, render_key(RenderKind.ITEM, text))


# --- Synthesis ------------------------------------------------------------------


def trim_edges(samples: np.ndarray) -> np.ndarray:
    """``samples`` without the near-silence at either end, but with
    :data:`_EDGE_KEEP_MS` of it kept. A synthesised word comes with a few
    hundred ms of lead-in and tail; left in, every "word" would start late
    and the pause after a definition would be a different length every time."""
    if len(samples) == 0:
        return samples
    threshold = 10.0 ** (_EDGE_THRESHOLD_DBFS / 20.0)
    loud = np.flatnonzero(np.abs(samples) > threshold)
    if len(loud) == 0:
        return samples
    keep = round(_EDGE_KEEP_MS * audio_pcm.SAMPLE_RATE / 1000)
    return samples[max(0, loud[0] - keep) : min(len(samples), loud[-1] + 1 + keep)]


def split_masked(masked: str) -> list[str | None]:
    """A masked definition as ``[text, None, text ...]``: ``None`` is one
    silence where one run of masks was. Pieces with no letter or digit
    (a stray comma left between two masks) are dropped."""
    pieces: list[str | None] = []
    cursor = 0
    for match in _MASK_RUN.finditer(masked):
        pieces.append(masked[cursor : match.start()])
        pieces.append(None)
        cursor = match.end()
    pieces.append(masked[cursor:])
    out: list[str | None] = []
    for piece in pieces:
        if piece is None:
            if not out or out[-1] is not None:
                out.append(None)
        elif re.search(r"[A-Za-z0-9]", piece):
            out.append(piece.strip())
    return out


def synthesise_word(synth: Synth, text: str) -> np.ndarray:
    return audio_pcm.normalise_rms(trim_edges(synth(text)))


def synthesise_definition(synth: Synth, masked: str) -> np.ndarray:
    """The masked definition spoken, each mask a silence of
    :data:`MASK_PAUSE_MS`."""
    parts: list[np.ndarray] = []
    for piece in split_masked(masked):
        if piece is None:
            parts.append(audio_pcm.silence(MASK_PAUSE_MS))
        else:
            parts.append(trim_edges(synth(piece)))
    return audio_pcm.normalise_rms(audio_pcm.concat(*parts))


def compose_item(
    definition: np.ndarray,
    word: np.ndarray,
    *,
    pause_ms: int = ITEM_PAUSE_MS,
    tail_ms: int = ITEM_TAIL_MS,
) -> tuple[np.ndarray, int]:
    """``(file samples, word_offset_ms)``: definition, ``pause_ms`` of silence,
    word, ``tail_ms`` of silence; both speech parts levelled to the same RMS.
    The offset is where the word's first sample is."""
    lead = audio_pcm.concat(audio_pcm.normalise_rms(definition), audio_pcm.silence(pause_ms))
    offset_ms = audio_pcm.duration_ms(lead)
    samples = audio_pcm.concat(lead, audio_pcm.normalise_rms(word), audio_pcm.silence(tail_ms))
    return samples, offset_ms


# --- The queue ------------------------------------------------------------------


async def enqueue(specs: Iterable[RenderSpec]) -> int:
    """Make sure each render has a row; ``pending`` if it is new.

    ``INSERT ... ON CONFLICT (key) DO NOTHING``: asking twice, from two
    requests at once, is the same as asking once, and a row that is already
    ``ready``, ``processing`` or ``failed`` is left exactly as it is (a
    ``failed`` render is retried by :func:`requeue_failed`, deliberately, not
    by every request that wants it).

    Runs on its OWN short transaction, committed at once. A GET handler never
    commits its session, and a request that later rolls back must not lose
    the work it already asked for; neither is the caller's transaction ours to
    commit. Returns how many rows were new."""
    rows = {
        spec.key: {
            "id": uuid.uuid4(),
            "key": spec.key,
            "kind": spec.kind,
            "input": spec.input,
            "voice": spec.voice,
            "model": spec.model,
            "status": RenderStatus.PENDING,
            "attempts": 0,
            "created_at": datetime.now(timezone.utc),
        }
        for spec in specs
    }
    if not rows:
        return 0
    async with async_session_factory() as session:
        result = await session.execute(
            pg_insert(AudioRender).values(list(rows.values())).on_conflict_do_nothing(
                index_elements=["key"]
            )
        )
        await session.commit()
        return result.rowcount or 0


async def requeue_failed(session: AsyncSession, *, kinds: Iterable[str] | None = None) -> int:
    """Put ``failed`` renders back to ``pending`` with their attempts reset --
    the operator's lever after fixing whatever made them fail."""
    stmt = (
        update(AudioRender)
        .where(AudioRender.status == RenderStatus.FAILED)
        .values(status=RenderStatus.PENDING, attempts=0, error=None)
    )
    if kinds is not None:
        stmt = stmt.where(AudioRender.kind.in_(list(kinds)))
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount or 0


async def recover_stale_renders(session: AsyncSession) -> int:
    """Startup recovery, like ``worker.recover_stale``: a render left
    ``processing`` by a crashed worker goes back to ``pending``."""
    result = await session.execute(
        update(AudioRender)
        .where(AudioRender.status == RenderStatus.PROCESSING)
        .values(status=RenderStatus.PENDING)
    )
    await session.commit()
    return result.rowcount or 0


async def claim_render(
    session: AsyncSession,
    *,
    kinds: Iterable[str] | None = None,
    keys: Iterable[str] | None = None,
) -> AudioRender | None:
    """Atomically claim one ``pending`` render, or ``None`` when the queue is
    empty (or every pending row is locked by another worker): ``FOR UPDATE
    SKIP LOCKED``, exactly :func:`app.worker.claim_one`'s shape.

    Words first, then definitions, then items, oldest first within a kind: a
    request is most often waiting on a word, and an item would only have to
    synthesise its parts inline if it were claimed ahead of them. ``kinds`` and
    ``keys`` narrow the claim to those kinds / exactly those renders (a seed
    run that must not touch whatever else is pending; tests)."""
    rank = case(
        (AudioRender.kind == RenderKind.WORD, 0),
        (AudioRender.kind == RenderKind.DEFINITION, 1),
        else_=2,
    )
    stmt = select(AudioRender).where(AudioRender.status == RenderStatus.PENDING)
    if kinds is not None:
        stmt = stmt.where(AudioRender.kind.in_(list(kinds)))
    if keys is not None:
        stmt = stmt.where(AudioRender.key.in_(list(keys)))
    row = (
        await session.exec(
            stmt.order_by(rank, AudioRender.created_at).limit(1).with_for_update(skip_locked=True)
        )
    ).first()
    if row is None:
        return None
    row.status = RenderStatus.PROCESSING
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def _store(
    storage: MediaStorage, kind: str, key: str, samples: np.ndarray
) -> tuple[str, int]:
    data = await asyncio.to_thread(audio_pcm.encode_m4a, samples)
    storage_key = storage_key_for(kind, key)
    await storage.put(storage_key, data, AUDIO_MIME)
    return storage_key, audio_pcm.duration_ms(samples)


async def _tts_part(
    session: AsyncSession,
    spec: RenderSpec,
    synth: Synth,
    storage: MediaStorage,
) -> np.ndarray:
    """The audio of a word/definition render, for use inside an item: read it
    if it is ready and in storage, otherwise make it now and record it."""
    row = (await session.exec(select(AudioRender).where(AudioRender.key == spec.key))).first()
    if row is not None and row.status == RenderStatus.READY and row.storage_key:
        try:
            return await asyncio.to_thread(audio_pcm.decode_range, await storage.get(row.storage_key))
        except Exception:  # noqa: BLE001 - the file is gone; fall through and remake it
            logger.warning("render %s is ready but unreadable; remaking", spec.key)
    samples = await asyncio.to_thread(_synthesise, spec, synth)
    storage_key, duration = await _store(storage, spec.kind, spec.key, samples)
    stmt = pg_insert(AudioRender).values(
        id=uuid.uuid4(),
        key=spec.key,
        kind=spec.kind,
        input=spec.input,
        voice=spec.voice,
        model=spec.model,
        status=RenderStatus.READY,
        attempts=0,
        storage_key=storage_key,
        duration_ms=duration,
        created_at=datetime.now(timezone.utc),
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["key"],
            set_={
                "status": RenderStatus.READY,
                "storage_key": storage_key,
                "duration_ms": duration,
                "error": None,
                "updated_at": func.now(),
            },
        )
    )
    await session.commit()
    return samples


def _synthesise(spec: RenderSpec, synth: Synth) -> np.ndarray:
    if spec.kind == RenderKind.WORD:
        return synthesise_word(synth, spec.input)
    if spec.kind == RenderKind.DEFINITION:
        return synthesise_definition(synth, spec.input)
    raise ValueError(f"{spec.kind} is not synthesised directly")


async def build_item(
    session: AsyncSession, row: AudioRender, synth: Synth, storage: MediaStorage
) -> tuple[np.ndarray, int]:
    """Resolve an item's parts (see the module docstring) and compose it."""
    spec = json.loads(row.input)
    definition = await _tts_part(
        session,
        RenderSpec(
            RenderKind.DEFINITION,
            spec["definition"]["input"],
            render_key(RenderKind.DEFINITION, spec["definition"]["input"], row.voice, row.model),
            row.voice,
            row.model,
        ),
        synth,
        storage,
    )
    word_part = spec["word"]
    if word_part["source"] == "clip":
        word = await asyncio.to_thread(
            audio_pcm.decode_range, await storage.get(word_part["storage_key"])
        )
    else:
        word = await _tts_part(
            session,
            RenderSpec(
                RenderKind.WORD,
                word_part["input"],
                render_key(RenderKind.WORD, word_part["input"], row.voice, row.model),
                row.voice,
                row.model,
            ),
            synth,
            storage,
        )
    return compose_item(
        definition, word, pause_ms=int(spec["pause_ms"]), tail_ms=int(spec["tail_ms"])
    )


async def process_render(
    session: AsyncSession,
    row: AudioRender,
    synth: Synth,
    storage: MediaStorage | None = None,
    *,
    max_attempts: int | None = None,
) -> None:
    """Make one claimed (``processing``) render and resolve its row. Never
    raises: a failure is recorded on the row (``pending`` again with
    ``attempts`` bumped, or ``failed`` once ``max_attempts`` is reached) --
    the same contract as ``worker.process_blob``, for the same reason: one
    bad input must not take down the loop that serves every other."""
    storage = storage or get_storage()
    limit = max_attempts if max_attempts is not None else settings.tts_max_attempts
    row_id, kind, key = row.id, row.kind, row.key
    try:
        offset: int | None = None
        if kind == RenderKind.ITEM:
            samples, offset = await build_item(session, row, synth, storage)
        else:
            samples = await asyncio.to_thread(
                _synthesise,
                RenderSpec(kind, row.input, key, row.voice, row.model),
                synth,
            )
        storage_key, duration = await _store(storage, kind, key, samples)
    except Exception as exc:  # noqa: BLE001 - recorded on the row, never propagated
        await session.rollback()
        message = f"{type(exc).__name__}: {exc}"
        logger.warning("render %s (%s) failed: %s", key[:12], kind, message)
        fresh = await session.get(AudioRender, row_id)
        if fresh is None:
            return
        fresh.attempts += 1
        fresh.error = message[:2000]
        fresh.status = (
            RenderStatus.FAILED if fresh.attempts >= limit else RenderStatus.PENDING
        )
        session.add(fresh)
        await session.commit()
        return

    fresh = await session.get(AudioRender, row_id)
    assert fresh is not None
    fresh.status = RenderStatus.READY
    fresh.storage_key = storage_key
    fresh.duration_ms = duration
    fresh.word_offset_ms = offset
    fresh.error = None
    session.add(fresh)
    await session.commit()


async def drain(
    synth: Synth,
    *,
    kinds: Iterable[str] | None = None,
    keys: Iterable[str] | None = None,
    limit: int | None = None,
    storage: MediaStorage | None = None,
    on_progress: Callable[[int], None] | None = None,
) -> int:
    """Claim and process renders until the queue is empty (or ``limit``). The
    seed script's engine -- the 3060 has no worker -- using exactly the
    worker's claim and process. Returns how many it handled (ready or not)."""
    storage = storage or get_storage()
    kinds = list(kinds) if kinds is not None else None
    keys = list(keys) if keys is not None else None
    done = 0
    while limit is None or done < limit:
        async with async_session_factory() as session:
            row = await claim_render(session, kinds=kinds, keys=keys)
        if row is None:
            break
        async with async_session_factory() as session:
            fresh = await session.get(AudioRender, row.id)
            assert fresh is not None
            await process_render(session, fresh, synth, storage)
        done += 1
        if on_progress is not None:
            on_progress(done)
    return done

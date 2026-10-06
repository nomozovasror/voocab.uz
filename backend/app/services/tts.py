"""Text to speech, and the queue that makes it: words, definitions, and the
single On the go file per word.

Everything the learner hears that is NOT cut from a recording is made here, by
Kokoro-82M in the voice of the learner's accent (:mod:`app.services.accents`:
British ``bf_emma``, American ``af_heart``) -- and always OUTSIDE a request. A request that needs audio that does not exist only writes a row into
``audio_renders`` (:func:`enqueue`); the worker (``app.worker``) or the seed
script (``scripts/seed_tts.py``) claims it, synthesises, stores, marks it
``ready``. The two run the same functions, so the same input gives the same
key and the same file wherever it was made ("same model, same voice, in both
places: a mismatch would be heard at once", brief §2).

## What a render is, and what its key is

``audio_renders.key`` is the SHA-256 of the INPUT (:func:`render_key`): for a
word, the exact synthesis string + voice + model; for a definition, the masked
text + voice + model; for an item, the parts it is composed of + voice + model.
The VOICE is in every key, so an American render never collides with, or
replaces, a British one -- the two accents are two sets of rows and files, and
an item (whose word may be a shared clip) still differs by accent because its
definition is spoken in the voice. Content
addressing the input rather than the output is what lets a row exist, and be
looked up, before the audio does. Consequences worth stating:

* One word is synthesised once per voice in the whole system, whoever asks.
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
import contextvars
import hashlib
import importlib.util
import json
import logging
import re
import threading
import uuid
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
from sqlalchemy import case, func, or_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select

from app.core.config import settings
from app.core.database import AsyncSession, async_session_factory
from app.models.audio_render import AudioRender, RenderKind, RenderStatus
from app.services import accents, audio_pcm
from app.services.infra_errors import InfrastructureError, guarded
from app.services.storage import MediaStorage, get_storage

logger = logging.getLogger(__name__)

#: The default accent's voice. Every spec function takes an ``accent`` (default
#: British) and gets its voice from :mod:`app.services.accents`; this name is
#: what a render row written before accents existed carries.
VOICE = accents.voice_for(accents.DEFAULT_ACCENT)
MODEL = "hexgrad/Kokoro-82M"

#: Decision 12: definition, three seconds to recall, the word, then a beat.
ITEM_PAUSE_MS = 3000
ITEM_TAIL_MS = 1500
#: Decision 11: how long a masked word is silent.
MASK_PAUSE_MS = 400

#: Bump to re-render everything (a change to trimming, levelling or the
#: composition): it is part of every key.
KEY_VERSION = 1

AUDIO_MIME = "audio/mp4"

#: Longest per-row wait between a render's own failed attempts.
TTS_RETRY_BACKOFF_MAX_S = 3600.0

#: Silence at the edges of synthesised speech is trimmed to this much.
_EDGE_KEEP_MS = 60
_EDGE_THRESHOLD_DBFS = -45.0

#: (text, voice) -> float32 mono samples at 24 kHz. Synchronous (it is the
#: model); the callers run it in a thread. Kokoro in production, a fake in
#: tests. The voice is the render row's own, so one synthesiser serves both
#: accents.
Synth = Callable[[str, str], np.ndarray]

#: The thread every synthesis runs on during a concurrent drain (see
#: :func:`drain`); ``None`` outside one, where ``asyncio.to_thread`` serves.
_synth_executor: contextvars.ContextVar[ThreadPoolExecutor | None] = contextvars.ContextVar(
    "tts_synth_executor", default=None
)

#: Most renders a drain works on at once. Each holds a database connection for
#: its whole life and the engine's pool is 5 + 10 overflow.
MAX_CONCURRENCY = 12


async def _in_synth_thread(fn: Callable[..., Any], *args: Any) -> Any:
    executor = _synth_executor.get()
    if executor is None:
        return await asyncio.to_thread(fn, *args)
    return await asyncio.get_running_loop().run_in_executor(executor, fn, *args)


_MASK_RUN = re.compile(r"(?:\s*_{3,}\s*)+")


def kokoro_available() -> bool:
    """Whether the ``tts`` extra is installed here. False in the API image and
    on a Mac host -- where importing kokoro must never be attempted (its
    ``espeakng-loader`` wheel kills the interpreter), which is why this checks
    for the module without importing it."""
    return importlib.util.find_spec("kokoro") is not None


#: What misaki is told to put where it cannot pronounce something, instead of
#: Kokoro's own ``unk=''``. An empty string is invisible -- the word is simply
#: not spoken and the file has a silent gap where it was (the one defect that
#: raises no error, brief §2) -- and, inside a hyphenated compound, one unknown
#: half is dropped from the merged token while the other half survives. A mark
#: that cannot be a phoneme survives the merge, so :func:`unknown_words` can see it.
UNKNOWN_MARK = "❓"


class UnknownPronunciation(ValueError):
    """The text has a word the voice cannot pronounce: misaki has no entry for
    it and its espeak fallback produced nothing (or is not available on this
    machine). The render FAILS with this reason rather than being spoken with
    a silent gap where the word should be. The render's own fault -- it spends
    an attempt -- unless every out-of-lexicon word fails on a machine whose
    fallback is missing, which ``seed_tts doctor`` reports up front."""


def unknown_words(tokens: Iterable[Any]) -> list[str]:
    """The words among misaki's ``tokens`` (anything with ``.text`` and
    ``.phonemes``) that would be spoken as nothing: a token with a letter or
    digit in it whose phonemes are missing, empty, or carry the
    :data:`UNKNOWN_MARK`. Punctuation has phonemes of its own or none and is
    not a word."""
    bad: list[str] = []
    for token in tokens:
        text = str(getattr(token, "text", "") or "")
        if not any(ch.isalnum() for ch in text):
            continue
        phonemes = getattr(token, "phonemes", None)
        if not phonemes or UNKNOWN_MARK in phonemes:
            bad.append(text)
    return bad


class KokoroSynth:
    """The production :data:`Synth`: one ``KPipeline`` per language code (a
    British and an American front end), voice picked per call, each built on
    first use and then kept. ``device`` is ``None`` for torch's own choice (CPU
    in the worker image), ``"cuda"`` on the seed machine.

    The pipelines SHARE ONE ``KModel`` (~330 MB of weights): the language code
    only selects the grapheme-to-phoneme front end (misaki's gb or us
    lexicon), the network is the same. The first pipeline loads the model and
    the next ones are handed it (``KPipeline(model=<KModel>)``), so serving
    both accents costs one model, not two. The voices themselves are small
    (~0.5 MB each) and load when first asked for.

    **A word with no pronunciation fails the render.** The G2P is run here, not
    inside ``KPipeline.__call__``, so its tokens can be read before any audio is
    made: a token with no phonemes (:func:`unknown_words`) raises
    :class:`UnknownPronunciation`. Kokoro builds its G2P with ``unk=''`` and
    swallows an espeak fallback that fails to load (a warning, then "OOD words
    will be skipped"), so left alone the word is just missing from the audio.

    Not safe to call from two threads at once (they share a model and torch
    state), so ``__call__`` holds a lock; the seed's drain goes further and runs
    every call on ONE dedicated thread (:func:`_in_synth_thread`), so nothing
    ever waits on that lock."""

    def __init__(
        self,
        device: str | None = None,
        *,
        pipeline_factory: Callable[[str, Any], Any] | None = None,
    ) -> None:
        self._device = device
        self._pipelines: dict[str, Any] = {}
        self._lock = threading.Lock()
        #: ``(lang_code, shared KModel or True) -> pipeline``; tests inject a fake.
        self._factory = pipeline_factory or self._build_pipeline

    def _build_pipeline(self, lang_code: str, model: Any) -> Any:
        from kokoro import KPipeline  # lazy: the `tts` extra only

        pipeline = KPipeline(
            lang_code=lang_code, repo_id=MODEL, model=model, device=self._device
        )
        # See UNKNOWN_MARK. Set after construction: Kokoro hard-codes ``unk=''``.
        if hasattr(pipeline, "g2p"):
            pipeline.g2p.unk = UNKNOWN_MARK
        return pipeline

    def _load(self, lang_code: str) -> Any:
        pipeline = self._pipelines.get(lang_code)
        if pipeline is None:
            try:
                shared = next(iter(self._pipelines.values()), None)
                pipeline = self._factory(
                    lang_code, shared.model if shared is not None else True
                )
            except Exception as exc:  # noqa: BLE001 - classified, not swallowed
                # The model not loading is the machine's fault, not the word's:
                # no render may spend an attempt on it (`process_render`).
                raise InfrastructureError(f"Kokoro failed to load: {exc}") from exc
            self._pipelines[lang_code] = pipeline
        return pipeline

    @staticmethod
    def _load_voice(pipeline: Any, voice: str) -> None:
        """The voice file (``voices/{voice}.pt``, fetched on first use) loaded
        up front: a missing or undownloadable file is the machine's fault, not
        the word's, and must not be read as the render's own failure when
        ``generate_from_tokens`` would otherwise load it lazily."""
        loader = getattr(pipeline, "load_voice", None)
        if loader is None:
            return
        try:
            loader(voice)
        except Exception as exc:  # noqa: BLE001 - classified, not swallowed
            raise InfrastructureError(f"Kokoro voice {voice!r} failed to load: {exc}") from exc

    def __call__(self, text: str, voice: str) -> np.ndarray:
        lang_code = accents.lang_code_for_voice(voice)
        # One caller at a time: the pipelines share a model and hold torch state.
        with self._lock:
            pipeline = self._load(lang_code)
            self._load_voice(pipeline, voice)
            chunks: list[np.ndarray] = []
            for segment in re.split(r"\n+", text.strip()):
                if not segment.strip():
                    continue
                _phonemes, tokens = pipeline.g2p(segment)
                missing = unknown_words(tokens)
                if missing:
                    fallback = getattr(pipeline.g2p, "fallback", None)
                    raise UnknownPronunciation(
                        f"no pronunciation for {', '.join(repr(w) for w in missing)} in "
                        f"{text!r} (misaki has no entry and its espeak fallback "
                        f"{'gave nothing' if fallback is not None else 'is not available'})"
                    )
                for result in pipeline.generate_from_tokens(tokens, voice=voice, speed=1.0):
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


def word_spec(
    lemma: str, pronunciation: str | None, accent: accents.Accent = accents.DEFAULT_ACCENT
) -> RenderSpec:
    """The render of a word in ``accent``'s voice. ``pronunciation`` is the
    sense's phonemes IN THAT ACCENT's alphabet (:func:`app.services
    .pronunciation.sense_pronunciation`)."""
    text = word_input(lemma, pronunciation)
    voice = accents.voice_for(accent)
    return RenderSpec(RenderKind.WORD, text, render_key(RenderKind.WORD, text, voice), voice)


def definition_spec(
    definition: str, lemma: str, accent: accents.Accent = accents.DEFAULT_ACCENT
) -> RenderSpec | None:
    """The render for a sense's masked definition, or ``None`` when there is
    no definition to speak."""
    text = masked_definition(definition, lemma)
    if not re.search(r"[A-Za-z0-9]", _MASK_RUN.sub(" ", text)):
        return None
    voice = accents.voice_for(accent)
    return RenderSpec(
        RenderKind.DEFINITION, text, render_key(RenderKind.DEFINITION, text, voice), voice
    )


def item_spec(
    definition: RenderSpec, *, word_spec_: RenderSpec | None, clip_storage_key: str | None
) -> RenderSpec:
    """The render for one On the go file. Exactly one of ``word_spec_`` (the
    word is TTS) and ``clip_storage_key`` (the word is a verified clip) is
    given. The input names the parts; see the module docstring. The item is in
    the voice of its ``definition`` (the word, if TTS, is the same voice by
    construction), so a clip-worded item still has one key per accent."""
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
    if word_spec_ is not None and word_spec_.voice != definition.voice:
        raise ValueError("an item's definition and word are in one voice")
    return RenderSpec(
        RenderKind.ITEM, text, render_key(RenderKind.ITEM, text, definition.voice),
        definition.voice,
    )


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


def synthesise_word(synth: Synth, text: str, voice: str = VOICE) -> np.ndarray:
    return audio_pcm.normalise_rms(trim_edges(synth(text, voice)))


def synthesise_definition(synth: Synth, masked: str, voice: str = VOICE) -> np.ndarray:
    """The masked definition spoken, each mask a silence of
    :data:`MASK_PAUSE_MS`."""
    parts: list[np.ndarray] = []
    for piece in split_masked(masked):
        if piece is None:
            parts.append(audio_pcm.silence(MASK_PAUSE_MS))
        else:
            parts.append(trim_edges(synth(piece, voice)))
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
    commit. Returns how many rows were new.

    The rows go in SORTED BY ``key``. A multi-row insert takes its row locks in
    VALUES order, and ``ON CONFLICT DO NOTHING`` waits on a row another
    transaction has inserted but not committed: two requests asking for
    overlapping sets in different orders (a list page and a session build) would
    each hold a lock the other wants -- a deadlock. One global order makes the
    waits a queue instead of a cycle. The trade-off of the own transaction is
    a second pooled connection while the request's own is open; at this scale
    (a handful of requests at once, a pool of ten) that is cheap, and the
    alternative -- inserting on the request's session -- would make a GET
    commit."""
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
    rows = dict(sorted(rows.items()))
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
        .values(status=RenderStatus.PENDING, attempts=0, error=None, next_attempt_at=None)
    )
    if kinds is not None:
        stmt = stmt.where(AudioRender.kind.in_(list(kinds)))
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount or 0


async def recover_stale_renders(
    session: AsyncSession, *, older_than_s: float | None = None
) -> int:
    """A render left ``processing`` by a dead worker goes back to ``pending``.

    With ``older_than_s`` only rows not touched for that long (``updated_at``,
    which claiming sets) are taken: a live worker's row is seconds old, so
    recovery -- at another worker's startup, or from inside the loop -- never
    steals one. ``None`` takes every ``processing`` row (a single-process
    caller that knows nothing else is running: the seed script, tests)."""
    stmt = (
        update(AudioRender)
        .where(AudioRender.status == RenderStatus.PROCESSING)
        .values(status=RenderStatus.PENDING, next_attempt_at=None)
    )
    if older_than_s is not None:
        stmt = stmt.where(
            AudioRender.updated_at < func.now() - timedelta(seconds=older_than_s)
        )
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount or 0


async def requeue_failed_older_than(session: AsyncSession, hours: float) -> int:
    """``failed`` renders untouched for ``hours`` go back to ``pending`` with
    their attempts reset: a fault that was since fixed (a model update, a
    storage outage that outlasted the back-off) heals itself. A word that
    always fails costs three attempts per period; nothing else does."""
    result = await session.execute(
        update(AudioRender)
        .where(
            AudioRender.status == RenderStatus.FAILED,
            AudioRender.updated_at < func.now() - timedelta(hours=hours),
        )
        .values(status=RenderStatus.PENDING, attempts=0, error=None, next_attempt_at=None)
    )
    await session.commit()
    return result.rowcount or 0


async def maintain_queue(session: AsyncSession) -> tuple[int, int]:
    """The loop's housekeeping, from the settings: ``(stale processing rows
    recovered, old failed rows requeued)``. Never raises -- recovery that
    cannot run (a database blip) must not stop the loop it exists to keep
    alive; the next pass tries again."""
    recovered = requeued = 0
    try:
        recovered = await recover_stale_renders(
            session, older_than_s=settings.tts_stale_after_s
        )
        if settings.tts_failed_requeue_h > 0:
            requeued = await requeue_failed_older_than(
                session, settings.tts_failed_requeue_h
            )
    except Exception:  # noqa: BLE001 - housekeeping only
        logger.exception("render queue maintenance failed; will retry")
        await session.rollback()
    return recovered, requeued


async def claim_renders(
    session: AsyncSession,
    *,
    kinds: Iterable[str] | None = None,
    keys: Iterable[str] | None = None,
    limit: int = 1,
) -> list[AudioRender]:
    """Atomically claim up to ``limit`` ``pending`` renders (empty list when the
    queue is empty, or every pending row is locked by another worker):
    ``FOR UPDATE SKIP LOCKED``, exactly :func:`app.worker.claim_one`'s shape,
    and the status flip is committed before anyone works on them -- so a second
    claimer (the dev worker draining the same queue while the seed runs
    elsewhere) skips what is taken whether or not the first is still alive. A
    row still in its failure back-off (``next_attempt_at`` in the future) is
    not claimable.

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
    stmt = select(AudioRender).where(
        AudioRender.status == RenderStatus.PENDING,
        or_(AudioRender.next_attempt_at.is_(None), AudioRender.next_attempt_at <= func.now()),
    )
    if kinds is not None:
        stmt = stmt.where(AudioRender.kind.in_(list(kinds)))
    if keys is not None:
        stmt = stmt.where(AudioRender.key.in_(list(keys)))
    rows = list(
        (
            await session.exec(
                stmt.order_by(rank, AudioRender.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    if not rows:
        await session.rollback()  # release the (empty) FOR UPDATE transaction
        return []
    now = datetime.now(timezone.utc)
    for row in rows:
        row.status = RenderStatus.PROCESSING
        row.updated_at = now  # the heartbeat stale recovery reads
        session.add(row)
    await session.commit()
    return rows


async def claim_render(
    session: AsyncSession,
    *,
    kinds: Iterable[str] | None = None,
    keys: Iterable[str] | None = None,
) -> AudioRender | None:
    """:func:`claim_renders` for one row (the worker's loop)."""
    rows = await claim_renders(session, kinds=kinds, keys=keys, limit=1)
    if not rows:
        return None
    await session.refresh(rows[0])
    return rows[0]


async def queue_depth(kinds: Iterable[str] | None = None) -> int:
    """Renders still to be made: ``pending`` or ``processing`` (any worker's)."""
    stmt = select(func.count()).select_from(AudioRender).where(
        AudioRender.status.in_((RenderStatus.PENDING, RenderStatus.PROCESSING))
    )
    if kinds is not None:
        stmt = stmt.where(AudioRender.kind.in_(list(kinds)))
    async with async_session_factory() as session:
        return int((await session.exec(stmt)).one())


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
        except InfrastructureError:
            raise  # storage is down: remaking would fail the same way, and say so
        except Exception:  # noqa: BLE001 - the file is gone; fall through and remake it
            logger.warning("render %s is ready but unreadable; remaking", spec.key)
    samples = await _in_synth_thread(_synthesise, spec, synth)
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
        return synthesise_word(synth, spec.input, spec.voice)
    if spec.kind == RenderKind.DEFINITION:
        return synthesise_definition(synth, spec.input, spec.voice)
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
    ``attempts`` bumped and a back-off before it may be claimed again, or
    ``failed`` once ``max_attempts`` is reached) -- the same contract as
    ``worker.process_blob``, for the same reason: one bad input must not take
    down the loop that serves every other. An INFRASTRUCTURE fault (storage
    down, Kokoro not loading: :class:`InfrastructureError`) spends no attempt
    at all: the row goes back to ``pending`` behind a back-off, so a systemic
    outage leaves the queue waiting rather than failed."""
    storage = guarded(storage or get_storage())
    limit = max_attempts if max_attempts is not None else settings.tts_max_attempts
    row_id, kind, key = row.id, row.kind, row.key
    try:
        offset: int | None = None
        if kind == RenderKind.ITEM:
            samples, offset = await build_item(session, row, synth, storage)
        else:
            samples = await _in_synth_thread(
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
        fresh.error = message[:2000]
        # Due times are the DATABASE's clock (`now()`), the same one `claim_render`
        # compares them with: a worker's own clock never decides when a row is due.
        if isinstance(exc, InfrastructureError):
            # The world's fault (storage down, the model did not load), not this
            # render's: no attempt is spent, so an outage cannot walk the whole
            # queue to `failed`. It waits out a back-off and is tried again.
            fresh.status = RenderStatus.PENDING
            fresh.next_attempt_at = func.now() + timedelta(seconds=settings.tts_infra_backoff_s)
        else:
            fresh.attempts += 1
            if fresh.attempts >= limit:
                fresh.status, fresh.next_attempt_at = RenderStatus.FAILED, None
            else:
                fresh.status = RenderStatus.PENDING
                fresh.next_attempt_at = func.now() + timedelta(
                    seconds=min(
                        settings.tts_retry_backoff_s * 2 ** (fresh.attempts - 1),
                        TTS_RETRY_BACKOFF_MAX_S,
                    )
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
    fresh.next_attempt_at = None
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
    concurrency: int = 1,
) -> int:
    """Claim and process renders until the queue is empty (or ``limit``). The
    seed script's engine -- the 3060 has no worker -- using exactly the
    worker's claim and process. Returns how many it handled (ready or not).

    **One synthesis stream, everything else overlapped.** The GPU is the scarce
    thing and Kokoro is not safe to call concurrently, so with ``concurrency``
    above 1 every synthesis runs on ONE dedicated thread
    (:func:`_in_synth_thread`), while up to ``concurrency`` renders are in
    flight at once: while one waits on encoding, a storage write or its commit
    (round trips to a database and a disk that may be across a tunnel), another
    is on the GPU. Memory is bounded: a claim is at most ``concurrency`` rows,
    the hand-off queue holds ``concurrency``, and only in-flight renders hold
    samples.

    **Safe beside another drainer** (the dev worker on the same queue): a claim
    is ``SKIP LOCKED`` and committed as ``processing`` before work starts, so no
    row is made twice; claimed rows' ``updated_at`` is at most a few seconds old
    while they wait, far inside ``tts_stale_after_s``, so the other side's
    stale recovery never takes them. If this drain is cancelled (Ctrl+C) the
    rows it claimed and did not resolve go straight back to ``pending``."""
    storage = storage or get_storage()
    kinds = list(kinds) if kinds is not None else None
    keys = list(keys) if keys is not None else None
    if concurrency > MAX_CONCURRENCY:
        logger.warning("concurrency %d capped at %d (database pool)", concurrency, MAX_CONCURRENCY)
    concurrency = max(1, min(concurrency, MAX_CONCURRENCY))
    queue: asyncio.Queue[AudioRender | None] = asyncio.Queue(maxsize=concurrency)
    held: dict[uuid.UUID, AudioRender] = {}  # claimed and not yet resolved
    handled = 0

    async def produce() -> None:
        claimed = 0
        try:
            while limit is None or claimed < limit:
                want = concurrency if limit is None else min(concurrency, limit - claimed)
                async with async_session_factory() as session:
                    rows = await claim_renders(session, kinds=kinds, keys=keys, limit=want)
                if not rows:
                    break
                claimed += len(rows)
                for row in rows:
                    held[row.id] = row
                for row in rows:
                    await queue.put(row)
        finally:
            for _ in range(concurrency):
                await queue.put(None)

    async def work() -> None:
        nonlocal handled
        while (row := await queue.get()) is not None:
            try:
                async with async_session_factory() as session:
                    fresh = await session.get(AudioRender, row.id)
                    if fresh is not None:
                        await process_render(session, fresh, synth, storage)
            except Exception:  # noqa: BLE001 - one row must not stop the drain
                # process_render records its own failures; this is the database
                # going away mid-row. The row stays `processing` and goes back
                # to `pending` below.
                logger.exception("render %s could not be resolved", row.key[:12])
            else:
                held.pop(row.id, None)
            handled += 1
            if on_progress is not None:
                on_progress(handled)

    executor = ThreadPoolExecutor(1, thread_name_prefix="tts-synth") if concurrency > 1 else None
    token = _synth_executor.set(executor)
    try:
        async with asyncio.TaskGroup() as group:
            group.create_task(produce())
            for _ in range(concurrency):
                group.create_task(work())
    finally:
        _synth_executor.reset(token)
        if executor is not None:
            executor.shutdown(wait=False)
        if held:
            await _release(list(held))
    return handled


async def _release(ids: list[uuid.UUID]) -> None:
    """Put claimed-but-unresolved renders back to ``pending`` (no attempt
    spent): the drain was stopped or the database blinked under it. Best
    effort -- stale recovery is the backstop."""
    try:
        async with async_session_factory() as session:
            await session.execute(
                update(AudioRender)
                .where(AudioRender.id.in_(ids), AudioRender.status == RenderStatus.PROCESSING)
                .values(status=RenderStatus.PENDING, next_attempt_at=None)
            )
            await session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("could not release %d claimed render(s)", len(ids))

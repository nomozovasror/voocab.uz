"""What a learner hears for a word: the one door the rest of the app uses.

Everything vocabulary stage 3 plays -- the speaker button, the `listen`
exercise, the `speak` prompt, On the go -- asks THIS module for its audio and
gets back a URL or "not ready yet". Nothing here synthesises anything: it reads
what :mod:`app.services.tts` has already made and, for what does not exist,
**queues it and answers ``None``** (the work is the worker's; a request never
waits on a model).

## A word is a recording, or TTS

Live clips cut from listening recordings were tried and dropped (2026-10-07:
the owner listened -- fragments of neighbouring words, the emotion and pitch of
the sentence). What replaced them is the dictionary's own recording OF THE
WORD, imported ahead of time (:mod:`app.services.word_recordings`).

The learner chooses (``vocabulary_settings.word_voice``): ``recorded``
(default) -- the recording for their accent where the sense has one, else
Kokoro -- or ``synthetic`` -- always Kokoro. A recording is one indexed row
(``word_recordings``: sense + accent), so the whole list is ONE query and the
senses it answers never touch the render queue. The Kokoro render in the
learner's ACCENT is served if ready, otherwise **enqueued** and the answer is
``None``. Definitions are always Kokoro.

## The accent (decisions 22-26)

Every function takes the learner's ``accent`` (``settings.accent``, default
British) and it decides three things: which RECORDING a ``recorded`` learner
hears (British the ``uk`` one, American the ``us`` one), which Kokoro VOICE a
render is in (the voice is in the render key, so each accent has its own rows
and files, for words and definitions alike) and which stored heteronym choice
is used (``LexemeSense.pronunciation`` British, ``pronunciation_us`` American
-- a phoneme string belongs to its alphabet). A heteronym's sense carries its
own phonemes, so its two senses are two renders.

## Works from a SENSE, not a saved word

A word-list entry nobody has saved yet is just a ``LexemeSense``; a saved word
is a ``LexemeSense`` plus a learner. Audio depends only on the sense (and its
lexeme's lemma and POS), so every function here takes senses. Lexemes are loaded
for you if not passed.

## Batch variants, and why they are the real API

A list endpoint (On the go lists every word in rotation) cannot ask per word.
The ``*_many`` functions do one query per table for any number of senses, and
the single-sense functions are one-element calls of them -- one code path, so
the single and the list answer cannot disagree.

## Enqueueing

:func:`app.services.tts.enqueue` runs on its own transaction (see its
docstring) and only for specs that have NO row at all: a ``failed`` render is
not silently retried by every page view -- :func:`app.services.tts
.requeue_failed` is the lever -- and a ``pending`` or ``processing`` one is
already on its way.
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlmodel import select

from app.core.database import AsyncSession
from app.models.audio_render import AudioRender, RenderStatus
from app.models.lexicon import Lexeme, LexemeSense
from app.models.word_recording import WordRecording
from app.services import pronunciation, tts
from app.services.accents import DEFAULT_ACCENT, DEFAULT_WORD_VOICE, Accent, WordVoice
from app.services.storage import get_storage


@dataclass(frozen=True)
class AudioOut:
    """The wire shape of a word's audio: the URL of the word alone."""

    url: str


def decided_pronunciation(sense: LexemeSense, accent: Accent) -> str | None:
    """The sense's stored heteronym choice for ``accent``'s alphabet."""
    return sense.pronunciation_us if accent == "american" else sense.pronunciation


def tts_word_spec(sense: LexemeSense, lexeme: Lexeme, accent: Accent) -> tts.RenderSpec:
    """The TTS render of a sense's word in ``accent``'s voice -- with the
    sense's phonemes when the lemma is a heteronym in that accent. The
    seed uses it directly, with the worker and the API: one spec, one key."""
    phonemes = pronunciation.sense_pronunciation(
        lexeme.lemma, lexeme.pos, decided_pronunciation(sense, accent), accent
    )
    return tts.word_spec(lexeme.lemma, phonemes, accent)


async def _pairs(
    session: AsyncSession,
    senses: Sequence[LexemeSense],
    lexemes: dict[uuid.UUID, Lexeme] | None,
) -> list[tuple[LexemeSense, Lexeme]]:
    """Each sense with its lexeme, loading the missing lexemes in one query."""
    known = dict(lexemes or {})
    missing = {s.lexeme_id for s in senses if s.lexeme_id not in known}
    if missing:
        for lexeme in (
            await session.exec(select(Lexeme).where(Lexeme.id.in_(missing)))
        ).all():
            known[lexeme.id] = lexeme
    return [(s, known[s.lexeme_id]) for s in senses if s.lexeme_id in known]


async def _render_rows(
    session: AsyncSession, keys: Iterable[str]
) -> dict[str, AudioRender]:
    wanted = list(set(keys))
    if not wanted:
        return {}
    rows = await session.exec(select(AudioRender).where(AudioRender.key.in_(wanted)))
    return {row.key: row for row in rows.all()}


async def _enqueue_missing(
    rows: dict[str, AudioRender], specs: Iterable[tts.RenderSpec]
) -> None:
    """Queue the specs that have no row yet. ``rows`` is what was just read."""
    missing = {spec.key: spec for spec in specs if spec.key not in rows}
    if missing:
        await tts.enqueue(missing.values())


async def _recordings(
    session: AsyncSession, sense_ids: Iterable[uuid.UUID], accent: Accent
) -> dict[uuid.UUID, str]:
    """``{sense id: storage key}`` of the human recordings in ``accent`` -- one
    query for any number of senses."""
    wanted = list(set(sense_ids))
    if not wanted:
        return {}
    rows = await session.exec(
        select(WordRecording.lexeme_sense_id, WordRecording.storage_key).where(
            WordRecording.lexeme_sense_id.in_(wanted), WordRecording.accent == accent
        )
    )
    return {sense_id: key for sense_id, key in rows.all()}


def _ready(row: AudioRender | None) -> bool:
    return (
        row is not None and row.status == RenderStatus.READY and bool(row.storage_key)
    )


async def word_audio_many(
    session: AsyncSession,
    senses: Sequence[LexemeSense],
    *,
    lexemes: dict[uuid.UUID, Lexeme] | None = None,
    accent: Accent = DEFAULT_ACCENT,
    word_voice: WordVoice = DEFAULT_WORD_VOICE,
) -> dict[uuid.UUID, AudioOut | None]:
    """The word audio for every sense in one go: ``{sense id: AudioOut | None}``.
    ``None`` = not ready yet, and already queued (a sense whose lexeme cannot
    be found is simply absent).

    ``word_voice == 'recorded'``: a sense with a human recording in ``accent``
    is answered by it, immediately; every other sense takes the TTS path below
    exactly as under ``'synthetic'`` -- nothing is queued for a word a person
    already said."""
    storage = get_storage()
    recorded = (
        await _recordings(session, (s.id for s in senses), accent)
        if word_voice == "recorded"
        else {}
    )
    out: dict[uuid.UUID, AudioOut | None] = {
        sense_id: AudioOut(url=await storage.url(key)) for sense_id, key in recorded.items()
    }
    specs = {
        sense.id: tts_word_spec(sense, lexeme, accent)
        for sense, lexeme in await _pairs(
            session, [s for s in senses if s.id not in recorded], lexemes
        )
    }
    rows = await _render_rows(session, (spec.key for spec in specs.values()))
    await _enqueue_missing(rows, specs.values())

    for sense_id, spec in specs.items():
        row = rows.get(spec.key)
        out[sense_id] = (
            AudioOut(url=await storage.url(row.storage_key))  # type: ignore[arg-type]
            if _ready(row)
            else None
        )
    return out


async def word_audio(
    session: AsyncSession,
    sense: LexemeSense,
    lexeme: Lexeme | None = None,
    *,
    accent: Accent = DEFAULT_ACCENT,
    word_voice: WordVoice = DEFAULT_WORD_VOICE,
) -> AudioOut | None:
    """The audio for one sense's word, or ``None`` if it is not ready (it is
    then queued)."""
    result = await word_audio_many(
        session,
        [sense],
        lexemes={lexeme.id: lexeme} if lexeme is not None else None,
        accent=accent,
        word_voice=word_voice,
    )
    return result.get(sense.id)


async def definition_audio_urls(
    session: AsyncSession,
    senses: Sequence[LexemeSense],
    *,
    lexemes: dict[uuid.UUID, Lexeme] | None = None,
    accent: Accent = DEFAULT_ACCENT,
) -> dict[uuid.UUID, str | None]:
    """URL of each sense's spoken, MASKED definition (the headword a silence),
    or ``None`` -- not ready (queued), or the sense has no definition."""
    storage = get_storage()
    specs: dict[uuid.UUID, tts.RenderSpec] = {}
    for sense, lexeme in await _pairs(session, senses, lexemes):
        spec = tts.definition_spec(sense.definition_en, lexeme.lemma, accent)
        if spec is not None:
            specs[sense.id] = spec
    rows = await _render_rows(session, (s.key for s in specs.values()))
    await _enqueue_missing(rows, specs.values())

    out: dict[uuid.UUID, str | None] = {sense.id: None for sense in senses}
    for sense_id, spec in specs.items():
        row = rows.get(spec.key)
        if _ready(row):
            out[sense_id] = await storage.url(row.storage_key)  # type: ignore[arg-type]
    return out


async def definition_audio_url(
    session: AsyncSession,
    sense: LexemeSense,
    lexeme: Lexeme | None = None,
    accent: Accent = DEFAULT_ACCENT,
) -> str | None:
    result = await definition_audio_urls(
        session, [sense], lexemes={lexeme.id: lexeme} if lexeme is not None else None,
        accent=accent,
    )
    return result.get(sense.id)

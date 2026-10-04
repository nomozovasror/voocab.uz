"""What a learner hears for a word: the one door the rest of the app uses.

Everything vocabulary stage 3 plays -- the speaker button, the `listen`
exercise, the `speak` prompt, On the go -- asks THIS module for its audio and
gets back a URL or "not ready yet". Nothing here synthesises or cuts anything:
it reads what :mod:`app.services.word_clips` and :mod:`app.services.tts` have
already made and, for what does not exist, **queues it and answers ``None``**
(the work is the worker's; a request never waits on a model).

## The resolution order, per sense

1. **A heteronym is always TTS**, with the sense's own pronunciation
   (decision 2). The transcript has no part of speech, so a recording of
   `record` could be either word; a clip is never even looked for.
2. **A verified clip** of the lemma's exact form (decisions 1 and 3), the
   learner's OWN listening materials first (rule 1 of the brief: a word they
   met in a recording they sat is best heard in that recording -- it cannot
   fire today, because listening materials have no vocabulary, and is built
   anyway), then any recording, longest word first. It carries the context
   clip when one was cut.
3. **The word read by the TTS voice**, if that render is ready.
4. Otherwise the TTS render is **enqueued** and the answer is ``None``.

``source`` on :class:`AudioOut` says which of the two it was, because the
client treats them differently (a clip has a context press, TTS does not).

## Works from a SENSE, not a saved word

A word-list entry nobody has saved yet is just a ``LexemeSense``; a saved word
is a ``LexemeSense`` plus a learner. Audio depends only on the sense (and its
lexeme's lemma and POS), so every function here takes senses; only
:func:`item_renders` takes a saved word, because an On the go item is a thing a
learner has in rotation. Lexemes are loaded for you if not passed.

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
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal, NamedTuple

from sqlmodel import select

from app.core.database import AsyncSession
from app.models.audio_asset import AudioAsset
from app.models.audio_render import AudioRender, RenderStatus
from app.models.lexicon import Lexeme, LexemeSense
from app.models.material import Material
from app.models.vocabulary import SavedWord
from app.models.word_clip import ClipStatus, WordClip
from app.services import pronunciation, tts
from app.services.storage import get_storage
from app.services.word_clips import normalise_form, servable_clip_clauses


@dataclass(frozen=True)
class AudioOut:
    """The wire shape of a word's audio. ``context_url`` is the word with its
    neighbours (a clip only); ``None`` for TTS."""

    url: str
    context_url: str | None
    source: Literal["clip", "tts"]


class ItemAudio(NamedTuple):
    """One On the go file: where it is, how long, and where the word starts
    inside it."""

    url: str
    duration_ms: int
    word_offset_ms: int


@dataclass(frozen=True)
class WordSource:
    """Where a sense's word audio comes from: a verified clip, or a TTS spec."""

    clip: WordClip | None = None
    spec: tts.RenderSpec | None = None

    @property
    def source(self) -> Literal["clip", "tts"]:
        return "clip" if self.clip is not None else "tts"


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


async def _blob_ids(
    session: AsyncSession, material_ids: Iterable[uuid.UUID]
) -> set[uuid.UUID]:
    """The recordings behind these materials (``material -> audio asset ->
    blob``)."""
    ids = list(material_ids)
    if not ids:
        return set()
    rows = await session.exec(
        select(AudioAsset.blob_id)
        .join(Material, Material.audio_asset_id == AudioAsset.id)
        .where(Material.id.in_(ids))
    )
    return set(rows.all())


async def _verified_clips(
    session: AsyncSession, forms: Iterable[str]
) -> dict[str, list[WordClip]]:
    """The servable clips of each form: ``verified``, AND still allowed at
    this moment -- the recording is still in a public material and the clip's
    segment is still uncorrected (:func:`word_clips.servable_clip_clauses`).
    Verification and indexing are earlier decisions; a material made private
    afterwards must stop being heard now, not at the next seed run."""
    wanted = list(set(forms))
    if not wanted:
        return {}
    rows = (
        await session.exec(
            select(WordClip).where(
                WordClip.form.in_(wanted),
                WordClip.status == ClipStatus.VERIFIED,
                WordClip.storage_key.is_not(None),
                *servable_clip_clauses(),
            )
        )
    ).all()
    out: dict[str, list[WordClip]] = defaultdict(list)
    for clip in rows:
        out[clip.form].append(clip)
    return out


async def word_sources(
    session: AsyncSession,
    senses: Sequence[LexemeSense],
    *,
    lexemes: dict[uuid.UUID, Lexeme] | None = None,
    prefer_material_ids: Iterable[uuid.UUID] = (),
) -> dict[uuid.UUID, WordSource]:
    """Decide, per sense, clip or TTS (the module docstring's order). Pure
    resolution: nothing is enqueued here. Keyed by sense id."""
    pairs = await _pairs(session, senses, lexemes)
    preferred_blobs = await _blob_ids(session, prefer_material_ids)

    plans: dict[uuid.UUID, tuple[Lexeme, str | None, str]] = {}
    for sense, lexeme in pairs:
        phonemes = pronunciation.sense_pronunciation(
            lexeme.lemma, lexeme.pos, sense.pronunciation
        )
        plans[sense.id] = (lexeme, phonemes, normalise_form(lexeme.lemma))
    clips = await _verified_clips(
        session, (form for _lexeme, phonemes, form in plans.values() if phonemes is None)
    )

    out: dict[uuid.UUID, WordSource] = {}
    for sense_id, (lexeme, phonemes, form) in plans.items():
        if phonemes is None and clips.get(form):
            best = min(
                clips[form],
                key=lambda c: (
                    0 if c.blob_id in preferred_blobs else 1,
                    -(c.end_ms - c.start_ms),
                    str(c.id),
                ),
            )
            out[sense_id] = WordSource(clip=best)
        else:
            out[sense_id] = WordSource(spec=tts.word_spec(lexeme.lemma, phonemes))
    return out


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


def _ready(row: AudioRender | None) -> bool:
    return (
        row is not None and row.status == RenderStatus.READY and bool(row.storage_key)
    )


async def word_audio_many(
    session: AsyncSession,
    senses: Sequence[LexemeSense],
    *,
    lexemes: dict[uuid.UUID, Lexeme] | None = None,
    prefer_material_ids: Iterable[uuid.UUID] = (),
) -> dict[uuid.UUID, AudioOut | None]:
    """The word audio for every sense in one go: ``{sense id: AudioOut | None}``.
    ``None`` = not ready yet, and already queued (a sense whose lexeme cannot
    be found is simply absent)."""
    storage = get_storage()
    sources = await word_sources(
        session, senses, lexemes=lexemes, prefer_material_ids=prefer_material_ids
    )
    rows = await _render_rows(
        session, (s.spec.key for s in sources.values() if s.spec is not None)
    )
    await _enqueue_missing(rows, (s.spec for s in sources.values() if s.spec is not None))

    out: dict[uuid.UUID, AudioOut | None] = {}
    for sense_id, source in sources.items():
        if source.clip is not None:
            clip = source.clip
            assert clip.storage_key is not None
            out[sense_id] = AudioOut(
                url=await storage.url(clip.storage_key),
                context_url=(
                    await storage.url(clip.context_storage_key)
                    if clip.context_storage_key
                    else None
                ),
                source="clip",
            )
            continue
        assert source.spec is not None
        row = rows.get(source.spec.key)
        out[sense_id] = (
            AudioOut(url=await storage.url(row.storage_key), context_url=None, source="tts")  # type: ignore[arg-type]
            if _ready(row)
            else None
        )
    return out


async def word_audio(
    session: AsyncSession,
    sense: LexemeSense,
    lexeme: Lexeme | None = None,
    *,
    prefer_material_ids: Iterable[uuid.UUID] = (),
) -> AudioOut | None:
    """The audio for one sense's word, or ``None`` if it is not ready (it is
    then queued). ``prefer_material_ids`` are the learner's own listening
    materials: a verified clip from their recordings wins over any other."""
    result = await word_audio_many(
        session,
        [sense],
        lexemes={lexeme.id: lexeme} if lexeme is not None else None,
        prefer_material_ids=prefer_material_ids,
    )
    return result.get(sense.id)


async def definition_audio_urls(
    session: AsyncSession,
    senses: Sequence[LexemeSense],
    *,
    lexemes: dict[uuid.UUID, Lexeme] | None = None,
) -> dict[uuid.UUID, str | None]:
    """URL of each sense's spoken, MASKED definition (the headword a silence),
    or ``None`` -- not ready (queued), or the sense has no definition."""
    storage = get_storage()
    specs: dict[uuid.UUID, tts.RenderSpec] = {}
    for sense, lexeme in await _pairs(session, senses, lexemes):
        spec = tts.definition_spec(sense.definition_en, lexeme.lemma)
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
    session: AsyncSession, sense: LexemeSense, lexeme: Lexeme | None = None
) -> str | None:
    result = await definition_audio_urls(
        session, [sense], lexemes={lexeme.id: lexeme} if lexeme is not None else None
    )
    return result.get(sense.id)


async def item_renders(
    session: AsyncSession,
    saved_words: Sequence[SavedWord],
    *,
    prefer_material_ids: Iterable[uuid.UUID] = (),
) -> dict[uuid.UUID, ItemAudio | None]:
    """The On the go file of every saved word: ``{saved word id: ItemAudio |
    None}``. ``None`` = not ready (its parts and the item are queued, parts
    first) or the sense has no definition to play."""
    storage = get_storage()
    senses = {
        s.id: s
        for s in (
            await session.exec(
                select(LexemeSense).where(
                    LexemeSense.id.in_({w.lexeme_sense_id for w in saved_words})
                )
            )
        ).all()
    } if saved_words else {}
    ordered = list(senses.values())
    pairs = {s.id: lexeme for s, lexeme in await _pairs(session, ordered, None)}
    sources = await word_sources(
        session, ordered, lexemes={lexeme.id: lexeme for lexeme in pairs.values()},
        prefer_material_ids=prefer_material_ids,
    )

    parts: dict[uuid.UUID, tuple[tts.RenderSpec, tts.RenderSpec | None, tts.RenderSpec]] = {}
    for sense_id, sense in senses.items():
        lexeme = pairs.get(sense_id)
        if lexeme is None:
            continue
        definition = tts.definition_spec(sense.definition_en, lexeme.lemma)
        if definition is None:
            continue
        source = sources[sense_id]
        item = tts.item_spec(
            definition,
            word_spec_=source.spec,
            clip_storage_key=source.clip.storage_key if source.clip is not None else None,
        )
        parts[sense_id] = (definition, source.spec, item)

    rows = await _render_rows(
        session,
        (
            spec.key
            for definition, word, item in parts.values()
            for spec in (definition, word, item)
            if spec is not None
        ),
    )
    # Parts first: the claim order is by kind anyway, but one insert holding all
    # three keeps a half-queued item from ever existing.
    await _enqueue_missing(
        rows,
        (
            spec
            for definition, word, item in parts.values()
            if not _ready(rows.get(item.key))
            for spec in (definition, word, item)
            if spec is not None
        ),
    )

    out: dict[uuid.UUID, ItemAudio | None] = {}
    for saved in saved_words:
        triple = parts.get(saved.lexeme_sense_id)
        row = rows.get(triple[2].key) if triple is not None else None
        if (
            row is not None
            and _ready(row)
            and row.duration_ms is not None
            and row.word_offset_ms is not None
        ):
            out[saved.id] = ItemAudio(
                await storage.url(row.storage_key),  # type: ignore[arg-type]
                row.duration_ms,
                row.word_offset_ms,
            )
        else:
            out[saved.id] = None
    return out


async def item_render(
    session: AsyncSession,
    saved_word: SavedWord,
    *,
    prefer_material_ids: Iterable[uuid.UUID] = (),
) -> ItemAudio | None:
    """``(url, duration_ms, word_offset_ms)`` of one word's On the go file, or
    ``None`` (queued, or nothing to play)."""
    result = await item_renders(
        session, [saved_word], prefer_material_ids=prefer_material_ids
    )
    return result.get(saved_word.id)

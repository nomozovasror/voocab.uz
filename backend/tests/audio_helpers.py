"""Shared fakes and builders for the audio-layer tests (vocabulary stage 3):
a fake Kokoro, an in-memory storage, a generated tone, and rows built with
unique names so the tests never collide with each other or with real data in a
shared database. Not a test module itself."""

import uuid
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import delete
from sqlalchemy import select as sa_select

from app.core.database import async_session_factory
from app.models.audio_asset import AudioAsset
from app.models.audio_blob import AudioBlob, TranscriptStatus
from app.models.audio_render import AudioRender
from app.models.audio_segment import AudioSegment
from app.models.lexicon import Lexeme, LexemeSense
from app.models.material import Material
from app.models.user import User
from app.models.vocabulary import SavedWord
from app.models.word_clip import WordClip
from app.services import audio_pcm


def unique_word(prefix: str = "zq") -> str:
    """A lowercase, letters-only token no real transcript contains (letters
    only because definition masking tokenises on ``[A-Za-z']``: a digit would
    split the word)."""
    return prefix + "".join(chr(97 + int(c, 16)) for c in uuid.uuid4().hex[:12])


def tone(ms: int, freq: float = 440.0, amp: float = 0.1) -> np.ndarray:
    n = round(ms * audio_pcm.SAMPLE_RATE / 1000)
    t = np.arange(n) / audio_pcm.SAMPLE_RATE
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


class FakeSynth:
    """A Kokoro stand-in: a tone 25 ms long per character of its input, with a
    quiet lead-in and tail (so trimming has something to trim). Records every
    input it was asked to speak."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.calls: list[str] = []
        self.fail_on = fail_on

    def __call__(self, text: str) -> np.ndarray:
        self.calls.append(text)
        if self.fail_on is not None and self.fail_on in text:
            raise RuntimeError("synthesis failed")
        body = tone(max(100, 25 * len(text)), amp=0.05)
        edge = np.zeros(audio_pcm.SAMPLE_RATE // 5, dtype=np.float32)
        return np.concatenate([edge, body, edge])


class FakeStorage:
    """In-memory ``MediaStorage``."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, mime_type: str) -> None:
        self.objects.setdefault(key, data)

    async def exists(self, key: str) -> bool:
        return key in self.objects

    async def get(self, key: str) -> bytes:
        return self.objects[key]

    async def url(self, key: str) -> str:
        return f"/media/{key}"


@dataclass
class Created:
    """What a test made, for one call to :meth:`cleanup`."""

    blob_ids: list[uuid.UUID] = field(default_factory=list)
    render_keys: list[str] = field(default_factory=list)
    lexeme_ids: list[uuid.UUID] = field(default_factory=list)
    user_ids: list[uuid.UUID] = field(default_factory=list)
    material_ids: list[uuid.UUID] = field(default_factory=list)
    asset_ids: list[uuid.UUID] = field(default_factory=list)

    async def cleanup(self) -> None:
        async with async_session_factory() as session:
            if self.render_keys:
                await session.execute(
                    delete(AudioRender).where(AudioRender.key.in_(self.render_keys))
                )
            if self.blob_ids:
                await session.execute(delete(WordClip).where(WordClip.blob_id.in_(self.blob_ids)))
            if self.material_ids:
                await session.execute(delete(Material).where(Material.id.in_(self.material_ids)))
            if self.asset_ids:
                await session.execute(delete(AudioAsset).where(AudioAsset.id.in_(self.asset_ids)))
            if self.blob_ids:
                await session.execute(
                    delete(AudioSegment).where(AudioSegment.blob_id.in_(self.blob_ids))
                )
                await session.execute(delete(AudioBlob).where(AudioBlob.id.in_(self.blob_ids)))
            if self.lexeme_ids:
                await session.execute(
                    delete(SavedWord).where(
                        SavedWord.lexeme_sense_id.in_(
                            sa_select(LexemeSense.id).where(
                                LexemeSense.lexeme_id.in_(self.lexeme_ids)
                            )
                        )
                    )
                )
                await session.execute(
                    delete(LexemeSense).where(LexemeSense.lexeme_id.in_(self.lexeme_ids))
                )
                await session.execute(delete(Lexeme).where(Lexeme.id.in_(self.lexeme_ids)))
            if self.user_ids:
                await session.execute(delete(User).where(User.id.in_(self.user_ids)))
            await session.commit()


def words(*items: tuple[str, int, int]) -> list[dict]:
    """``[{word, start_ms, end_ms}]`` from ``(word, start, end)`` triples."""
    return [{"word": w, "start_ms": s, "end_ms": e} for w, s, e in items]


def sentence(tokens: list[str], *, start_ms: int = 1000, each_ms: int = 400) -> list[dict]:
    """A segment of consecutive words, ``each_ms`` long with 100 ms gaps."""
    out, cursor = [], start_ms
    for token in tokens:
        out.append({"word": token, "start_ms": cursor, "end_ms": cursor + each_ms})
        cursor += each_ms + 100
    return out


async def make_blob(
    created: Created,
    segments: list[list[dict]],
    *,
    duration_ms: int = 60_000,
    status: str = TranscriptStatus.READY,
) -> AudioBlob:
    """A ready blob with one ``AudioSegment`` per list of words."""
    async with async_session_factory() as session:
        blob = AudioBlob(
            sha256=f"test-{uuid.uuid4().hex}",
            storage_key=f"audio/test-{uuid.uuid4().hex}.m4a",
            size_bytes=10,
            mime_type="audio/mp4",
            duration_ms=duration_ms,
            transcript_status=status,
        )
        session.add(blob)
        await session.flush()
        for index, seg_words in enumerate(segments):
            session.add(
                AudioSegment(
                    blob_id=blob.id,
                    order_index=index,
                    start_ms=seg_words[0]["start_ms"] if seg_words else 0,
                    end_ms=seg_words[-1]["end_ms"] if seg_words else 0,
                    text=" ".join(w["word"] for w in seg_words),
                    words=seg_words,
                )
            )
        await session.commit()
        await session.refresh(blob)
    created.blob_ids.append(blob.id)
    return blob


async def make_user(created: Created) -> User:
    async with async_session_factory() as session:
        user = User(email=f"audio-{uuid.uuid4().hex}@example.test", display_name="Audio test")
        session.add(user)
        await session.commit()
        await session.refresh(user)
    created.user_ids.append(user.id)
    return user


async def make_lexeme(
    created: Created,
    lemma: str,
    *,
    pos: str | None = None,
    definition: str = "a thing that exists",
    pronunciation: str | None = None,
) -> tuple[Lexeme, LexemeSense]:
    """A lexeme and one sense. ``pos`` defaults to a unique tag so a real
    lemma (``record``) never collides with another test's row."""
    async with async_session_factory() as session:
        lexeme = Lexeme(lemma=lemma, pos=pos or f"t{uuid.uuid4().hex[:6]}")
        session.add(lexeme)
        await session.flush()
        sense = LexemeSense(
            lexeme_id=lexeme.id,
            definition_en=definition,
            meaning_uz="x",
            pronunciation=pronunciation,
        )
        session.add(sense)
        await session.commit()
        await session.refresh(lexeme)
        await session.refresh(sense)
    created.lexeme_ids.append(lexeme.id)
    return lexeme, sense


async def add_clip(
    blob: AudioBlob,
    form: str,
    *,
    status: str = "verified",
    start_ms: int = 1000,
    end_ms: int = 1500,
    with_context: bool = True,
) -> WordClip:
    """A clip row, as if cut (and, by default, verified). Each gets its own
    word index so several can sit on one blob."""
    index = uuid.uuid4().int % 1_000_000 + 1
    async with async_session_factory() as session:
        clip = WordClip(
            form=form,
            blob_id=blob.id,
            segment_order_index=0,
            word_start_index=index,
            word_end_index=index,
            start_ms=start_ms,
            end_ms=end_ms,
            context_start_index=0,
            context_end_index=2,
            context_start_ms=start_ms - 400,
            context_end_ms=end_ms + 400,
            storage_key=f"clips/test-{uuid.uuid4().hex}.m4a",
            context_storage_key=(f"clips/test-{uuid.uuid4().hex}.m4a" if with_context else None),
            status=status,
        )
        session.add(clip)
        await session.commit()
        await session.refresh(clip)
    return clip

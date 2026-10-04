"""Shared fakes and builders for the audio-layer tests (vocabulary stage 3):
a fake Kokoro, an in-memory storage, a generated tone, and rows built with
unique names so the tests never collide with each other or with real data in a
shared database. Not a test module itself."""

import uuid
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import delete
from sqlalchemy import select as sa_select
from sqlmodel import select

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


class FlakyStorage(FakeStorage):
    """A storage that raises ``get_error`` / ``put_error`` while they are set --
    an outage that a test can end."""

    def __init__(self) -> None:
        super().__init__()
        self.get_error: Exception | None = None
        self.put_error: Exception | None = None

    async def put(self, key: str, data: bytes, mime_type: str) -> None:
        if self.put_error is not None:
            raise self.put_error
        await super().put(key, data, mime_type)

    async def get(self, key: str) -> bytes:
        if self.get_error is not None:
            raise self.get_error
        return await super().get(key)


def s3_error(code: str) -> Exception:
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": code, "Message": code}}, "GetObject")


@dataclass
class Created:
    """What a test made, for one call to :meth:`cleanup`."""

    blob_ids: list[uuid.UUID] = field(default_factory=list)
    render_keys: list[str] = field(default_factory=list)
    lexeme_ids: list[uuid.UUID] = field(default_factory=list)
    user_ids: list[uuid.UUID] = field(default_factory=list)
    material_ids: list[uuid.UUID] = field(default_factory=list)
    asset_ids: list[uuid.UUID] = field(default_factory=list)
    #: The one user who owns every recording ``attach`` makes for a test.
    owner_id: uuid.UUID | None = None

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


async def attach(
    created: Created, blob: AudioBlob, visibility: str | None = "public"
) -> tuple[AudioAsset, Material | None]:
    """An owner's asset over ``blob``, and -- unless ``visibility`` is ``None``
    -- a listening material of that visibility using it. ``None`` is an
    unattached upload: some user's private file, in no material at all."""
    if created.owner_id is None:
        created.owner_id = (await make_user(created)).id
    async with async_session_factory() as session:
        asset = (
            await session.exec(
                select(AudioAsset).where(
                    AudioAsset.owner_id == created.owner_id, AudioAsset.blob_id == blob.id
                )
            )
        ).first()
        if asset is None:
            asset = AudioAsset(owner_id=created.owner_id, blob_id=blob.id)
            session.add(asset)
            await session.flush()
            created.asset_ids.append(asset.id)
        material = None
        if visibility is not None:
            material = Material(
                author_id=created.owner_id,
                type="listening",
                title="audio test",
                audio_asset_id=asset.id,
                visibility=visibility,
            )
            session.add(material)
            await session.flush()
            created.material_ids.append(material.id)
        await session.commit()
    return asset, material


async def make_blob(
    created: Created,
    segments: list[list[dict]],
    *,
    duration_ms: int = 60_000,
    status: str = TranscriptStatus.READY,
    visibility: str | None = "public",
) -> AudioBlob:
    """A ready blob with one ``AudioSegment`` per list of words, used by a
    PUBLIC material by default -- the only kind of recording a clip may come
    from. ``visibility="private"`` or ``None`` (no material) make the others."""
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
    if visibility is not None:
        await attach(created, blob, visibility)
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


def encode_mp3(left: np.ndarray, right: np.ndarray | None = None, *, rate: int = 44_100) -> bytes:
    """``left``/``right`` (float32 at ``rate``) as a stereo MP3 -- what the
    material recordings really look like (44.1 kHz stereo), as opposed to the
    24 kHz mono AAC the layer itself stores. Through a real file: PyAV's mp3
    muxer wants a seekable output with a name."""
    import os
    import tempfile
    from fractions import Fraction

    import av

    right = left if right is None else right
    pcm = np.clip(np.stack([left, right]), -1.0, 1.0).astype(np.float32)
    with tempfile.TemporaryDirectory() as workdir:
        path = os.path.join(workdir, "in.mp3")
        with av.open(path, mode="w", format="mp3") as container:
            stream = container.add_stream("libmp3lame", rate=rate, layout="stereo")
            stream.bit_rate = 128_000
            pts = 0
            for offset in range(0, pcm.shape[1], rate):
                piece = np.ascontiguousarray(pcm[:, offset : offset + rate])
                frame = av.AudioFrame.from_ndarray(
                    piece.reshape(1, -1, order="F").copy(), format="flt", layout="stereo"
                )
                frame.sample_rate = rate
                frame.pts = pts
                frame.time_base = Fraction(1, rate)
                pts += piece.shape[1]
                for packet in stream.encode(frame):
                    container.mux(packet)
            for packet in stream.encode(None):
                container.mux(packet)
        with open(path, "rb") as handle:
            return handle.read()

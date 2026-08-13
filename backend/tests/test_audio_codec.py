"""What the upload endpoint lets through, and why.

An extension names a container. ``.m4a`` is the one where that isn't enough:
AAC inside it plays everywhere, ALAC inside it plays nowhere, and both
transcribe fine — so an unplayable recording used to sail through and only
show itself when the author pressed play, on a material that otherwise
looked finished.

The MP4s here are built by hand rather than encoded, because what is being
tested is the box reader, and a hand-built file can be exactly the shape the
test is about — a video track ahead of the audio one, a truncated header —
without carrying a megabyte of samples to say it.
"""

import struct
import uuid
from pathlib import Path

import httpx
import pytest
from sqlmodel import select

from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.main import app
from app.models.user import User
from app.services.audio_codec import mp4_audio_codec, unplayable_reason

FIXTURES = Path(__file__).parent / "fixtures"


def _box(box_type: str, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + box_type.encode("latin-1") + payload


def _hdlr(handler: str) -> bytes:
    # FullBox(version+flags) + pre_defined + handler_type + the rest, which
    # nothing here reads.
    return _box("hdlr", b"\x00" * 4 + b"\x00" * 4 + handler.encode("latin-1") + b"\x00" * 12)


def _stsd(codec: str) -> bytes:
    entry = _box(codec, b"\x00" * 8)
    return _box("stsd", b"\x00" * 4 + struct.pack(">I", 1) + entry)


def _trak(handler: str, codec: str) -> bytes:
    stbl = _box("stbl", _stsd(codec))
    minf = _box("minf", stbl)
    mdia = _box("mdia", _hdlr(handler) + minf)
    return _box("trak", mdia)


def _mp4(*traks: bytes) -> bytes:
    return _box("ftyp", b"M4A isom") + _box("moov", b"".join(traks))


# --- The reader --------------------------------------------------------------


def test_the_audio_track_is_the_one_read_even_behind_a_video_track() -> None:
    """A .mp4 commonly opens with video. Reading the first sample entry in
    the file would report `avc1` and refuse a recording whose audio is
    perfectly ordinary AAC."""
    data = _mp4(_trak("vide", "avc1"), _trak("soun", "mp4a"))
    assert mp4_audio_codec(data) == "mp4a"
    assert unplayable_reason(".mp4", data) is None


def test_alac_is_named_when_it_is_refused() -> None:
    data = _mp4(_trak("soun", "alac"))
    reason = unplayable_reason(".m4a", data)
    assert reason is not None
    assert "Apple Lossless" in reason
    # And says what to do about it, which is the only reason to say anything.
    assert "MP3" in reason


def test_the_real_alac_fixture_is_caught() -> None:
    """The hand-built files above prove the reader; this proves it against a
    file an encoder actually produced."""
    data = (FIXTURES / "hello.m4a").read_bytes()
    assert mp4_audio_codec(data) == "alac"
    assert unplayable_reason(".m4a", data) is not None


@pytest.mark.parametrize("codec", ["mp4a", "Opus", "fLaC"])
def test_what_browsers_play_is_let_through(codec: str) -> None:
    assert unplayable_reason(".m4a", _mp4(_trak("soun", codec))) is None


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not an mp4 at all",
        _box("ftyp", b"M4A isom"),  # no moov
        _box("ftyp", b"M4A ") + _box("moov", _box("trak", b"\x00\x00")),  # no stsd
        _mp4(_trak("soun", "mp4a"))[:20],  # truncated mid-box
    ],
)
def test_anything_unreadable_is_let_through(data: bytes) -> None:
    """Fails open on purpose. A file this reader can't make sense of is far
    more likely to be a container shape it doesn't know than a broken upload,
    and refusing those would refuse work that plays perfectly well."""
    assert unplayable_reason(".m4a", data) is None


def test_only_the_mp4_family_is_inspected() -> None:
    """An .mp3 is MPEG audio and a .wav is PCM; opening them to ask would be
    answering a question nobody asked. The ALAC bytes stand in for "anything
    at all" here."""
    data = _mp4(_trak("soun", "alac"))
    for extension in [".mp3", ".wav", ".ogg", ".webm"]:
        assert unplayable_reason(extension, data) is None


# --- The endpoint ------------------------------------------------------------


@pytest.mark.asyncio
async def test_uploading_an_unplayable_recording_is_refused() -> None:
    email = f"codec-{uuid.uuid4()}@example.com"
    async with async_session_factory() as session:
        user = User(email=email, display_name="Codec test")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        user_id = user.id
    token = create_access_token(str(user_id))

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                "/api/uploads/audio",
                files={
                    "file": (
                        "lossless.m4a",
                        (FIXTURES / "hello.m4a").read_bytes(),
                        "audio/mp4",
                    )
                },
                cookies={"access_token": token},
            )
        assert r.status_code == 422, r.text
        assert "Apple Lossless" in r.json()["detail"]
    finally:
        async with async_session_factory() as session:
            found = (
                await session.exec(select(User).where(User.email == email))
            ).first()
            if found is not None:
                await session.delete(found)
            await session.commit()

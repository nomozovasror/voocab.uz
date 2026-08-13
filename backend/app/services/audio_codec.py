"""Whether a browser will be able to play what was just uploaded.

The upload endpoint used to check the filename's extension and nothing else.
But an extension names a *container*, not a codec, and ``.m4a`` is the one
that matters: almost every m4a in the world holds AAC, which every browser
plays, and some hold ALAC (Apple Lossless), which none of them do. Both are
".m4a", both pass an extension check, and both transcribe fine server-side —
so the material came out looking healthy, with a transcript and segments,
and only the player was dead. The author could not hear the recording, could
not link an answer to the moment it was said, and nothing stopped them
publishing it for candidates to meet the same dead player.

So the container is opened far enough to read which codec is inside, and the
ones browsers can't decode are refused at the door with a message that says
what to do about it.

Only the MP4 family is inspected, because it is the only one of the accepted
extensions where the answer is in doubt: .mp3 is MPEG audio, .wav is
overwhelmingly PCM, and .ogg/.webm carry Vorbis or Opus — all of them
playable, all of them everywhere. Adding a codec inspection for those would
be answering a question nobody asked.

Nothing here shells out to ffprobe. The boxes needed are a dozen lines of
structure at the front of the file, the check runs on every upload, and a
subprocess (plus an ffmpeg the deploy has to guarantee) is a lot to take on
for a fourcc.
"""

import struct

#: MP4 audio sample entries every current browser decodes. `mp4a` is AAC —
#: and also MP3-in-MP4, which is equally fine. Opus and FLAC in MP4 are
#: rarer but supported, and refusing them would be refusing something that
#: works.
PLAYABLE_MP4_AUDIO = {"mp4a", "Opus", "fLaC"}

#: The ones worth naming when refusing, because the author can act on it.
CODEC_NAMES = {
    "alac": "Apple Lossless (ALAC)",
    "ac-3": "Dolby Digital (AC-3)",
    "ec-3": "Dolby Digital Plus (E-AC-3)",
    "dtsc": "DTS",
    "samr": "AMR",
}

#: Boxes that hold other boxes on the path down to the sample description.
#: Anything not listed is skipped over whole, which is what keeps this from
#: wandering into the media data.
_CONTAINERS = {"moov", "trak", "mdia", "minf", "stbl"}

_MP4_EXTENSIONS = {".m4a", ".mp4"}


def _boxes(data: bytes, start: int, end: int):
    """The boxes directly inside ``data[start:end]``, as (type, body slice).

    Written defensively on purpose: this is the first thing that touches an
    uploaded file, so a truncated or hostile one has to come out as "no
    boxes" rather than an exception or a loop that never ends.
    """
    offset = start
    while offset + 8 <= end:
        (size,) = struct.unpack_from(">I", data, offset)
        box_type = data[offset + 4 : offset + 8].decode("latin-1")
        header = 8
        if size == 1:
            # 64-bit largesize lives after the type.
            if offset + 16 > end:
                return
            (size,) = struct.unpack_from(">Q", data, offset + 8)
            header = 16
        elif size == 0:
            # "to the end of the file", which is a valid last box.
            size = end - offset
        if size < header or offset + size > end:
            return
        yield box_type, offset + header, offset + size
        offset += size


def _find(data: bytes, start: int, end: int, wanted: str):
    """The first ``wanted`` box anywhere under this range, depth-first."""
    for box_type, body_start, body_end in _boxes(data, start, end):
        if box_type == wanted:
            return body_start, body_end
        if box_type in _CONTAINERS:
            found = _find(data, body_start, body_end, wanted)
            if found is not None:
                return found
    return None


def _handler_type(data: bytes, trak_start: int, trak_end: int) -> str | None:
    """What kind of track this is — "soun" for audio, "vide" for video."""
    hdlr = _find(data, trak_start, trak_end, "hdlr")
    if hdlr is None:
        return None
    body_start, body_end = hdlr
    # FullBox: version+flags, then pre_defined, then the handler type.
    if body_start + 12 > body_end:
        return None
    return data[body_start + 8 : body_start + 12].decode("latin-1")


def _sample_entry(data: bytes, start: int, end: int) -> str | None:
    """The codec fourcc of the first sample entry in this track's stsd."""
    stsd = _find(data, start, end, "stsd")
    if stsd is None:
        return None
    body_start, body_end = stsd
    # FullBox: version+flags (4), entry_count (4), then the first entry,
    # which is itself a box: size (4), type (4).
    if body_start + 16 > body_end:
        return None
    return data[body_start + 12 : body_start + 16].decode("latin-1")


def mp4_audio_codec(data: bytes) -> str | None:
    """The codec of the audio track in an MP4/M4A, or None if it can't be
    read.

    The AUDIO track specifically: a ``.mp4`` may well open with a video
    track, and reading the first sample entry it finds would report `avc1`
    for a file whose audio is perfectly ordinary AAC.
    """
    end = len(data)
    moov = _find(data, 0, end, "moov")
    if moov is None:
        return None
    moov_start, moov_end = moov

    for box_type, trak_start, trak_end in _boxes(data, moov_start, moov_end):
        if box_type != "trak":
            continue
        if _handler_type(data, trak_start, trak_end) != "soun":
            continue
        return _sample_entry(data, trak_start, trak_end)
    return None


def unplayable_reason(extension: str, data: bytes) -> str | None:
    """Why a browser won't play this, phrased for the author — or None when
    there is no reason to think it won't.

    Fails open, deliberately. A file this can't make sense of is far more
    likely to be a container shape the reader above doesn't know than a
    genuinely broken upload, and refusing those would be refusing work that
    plays perfectly well. What is caught is the case that is actually known
    to be bad, which is what it is here to catch.
    """
    if extension not in _MP4_EXTENSIONS:
        return None

    codec = mp4_audio_codec(data)
    if codec is None or codec in PLAYABLE_MP4_AUDIO:
        return None

    named = CODEC_NAMES.get(codec, codec)
    return (
        f"This {extension} holds {named} audio, which browsers can't play — "
        "the recording would be silent for you and for anyone taking the "
        "material. Export it as MP3, or as an .m4a with AAC audio, and "
        "upload that."
    )

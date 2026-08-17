"""What was actually uploaded, and how big it is — read from the bytes.

Two things the image pipeline needs before it will store anything, and both of
them come from the file's own header rather than from its name:

* **what format it is.** The filename is a claim, and here it is one worth
  distrusting. An ``.svg`` renamed to ``.png`` passes any extension check and
  is then served from our own origin as a document full of executable
  ``<script>``; a ``.png`` that is really a JPEG is harmless but still means
  the stored key lies about its contents. Sniffing the header answers both at
  once: a file is a PNG, a JPEG or a WebP because it starts like one, and
  everything else — SVG included — has no answer here and is refused.
* **its dimensions.** A map is drawn above the questions it labels, and the
  page has to reserve the right box for it before the bytes arrive, or every
  take begins with the questions jumping down the screen. The author's browser
  knows the size; so should we, rather than trusting a number the client sends.

The headers are a few dozen bytes at the front of the file, so nothing here
shells out or decodes an image. That also means no Pillow: the one thing it
would add is decoding, and decoding an untrusted upload is the risk this
avoids having.

Unlike :mod:`app.services.audio_codec`, which fails OPEN — a container it
can't parse is far likelier to be a shape its reader doesn't know than a
broken file, and refusing those would refuse work that plays fine — this
fails CLOSED. The set of formats is three and they are all read here in full,
so bytes this can't make sense of are not one of the three, which is exactly
the case to refuse.
"""

import struct

#: What a sniffed format is stored and served as.
PNG = "image/png"
JPEG = "image/jpeg"
WEBP = "image/webp"

#: What the author is told they can upload, in their words.
FORMAT_NAMES = "PNG, JPEG or WebP"


def read_image(data: bytes) -> tuple[str, int, int] | None:
    """``(mime_type, width, height)`` for one of the three formats we accept,
    or ``None`` when the bytes aren't any of them.

    ``None`` covers both "not an image at all" and "an image of a kind we
    don't take" on purpose: the caller's answer to the author is the same
    sentence either way, and telling an author their SVG was recognised but
    declined invites them to look for the setting that would allow it.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        size = _png_size(data)
        return (PNG, *size) if size else None
    if data.startswith(b"\xff\xd8\xff"):
        size = _jpeg_size(data)
        return (JPEG, *size) if size else None
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        size = _webp_size(data)
        return (WEBP, *size) if size else None
    return None


def _png_size(data: bytes) -> tuple[int, int] | None:
    """PNG: the first chunk after the signature must be IHDR, and it opens
    with the two dimensions as big-endian 32-bit ints."""
    if len(data) < 24 or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack_from(">II", data, 16)
    return _sane(width, height)


#: The JPEG markers that introduce a frame, whichever coding it uses —
#: baseline, progressive, arithmetic, lossless. All of them carry the
#: dimensions in the same place. 0xC4 (DHT), 0xC8 (JPG) and 0xCC (DAC) share
#: the range without being frames, which is why this is a set and not a span.
_SOF_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    """JPEG: a chain of marker segments, walked until one of them is a frame
    header. Every segment declares its own length, so this skips over the
    thumbnails, colour profiles and EXIF blocks that come first without
    looking inside any of them.

    Written to end rather than to keep reading on anything unexpected: this
    walks a file nobody has vouched for, so a length that would step backwards
    or past the end is a file we have no size for, not one to guess at.
    """
    offset = 2  # past the SOI
    end = len(data)
    while offset + 4 <= end:
        if data[offset] != 0xFF:
            return None
        marker = data[offset + 1]
        # Fill bytes: any number of 0xFF may pad the gap before a marker.
        if marker == 0xFF:
            offset += 1
            continue
        # Standalone markers, carrying no length and no payload.
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            offset += 2
            continue
        (length,) = struct.unpack_from(">H", data, offset + 2)
        if length < 2 or offset + 2 + length > end:
            return None
        if marker in _SOF_MARKERS:
            # length(2), precision(1), height(2), width(2) — height first.
            if length < 7:
                return None
            height, width = struct.unpack_from(">HH", data, offset + 5)
            return _sane(width, height)
        offset += 2 + length
    return None


def _webp_size(data: bytes) -> tuple[int, int] | None:
    """WebP: a RIFF container whose first chunk says which of the three
    encodings it is. All three are read, because which one an author's export
    produced is not something they chose or can see — refusing a lossy WebP
    while taking a lossless one would look like refusing WebP at random.
    """
    if len(data) < 16:
        return None
    chunk = data[12:16]

    if chunk == b"VP8X":
        # Extended format: flags(4), then the canvas size as two 24-bit
        # little-endian values, each stored one less than it is.
        if len(data) < 30:
            return None
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return _sane(width, height)

    if chunk == b"VP8 ":
        # Lossy: chunk header(8), frame tag(3), a fixed start code, then the
        # two dimensions as 14-bit little-endian values (the top two bits of
        # each are a scaling hint, not size).
        if len(data) < 30 or data[23:26] != b"\x9d\x01\x2a":
            return None
        width = struct.unpack_from("<H", data, 26)[0] & 0x3FFF
        height = struct.unpack_from("<H", data, 28)[0] & 0x3FFF
        return _sane(width, height)

    if chunk == b"VP8L":
        # Lossless: a signature byte, then 28 bits packed as width-1 (14) and
        # height-1 (14), little-endian.
        if len(data) < 25 or data[20] != 0x2F:
            return None
        (bits,) = struct.unpack_from("<I", data, 21)
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return _sane(width, height)

    return None


def _sane(width: int, height: int) -> tuple[int, int] | None:
    """A header claiming a zero or negative side is a header we didn't read
    correctly. How LARGE a picture is allowed to be is a different question,
    and a policy one — it lives with the upload endpoint, next to the size
    cap."""
    return (width, height) if width > 0 and height > 0 else None

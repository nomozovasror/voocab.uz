"""Unit tests for app/services/image_codec.py — no DB, no HTTP.

Every fixture here is a header built by hand, byte by byte, rather than a real
file produced by a real encoder. That is deliberate twice over: the reader's
whole job is to walk a header it has not been promised anything about, so the
interesting inputs are the malformed ones no encoder would emit; and a
committed .png binary would be a fixture nobody can read or adjust when this
changes.
"""

import struct

import pytest

from app.services import image_codec

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def png(width: int, height: int) -> bytes:
    """A PNG up to the end of IHDR, which is all the reader looks at."""
    ihdr = b"IHDR" + struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    return PNG_MAGIC + struct.pack(">I", 13) + ihdr + b"\x00\x00\x00\x00"


def jpeg(width: int, height: int, *, marker: int = 0xC0, preamble: bytes = b"") -> bytes:
    """A JPEG whose frame header sits behind ``preamble`` — the APP/EXIF/ICC
    segments a real file puts in front of it."""
    sof = (
        bytes([0xFF, marker])
        + struct.pack(">H", 17)
        + b"\x08"
        + struct.pack(">HH", height, width)  # height first, per the spec
        + b"\x03" + b"\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    )
    return b"\xff\xd8" + preamble + sof + b"\xff\xd9"


def app0(payload: bytes = b"JFIF\x00\x01\x02\x00\x00\x01\x00\x01\x00\x00") -> bytes:
    return b"\xff\xe0" + struct.pack(">H", len(payload) + 2) + payload


def webp_vp8x(width: int, height: int) -> bytes:
    body = (
        b"VP8X"
        + struct.pack("<I", 10)
        + b"\x00\x00\x00\x00"
        + (width - 1).to_bytes(3, "little")
        + (height - 1).to_bytes(3, "little")
    )
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + body


def webp_vp8(width: int, height: int) -> bytes:
    frame = (
        b"\x00\x00\x00"  # frame tag
        + b"\x9d\x01\x2a"  # start code
        + struct.pack("<HH", width, height)
        + b"\x00\x00"
    )
    body = b"VP8 " + struct.pack("<I", len(frame)) + frame
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + body


def webp_vp8l(width: int, height: int) -> bytes:
    bits = (width - 1) | ((height - 1) << 14)
    body = b"VP8L" + struct.pack("<I", 5) + b"\x2f" + struct.pack("<I", bits)
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + body


# --- the three formats we take ---------------------------------------------


def test_png_dimensions_come_from_ihdr() -> None:
    assert image_codec.read_image(png(1240, 874)) == (image_codec.PNG, 1240, 874)


def test_jpeg_dimensions_come_from_the_frame_header() -> None:
    assert image_codec.read_image(jpeg(800, 600)) == (image_codec.JPEG, 800, 600)


def test_jpeg_frame_header_is_found_behind_the_segments_in_front_of_it() -> None:
    """A real JPEG opens with APP0/EXIF/ICC blocks. Each declares its length,
    and skipping them by that length — rather than scanning for the next 0xFF,
    which appears inside payloads all the time — is what gets to the frame."""
    noisy = app0() + app0(b"Exif\x00\x00" + b"\xff\xc0" * 8)
    assert image_codec.read_image(jpeg(1024, 768, preamble=noisy)) == (
        image_codec.JPEG,
        1024,
        768,
    )


@pytest.mark.parametrize("marker", [0xC0, 0xC1, 0xC2, 0xC9, 0xCF])
def test_every_kind_of_jpeg_frame_carries_its_size_the_same_way(marker: int) -> None:
    """Baseline, extended, progressive, arithmetic, lossless. Which one an
    author's export produced is not something they chose or can see."""
    assert image_codec.read_image(jpeg(640, 480, marker=marker)) == (
        image_codec.JPEG,
        640,
        480,
    )


@pytest.mark.parametrize("marker", [0xC4, 0xC8, 0xCC])
def test_the_non_frame_markers_in_the_frame_range_are_skipped(marker: int) -> None:
    """DHT, JPG and DAC share the 0xC0-0xCF range without being frames. Read
    as one, a Huffman table's first bytes become a picture's dimensions."""
    data = jpeg(640, 480, preamble=bytes([0xFF, marker]) + struct.pack(">H", 6) + b"junk")
    assert image_codec.read_image(data) == (image_codec.JPEG, 640, 480)


@pytest.mark.parametrize(
    "build", [webp_vp8x, webp_vp8, webp_vp8l], ids=["extended", "lossy", "lossless"]
)
def test_all_three_webp_encodings_are_read(build) -> None:
    assert image_codec.read_image(build(1600, 900)) == (image_codec.WEBP, 1600, 900)


# --- everything else is refused --------------------------------------------


def test_svg_is_not_a_picture_we_can_use() -> None:
    """The case the whole sniffing approach exists for: markup renaming itself
    .png, which would then be served from our own origin."""
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    assert image_codec.read_image(svg) is None


def test_a_gif_is_recognisably_an_image_and_still_refused() -> None:
    """Refused with the same answer as anything else, because the author's next
    step is the same: export it as one of the three."""
    assert image_codec.read_image(b"GIF89a" + b"\x10\x00\x10\x00") is None


def test_audio_bytes_are_not_an_image() -> None:
    assert image_codec.read_image(b"ID3\x03\x00\x00\x00\x00\x00\x00mp3 data") is None


def test_empty_bytes_are_not_an_image() -> None:
    assert image_codec.read_image(b"") is None


def test_a_png_signature_with_nothing_behind_it_fails_closed() -> None:
    assert image_codec.read_image(PNG_MAGIC) is None
    assert image_codec.read_image(PNG_MAGIC + struct.pack(">I", 13) + b"IHD") is None


def test_a_png_whose_first_chunk_is_not_ihdr_fails_closed() -> None:
    """IHDR is required to come first. A file where it doesn't is not one to
    go hunting through — the offsets this reads would be someone else's."""
    data = PNG_MAGIC + struct.pack(">I", 4) + b"tEXtnote" + png(10, 10)[8:]
    assert image_codec.read_image(data) is None


def test_a_zero_side_is_not_a_size() -> None:
    assert image_codec.read_image(png(0, 500)) is None
    assert image_codec.read_image(png(500, 0)) is None


def test_a_jpeg_with_no_frame_header_fails_closed() -> None:
    assert image_codec.read_image(b"\xff\xd8" + app0() + b"\xff\xd9") is None


def test_a_jpeg_segment_length_running_past_the_end_fails_closed() -> None:
    """A length that would step outside the file is a file we have no size
    for, not one to guess at."""
    data = b"\xff\xd8\xff\xe0" + struct.pack(">H", 9999) + b"short"
    assert image_codec.read_image(data) is None


def test_a_jpeg_segment_length_of_zero_cannot_loop_forever() -> None:
    """A length must count its own two bytes, so anything below 2 would leave
    the walker standing still. This test is here to fail by hanging."""
    data = b"\xff\xd8\xff\xe0" + struct.pack(">H", 0) + b"\xff\xc0" + b"\x00" * 20
    assert image_codec.read_image(data) is None


def test_padding_before_a_jpeg_marker_is_allowed() -> None:
    """Any number of 0xFF bytes may fill the gap before a marker."""
    assert image_codec.read_image(jpeg(320, 240, preamble=b"\xff\xff\xff")) == (
        image_codec.JPEG,
        320,
        240,
    )


def test_a_webp_riff_wrapper_around_something_else_fails_closed() -> None:
    """RIFF also wraps WAV. The four bytes at offset 8 are what separate the
    two, and a WAV read as a WebP would come out with a size."""
    wav = b"RIFF" + struct.pack("<I", 36) + b"WAVEfmt " + b"\x00" * 20
    assert image_codec.read_image(wav) is None


def test_a_webp_chunk_we_do_not_know_fails_closed() -> None:
    body = b"ANIM" + struct.pack("<I", 6) + b"\x00" * 6
    data = b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + body
    assert image_codec.read_image(data) is None


def test_a_lossy_webp_without_its_start_code_fails_closed() -> None:
    data = bytearray(webp_vp8(100, 100))
    data[23] = 0x00
    assert image_codec.read_image(bytes(data)) is None


def test_a_truncated_webp_header_fails_closed() -> None:
    for build in (webp_vp8x, webp_vp8, webp_vp8l):
        full = build(800, 600)
        assert image_codec.read_image(full[: len(full) - 4]) is None


def test_a_very_large_picture_still_reports_its_size() -> None:
    """The reader's answer is what the header says. Whether a size that big is
    ALLOWED is policy, and lives with the upload endpoint — so a 30000px PNG
    must come back with its dimensions here, not as "not an image"."""
    assert image_codec.read_image(png(30000, 30000)) == (image_codec.PNG, 30000, 30000)

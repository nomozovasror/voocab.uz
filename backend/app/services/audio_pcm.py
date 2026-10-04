"""PCM in, PCM out: cutting a clip, encoding it, laying clips end to end.

Everything the audio layer does to sound lives here and is synchronous and
pure -- bytes or arrays in, bytes or arrays out, no database, no storage -- so
the callers (`word_clips`, `tts`) decide where it runs (a worker thread, the
seed script) and the tests can drive it on a generated tone.

One working format. Every clip and every render the layer stores is **24 kHz
mono AAC in an MP4 container** (`.m4a`): Kokoro's native rate, so the TTS side
is never resampled, and ample for speech (12 kHz of bandwidth). Material
recordings come in at 44.1/48 kHz stereo; they are resampled DOWN on the way
in, which is what lets a clip and a synthesised word be laid in one file
without a rate or channel mismatch, and what makes the files small (a one
second word is ~3 KB). FFmpeg's native ``aac`` encoder is used because it is
the one that is always compiled in -- ``libfdk_aac`` and friends are not
guaranteed in PyAV's bundled build.

Decoding goes through PyAV (``av``; binary wheels bundle FFmpeg), so there is
no ``ffmpeg`` executable anywhere in the stack.

## Loudness

A word cut from a lecture and a word Kokoro synthesised differ by many dB,
and One file holding both (an On the go item) must not make the learner reach
for the volume between the definition and the answer. :func:`normalise_rms`
brings a piece to :data:`TARGET_RMS_DBFS` -- RMS, not peak, because RMS tracks
perceived loudness of speech far better than a single spike does -- with a
ceiling on the peak so a quiet clip with one sharp consonant is not driven
into clipping to reach the target. It is applied to every artefact when it is
made AND again when pieces are composed, which is harmless: a piece already at
the target gets a gain of ~1.
"""

import io
import os
import tempfile
from fractions import Fraction

import av
import numpy as np

#: The one rate everything is stored at (Kokoro's own).
SAMPLE_RATE = 24_000

#: Where speech is levelled to. -20 dBFS RMS is conventional for spoken-word
#: audio (podcasts sit around -16 to -20) and leaves 20 dB of headroom.
TARGET_RMS_DBFS = -20.0

#: The loudest a sample may be after levelling (just under full scale).
PEAK_CEILING = 0.97

#: Below this RMS a piece is treated as silence and left alone: levelling
#: digital silence would divide by ~zero and amplify the encoder's noise floor
#: into something audible.
_SILENCE_RMS = 1e-5


def decode_range(
    data: bytes, start_ms: int | None = None, end_ms: int | None = None
) -> np.ndarray:
    """``data`` (any container/codec PyAV reads) as float32 mono at
    :data:`SAMPLE_RATE`, optionally only ``start_ms``..``end_ms``.

    A range is reached by SEEKING (to a second before ``start_ms``, then
    decoding forward and trimming to the sample), not by decoding the whole
    recording and slicing: a clip is cut from a thirty-minute file, and the
    cost of a cut should be the cost of the clip. The trim is by the decoded
    frames' own timestamps, so a keyframe-granular seek never moves the cut.
    """
    with av.open(io.BytesIO(data)) as container:
        stream = container.streams.audio[0]
        if start_ms is not None and start_ms > 1000:
            # Seek a little early: the demuxer lands on a packet at or before
            # the target, and an MP3/AAC decoder needs a frame or two of
            # lead-in before its output is exact.
            container.seek(
                int((start_ms - 1000) * 1000), backward=True, any_frame=False
            )
        resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
        chunks: list[np.ndarray] = []
        first_time: float | None = None
        for frame in container.decode(stream):
            if first_time is None:
                first_time = float(frame.pts * stream.time_base) if frame.pts is not None else 0.0
            frame_time = float(frame.pts * stream.time_base) if frame.pts is not None else None
            if end_ms is not None and frame_time is not None and frame_time * 1000 > end_ms + 500:
                break
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):
            chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    samples = np.concatenate(chunks).astype(np.float32, copy=False)
    origin_ms = (first_time or 0.0) * 1000.0
    lo = 0 if start_ms is None else max(0, round((start_ms - origin_ms) * SAMPLE_RATE / 1000))
    hi = len(samples) if end_ms is None else max(lo, round((end_ms - origin_ms) * SAMPLE_RATE / 1000))
    return samples[lo:hi]


def encode_m4a(samples: np.ndarray) -> bytes:
    """``samples`` (float32 mono at :data:`SAMPLE_RATE`) as AAC in MP4, moov
    atom first (``faststart``) so a browser can begin playing before the file
    has arrived -- these are small files fetched on demand, and the default
    layout (index at the END) would make every play wait for the whole body."""
    # `faststart` rewrites the file once the index is known, which FFmpeg does
    # by re-opening it by NAME -- an in-memory buffer has none, so the encode
    # goes through a real temporary file.
    with tempfile.TemporaryDirectory() as workdir:
        path = os.path.join(workdir, "out.m4a")
        _encode_to(path, samples)
        with open(path, "rb") as handle:
            return handle.read()


def _encode_to(path: str, samples: np.ndarray) -> None:
    with av.open(path, mode="w", format="mp4", options={"movflags": "faststart"}) as container:
        stream = container.add_stream("aac", rate=SAMPLE_RATE, layout="mono")
        stream.bit_rate = 64_000
        pcm = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
        # Whole-second slabs keep each frame small; PyAV re-frames them to the
        # encoder's own size (1024 samples for AAC).
        step = SAMPLE_RATE
        pts = 0
        for offset in range(0, max(len(pcm), 1), step):
            piece = pcm[offset : offset + step]
            if len(piece) == 0:
                break
            frame = av.AudioFrame.from_ndarray(piece.reshape(1, -1), format="flt", layout="mono")
            frame.sample_rate = SAMPLE_RATE
            frame.pts = pts
            frame.time_base = Fraction(1, SAMPLE_RATE)
            pts += len(piece)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)


def duration_ms(samples: np.ndarray) -> int:
    return round(len(samples) * 1000 / SAMPLE_RATE)


def silence(ms: int) -> np.ndarray:
    return np.zeros(round(ms * SAMPLE_RATE / 1000), dtype=np.float32)


def rms_dbfs(samples: np.ndarray) -> float:
    """RMS level in dB relative to full scale; ``-inf`` for digital silence."""
    if len(samples) == 0:
        return float("-inf")
    rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    return 20.0 * np.log10(rms) if rms > 0 else float("-inf")


def normalise_rms(
    samples: np.ndarray,
    target_dbfs: float = TARGET_RMS_DBFS,
    peak_ceiling: float = PEAK_CEILING,
) -> np.ndarray:
    """``samples`` scaled to ``target_dbfs`` RMS, the peak held under
    ``peak_ceiling``. Silence is returned unchanged (see :data:`_SILENCE_RMS`).

    The peak ceiling wins over the target: a piece that cannot reach the
    target without clipping ends up quieter than it, which is the right way
    round -- a little quiet is a setting on the phone, clipping is damage."""
    if len(samples) == 0:
        return samples.astype(np.float32, copy=False)
    rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    if rms < _SILENCE_RMS:
        return samples.astype(np.float32, copy=False)
    gain = (10.0 ** (target_dbfs / 20.0)) / rms
    peak = float(np.max(np.abs(samples)))
    if peak * gain > peak_ceiling:
        gain = peak_ceiling / peak
    return (samples * gain).astype(np.float32, copy=False)


def concat(*pieces: np.ndarray) -> np.ndarray:
    """The pieces end to end (empty ones are fine)."""
    nonempty = [p.astype(np.float32, copy=False) for p in pieces if len(p)]
    return np.concatenate(nonempty) if nonempty else np.zeros(0, dtype=np.float32)

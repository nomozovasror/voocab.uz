"""PyAV for real, on generated tones: decode, seek, encode, level."""

from fractions import Fraction
from types import SimpleNamespace

import numpy as np
import pytest

from app.services import audio_pcm
from tests.audio_helpers import encode_mp3, tone

SR = audio_pcm.SAMPLE_RATE


def _dominant_hz(samples: np.ndarray) -> float:
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
    return float(np.argmax(spectrum) * SR / len(samples))


def test_m4a_round_trip_keeps_duration_pitch_and_level() -> None:
    source = tone(2000, freq=500, amp=0.2)
    data = audio_pcm.encode_m4a(source)
    assert data[4:8] == b"ftyp"  # an MP4 container
    # `faststart`: the index (moov) is before the audio (mdat).
    assert data.index(b"moov") < data.index(b"mdat")
    back = audio_pcm.decode_range(data)
    # AAC adds a frame or two of padding; never more than ~60 ms.
    assert abs(audio_pcm.duration_ms(back) - 2000) < 60
    assert abs(_dominant_hz(back[SR // 2 : SR // 2 + 8192]) - 500) < 10
    assert abs(audio_pcm.rms_dbfs(back) - audio_pcm.rms_dbfs(source)) < 1.0


def test_decode_range_cuts_the_window_asked_for() -> None:
    # Three seconds, a different pitch each second.
    source = np.concatenate([tone(1000, 300), tone(1000, 600), tone(1000, 900)])
    data = audio_pcm.encode_m4a(source)
    middle = audio_pcm.decode_range(data, 1000, 2000)
    assert abs(audio_pcm.duration_ms(middle) - 1000) <= 5
    assert abs(_dominant_hz(middle[2000:10000]) - 600) < 15
    tail = audio_pcm.decode_range(data, 2200, 2800)
    assert abs(audio_pcm.duration_ms(tail) - 600) <= 5
    assert abs(_dominant_hz(tail[1000:9000]) - 900) < 15


def test_a_range_past_the_end_is_empty_not_an_error() -> None:
    data = audio_pcm.encode_m4a(tone(500))
    assert len(audio_pcm.decode_range(data, 5000, 6000)) == 0


def test_normalise_rms_levels_quiet_and_loud_pieces_to_one_target() -> None:
    quiet, loud = tone(500, amp=0.03), tone(500, amp=0.5)  # -37 dBFS needs +17 dB: inside the cap
    for piece in (quiet, loud):
        out = audio_pcm.normalise_rms(piece)
        assert abs(audio_pcm.rms_dbfs(out) - audio_pcm.TARGET_RMS_DBFS) < 0.1
    # Levelling twice is a no-op: it is applied at make time AND at compose time.
    once = audio_pcm.normalise_rms(quiet)
    assert np.allclose(audio_pcm.normalise_rms(once), once, atol=1e-6)


def test_the_peak_ceiling_beats_the_target() -> None:
    # Mostly silence with one sharp spike: reaching -20 dBFS RMS would clip.
    spiky = np.zeros(SR, dtype=np.float32)
    spiky[1000] = 0.9
    out = audio_pcm.normalise_rms(spiky)
    assert float(np.max(np.abs(out))) <= audio_pcm.PEAK_CEILING + 1e-6


def test_silence_is_left_alone_and_concat_skips_empties() -> None:
    silent = audio_pcm.silence(100)
    assert float(np.max(np.abs(audio_pcm.normalise_rms(silent)))) == 0.0
    assert audio_pcm.duration_ms(audio_pcm.silence(1500)) == 1500
    joined = audio_pcm.concat(tone(100), np.zeros(0, dtype=np.float32), tone(200))
    assert audio_pcm.duration_ms(joined) == 300


def test_the_gain_is_capped_so_a_near_silent_piece_is_not_blown_up_into_noise() -> None:
    hiss = tone(500, amp=0.002)  # -57 dBFS RMS: would need +37 dB to reach the target
    out = audio_pcm.normalise_rms(hiss)
    gained = audio_pcm.rms_dbfs(out) - audio_pcm.rms_dbfs(hiss)
    assert abs(gained - audio_pcm.MAX_GAIN_DB) < 0.1
    assert audio_pcm.rms_dbfs(out) < audio_pcm.TARGET_RMS_DBFS - 15
    # A piece inside the cap still reaches the target exactly.
    ok = tone(500, amp=0.03)
    assert abs(audio_pcm.rms_dbfs(audio_pcm.normalise_rms(ok)) - audio_pcm.TARGET_RMS_DBFS) < 0.1


# --- cutting from a real recording: 44.1 kHz stereo MP3, well past a minute -------

_RATE = 44_100


@pytest.fixture(scope="module")
def long_mp3() -> bytes:
    """75 s of a quiet 220 Hz hum with a loud 1 kHz burst at exactly
    65.000-65.500 s (left only: the right channel stays hum)."""
    n = _RATE * 75
    t = np.arange(n) / _RATE
    left = (0.05 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    right = left.copy()
    a, b = 65 * _RATE, round(65.5 * _RATE)
    left[a:b] = (0.3 * np.sin(2 * np.pi * 1000 * t[a:b])).astype(np.float32)
    return encode_mp3(left, right, rate=_RATE)


def _burst_ms(samples: np.ndarray) -> tuple[float, float]:
    loud = np.flatnonzero(np.abs(samples) > 0.1)
    return loud[0] * 1000 / SR, loud[-1] * 1000 / SR


def test_a_cut_far_past_a_minute_lands_on_the_audio_asked_for(long_mp3: bytes) -> None:
    # The window 64.8-65.8 s holds the burst from 200 to 700 ms into it.
    cut = audio_pcm.decode_range(long_mp3, 64_800, 65_800)
    assert abs(audio_pcm.duration_ms(cut) - 1000) <= 5
    first, last = _burst_ms(cut)
    # An MP3 stream starts ~25 ms in (encoder delay); the cut must NOT inherit it.
    assert abs(first - 200) < 10 and abs(last - 700) < 10
    assert abs(_dominant_hz(cut[SR // 4 : SR // 4 + 8192]) - 1000) < 15


def test_a_seeked_cut_matches_the_same_range_of_a_full_decode(long_mp3: bytes) -> None:
    full = audio_pcm.decode_range(long_mp3)
    cut = audio_pcm.decode_range(long_mp3, 64_000, 66_000)
    lo = 64_000 * SR // 1000
    expected = full[lo : lo + len(cut)]
    assert len(cut) == pytest.approx(2 * SR, abs=SR // 200)
    assert float(np.max(np.abs(cut - expected))) < 0.02


def test_a_cut_just_after_the_seek_threshold_and_at_the_very_start(long_mp3: bytes) -> None:
    # 1.5 s: seeks (> 1 s) and lands close to the file's start.
    near = audio_pcm.decode_range(long_mp3, 1_500, 2_000)
    assert abs(audio_pcm.duration_ms(near) - 500) <= 5
    # 0.5 s: no seek at all.
    top = audio_pcm.decode_range(long_mp3, 500, 1_000)
    assert abs(audio_pcm.duration_ms(top) - 500) <= 5


def test_a_first_frame_with_no_timestamp_after_a_seek_raises_instead_of_guessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Container:
        streams = SimpleNamespace(
            audio=[SimpleNamespace(time_base=Fraction(1, 1000), start_time=0)]
        )

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def seek(self, *args, **kwargs) -> None:
            pass

        def decode(self, stream):
            yield SimpleNamespace(pts=None)

    monkeypatch.setattr(audio_pcm.av, "open", lambda *a, **k: Container())
    with pytest.raises(ValueError, match="no timestamp"):
        audio_pcm.decode_range(b"x", 5_000, 6_000)

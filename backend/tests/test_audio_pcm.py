"""PyAV for real, on generated tones: decode, encode, level."""

import numpy as np
import pytest

from app.services import audio_pcm
from tests.audio_helpers import tone

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
    back = audio_pcm.decode(data)
    # AAC adds a frame or two of padding; never more than ~60 ms.
    assert abs(audio_pcm.duration_ms(back) - 2000) < 60
    assert abs(_dominant_hz(back[SR // 2 : SR // 2 + 8192]) - 500) < 10
    assert abs(audio_pcm.rms_dbfs(back) - audio_pcm.rms_dbfs(source)) < 1.0


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

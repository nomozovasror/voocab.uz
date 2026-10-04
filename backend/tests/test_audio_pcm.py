"""PyAV for real, on generated tones: decode, seek, encode, level."""

import numpy as np

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
    quiet, loud = tone(500, amp=0.01), tone(500, amp=0.5)
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

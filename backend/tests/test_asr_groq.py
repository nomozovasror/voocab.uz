"""Offline tests for app.services.asr — no network, no DB, no live API key.

Uses httpx.MockTransport to fake the Groq HTTP endpoint: verifies both the
outgoing request shape (model/language/granularity params) and that a
realistic verbose_json fixture (segments + top-level word timings, seconds as
floats) normalizes into non-empty segments with integer-ms word timings and
correct order_index.
"""

import json
from pathlib import Path

import httpx
import pytest

from app.services.asr import (
    GroqASR,
    TranscriptResult,
    WordTiming,
    _bucket_words_into_segments,
    normalize_groq_response,
)

GROQ_FIXTURE: dict = {
    "text": " Hello world. This is a test.",
    "language": "en",
    "duration": 3.5,
    "segments": [
        {
            "id": 0,
            "seek": 0,
            "start": 0.0,
            "end": 1.8,
            "text": " Hello world.",
            "tokens": [1, 2, 3],
            "temperature": 0.0,
            "avg_logprob": -0.1,
            "compression_ratio": 1.2,
            "no_speech_prob": 0.01,
        },
        {
            "id": 1,
            "seek": 180,
            "start": 1.8,
            "end": 3.5,
            "text": " This is a test.",
            "tokens": [4, 5, 6],
            "temperature": 0.0,
            "avg_logprob": -0.1,
            "compression_ratio": 1.2,
            "no_speech_prob": 0.01,
        },
    ],
    # Top-level, NOT nested per-segment — this is the actual Groq/OpenAI
    # verbose_json shape when timestamp_granularities[]=word is requested.
    "words": [
        {"word": "Hello", "start": 0.0, "end": 0.5},
        {"word": "world", "start": 0.6, "end": 1.0},
        {"word": "This", "start": 1.8, "end": 2.0},
        {"word": "is", "start": 2.0, "end": 2.2},
        {"word": "a", "start": 2.2, "end": 2.3},
        {"word": "test", "start": 2.3, "end": 2.6},
    ],
}


def test_normalize_groq_response_shape() -> None:
    result = normalize_groq_response(GROQ_FIXTURE)

    assert isinstance(result, TranscriptResult)
    assert result.duration_ms == 3500  # 3.5s -> ms

    assert len(result.segments) == 2

    seg0, seg1 = result.segments
    assert seg0.order_index == 0
    assert seg1.order_index == 1

    # integer ms, not float seconds
    assert seg0.start_ms == 0
    assert seg0.end_ms == 1800
    assert seg1.start_ms == 1800
    assert seg1.end_ms == 3500

    assert seg0.text == "Hello world."
    assert seg1.text == "This is a test."

    # every segment got non-empty word-level timing, correctly bucketed by
    # time range from the top-level words[] array
    assert seg0.words, "segment 0 must have word-level timings"
    assert seg1.words, "segment 1 must have word-level timings"
    assert [w.word for w in seg0.words] == ["Hello", "world"]
    assert [w.word for w in seg1.words] == ["This", "is", "a", "test"]

    for w in seg0.words + seg1.words:
        assert isinstance(w.start_ms, int)
        assert isinstance(w.end_ms, int)
        assert w.end_ms >= w.start_ms

    # spot check one word's ms conversion
    assert seg0.words[0].start_ms == 0
    assert seg0.words[0].end_ms == 500


def test_normalize_groq_response_nested_words_preferred() -> None:
    """If a segment already carries nested words, use those directly rather
    than re-deriving from a top-level list."""
    raw = {
        "duration": 1.0,
        "segments": [
            {
                "start": 0.0,
                "end": 1.0,
                "text": "hi",
                "words": [{"word": "hi", "start": 0.1, "end": 0.4}],
            }
        ],
        "words": [{"word": "hi", "start": 0.0, "end": 1.0}],  # different range
    }
    result = normalize_groq_response(raw)
    assert len(result.segments) == 1
    assert result.segments[0].words == [WordTiming(word="hi", start_ms=100, end_ms=400)]


def test_bucket_words_gap_word_is_not_dropped() -> None:
    """A word whose midpoint falls in the silence gap between two segments
    must land in the NEAREST segment, never be silently discarded."""
    bounds = [(0.0, 1.0), (2.0, 3.0)]
    words = [
        {"word": "in-gap-closer-to-first", "start": 1.2, "end": 1.3},  # mid=1.25
        {"word": "in-gap-closer-to-second", "start": 1.6, "end": 1.7},  # mid=1.65
    ]
    buckets = _bucket_words_into_segments(bounds, words)

    total = sum(len(b) for b in buckets)
    assert total == len(words), "no word may be dropped"
    assert [w.word for w in buckets[0]] == ["in-gap-closer-to-first"]
    assert [w.word for w in buckets[1]] == ["in-gap-closer-to-second"]


def test_bucket_words_boundary_word_matches_exactly_one_segment() -> None:
    """A word whose midpoint sits exactly on a shared segment boundary must
    match exactly one segment (the later one, via half-open [start, end)),
    never both."""
    bounds = [(0.0, 1.0), (1.0, 2.0)]
    words = [{"word": "on-boundary", "start": 0.9, "end": 1.1}]  # mid=1.0 exactly
    buckets = _bucket_words_into_segments(bounds, words)

    total = sum(len(b) for b in buckets)
    assert total == 1, "a boundary word must not be duplicated across segments"
    assert buckets[0] == []
    assert [w.word for w in buckets[1]] == ["on-boundary"]


def test_bucket_words_before_first_and_after_last_go_to_nearest() -> None:
    bounds = [(1.0, 2.0), (3.0, 4.0)]
    words = [
        {"word": "before-everything", "start": 0.0, "end": 0.2},  # mid=0.1
        {"word": "after-everything", "start": 5.0, "end": 5.2},  # mid=5.1
    ]
    buckets = _bucket_words_into_segments(bounds, words)

    assert sum(len(b) for b in buckets) == 2
    assert [w.word for w in buckets[0]] == ["before-everything"]
    assert [w.word for w in buckets[1]] == ["after-everything"]


@pytest.mark.asyncio
async def test_groq_asr_sends_expected_request_params() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        captured["body"] = request.read()
        return httpx.Response(200, json=GROQ_FIXTURE)

    transport = httpx.MockTransport(handler)

    provider = GroqASR(api_key="test-key-123")

    # Monkeypatch the AsyncClient used inside transcribe() to route through
    # our MockTransport instead of hitting the network.
    import app.services.asr as asr_module

    original_async_client = httpx.AsyncClient

    class _PatchedAsyncClient(original_async_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    asr_module.httpx.AsyncClient = _PatchedAsyncClient
    try:
        result = await provider.transcribe(b"fake-audio-bytes", "audio/mpeg", language="en")
    finally:
        asr_module.httpx.AsyncClient = original_async_client

    assert isinstance(result, TranscriptResult)
    assert len(result.segments) == 2

    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.groq.com/openai/v1/audio/transcriptions"
    assert captured["headers"]["authorization"] == "Bearer test-key-123"

    body = captured["body"]
    # Multipart body: assert the key fields/values are present as form parts.
    assert b'name="model"' in body and b"whisper-large-v3" in body
    assert b'name="language"' in body
    # language=en, sent explicitly (never auto-detect, per brief 3.5)
    assert b"\r\n\r\nen\r\n" in body
    assert b'name="response_format"' in body and b"verbose_json" in body
    assert body.count(b'name="timestamp_granularities[]"') == 2
    assert b"\r\n\r\nword\r\n" in body
    assert b"\r\n\r\nsegment\r\n" in body
    # the file part carries a real filename+extension (not a bare "audio"),
    # derived from mime_type, so Groq can reliably infer the container/codec.
    assert b'name="file"; filename="audio.mp3"' in body


@pytest.mark.asyncio
async def test_groq_asr_raises_without_api_key() -> None:
    provider = GroqASR(api_key="")
    with pytest.raises(RuntimeError):
        await provider.transcribe(b"x", "audio/mpeg")


LIVE_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "hello.m4a"


@pytest.mark.asyncio
async def test_groq_asr_live_transcription() -> None:
    """Live smoke test against the real Groq API. SKIPPED unless
    GROQ_API_KEY is configured (never fails CI/dev without one, per Faza 3
    acceptance criteria).

    Fixture: tests/fixtures/hello.m4a, a few seconds of real English speech
    (macOS `say` -> .m4a/ALAC), saying "The quick brown fox jumps over the
    lazy dog. This is a test recording for automatic speech recognition."
    """
    from app.core.config import settings

    if not settings.groq_api_key:
        pytest.skip("GROQ_API_KEY not configured; live ASR test skipped")
    if not LIVE_FIXTURE_PATH.exists():
        pytest.skip(f"live audio fixture missing: {LIVE_FIXTURE_PATH}")

    audio_bytes = LIVE_FIXTURE_PATH.read_bytes()

    captured_language: dict[str, str] = {}
    original_async_client = httpx.AsyncClient

    class _CapturingAsyncClient(original_async_client):
        async def post(self, url, **kwargs):
            data = kwargs.get("data") or {}
            captured_language["language"] = data.get("language")
            return await super().post(url, **kwargs)

    import app.services.asr as asr_module

    asr_module.httpx.AsyncClient = _CapturingAsyncClient
    try:
        provider = GroqASR()
        result = await provider.transcribe(audio_bytes, "audio/mp4", language="en")
    finally:
        asr_module.httpx.AsyncClient = original_async_client

    assert captured_language["language"] == "en"  # explicit, never auto-detect

    assert isinstance(result, TranscriptResult)
    assert result.segments, "expected at least one segment from real speech"
    for seg in result.segments:
        assert seg.text.strip()
        assert seg.words, f"segment {seg.order_index!r} has no word-level timings"
        for w in seg.words:
            assert isinstance(w.start_ms, int)
            assert isinstance(w.end_ms, int)
            assert w.end_ms >= w.start_ms

    full_text = " ".join(seg.text for seg in result.segments).lower()
    assert "fox" in full_text or "dog" in full_text, (
        f"expected recognizable speech content, got: {full_text!r}"
    )

"""ASR (speech-to-text) provider interface + the Groq implementation.

Every provider — Groq today (``GroqASR``), the offline faster-whisper seed
script later, any future provider — emits the SAME normalized
``TranscriptResult`` shape (§8.1 of the audio-ingestion brief), so the rest of
the pipeline (the transcription worker, ``AudioSegment`` persistence) never
has to know which provider produced it. Swapping providers is a matter of
implementing ``ASRProvider``, not touching any caller.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.core.config import settings
from app.services.storage import AUDIO_CONTENT_TYPES

# Groq's OpenAI-compatible transcription endpoint. Source: Groq docs
# (console.groq.com/docs/speech-to-text) + groq-python SDK type stubs
# (transcription_create_params.py), verified via Context7.
GROQ_TRANSCRIPTIONS_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = "whisper-large-v3"

# Reuse the storage layer's extension<->MIME mapping so the multipart file
# part can carry a real filename+extension (e.g. "audio.mp3") instead of a
# bare "audio" -- Groq/Whisper use the filename to help infer the
# container/codec, which is more reliable than Content-Type alone for some
# formats.
_EXT_BY_CONTENT_TYPE: dict[str, str] = {v: k for k, v in AUDIO_CONTENT_TYPES.items()}


# --- Normalized result types (§8.1) -----------------------------------------


@dataclass(frozen=True)
class WordTiming:
    word: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class TranscriptSegment:
    order_index: int
    start_ms: int
    end_ms: int
    text: str
    words: list[WordTiming] = field(default_factory=list)


@dataclass(frozen=True)
class TranscriptResult:
    duration_ms: int
    segments: list[TranscriptSegment] = field(default_factory=list)


class ASRProvider(Protocol):
    """One interface every transcription backend implements. Only
    ``GroqASR`` is active today; adding another provider later means
    implementing this Protocol, with no changes to any caller."""

    async def transcribe(
        self, audio: bytes, mime_type: str, language: str = "en"
    ) -> TranscriptResult: ...


def _to_ms(seconds: float) -> int:
    """Whisper/Groq report timestamps in fractional seconds; we store
    integer milliseconds everywhere else in the schema."""
    return round(seconds * 1000)


def _bucket_words_into_segments(
    bounds: list[tuple[float, float]], words: list[dict[str, Any]]
) -> list[list[WordTiming]]:
    """Assign each top-level ``words[]`` entry to exactly one segment, by
    its midpoint against each segment's ``[start, end)`` bound.

    Two correctness properties this guarantees (fixing a prior bug):
      * **No duplicates**: bounds are checked half-open (``start <= mid <
        end``), so a midpoint sitting exactly on a shared segment boundary
        matches only the later segment, never both.
      * **No drops**: a word whose midpoint falls in a silence gap between
        segments (or before the first / after the last) matches no bound
        directly, so it's assigned to the segment NEAREST that midpoint
        instead of being discarded.

    Every word ends up in exactly one bucket.
    """
    buckets: list[list[WordTiming]] = [[] for _ in bounds]
    if not bounds:
        return buckets

    for w in words:
        w_start = float(w["start"])
        w_end = float(w["end"])
        midpoint = (w_start + w_end) / 2
        timing = WordTiming(
            word=w["word"], start_ms=_to_ms(w_start), end_ms=_to_ms(w_end)
        )

        matched_index: int | None = None
        for i, (seg_start, seg_end) in enumerate(bounds):
            if seg_start <= midpoint < seg_end:
                matched_index = i
                break

        if matched_index is None:
            # Gap word (or outside the first/last segment's range): fall
            # back to the nearest segment by distance to its [start, end)
            # range, so it's never silently dropped.
            best_index = 0
            best_distance: float | None = None
            for i, (seg_start, seg_end) in enumerate(bounds):
                if midpoint < seg_start:
                    distance = seg_start - midpoint
                elif midpoint >= seg_end:
                    distance = midpoint - seg_end
                else:
                    distance = 0.0
                if best_distance is None or distance < best_distance:
                    best_distance = distance
                    best_index = i
            matched_index = best_index

        buckets[matched_index].append(timing)

    return buckets


def normalize_groq_response(raw: dict[str, Any]) -> TranscriptResult:
    """Normalize a Groq/OpenAI-compatible ``verbose_json`` transcription
    response into a :class:`TranscriptResult`.

    Response shape (per Groq's docs + OpenAI Whisper API, which Groq mirrors):
    top-level ``duration`` (seconds), ``segments`` (each with ``start``/
    ``end``/``text``, in seconds), and — because we requested
    ``timestamp_granularities[]=word`` — a top-level ``words`` array of
    ``{word, start, end}`` (also seconds), NOT nested inside each segment.
    We bucket words into their containing segment by time (see
    ``_bucket_words_into_segments``), which guarantees no word is dropped
    (silence-gap words go to the nearest segment) or duplicated (shared
    boundaries resolve to exactly one segment). Defensively, if segments
    already carry a nested ``words`` list (some providers/versions may do
    this), we use that directly instead of re-deriving it.
    """
    duration_ms = _to_ms(float(raw.get("duration", 0.0)))
    raw_segments: list[dict[str, Any]] = raw.get("segments") or []
    top_level_words: list[dict[str, Any]] = raw.get("words") or []

    # All-or-nothing: if the response nests words per segment, trust that
    # directly rather than mixing it with top-level bucketing.
    use_nested = any(seg.get("words") for seg in raw_segments)

    word_buckets: list[list[WordTiming]]
    if use_nested:
        word_buckets = [
            [
                WordTiming(
                    word=w["word"],
                    start_ms=_to_ms(float(w["start"])),
                    end_ms=_to_ms(float(w["end"])),
                )
                for w in (seg.get("words") or [])
            ]
            for seg in raw_segments
        ]
    else:
        bounds = [(float(seg["start"]), float(seg["end"])) for seg in raw_segments]
        word_buckets = _bucket_words_into_segments(bounds, top_level_words)

    segments: list[TranscriptSegment] = [
        TranscriptSegment(
            order_index=order_index,
            start_ms=_to_ms(float(seg["start"])),
            end_ms=_to_ms(float(seg["end"])),
            text=str(seg["text"]).strip(),
            words=word_buckets[order_index],
        )
        for order_index, seg in enumerate(raw_segments)
    ]
    return TranscriptResult(duration_ms=duration_ms, segments=segments)


class GroqASR:
    """The only active :class:`ASRProvider` today: Groq's
    ``whisper-large-v3`` via its OpenAI-compatible transcription endpoint.

    Retry/error classification is deliberately NOT this class's job — it
    raises (``httpx.HTTPStatusError`` via ``raise_for_status()``, or any
    transport-level ``httpx.HTTPError``) and lets the caller (the Faza 4
    worker) decide retryable vs. non-retryable from the exception/status
    code.
    """

    def __init__(self, api_key: str | None = None, timeout: float | None = None) -> None:
        # Defaults to config so callers don't have to thread these through;
        # overridable (e.g. in tests) without touching global settings.
        self._api_key = settings.groq_api_key if api_key is None else api_key
        self._timeout = settings.groq_timeout_s if timeout is None else timeout

    async def transcribe(
        self, audio: bytes, mime_type: str, language: str = "en"
    ) -> TranscriptResult:
        if not self._api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not configured (settings.groq_api_key is empty)"
            )

        # A real filename+extension (not a bare "audio") helps Groq/Whisper
        # reliably infer the container/codec.
        ext = _EXT_BY_CONTENT_TYPE.get(mime_type, "")
        files = {"file": (f"audio{ext}", audio, mime_type)}
        # timestamp_granularities[] must be sent as a REPEATED form field, not
        # JSON — httpx sends a list value as repeated fields under the same
        # key (see httpx docs on form data with repeated values).
        data = {
            "model": GROQ_MODEL,
            "language": language,  # §3.5: always explicit, never auto-detect
            "response_format": "verbose_json",
            "timestamp_granularities[]": ["word", "segment"],
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                GROQ_TRANSCRIPTIONS_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                files=files,
                data=data,
            )
        response.raise_for_status()
        return normalize_groq_response(response.json())

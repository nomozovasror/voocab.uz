"""Object storage for uploaded media (audio clips today).

One small abstraction over two backends, chosen by config:
* **R2 / S3** in production (``settings.use_r2``) — objects go to the bucket and
  are served from ``settings.r2_public_base_url``.
* **Local disk** in development — objects are written under ``settings.media_root``
  and served by the app at ``settings.media_url_prefix`` (see main.py).

boto3 is synchronous, so its calls run in a threadpool to keep the event loop free.
"""

import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi.concurrency import run_in_threadpool

from app.core.config import settings

# Allowed audio uploads: extension → MIME type.
AUDIO_CONTENT_TYPES: dict[str, str] = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".webm": "audio/webm",
}


def audio_key(ext: str) -> str:
    """A unique storage key for an audio object with the given extension."""
    return f"audio/{uuid.uuid4().hex}{ext}"


@lru_cache(maxsize=1)
def _s3_client() -> Any:
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name="auto",
    )


def _media_root() -> Path:
    root = Path(settings.media_root)
    root.mkdir(parents=True, exist_ok=True)
    return root


async def save(key: str, data: bytes, content_type: str) -> str:
    """Persist ``data`` under ``key`` and return a URL the frontend can fetch.

    R2 returns an absolute URL; local returns a path relative to the API origin
    (e.g. ``/media/audio/…``), which the frontend resolves against its API base.
    """
    if settings.use_r2:
        def _put() -> None:
            _s3_client().put_object(
                Bucket=settings.r2_bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )

        await run_in_threadpool(_put)
        base = settings.r2_public_base_url.rstrip("/")
        return f"{base}/{key}"

    def _write() -> None:
        path = _media_root() / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    await run_in_threadpool(_write)
    prefix = settings.media_url_prefix.rstrip("/")
    return f"{prefix}/{key}"

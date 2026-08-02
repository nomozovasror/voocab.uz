"""Object storage for uploaded media (audio clips today).

``AudioStorage`` is a hash-keyed abstraction over two backends, chosen by
config:
* **R2 / S3** in production (``settings.use_r2``) — objects go to the bucket
  and are served from ``settings.r2_public_base_url``.
* **Local disk** in development — objects are written under
  ``settings.media_root`` and served by the app at ``settings.media_url_prefix``
  (see main.py).

Keys are content-addressed: derived from the SHA-256 of the bytes (see
``audio_storage_key``), never a random UUID. Identical bytes always resolve to
the identical key, which is what makes ``put`` idempotent/dedup-safe.

boto3 is synchronous, so its calls run in a threadpool to keep the event loop
free; local file IO is offloaded the same way for consistency.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from fastapi.concurrency import run_in_threadpool

from app.core.config import settings

# Allowed audio uploads: extension -> MIME type.
AUDIO_CONTENT_TYPES: dict[str, str] = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".webm": "audio/webm",
}

# Reverse lookup used only to add a cosmetic extension suffix to storage keys
# (browsers/tooling are happier with a recognizable extension). It plays no
# role in dedup — the hash alone determines the key.
_EXT_BY_CONTENT_TYPE: dict[str, str] = {v: k for k, v in AUDIO_CONTENT_TYPES.items()}


def audio_storage_key(sha256: str, mime_type: str) -> str:
    """The content-addressed storage key for an audio blob.

    Fully determined by ``sha256`` — the same bytes always produce the same
    key, which is the basis for dedup at both the storage and DB layers. The
    extension suffix (from ``mime_type``) is cosmetic only.
    """
    ext = _EXT_BY_CONTENT_TYPE.get(mime_type, "")
    return f"audio/{sha256}{ext}"


class AudioStorage(Protocol):
    """Storage backend for content-addressed audio blobs.

    All methods are async for a consistent interface across backends, even
    where an implementation (e.g. building a URL string) has no actual I/O.
    """

    async def put(self, key: str, data: bytes, mime_type: str) -> None:
        """Store ``data`` under ``key``. Idempotent: if ``key`` already
        exists, this is a no-op (same bytes are never written twice)."""
        ...

    async def exists(self, key: str) -> bool: ...

    async def get(self, key: str) -> bytes: ...

    async def url(self, key: str) -> str:
        """A URL the frontend can fetch ``key`` from."""
        ...


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


class LocalStorage:
    """Dev backend: files under ``settings.media_root``, keyed by
    ``audio_storage_key``. Served by the app's ``/media`` static mount."""

    def _root(self) -> Path:
        root = Path(settings.media_root)
        root.mkdir(parents=True, exist_ok=True)
        return root

    async def exists(self, key: str) -> bool:
        return await run_in_threadpool(lambda: (self._root() / key).exists())

    async def put(self, key: str, data: bytes, mime_type: str) -> None:
        if await self.exists(key):
            # Idempotent: identical bytes are already stored under this
            # content-addressed key, so there's nothing to do.
            return

        def _write() -> None:
            path = self._root() / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await run_in_threadpool(_write)

    async def get(self, key: str) -> bytes:
        return await run_in_threadpool(lambda: (self._root() / key).read_bytes())

    async def url(self, key: str) -> str:
        prefix = settings.media_url_prefix.rstrip("/")
        return f"{prefix}/{key}"


class R2Storage:
    """Prod backend: Cloudflare R2 (S3-compatible), keyed by
    ``audio_storage_key``. Served from ``settings.r2_public_base_url``."""

    async def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        def _head() -> bool:
            try:
                _s3_client().head_object(Bucket=settings.r2_bucket, Key=key)
                return True
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code in ("404", "NoSuchKey"):
                    return False
                raise

        return await run_in_threadpool(_head)

    async def put(self, key: str, data: bytes, mime_type: str) -> None:
        if await self.exists(key):
            # Idempotent: same object already stored at this key — a
            # duplicate put would waste bandwidth/storage for no reason.
            return

        def _put() -> None:
            _s3_client().put_object(
                Bucket=settings.r2_bucket,
                Key=key,
                Body=data,
                ContentType=mime_type,
            )

        await run_in_threadpool(_put)

    async def get(self, key: str) -> bytes:
        def _get() -> bytes:
            response = _s3_client().get_object(Bucket=settings.r2_bucket, Key=key)
            return response["Body"].read()

        return await run_in_threadpool(_get)

    async def url(self, key: str) -> str:
        base = settings.r2_public_base_url.rstrip("/")
        return f"{base}/{key}"


@lru_cache(maxsize=1)
def get_storage() -> AudioStorage:
    """The configured storage backend, selected the same way as
    ``settings.use_r2`` (R2 when fully configured, else local disk)."""
    return R2Storage() if settings.use_r2 else LocalStorage()

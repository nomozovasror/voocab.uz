"""Object storage for uploaded media: the recordings, and the pictures a map
or diagram task is labelled on.

``MediaStorage`` is a hash-keyed abstraction over two backends, chosen by
config:
* **R2 / S3** in production (``settings.use_r2``) — objects go to the bucket
  and are served from ``settings.r2_public_base_url``.
* **Local disk** in development — objects are written under
  ``settings.media_root`` and served by the app at ``settings.media_url_prefix``
  (see main.py).

Keys are content-addressed: derived from the SHA-256 of the bytes (see
``audio_storage_key`` and ``image_storage_key``), never a random UUID.
Identical bytes always resolve to the identical key, which is what makes
``put`` idempotent/dedup-safe. The two kinds of media are kept in separate
prefixes rather than one flat space — the hash alone would be unambiguous, but
``audio/`` and ``images/`` is what makes a bucket readable to whoever inherits
it, and lets a lifecycle rule apply to one and not the other.

boto3 is synchronous, so its calls run in a threadpool to keep the event loop
free; local file IO is offloaded the same way for consistency.
"""

import hashlib
import os
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from fastapi.concurrency import run_in_threadpool

from app.core.config import settings


def sha256_hex(data: bytes) -> str:
    """The content address of these bytes. Lives here because that is what a
    storage key is made of, and because both media pipelines need it."""
    return hashlib.sha256(data).hexdigest()


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

#: Allowed image uploads: MIME type -> extension, and keyed that way round
#: because an image's type is read from its own header rather than from its
#: filename (see :mod:`app.services.image_codec`). There is no extension to
#: look up — the bytes said what they are.
IMAGE_CONTENT_TYPES: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
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


def image_storage_key(sha256: str, mime_type: str) -> str:
    """The content-addressed storage key for an image blob. Same contract as
    :func:`audio_storage_key`, under its own prefix."""
    ext = IMAGE_CONTENT_TYPES.get(mime_type, "")
    return f"images/{sha256}{ext}"


def recording_storage_key(sha256: str) -> str:
    """The content-addressed key of a normalised human word recording
    (:mod:`app.services.word_recordings`): always m4a, always under ``rec/`` --
    its own prefix, so a lifecycle rule or a bucket listing can tell the
    dictionary's recordings from our own TTS (``tts/``) and from uploads."""
    return f"rec/{sha256}.m4a"


class MediaStorage(Protocol):
    """Storage backend for content-addressed blobs — audio or image alike.
    The key carries the prefix, so nothing below this line knows or needs to
    know which kind it is holding.

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
    """Dev backend: files under ``settings.media_root``, at the key the
    caller derived. Served by the app's ``/media`` static mount.

    Also the backend of the Windows seed run, where ``media_root`` is an
    absolute drive path (``D:\\voocab-media``): keys always use ``/``, which
    ``pathlib`` joins correctly on Windows too.

    ``put`` is atomic (temp file in the same directory, then ``os.replace``):
    ``exists`` is the idempotency check, so a half-written file left by a killed
    process would otherwise be "already stored" for ever, and a reader on the
    other side of a share would see a truncated file."""

    def _root(self) -> Path:
        root = Path(settings.media_root)
        try:
            root.mkdir(parents=True, exist_ok=True)
        except FileNotFoundError as exc:
            # A drive or share that is not there (unmapped, asleep) is the
            # world's fault: surface it as a plain OSError, which the queues
            # treat as retryable -- FileNotFoundError means "this key points at
            # nothing" and would fail the row for good.
            raise OSError(f"media root {root} is not available: {exc}") from exc
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
            tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            try:
                tmp.write_bytes(data)
                try:
                    os.replace(tmp, path)
                except OSError:
                    # Windows refuses to replace a file another process has
                    # open; if the key is there now somebody else stored the
                    # same bytes, which is all `put` promises.
                    if not path.exists():
                        raise
            finally:
                tmp.unlink(missing_ok=True)

        await run_in_threadpool(_write)

    async def get(self, key: str) -> bytes:
        return await run_in_threadpool(lambda: (self._root() / key).read_bytes())

    async def url(self, key: str) -> str:
        prefix = settings.media_url_prefix.rstrip("/")
        return f"{prefix}/{key}"


class R2Storage:
    """Prod backend: Cloudflare R2 (S3-compatible), at the key the caller
    derived. Served from ``settings.r2_public_base_url``."""

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
def get_storage() -> MediaStorage:
    """The configured storage backend, selected the same way as
    ``settings.use_r2`` (R2 when fully configured, else local disk)."""
    return R2Storage() if settings.use_r2 else LocalStorage()

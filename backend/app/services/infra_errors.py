"""Which errors are the infrastructure's fault, and which are the input's.

One classification, shared by the transcription worker (``process_blob``) and
the render queue (``tts.process_render``). It lives in its own small module
because both need it and ``app.worker`` imports ``tts``: defining it in the
worker would make ``tts`` import the worker (a cycle).
``app.worker`` re-exports the names, so nothing that imported them from there
changes.

The line that matters for a queue: a **retryable** error is a fault of the
world (storage throttling or down, a disk blip) -- the same input will work
later, so it must neither mark a row ``failed`` nor use up one of its
attempts. A **non-retryable** one is a fault of the input (undecodable audio, a
key that points at nothing) -- retrying the same bytes fails the same way.
"""

import httpx

RETRYABLE_HTTP_STATUS_CODES = {408, 429, 500, 502, 503, 504}
NON_RETRYABLE_HTTP_STATUS_CODES = {400, 413, 415, 422}

# S3/R2 (botocore) error codes that mean "the object/bucket/credentials are
# genuinely wrong" -- retrying won't help, so these stay non-retryable.
# Everything else from botocore (throttling, 5xx, transient timeouts) is
# treated as a transient infra hiccup -- retryable.
NON_RETRYABLE_S3_ERROR_CODES = {
    "NoSuchKey",
    "NoSuchBucket",
    "404",
    "AccessDenied",
    "InvalidAccessKeyId",
    "SignatureDoesNotMatch",
}


def classify_error(exc: Exception) -> str:
    """Map an exception raised while processing a blob to ``"retryable"`` or
    ``"non_retryable"`` per §9.3.

    Retryable: network timeouts/transport errors, HTTP
    408/429/500/502/503/504, and transient storage-layer errors (R2/S3
    throttling or 5xx via botocore, or a local-disk I/O hiccup) — these are
    infra problems, not a problem with the audio, so they're worth retrying.
    Non-retryable: HTTP 400/413/415/422, corrupt/unreadable audio, a storage
    error that means the object genuinely doesn't exist or credentials are
    wrong (retrying can't fix that), and any other unexpected error —
    retrying the same bytes against the same provider would just fail the
    same way, so these go straight to ``failed`` with no fallback provider
    (§9.3 note).
    """
    if isinstance(exc, InfrastructureError):
        return "retryable"
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return "retryable" if code in RETRYABLE_HTTP_STATUS_CODES else "non_retryable"
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return "retryable"

    # boto3/botocore is only actually exercised by R2Storage, but importing
    # botocore.exceptions is cheap (boto3 is already a main dependency) and
    # lets us classify storage errors instead of lumping every non-httpx
    # exception into "non_retryable".
    from botocore.exceptions import ClientError

    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        return "non_retryable" if code in NON_RETRYABLE_S3_ERROR_CODES else "retryable"

    if isinstance(exc, OSError):
        # Local-disk hiccups (permission/IO blips) are infra -- retryable.
        # A genuinely missing file means the blob's storage_key points at
        # nothing, which retrying can't fix.
        return "non_retryable" if isinstance(exc, FileNotFoundError) else "retryable"

    return "non_retryable"


class InfrastructureError(Exception):
    """A fault of the world, not of the input: storage that is down or
    throttling, a model that failed to load. Queues leave the row waiting
    (no attempt used) instead of failing it. Raised by :class:`GuardedStorage`
    and by ``KokoroSynth``; ``__cause__`` is the original error."""


class GuardedStorage:
    """A ``MediaStorage`` whose RETRYABLE failures (per :func:`classify_error`)
    surface as :class:`InfrastructureError`, and whose permanent ones pass
    through untouched. Wrapping the storage once at the top of a job is what
    lets everything beneath it -- fetching a recording, laying a part down --
    stay free of error classification, and be sure that a storage outage is
    never mistaken for a bad input."""

    def __init__(self, inner) -> None:  # MediaStorage; avoids importing storage here
        self._inner = inner

    async def _guard(self, call):
        try:
            return await call
        except Exception as exc:  # noqa: BLE001 - classified, then re-raised either way
            if classify_error(exc) == "retryable":
                raise InfrastructureError(f"{type(exc).__name__}: {exc}") from exc
            raise

    async def put(self, key: str, data: bytes, mime_type: str) -> None:
        return await self._guard(self._inner.put(key, data, mime_type))

    async def get(self, key: str) -> bytes:
        return await self._guard(self._inner.get(key))

    async def exists(self, key: str) -> bool:
        return await self._guard(self._inner.exists(key))

    async def url(self, key: str) -> str:
        return await self._guard(self._inner.url(key))


def guarded(storage):
    """``storage`` wrapped in :class:`GuardedStorage` (idempotent)."""
    return storage if isinstance(storage, GuardedStorage) else GuardedStorage(storage)

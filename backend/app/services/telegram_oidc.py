"""Telegram OpenID Connect (OIDC) client.

Telegram runs a standard OIDC provider at ``https://oauth.telegram.org`` (see
core.telegram.org/bots/telegram-login). We drive the Authorization Code + PKCE
flow manually:

1. :func:`build_authorization_url` — send the user to Telegram's ``/auth`` with
   PKCE ``code_challenge``, ``state`` and ``nonce``.
2. :func:`exchange_code` — POST the returned ``code`` to ``/token`` with HTTP
   Basic auth (bot id : bot token) and the PKCE ``code_verifier``; get an
   ``id_token``.
3. :func:`verify_id_token` — validate the id_token's RS256 signature against
   Telegram's JWKS and check ``iss`` / ``aud`` / ``exp`` / ``nonce`` before
   trusting any claim. Telegram exposes NO UserInfo endpoint — all user claims
   (``sub``, ``name``, ``preferred_username``, ``picture``) come from here.
"""

import base64
import hashlib
import secrets
from typing import Any

import httpx
import jwt
from fastapi.concurrency import run_in_threadpool
from jwt import PyJWKClient

from app.core.config import settings

ISSUER = "https://oauth.telegram.org"
AUTHORIZATION_ENDPOINT = f"{ISSUER}/auth"
TOKEN_ENDPOINT = f"{ISSUER}/token"
JWKS_URI = f"{ISSUER}/.well-known/jwks.json"

SCOPE = "openid profile"
SIGNING_ALGORITHMS = ["RS256"]
HTTP_TIMEOUT = 10.0

# PyJWKClient fetches + caches Telegram's public keys and picks the right one by
# the token's `kid`. It's module-level so the cache is shared across requests.
_jwks_client = PyJWKClient(JWKS_URI)


def generate_pkce_pair() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` for PKCE S256."""
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def generate_nonce() -> str:
    return secrets.token_urlsafe(32)


def build_authorization_url(
    *, state: str, nonce: str, code_challenge: str
) -> str:
    params = {
        "client_id": settings.telegram_bot_id,
        "redirect_uri": settings.telegram_redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        # Telegram's /auth requires the calling site's origin (must be a
        # registered Allowed URL); without it the page returns "origin required".
        "origin": settings.frontend_url,
    }
    return str(httpx.URL(AUTHORIZATION_ENDPOINT, params=params))


async def exchange_code(*, code: str, code_verifier: str) -> str:
    """Exchange an authorization ``code`` for an id_token. Returns the raw
    (still unverified) id_token JWT. Raises httpx.HTTPStatusError on failure."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.telegram_redirect_uri,
        "client_id": settings.telegram_bot_id,
        "code_verifier": code_verifier,
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.post(
            TOKEN_ENDPOINT,
            data=data,
            # Token endpoint auth is client_secret_basic: base64(id:token).
            auth=(settings.telegram_bot_id, settings.telegram_bot_token),
        )
    response.raise_for_status()
    payload = response.json()
    id_token = payload.get("id_token")
    if not id_token:
        raise ValueError("token response missing id_token")
    return id_token


async def verify_id_token(id_token: str, *, nonce: str) -> dict[str, Any]:
    """Validate the id_token and return its claims. Never trust an id_token's
    contents without this. Raises on any signature/claim failure.

    PyJWKClient does blocking network I/O (fetching JWKS), so it runs in a
    threadpool to keep the event loop free."""
    signing_key = await run_in_threadpool(
        _jwks_client.get_signing_key_from_jwt, id_token
    )
    claims: dict[str, Any] = jwt.decode(
        id_token,
        signing_key.key,
        algorithms=SIGNING_ALGORITHMS,
        audience=settings.telegram_bot_id,
        issuer=ISSUER,
        options={"require": ["exp", "iss", "aud", "sub"]},
    )
    # jwt.decode doesn't check nonce; enforce it ourselves against the value we
    # bound into the OIDC transaction cookie, to defeat replay.
    if claims.get("nonce") != nonce:
        raise jwt.InvalidTokenError("nonce mismatch")
    return claims

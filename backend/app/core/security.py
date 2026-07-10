"""Our own stateless session layer.

Telegram is only the identity provider; once a user is verified we mint our
OWN JWTs (signed with ``SESSION_SECRET``) and store them in httpOnly cookies.
Three token kinds, all HS256:

* ``access``  — short-lived (~30 min), identifies the user on each request.
* ``refresh`` — long-lived (~30 days), exchanged for a fresh access token.
* ``oidc_tx`` — very short-lived (~10 min), carries the PKCE verifier / state /
  nonce between the ``/start`` redirect and the ``/callback`` so the handshake
  needs no server-side storage.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.core.config import settings

ALGORITHM = "HS256"

ACCESS_TOKEN_TTL = timedelta(minutes=30)
REFRESH_TOKEN_TTL = timedelta(days=30)
OIDC_TX_TTL = timedelta(minutes=10)

# Cookie names.
ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"
OIDC_TX_COOKIE = "tg_oidc_tx"


def _encode(claims: dict[str, Any], ttl: timedelta, token_type: str) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        **claims,
        "type": token_type,
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(payload, settings.session_secret, algorithm=ALGORITHM)


def _decode(token: str, expected_type: str) -> dict[str, Any]:
    """Decode and validate one of our tokens. Raises jwt.InvalidTokenError
    (incl. expiry) on any problem, or ValueError on a type mismatch."""
    payload: dict[str, Any] = jwt.decode(
        token,
        settings.session_secret,
        algorithms=[ALGORITHM],
        options={"require": ["exp", "iat", "type"]},
    )
    if payload.get("type") != expected_type:
        raise ValueError("unexpected token type")
    return payload


def create_access_token(user_id: str) -> str:
    return _encode({"sub": user_id}, ACCESS_TOKEN_TTL, "access")


def create_refresh_token(user_id: str) -> str:
    return _encode({"sub": user_id}, REFRESH_TOKEN_TTL, "refresh")


def decode_access_token(token: str) -> dict[str, Any]:
    return _decode(token, "access")


def decode_refresh_token(token: str) -> dict[str, Any]:
    return _decode(token, "refresh")


def create_oidc_tx_token(*, state: str, nonce: str, code_verifier: str) -> str:
    return _encode(
        {"state": state, "nonce": nonce, "code_verifier": code_verifier},
        OIDC_TX_TTL,
        "oidc_tx",
    )


def decode_oidc_tx_token(token: str) -> dict[str, Any]:
    return _decode(token, "oidc_tx")

"""Auth endpoints: Telegram OIDC login + our own session lifecycle.

Routes (mounted under ``/api/auth``):

* ``GET  /telegram/start``     — begin the OIDC handshake (redirect to Telegram)
* ``GET  /telegram/callback``  — finish it: verify id_token, find-or-create user,
                                 set session cookies, redirect to the frontend
* ``POST /refresh``            — rotate: new access (+refresh) from the refresh cookie
* ``POST /logout``            — clear session cookies
* ``GET  /me``                — the current user
"""

import logging
import uuid
from typing import Annotated

import httpx
import jwt
from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.api.deps import CurrentUser
from app.core.config import settings
from app.core.database import AsyncSession, get_session
from app.core.security import (
    ACCESS_COOKIE,
    ACCESS_TOKEN_TTL,
    OIDC_TX_COOKIE,
    OIDC_TX_TTL,
    REFRESH_COOKIE,
    REFRESH_TOKEN_TTL,
    create_access_token,
    create_oidc_tx_token,
    create_refresh_token,
    decode_oidc_tx_token,
    decode_refresh_token,
)
from app.models.user import User
from app.services import telegram_oidc
from app.services.auth import get_or_create_user_from_telegram

logger = logging.getLogger("app.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])


class UserRead(BaseModel):
    id: uuid.UUID
    display_name: str
    email: str | None
    avatar_url: str | None


def _cookie_domain() -> str | None:
    # Scope cookies to the parent domain (e.g. ".voocab.uz") so they're shared
    # between the frontend host and the API subdomain. Empty config = host-only
    # cookie (local dev, single host).
    return settings.cookie_domain or None


def _cookie_kwargs() -> dict[str, object]:
    # Session cookies are sent on same-site frontend fetches (Lax is sufficient
    # and safer). In production the Domain attribute lets voocab.uz and
    # api.voocab.uz share them.
    return {
        "httponly": True,
        "secure": settings.cookie_secure,
        "samesite": "lax",
        "domain": _cookie_domain(),
        "path": "/",
    }


def _tx_cookie_kwargs() -> dict[str, object]:
    # The OIDC transaction cookie must come back on Telegram's cross-site return,
    # which isn't guaranteed to be a top-level GET (the already-authorized fast
    # path can return via POST/JS), where a Lax cookie would be dropped. So use
    # SameSite=None — which requires Secure. Falls back to Lax only for insecure
    # local dev, where there's no cross-site hop anyway.
    secure = settings.cookie_secure
    return {
        "httponly": True,
        "secure": secure,
        "samesite": "none" if secure else "lax",
        "domain": _cookie_domain(),
        "path": "/",
    }


def _set_session_cookies(response: Response, user_id: str) -> None:
    response.set_cookie(
        ACCESS_COOKIE,
        create_access_token(user_id),
        max_age=int(ACCESS_TOKEN_TTL.total_seconds()),
        **_cookie_kwargs(),
    )
    response.set_cookie(
        REFRESH_COOKIE,
        create_refresh_token(user_id),
        max_age=int(REFRESH_TOKEN_TTL.total_seconds()),
        **_cookie_kwargs(),
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/", domain=_cookie_domain())
    response.delete_cookie(REFRESH_COOKIE, path="/", domain=_cookie_domain())


@router.get("/telegram/start")
async def telegram_start() -> RedirectResponse:
    """Kick off the Authorization Code + PKCE flow. The PKCE verifier, state and
    nonce are sealed into a short-lived signed httpOnly cookie so the callback
    can validate the round-trip without any server-side storage."""
    if not settings.telegram_bot_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram login is not configured",
        )

    code_verifier, code_challenge = telegram_oidc.generate_pkce_pair()
    state = telegram_oidc.generate_state()
    nonce = telegram_oidc.generate_nonce()

    auth_url = telegram_oidc.build_authorization_url(
        state=state, nonce=nonce, code_challenge=code_challenge
    )

    response = RedirectResponse(auth_url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        OIDC_TX_COOKIE,
        create_oidc_tx_token(
            state=state, nonce=nonce, code_verifier=code_verifier
        ),
        max_age=int(OIDC_TX_TTL.total_seconds()),
        **_tx_cookie_kwargs(),
    )
    return response


@router.get("/telegram/callback")
async def telegram_callback(
    session: Annotated[AsyncSession, Depends(get_session)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    tx: Annotated[str | None, Cookie(alias=OIDC_TX_COOKIE)] = None,
) -> RedirectResponse:
    """Complete the handshake. On any failure the browser is bounced back to the
    frontend with ``?login=error`` rather than shown a raw 4xx."""
    failure = RedirectResponse(
        f"{settings.frontend_url}/auth?login=error",
        status_code=status.HTTP_302_FOUND,
    )
    failure.delete_cookie(
        OIDC_TX_COOKIE,
        path="/",
        domain=_cookie_domain(),
        secure=settings.cookie_secure,
        samesite="none" if settings.cookie_secure else "lax",
    )

    if error or not code or not state or not tx:
        logger.warning(
            "callback bad request: error=%s code=%s state=%s tx_cookie=%s",
            error,
            bool(code),
            bool(state),
            bool(tx),
        )
        return failure

    try:
        tx_claims = decode_oidc_tx_token(tx)
    except (jwt.InvalidTokenError, ValueError) as exc:
        logger.warning("callback tx cookie invalid: %r", exc)
        return failure

    # CSRF: the state echoed by Telegram must match the one we issued.
    if state != tx_claims.get("state"):
        logger.warning("callback state mismatch")
        return failure

    try:
        id_token = await telegram_oidc.exchange_code(
            code=code, code_verifier=tx_claims["code_verifier"]
        )
        claims = await telegram_oidc.verify_id_token(
            id_token, nonce=tx_claims["nonce"]
        )
    except httpx.HTTPStatusError as exc:
        logger.error(
            "callback token exchange failed: %s -> %s",
            exc.response.status_code,
            exc.response.text[:300],
        )
        return failure
    except (httpx.HTTPError, jwt.InvalidTokenError, ValueError, KeyError):
        logger.exception("callback token/id_token verification failed")
        return failure

    user = await get_or_create_user_from_telegram(session, claims)

    success = RedirectResponse(
        settings.frontend_url, status_code=status.HTTP_302_FOUND
    )
    success.delete_cookie(
        OIDC_TX_COOKIE,
        path="/",
        domain=_cookie_domain(),
        secure=settings.cookie_secure,
        samesite="none" if settings.cookie_secure else "lax",
    )
    _set_session_cookies(success, str(user.id))
    return success


@router.post("/refresh")
async def refresh(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Mint a fresh access token from the refresh cookie, rotating the refresh
    cookie too. 401 if the refresh token is missing/invalid or the user is gone."""
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = decode_refresh_token(token)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _set_session_cookies(response, str(user.id))
    return response


@router.post("/logout")
async def logout() -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_session_cookies(response)
    return response


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUser) -> User:
    return user

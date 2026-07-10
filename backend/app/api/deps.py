"""Request dependencies for auth."""

import uuid
from typing import Annotated

import jwt
from fastapi import Cookie, Depends, HTTPException, status

from app.core.database import AsyncSession, get_session
from app.core.security import ACCESS_COOKIE, decode_access_token
from app.models.user import User

_CREDENTIALS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
)


async def get_current_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    access_token: Annotated[str | None, Cookie(alias=ACCESS_COOKIE)] = None,
) -> User:
    """Resolve the current user from our access-token cookie. Any missing,
    malformed, expired, or dangling token yields 401."""
    if not access_token:
        raise _CREDENTIALS_EXC
    try:
        payload = decode_access_token(access_token)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise _CREDENTIALS_EXC

    user = await session.get(User, user_id)
    if user is None:
        raise _CREDENTIALS_EXC
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]

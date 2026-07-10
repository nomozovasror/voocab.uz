"""User provisioning from a verified external identity (find-or-create).

Given already-verified OIDC claims, resolve them to a canonical User via the
``auth_identities`` table: look up ``(provider, provider_user_id)``; if absent,
create both a User and its AuthIdentity. Telegram identity is the first
provider; the same path serves Google / email later."""

from typing import Any

from sqlmodel import select

from app.core.database import AsyncSession
from app.models.auth_identity import AuthIdentity
from app.models.user import User

PROVIDER_TELEGRAM = "telegram"


def _display_name(claims: dict[str, Any]) -> str:
    return (
        claims.get("name")
        or claims.get("preferred_username")
        or "Telegram user"
    )


async def get_or_create_user_from_telegram(
    session: AsyncSession, claims: dict[str, Any]
) -> User:
    provider_user_id = str(claims["sub"])
    username = claims.get("preferred_username")
    avatar_url = claims.get("picture")

    identity = (
        await session.exec(
            select(AuthIdentity).where(
                AuthIdentity.provider == PROVIDER_TELEGRAM,
                AuthIdentity.provider_user_id == provider_user_id,
            )
        )
    ).first()

    if identity is not None:
        user = await session.get(User, identity.user_id)
        # Keep the linked identity's mutable bits fresh on each login.
        if user is not None:
            identity.username = username
            identity.avatar_url = avatar_url
            session.add(identity)
            await session.commit()
            return user

    user = User(
        display_name=_display_name(claims),
        avatar_url=avatar_url,
    )
    session.add(user)
    await session.flush()  # populate user.id for the FK below

    identity = AuthIdentity(
        user_id=user.id,
        provider=PROVIDER_TELEGRAM,
        provider_user_id=provider_user_id,
        username=username,
        avatar_url=avatar_url,
    )
    session.add(identity)
    await session.commit()
    await session.refresh(user)
    return user

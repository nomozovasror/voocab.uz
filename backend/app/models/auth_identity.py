import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel


class AuthIdentity(SQLModel, table=True):
    """Links an external identity (Telegram today; Google / email-password
    later) to a canonical :class:`~app.models.user.User`.

    The find-or-create flow looks a user up by
    ``(provider, provider_user_id)`` — hence the unique constraint — so one
    person can accumulate several login methods that all resolve to one user."""

    __tablename__ = "auth_identities"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_user_id", name="uq_auth_identity_provider_user"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    provider: str  # e.g. "telegram"
    provider_user_id: str  # the id at the provider (Telegram's numeric id, as str)
    username: str | None = Field(default=None)
    avatar_url: str | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

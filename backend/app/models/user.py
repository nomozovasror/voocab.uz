import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    """A learner — the center of the system. All activity (attempts, and later
    interactions, XP and achievements) refers back to a user."""

    __tablename__ = "users"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # Nullable: users can sign up via Telegram without an email. Still unique
    # when present (Postgres allows multiple NULLs in a unique index), ready for
    # email/password login later.
    email: str | None = Field(default=None, unique=True, index=True)
    # Nullable for now: the email/password flow is a later task; this column just
    # has to exist so it can be filled in without a schema change.
    hashed_password: str | None = Field(default=None)
    display_name: str
    avatar_url: str | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

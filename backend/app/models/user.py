import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel

#: The system account the AI-assisted lexicon review signs its approvals as
#: (`app.services.lexicon_ai_review`). It is a row like any other so that
#: `lexeme_senses.approved_by` and Studio can name who approved a sense, and
#: it can never be signed in as: no password, no `auth_identities` row, not an
#: admin, and `is_system_account` makes the two places that turn a token into
#: a user (`app.api.deps.get_current_user`, `POST /api/auth/refresh`) refuse it
#: even for a token somebody managed to mint.
REVIEW_BOT_EMAIL = "claude-review@voocab.local"
REVIEW_BOT_NAME = "Claude review"


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
    #: The whole of this project's admin story (`lexicon-spec.md` D7): one
    #: flag, no role table. The lexicon brief needs exactly one gated screen
    #: -- Studio's translation-review tab, P5 -- and a role system built for
    #: a single boolean would be speculative scaffolding, not a feature.
    is_admin: bool = Field(default=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


def is_system_account(user: User) -> bool:
    """Whether ``user`` is an account no person signs in as -- today only the
    lexicon review's. Checked wherever a session token is resolved to a user."""
    return user.email == REVIEW_BOT_EMAIL

from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, overridable via environment variables or a .env file.

    ``DATABASE_URL`` must use the async ``postgresql+asyncpg`` driver so both the
    app and Alembic share one connection string. The default targets the
    docker-compose ``db`` service (user/pass ``postgres``, database ``app``); set
    the env var to point elsewhere for local runs outside Docker.

    The auth settings default to empty/dev values so the app and Alembic import
    cleanly without them; the Telegram endpoints fail loudly if the required
    ones are missing. Real secrets live in the environment (see .env.example).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/app"

    # --- Telegram OIDC (values from @BotFather) ---
    # Client ID (bot id) and client secret (bot token) issued by BotFather when
    # you register your Allowed URLs. Sent to the /token endpoint via HTTP Basic.
    telegram_bot_id: str = ""
    telegram_bot_token: str = ""
    # Must exactly match a redirect URI registered with BotFather.
    telegram_redirect_uri: str = "http://localhost:5173/api/auth/telegram/callback"

    # --- Our own session layer ---
    # HS256 signing key for our access/refresh cookies and the short-lived OIDC
    # transaction cookie. MUST be overridden in production.
    session_secret: str = "dev-insecure-session-secret-change-me"
    # Set true in production so cookies are only sent over HTTPS.
    cookie_secure: bool = False
    # Cookie Domain attribute. In production the frontend (voocab.uz) and API
    # (api.voocab.uz) live on different subdomains, so session cookies must be
    # scoped to the parent domain, e.g. ".voocab.uz". Empty = host-only cookie
    # (correct for single-host local dev).
    cookie_domain: str = ""
    # Where the callback sends the browser after a successful login.
    frontend_url: str = "http://localhost:5173"

    # --- CORS ---
    # Origins allowed to call the API with credentials. Accepts a comma-separated
    # string in the env (e.g. "https://voocab.uz,https://www.voocab.uz").
    # NoDecode stops pydantic-settings from JSON-parsing the env value so our
    # validator can split it.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    # --- Cloudflare R2 (audio storage + DB backups; S3-compatible) ---
    r2_bucket: str = ""
    r2_endpoint: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        """Allow the env var to be a comma-separated list rather than JSON."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


settings = Settings()
